"""
Brier-score calibration tracker for TrueScout knockout-stage predictions.

Compares model predictions vs market odds for completed R32/R16/etc. matches
using a strict 2-way "To Advance" framing — the only valid apples-to-apples
comparison for knockout fixtures.

The 2-Way Knockout Trap
-----------------------
Knockout matches cannot end in a draw.  Betting markets offer 3-way 90-minute
W/D/L odds, not 2-way "to advance" odds.  Naively using P(home wins 90 min)
from the market as the advance probability is wrong — a draw sends the game to
extra time + penalties where the stronger team is slightly favoured.

Conversion used here:
    P_mkt(home advances) = P_mkt(H) + P_mkt(D) × et_bias
    et_bias = 0.55 if home team is model-stronger, else 0.45

The model advance probability = logistic(s_home - s_away, scale=1.5)
which already encodes the full advance probability (the same formula the
Monte Carlo engine uses).

Metrics
-------
  Brier Score   (p - o)^2           binary, range [0, 1];  lower is better
  Log Loss      -log(p of outcome)  clipped to p ∈ [0.01, 0.99]; lower is better
  Coin-flip     p = 0.5 for every match → Brier = 0.25, LogLoss = 0.693

Writes one row per completed knockout match to brier_log, keyed on
(event_id, run_date) with a UNIQUE constraint — idempotent on re-runs.

Usage
-----
    python -m etl.models.brier_tracker
    python -m etl.models.brier_tracker --validate   # dry-run, no DB write
    python -m etl.models.brier_tracker --scale 2.0
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings
from etl.utils.team_aliases import normalize as _normalize
from etl.models.calibration import (
    advance_prob,
    load_fitted_scale,
    ET_BIAS_STRONGER,
    ET_BIAS_WEAKER,
)

logger = logging.getLogger(__name__)

# LOGISTIC_SCALE, ET_BIAS_STRONGER, ET_BIAS_WEAKER live in etl/models/calibration.py
CLIP_LO, CLIP_HI = 0.01, 0.99

# FT-pens results known before Sofascore Bronze refreshes ET data.
# Key: ESPN event_id (string). Value: canonical winning team name.
# Add new entries here when a Sofascore re-pull doesn't resolve the draw automatically.
MANUAL_FT_PENS_WINNERS: dict[str, str] = {
    "760488": "Morocco",   # Netherlands 1-1 Morocco (29 Jun 2026) — Morocco wins on pens
    "760489": "Paraguay",  # Germany 1-1 Paraguay (29 Jun 2026) — Paraguay wins on pens
    "760499": "Egypt",     # Australia 1-1 Egypt   (03 Jul 2026) — Egypt wins on pens
}


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_COMPLETED_SQL = """
SELECT
    m.event_id,
    m.match_date,
    m.round_name,
    m.home_team_name,
    m.away_team_name,
    m.home_score,
    m.away_score,
    -- raw implied probs (for overround sanity check)
    o.home_implied_raw,
    o.draw_implied_raw,
    o.away_implied_raw,
    -- vig-removed probs (normalised to 1.0 by espn_pull)
    o.home_win_prob,
    o.draw_prob,
    o.away_win_prob
FROM read_parquet('{matches}', union_by_name=true) m
LEFT JOIN read_parquet('{odds}', union_by_name=true) o
    ON m.event_id = o.event_id
WHERE m.is_completed = true
  AND m.round_name IN ('Round of 32', 'Round of 16',
                       'Quarterfinal', 'Semifinal', 'Final')
ORDER BY m.match_date, CAST(m.event_id AS BIGINT)
"""

_STRENGTH_SQL = """
WITH wc_players AS (
    SELECT DISTINCT
        CAST(l.player_id AS VARCHAR) AS sofascore_id,
        CASE l.team_side
            WHEN 'home' THEN e.home_team_name
            WHEN 'away' THEN e.away_team_name
        END AS national_team
    FROM read_parquet('{lineup_glob}', union_by_name=true) l
    JOIN read_parquet('{events_glob}', union_by_name=true) e
      ON CAST(l.event_id AS BIGINT) = CAST(e.event_id AS BIGINT)
),
player_national AS (
    SELECT wc.national_team, ip.reep_id, pr.posterior_mean
    FROM wc_players wc
    JOIN identity_players ip ON wc.sofascore_id = ip.key_sofascore
    JOIN player_ratings   pr ON ip.reep_id       = pr.reep_id
),
ranked AS (
    SELECT national_team, posterior_mean,
           ROW_NUMBER() OVER (
               PARTITION BY national_team ORDER BY posterior_mean DESC
           ) AS rn
    FROM player_national
)
SELECT national_team AS team, AVG(posterior_mean) AS strength
FROM ranked
WHERE rn <= 15
GROUP BY national_team
"""


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_completed_matches(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    bronze = Path(settings.parquet_bronze_dir)
    matches_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()
    odds_glob    = (bronze / "espn" / "odds"    / "*.parquet").as_posix()

    sql = _COMPLETED_SQL.format(matches=matches_glob, odds=odds_glob)
    df = conn.execute(sql).df()

    df["home_team_name"] = df["home_team_name"].map(_normalize)
    df["away_team_name"] = df["away_team_name"].map(_normalize)
    return df


def _build_strengths(conn: duckdb.DuckDBPyConnection) -> dict[str, float]:
    bronze      = Path(settings.parquet_bronze_dir)
    lineup_glob = (bronze / "sofascore" / "lineups" / "*.parquet").as_posix()
    events_glob = (bronze / "sofascore" / "events"  / "*.parquet").as_posix()

    sql = _STRENGTH_SQL.format(lineup_glob=lineup_glob, events_glob=events_glob)
    df  = conn.execute(sql).df()
    df["team"] = df["team"].map(_normalize)
    return dict(zip(df["team"], df["strength"].astype(float)))


# ---------------------------------------------------------------------------
# Probability helpers
# ---------------------------------------------------------------------------

def _logistic_advance(s_home: float, s_away: float, scale: float) -> float:
    """P(home team advances) — 2-way logistic strength-delta."""
    return 1.0 / (1.0 + 10.0 ** (-(s_home - s_away) / scale))


def _market_2way(
    home_win: float | None,
    draw:     float | None,
    away_win: float | None,
    et_bias:  float,
) -> float | None:
    """
    Collapse vig-removed 3-way 90-min probabilities to a 2-way advance probability.

    P(home advances) = P(home wins 90) + P(draw 90) * P(home wins ET/pens)
    If draw is absent (2-way market already): return home_win directly.
    Returns None if insufficient odds data.
    """
    if home_win is None or away_win is None:
        return None
    if draw is None:
        # Already a 2-way market (home_win + away_win already normalise to 1.0)
        return float(home_win)
    return float(home_win) + float(draw) * et_bias


def _brier(p: float, outcome: int) -> float:
    return (p - outcome) ** 2


def _log_loss(p: float, outcome: int) -> float:
    """Binary cross-entropy for one match. p is clipped to [0.01, 0.99]."""
    p_clipped = max(CLIP_LO, min(CLIP_HI, p))
    p_outcome = p_clipped if outcome == 1 else (1.0 - p_clipped)
    return -math.log(p_outcome)


# ---------------------------------------------------------------------------
# ET / penalties lookup
# ---------------------------------------------------------------------------

def _load_sofascore_et(
    conn: duckdb.DuckDBPyConnection,
) -> dict[tuple[str, str, str], dict]:
    """
    Load matches that went to ET/pens from Sofascore bronze parquet.
    Returns a dict keyed on (home_team, away_team, match_date YYYY-MM-DD) after
    alias normalisation so it can be joined with the ESPN-sourced matches df.
    """
    bronze = Path(settings.parquet_bronze_dir)
    events_glob = (bronze / "sofascore" / "events" / "*.parquet").as_posix()

    try:
        df = conn.execute(f"""
            SELECT home_team_name, away_team_name, match_date,
                   home_score_et, away_score_et,
                   home_score_penalties, away_score_penalties,
                   went_to_extra_time, went_to_penalties
            FROM read_parquet('{events_glob}', union_by_name=true)
            WHERE went_to_extra_time = true
        """).df()
    except Exception:
        logger.warning("Sofascore events not in Bronze yet — ET/pens lookup unavailable.")
        return {}

    index: dict[tuple[str, str, str], dict] = {}
    for _, row in df.iterrows():
        h = _normalize(row["home_team_name"]) or row["home_team_name"]
        a = _normalize(row["away_team_name"]) or row["away_team_name"]
        d = str(row["match_date"])[:10]
        index[(h, a, d)] = row.to_dict()
    return index


# ---------------------------------------------------------------------------
# Core grader
# ---------------------------------------------------------------------------

def _grade_matches(
    matches: pd.DataFrame,
    strengths: dict[str, float],
    scale: float,
    et_index: dict[tuple[str, str, str], dict],
) -> list[dict]:
    """
    For each completed knockout match, compute 2-way advance probabilities
    and scoring metrics.

    Returns a list of row dicts ready for brier_log insertion.
    """
    fallback_str = float(np.median(list(strengths.values())))
    rows: list[dict] = []

    for _, m in matches.iterrows():
        home = m["home_team_name"]
        away = m["away_team_name"]
        h_score = m["home_score"]
        a_score = m["away_score"]

        # ── Who advanced? ────────────────────────────────────────────────
        if pd.isna(h_score) or pd.isna(a_score):
            logger.warning("Missing scores for %s vs %s — skipping.", home, away)
            continue
        h_score = int(h_score)
        a_score = int(a_score)

        if h_score > a_score:
            advanced_team = home
            outcome = 1   # home advanced
        elif a_score > h_score:
            advanced_team = away
            outcome = 0   # away advanced
        else:
            # 90-min draw — resolve via Sofascore ET/pens data first,
            # then fall back to MANUAL_FT_PENS_WINNERS for known results.
            et_key = (_normalize(home) or home, _normalize(away) or away, str(m["match_date"])[:10])
            et_row = et_index.get(et_key)
            if et_row is None:
                ev_id = str(m["event_id"])
                manual_winner = MANUAL_FT_PENS_WINNERS.get(ev_id)
                if manual_winner:
                    norm_winner = _normalize(manual_winner) or manual_winner
                    if norm_winner == home:
                        advanced_team, outcome = home, 1
                    else:
                        advanced_team, outcome = away, 0
                    logger.info(
                        "Manual FT-pens override for event %s (%s vs %s): %s advanced.",
                        ev_id, home, away, advanced_team,
                    )
                else:
                    logger.warning(
                        "%s vs %s ended %d-%d (90-min draw) — no ET/pens data in Bronze yet, skipping.",
                        home, away, h_score, a_score,
                    )
                    continue
            if et_row is not None and et_row.get("went_to_penalties"):
                h_pens = et_row.get("home_score_penalties")
                a_pens = et_row.get("away_score_penalties")
                if h_pens is None or a_pens is None:
                    logger.warning("%s vs %s — penalty scores missing in Bronze, skipping.", home, away)
                    continue
                if int(h_pens) > int(a_pens):
                    advanced_team, outcome = home, 1
                else:
                    advanced_team, outcome = away, 0
            elif et_row is not None:
                # ET decided without going to pens
                h_et = int(et_row.get("home_score_et") or 0)
                a_et = int(et_row.get("away_score_et") or 0)
                if h_et > a_et:
                    advanced_team, outcome = home, 1
                elif a_et > h_et:
                    advanced_team, outcome = away, 0
                else:
                    logger.warning("%s vs %s — ET also tied with no pens recorded, skipping.", home, away)
                    continue

        # ── Model strength lookup ────────────────────────────────────────
        s_home = strengths.get(home)
        s_away = strengths.get(away)
        if s_home is None:
            logger.warning("No strength for %s — using median %.4f", home, fallback_str)
            s_home = fallback_str
        if s_away is None:
            logger.warning("No strength for %s — using median %.4f", away, fallback_str)
            s_away = fallback_str

        # ── Model 2-way advance probability (Davidson, from calibration) ──
        model_prob = advance_prob(s_home, s_away, scale)

        # ── Market odds ──────────────────────────────────────────────────
        home_raw = m.get("home_implied_raw")
        draw_raw = m.get("draw_implied_raw")
        away_raw = m.get("away_implied_raw")

        has_market = (
            not pd.isna(home_raw) if home_raw is not None else False
        ) and (
            not pd.isna(away_raw) if away_raw is not None else False
        )

        if has_market:
            # Overround sanity check
            draw_for_sum = float(draw_raw) if not pd.isna(draw_raw) else 0.0
            overround = float(home_raw) + draw_for_sum + float(away_raw)
            if overround <= 1.0:
                logger.warning(
                    "Market overround %.4f ≤ 1.0 for %s vs %s — odds may be vig-removed already.",
                    overround, home, away,
                )

        home_norm = m.get("home_win_prob")
        draw_norm = m.get("draw_prob")
        away_norm = m.get("away_win_prob")

        # ET/pens bias: favour the model-stronger team
        et_bias = ET_BIAS_STRONGER if s_home >= s_away else ET_BIAS_WEAKER

        market_prob: float | None
        if pd.isna(home_norm) if home_norm is not None else True:
            market_prob = None
        else:
            draw_norm_val = None if (pd.isna(draw_norm) if draw_norm is not None else True) else float(draw_norm)
            market_prob = _market_2way(
                home_win=float(home_norm),
                draw=draw_norm_val,
                away_win=float(away_norm) if not pd.isna(away_norm) else None,
                et_bias=et_bias,
            )

        # ── Compute metrics ──────────────────────────────────────────────
        brier_model    = _brier(model_prob, outcome)
        log_loss_model = _log_loss(model_prob, outcome)

        brier_market    = _brier(float(market_prob), outcome) if market_prob is not None else None
        log_loss_market = _log_loss(float(market_prob), outcome) if market_prob is not None else None

        rows.append({
            "run_date":        str(date.today()),
            "round":           m["round_name"],
            "event_id":        str(m["event_id"]),
            "home_team":       home,
            "away_team":       away,
            "advanced_team":   advanced_team,
            "model_prob":      model_prob,
            "market_prob":     market_prob,
            "brier_model":     brier_model,
            "brier_market":    brier_market,
            "log_loss_model":  log_loss_model,
            "log_loss_market": log_loss_market,
            # extras for display only
            "_s_home": s_home,
            "_s_away": s_away,
            "_home_win_prob":  float(home_norm) if home_norm is not None and not pd.isna(home_norm) else None,
            "_draw_prob":      float(draw_norm)  if draw_norm  is not None and not pd.isna(draw_norm)  else None,
            "_away_win_prob":  float(away_norm)  if away_norm  is not None and not pd.isna(away_norm)  else None,
            "_et_bias":        et_bias,
            "_outcome":        outcome,
        })

    return rows


# ---------------------------------------------------------------------------
# Validation printout
# ---------------------------------------------------------------------------

def _print_report(rows: list[dict]) -> None:
    COIN_BRIER    = 0.25
    COIN_LOGLOSS  = -math.log(0.5)    # = log(2) ≈ 0.6931

    print("\n" + "=" * 72)
    print("  2-WAY ADVANCE PROBABILITIES — MODEL vs MARKET vs COIN FLIP")
    print("=" * 72)

    for r in rows:
        home, away = r["home_team"], r["away_team"]
        adv  = r["advanced_team"]
        mp   = r["model_prob"]
        mkp  = r["market_prob"]
        outcome = r["_outcome"]

        # Which team's advance probability to display (the HOME team's)
        mp_home_str  = f"{mp*100:.1f}%"
        mkp_home_str = f"{mkp*100:.1f}%" if mkp is not None else "N/A (no odds)"

        # Market breakdown
        hw = r["_home_win_prob"];  dp = r["_draw_prob"];  aw = r["_away_win_prob"]
        mkt_breakdown = (
            f"Mkt 90-min: H={hw*100:.1f}% D={dp*100:.1f}% A={aw*100:.1f}%  →  "
            f"2-way (ET bias={r['_et_bias']:.2f}): {mkp_home_str}"
        ) if hw is not None else f"No market odds for this match."

        print(f"\n  {home} vs {away}")
        print(f"  Strengths: {home}={r['_s_home']:.3f}  {away}={r['_s_away']:.3f}")
        print(f"  Model P(home advances): {mp_home_str}")
        print(f"  {mkt_breakdown}")
        outcome_str = "home" if outcome else "away"
        brier_mkt_str = "N/A" if r["brier_market"] is None else f"{r['brier_market']:.4f}"
        ll_mkt_str    = "N/A" if r["log_loss_market"] is None else f"{r['log_loss_market']:.4f}"
        print(f"  Result: {adv} advanced  (outcome={outcome_str})")
        print(f"  Brier:    model={r['brier_model']:.4f}  market={brier_mkt_str}  coin={COIN_BRIER:.4f}")
        print(f"  Log loss: model={r['log_loss_model']:.4f}  market={ll_mkt_str}  coin={COIN_LOGLOSS:.4f}")

    # ── Summary table ────────────────────────────────────────────────────────
    n_total  = len(rows)
    n_market = sum(1 for r in rows if r["market_prob"] is not None)

    avg_brier_model  = sum(r["brier_model"]    for r in rows) / n_total if n_total else float("nan")
    avg_ll_model     = sum(r["log_loss_model"] for r in rows) / n_total if n_total else float("nan")

    if n_market:
        avg_brier_mkt = sum(r["brier_market"]    for r in rows if r["brier_market"]    is not None) / n_market
        avg_ll_mkt    = sum(r["log_loss_market"] for r in rows if r["log_loss_market"] is not None) / n_market
    else:
        avg_brier_mkt = avg_ll_mkt = float("nan")

    print("\n" + "=" * 72)
    print(f"  SUMMARY  ({n_total} completed match(es), {n_market} with market odds)")
    print("=" * 72)
    print(f"  {'Metric':<16}  {'Model':>10}  {'Market':>10}  {'Coin flip':>10}")
    print(f"  {'-'*16}  {'-'*10}  {'-'*10}  {'-'*10}")
    print(f"  {'Brier Score':<16}  {avg_brier_model:>10.4f}  "
          f"{'N/A' if math.isnan(avg_brier_mkt) else f'{avg_brier_mkt:.4f}':>10}  "
          f"{COIN_BRIER:>10.4f}")
    print(f"  {'Log Loss':<16}  {avg_ll_model:>10.4f}  "
          f"{'N/A' if math.isnan(avg_ll_mkt) else f'{avg_ll_mkt:.4f}':>10}  "
          f"{COIN_LOGLOSS:>10.4f}")
    print()

    if avg_brier_model < COIN_BRIER:
        delta = COIN_BRIER - avg_brier_model
        print(f"  Model beats coin-flip by {delta:.4f} Brier points ✓")
    else:
        delta = avg_brier_model - COIN_BRIER
        print(f"  Model trails coin-flip by {delta:.4f} Brier points (more data needed)")

    if n_market and not math.isnan(avg_brier_mkt):
        if avg_brier_model < avg_brier_mkt:
            print(f"  Model beats market by {avg_brier_mkt - avg_brier_model:.4f} Brier points ✓")
        else:
            print(f"  Model trails market by {avg_brier_model - avg_brier_mkt:.4f} Brier points "
                  "(expected early on — market has full squad/injury intel)")
    print()


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

def _write_brier_log(conn: duckdb.DuckDBPyConnection, rows: list[dict]) -> int:
    """
    Append new rows to brier_log, skipping any (event_id, run_date) that
    already exists (idempotent on re-runs).

    Returns the number of rows actually inserted.
    """
    cols = [
        "run_date", "round", "event_id", "home_team", "away_team",
        "advanced_team", "model_prob", "market_prob",
        "brier_model", "brier_market", "log_loss_model", "log_loss_market",
    ]

    # Filter out the display-only '_' prefixed columns
    clean_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

    df = pd.DataFrame(clean_rows, columns=cols)
    conn.register("_brier_batch", df)

    n_before = conn.execute("SELECT COUNT(*) FROM brier_log").fetchone()[0]

    conn.execute(f"""
        INSERT INTO brier_log ({", ".join(cols)})
        SELECT {", ".join(cols)} FROM _brier_batch
        WHERE NOT EXISTS (
            SELECT 1 FROM brier_log bl
            WHERE bl.event_id = _brier_batch.event_id
              AND bl.run_date  = CAST(_brier_batch.run_date AS DATE)
        )
    """)

    conn.unregister("_brier_batch")

    n_after = conn.execute("SELECT COUNT(*) FROM brier_log").fetchone()[0]
    return n_after - n_before


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Brier-score tracker (knockout, 2-way).")
    parser.add_argument("--validate", action="store_true",
                        help="Dry-run: print report, skip DB write.")
    parser.add_argument("--scale", type=float, default=None,
                        help="Logistic scale override (default: load from model_params or 1.0).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    conn = duckdb.connect(str(settings.duckdb_path), read_only=args.validate)

    if args.scale is None:
        args.scale = load_fitted_scale(conn)

    try:
        # Load data
        matches   = _load_completed_matches(conn)
        strengths = _build_strengths(conn)
        logger.info(
            "Loaded %d completed knockout match(es); strengths for %d teams.",
            len(matches), len(strengths),
        )

        if matches.empty:
            logger.info("No completed knockout matches in Bronze yet.  "
                        "Run espn_pull --knockout after matches finish.")
            return

        # Grade
        et_index = _load_sofascore_et(conn)
        rows = _grade_matches(matches, strengths, scale=args.scale, et_index=et_index)

        if not rows:
            logger.info("No gradeable matches (all drew in 90 min or missing scores).")
            return

        # Print validation report
        _print_report(rows)

        # Write (or skip in validate mode)
        if args.validate:
            logger.info("--validate: skipping DB write.")
        else:
            n_inserted = _write_brier_log(conn, rows)
            total = conn.execute("SELECT COUNT(*) FROM brier_log").fetchone()[0]
            logger.info(
                "brier_log: %d new row(s) inserted (%d already existed).  "
                "Total rows: %d.",
                n_inserted, len(rows) - n_inserted, total,
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
