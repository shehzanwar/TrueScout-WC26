"""
Monte Carlo bracket simulation for the 2026 World Cup knockout stage.

100,000 vectorised iterations of a 32-team single-elimination bracket.

Bracket construction — data-driven (no hardcoding):
  1. Read the 16 actual R32 fixtures from Bronze ESPN matches
     (round_name = 'Round of 32', fetched via espn_pull --knockout).
  2. Read the 8 R16 fixtures to derive the bracket pairing tree
     (the R16 entries contain "Round of 32 N Winner" placeholders that
     encode which R32 match numbers meet in each R16 slot).
  3. Arrange all 32 teams in bracket positions such that:
       - adjacent pairs (2k, 2k+1) play each other in R32
       - winners of adjacent R32-pairs fight in R16 (mirroring the real draw)
       - the full QF / SF / Final tree follows from standard elimination

Team strength = mean posterior_mean of the top-15 rated players per team
                (player_ratings joined to WC Sofascore lineups via identity_players).
Match winner  = logistic strength-delta:
                  P(A wins) = 1 / (1 + 10^(-(sA - sB) / SCALE))

NO Dixon-Coles, NO fatigue, NO injuries.

Writes 192 rows (32 teams × 6 rounds) to the ``simulations`` table:
    run_date, round, team_id (canonical ESPN name), advance_prob,
    title_prob, n_iterations

Bronze prerequisites
--------------------
    python -m etl.sources.espn_pull --knockout   # adds R32+R16 fixture Parquets

Usage
-----
    python -m etl.models.monte_carlo_sim
    python -m etl.models.monte_carlo_sim --validate   # dry-run, no DB write
    python -m etl.models.monte_carlo_sim --scale 2.0
"""
import argparse
import json
import logging
import math
import re
import sys
import time
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings
from etl.utils.team_aliases import TEAM_ALIASES, normalize as _alias_normalize
from etl.models.calibration import (
    advance_prob,
    advance_prob_vec,
    load_fitted_scale,
    fallback_strength,
    FALLBACK_STRENGTH,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

N_SIM         = 100_000
TOP_N_PLAYERS = 15
SEED          = 42
# LOGISTIC_SCALE and FALLBACK_STRENGTH live in etl/models/calibration.py

ROUNDS = ["R32", "R16", "QF", "SF", "F", "W"]

# Keep local reference for direct dict access (used by _R32_SQL glob expansions)
_NAME_ALIASES: dict[str, str] = TEAM_ALIASES


def _normalize(name: str) -> str:
    """Map any known team name variant to the canonical Sofascore name."""
    return _alias_normalize(name) or name


# ---------------------------------------------------------------------------
# Bracket construction from Bronze
# ---------------------------------------------------------------------------

_R32_SQL = """
SELECT home_team_name, away_team_name, match_date, event_id
FROM read_parquet('{glob}', union_by_name=true)
WHERE round_name = 'Round of 32'
ORDER BY match_date, CAST(event_id AS BIGINT)
"""

_R16_SQL = """
SELECT home_team_name, away_team_name, match_date, event_id
FROM read_parquet('{glob}', union_by_name=true)
WHERE round_name = 'Round of 16'
ORDER BY match_date, CAST(event_id AS BIGINT)
"""

_R32_MATCH_RE = re.compile(r"Round of 32 (\d+) Winner", re.IGNORECASE)


def _parse_r32_num(name: str) -> int | None:
    """
    Extract N from ESPN placeholder 'Round of 32 N Winner' (1-indexed).
    Returns None if the string is an actual team name (already resolved).
    """
    m = _R32_MATCH_RE.search(name)
    return int(m.group(1)) if m else None


def _load_bracket(
    conn: duckdb.DuckDBPyConnection,
) -> tuple[list[str], list[tuple[int, int]]]:
    """
    Build the 32-slot bracket position list from Bronze ESPN fixture data.

    Algorithm
    ---------
    1. Load R32 fixtures (chronological) → r32[0..15] = (home, away)
       ESPN numbers them 1-16 in this same order.

    2. Build reverse map: canonical_team_name → r32_match_index (0-based).

    3. Load R16 fixtures (chronological).  Each R16 entry names two R32
       match numbers via 'Round of 32 N Winner' placeholders (or an actual
       team name if that R32 match is already complete).

    4. The 8 R16 pairs give us the bracket pairing structure:
         r16_pair[i] = (r32_idx_A, r32_idx_B)
       Adjacent R16 pairs (i and i+1) feed into the same QF.

    5. Arrange bracket positions:
         positions 0,1 = r32_pair[0].A.home, r32_pair[0].A.away
         positions 2,3 = r32_pair[0].B.home, r32_pair[0].B.away
         positions 4,5 = r32_pair[1].A.home, r32_pair[1].A.away
         ...
       This makes standard adjacent-pair simulation correctly model the draw.

    Returns
    -------
    (bracket, r16_pairs)
        bracket   : 32 canonical team names in bracket position order
        r16_pairs : 8 (r32_idx_a, r32_idx_b) tuples using chronological
                    ESPN match indices — i.e. r16_pairs[i] says which two
                    ESPN R32 matches feed R16 slot i.
    """
    bronze = Path(settings.parquet_bronze_dir)
    espn_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()

    try:
        r32_df = conn.execute(_R32_SQL.format(glob=espn_glob)).df()
        r16_df = conn.execute(_R16_SQL.format(glob=espn_glob)).df()
    except Exception as exc:
        raise RuntimeError(
            f"Cannot load R32/R16 fixture data from Bronze: {exc}\n"
            "Run: python -m etl.sources.espn_pull --knockout"
        ) from exc

    if len(r32_df) != 16:
        raise RuntimeError(
            f"Expected 16 R32 fixtures in Bronze, found {len(r32_df)}. "
            "Run: python -m etl.sources.espn_pull --knockout"
        )
    if len(r16_df) != 8:
        raise RuntimeError(
            f"Expected 8 R16 fixtures in Bronze, found {len(r16_df)}. "
            "Run: python -m etl.sources.espn_pull --knockout"
        )

    # r32_fixtures[i] = (home_canonical, away_canonical)  0-indexed
    r32_fixtures = [
        (_normalize(row.home_team_name), _normalize(row.away_team_name))
        for row in r32_df.itertuples(index=False)
    ]

    # team → 0-based R32 match index (for resolving actual team names in R16)
    team_to_r32_idx: dict[str, int] = {}
    for idx, (home, away) in enumerate(r32_fixtures):
        team_to_r32_idx[home] = idx
        team_to_r32_idx[away] = idx

    # Parse each R16 fixture → two R32 match indices (0-based) + n_real (how
    # many sides used an actual team name rather than a placeholder).
    # n_real=2 means both teams are confirmed; n_real=0 means both are TBD.
    r16_pairs_meta: list[tuple[int, int, int]] = []
    for row in r16_df.itertuples(index=False):
        home_n = _parse_r32_num(row.home_team_name)
        away_n = _parse_r32_num(row.away_team_name)
        n_real = 0

        # If the R32 match is already complete, ESPN shows the real team name.
        # For placeholders "Round of 32 N Winner", N is ESPN's 0-based slot index
        # (matches our chronological sort order), so use N directly.
        if home_n is None:
            team = _normalize(row.home_team_name)
            home_n = team_to_r32_idx.get(team)
            if home_n is None:
                logger.warning(
                    "Cannot resolve R16 home '%s' to an R32 match — skipping pair.",
                    row.home_team_name,
                )
                continue
            n_real += 1
        if away_n is None:
            team = _normalize(row.away_team_name)
            away_n = team_to_r32_idx.get(team)
            if away_n is None:
                logger.warning(
                    "Cannot resolve R16 away '%s' to an R32 match — skipping pair.",
                    row.away_team_name,
                )
                continue
            n_real += 1

        r16_pairs_meta.append((home_n, away_n, n_real))

    # Record ESPN fixture slot order before the dedup sort so we can restore it
    # afterwards.  The sort by -n_real is needed for deduplication (confirmed data
    # wins over stale placeholders), but it also reorders DISTINCT slots when some
    # are confirmed (n_real=2) and others are still TBD (n_real=0) — e.g. a
    # confirmed R16 match can jump ahead of an earlier TBD slot.
    pair_to_espn_slot: dict[frozenset, int] = {}
    for espn_slot, (a, b, _) in enumerate(r16_pairs_meta):
        key: frozenset = frozenset([a, b])
        if key not in pair_to_espn_slot:
            pair_to_espn_slot[key] = espn_slot

    # Deduplicate: ESPN occasionally emits BOTH the stale "Round of 32 N Winner"
    # placeholder AND the updated real-team-name entry for the same bracket slot
    # in the same nightly pull (the resolved entry has a higher n_real score).
    # Process entries with MORE real names first (freshest data wins).
    # Indices that get orphaned from skipped stale pairs are repaired by pairing
    # them with the R32 match that would otherwise be absent from the bracket.
    r16_pairs_meta.sort(key=lambda x: -x[2])

    used_r32:  set[int]              = set()
    r16_pairs: list[tuple[int, int]] = []
    orphaned:  list[int]             = []

    for a, b, n_real in r16_pairs_meta:
        a_ok = a not in used_r32
        b_ok = b not in used_r32
        if a_ok and b_ok:
            r16_pairs.append((a, b))
            used_r32.add(a)
            used_r32.add(b)
        elif not a_ok and b_ok:
            orphaned.append(b)
            logger.warning(
                "R16 pair (%d, %d): R32 index %d already used "
                "(ESPN stale placeholder?) — orphaning index %d for repair.",
                a, b, a, b,
            )
        elif a_ok and not b_ok:
            orphaned.append(a)
            logger.warning(
                "R16 pair (%d, %d): R32 index %d already used "
                "(ESPN stale placeholder?) — orphaning index %d for repair.",
                a, b, b, a,
            )
        else:
            logger.warning("R16 pair (%d, %d): both indices already used — discarding.", a, b)

    # Pair each orphaned R32 index with the corresponding missing R32 index
    # so the bracket stays at exactly 32 unique teams.
    #
    # NOTE: orphaned indices are, by construction, always a subset of
    # (all_r32_indices - used_r32) — they were deliberately never added to
    # used_r32. That means an orphaned index always also appears in `missing`.
    # If we zip(orphaned_u, missing) directly, sorted() can place the SAME
    # index at position 0 of both lists, producing a degenerate self-pair
    # (e.g. (3, 3)) that duplicates that match's two teams in the bracket
    # while silently dropping whichever index was the real missing partner.
    # Exclude orphaned indices from the missing-partner pool to prevent this.
    all_r32_indices = set(range(len(r32_fixtures)))
    missing    = sorted(all_r32_indices - used_r32)
    orphaned_u = sorted(set(orphaned) - used_r32)
    missing_partners = sorted(set(missing) - set(orphaned_u))

    if orphaned_u or missing:
        logger.warning(
            "Bracket repair: %d orphaned R32 index(es) %s / "
            "%d missing R32 index(es) %s.",
            len(orphaned_u), orphaned_u, len(missing), missing,
        )
        if len(orphaned_u) != len(missing_partners):
            raise RuntimeError(
                f"Bracket repair imbalance: {len(orphaned_u)} orphaned index(es) "
                f"{orphaned_u} vs {len(missing_partners)} available missing-partner "
                f"index(es) {missing_partners}. Check Bronze R16 fixture data."
            )
        for orph, miss in zip(orphaned_u, missing_partners):
            r16_pairs.append((orph, miss))
            used_r32.add(orph)
            used_r32.add(miss)
            logger.warning("  Paired orphaned R32 %d ↔ missing R32 %d.", orph, miss)

    if len(r16_pairs) != 8:
        raise RuntimeError(
            f"Could only build {len(r16_pairs)}/8 R16 bracket pairs after repair.  "
            "Check Bronze R16 fixture data."
        )

    # Restore ESPN fixture slot order (the dedup sort can reorder slots when
    # confirmed and TBD matches are interleaved — e.g. a confirmed match at
    # ESPN slot 5 jumping ahead of a TBD match at slot 4).
    # Orphan-repaired pairs (not in pair_to_espn_slot) sort last.
    r16_pairs.sort(key=lambda p: pair_to_espn_slot.get(frozenset(p), len(r16_pairs_meta)))

    # Build bracket positions: for each R16 pair (a, b) in order, place
    # r32_fixtures[a] then r32_fixtures[b] as consecutive 4-slot sections.
    bracket: list[str] = []
    for a, b in r16_pairs:
        home_a, away_a = r32_fixtures[a]
        home_b, away_b = r32_fixtures[b]
        bracket.extend([home_a, away_a, home_b, away_b])

    assert len(bracket) == 32, f"Bracket has {len(bracket)} slots, expected 32"
    assert len(set(bracket)) == 32, f"Duplicate teams in bracket: {sorted(bracket)}"

    logger.info("Bracket loaded from Bronze (16 R32 + 8 R16 fixtures).")
    return bracket, r16_pairs


# ---------------------------------------------------------------------------
# Team strength aggregation (player_ratings via WC lineups)
# ---------------------------------------------------------------------------

def _build_team_strengths(
    conn: duckdb.DuckDBPyConnection,
) -> tuple[dict[str, float], pd.DataFrame]:
    bronze      = Path(settings.parquet_bronze_dir)
    lineup_glob = (bronze / "sofascore" / "lineups" / "*.parquet").as_posix()
    events_glob = (bronze / "sofascore" / "events"  / "*.parquet").as_posix()

    # Check whether market_value_eur has been populated (script may not have run yet)
    existing_cols = {row[0] for row in conn.execute("DESCRIBE identity_players").fetchall()}
    has_mv = "market_value_eur" in existing_cols

    mv_select = "COALESCE(ip.market_value_eur, 0)" if has_mv else "0"

    sql = f"""
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
        SELECT
            wc.national_team,
            ip.reep_id,
            pr.posterior_mean,
            {mv_select} AS market_value_eur
        FROM wc_players wc
        JOIN identity_players ip ON wc.sofascore_id = ip.key_sofascore
        JOIN player_ratings   pr ON ip.reep_id       = pr.reep_id
    ),
    squad_values AS (
        SELECT national_team, SUM(market_value_eur) AS squad_value_eur
        FROM player_national
        GROUP BY national_team
    ),
    ranked AS (
        SELECT
            national_team,
            posterior_mean,
            ROW_NUMBER() OVER (
                PARTITION BY national_team
                ORDER BY posterior_mean DESC
            ) AS rn
        FROM player_national
    )
    SELECT
        r.national_team       AS team,
        AVG(r.posterior_mean) AS strength,
        COUNT(*)              AS n_players,
        MAX(sv.squad_value_eur) AS squad_value_eur
    FROM ranked r
    JOIN squad_values sv ON r.national_team = sv.national_team
    WHERE r.rn <= {TOP_N_PLAYERS}
    GROUP BY r.national_team
    ORDER BY strength DESC
    """

    df = conn.execute(sql).df()
    df["team"]            = df["team"].map(_normalize)
    df["squad_value_eur"] = df["squad_value_eur"].fillna(0)

    strengths = dict(zip(df["team"], df["strength"].astype(float)))
    logger.info("Strength computed for %d teams (top-%d avg posterior).", len(df), TOP_N_PLAYERS)

    # Squad market-value prior adjustment: log-normalised [-0.3, +0.5] range.
    # Gracefully skipped when market_value_eur hasn't been populated yet (all zeros).
    squad_val_map  = dict(zip(df["team"], df["squad_value_eur"].astype(float)))
    positive_vals  = [v for v in squad_val_map.values() if v > 0]
    if len(positive_vals) >= 24:
        log_vals = [math.log(max(v, 1_000_000) / 1_000_000) for v in positive_vals]
        min_log, max_log = min(log_vals), max(log_vals)
        squad_adjustments: dict[str, float] = {}
        for team in strengths:
            sv = squad_val_map.get(team, 0)
            if sv > 0:
                log_sv     = math.log(max(sv, 1_000_000) / 1_000_000)
                normalized = (log_sv - min_log) / max(0.01, max_log - min_log)
                squad_adjustments[team] = -0.3 + normalized * 0.8   # [-0.3, +0.5]
            else:
                squad_adjustments[team] = -0.2   # no coverage → mild penalty
        for team, adj in squad_adjustments.items():
            strengths[team] = strengths[team] + adj
        top5 = sorted(squad_adjustments.items(), key=lambda x: -x[1])[:5]
        bot5 = sorted(squad_adjustments.items(), key=lambda x:  x[1])[:5]
        logger.info("Squad-value adjustments applied (%d teams with data).", len(positive_vals))
        for t, a in top5:
            logger.info("  %s: %+.3f (squad=€%.0fM)", t, a, squad_val_map.get(t, 0) / 1e6)
        logger.info("  …")
        for t, a in bot5:
            logger.info("  %s: %+.3f (squad=€%.0fM)", t, a, squad_val_map.get(t, 0) / 1e6)
    else:
        logger.info("Squad market-value data absent — strength adjustment skipped.")

    return strengths, df


# ---------------------------------------------------------------------------
# Rest / travel adjustment  (PR5b.1)
# ---------------------------------------------------------------------------

def _compute_rest_adjustments(
    conn: duckdb.DuckDBPyConnection,
    bracket_order: list[str],
) -> dict[str, float]:
    """
    Penalise teams with fewer than 3 rest days before their R32 fixture.

    Formula: delta = -0.10 * max(0, 3 - rest_days)
      0 rest days → -0.30
      1 rest day  → -0.20
      2 rest days → -0.10
      3+ rest days → 0.0 (no penalty)

    Returns {canonical_team_name: strength_delta}.
    Only teams with a non-zero delta are included.
    """
    bronze = Path(settings.parquet_bronze_dir)
    espn_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()

    try:
        all_df = conn.execute(f"""
            SELECT
                home_team_name, away_team_name,
                CAST(match_date AS DATE) AS match_date,
                round_name
            FROM read_parquet('{espn_glob}', union_by_name=true)
            WHERE match_date IS NOT NULL
        """).df()
    except Exception as exc:
        logger.warning("Rest adjustment: cannot read ESPN matches: %s", exc)
        return {}

    if all_df.empty:
        return {}

    all_df["match_date"] = pd.to_datetime(all_df["match_date"])
    all_df["home_norm"] = all_df["home_team_name"].map(_normalize)
    all_df["away_norm"] = all_df["away_team_name"].map(_normalize)

    # Team → R32 date
    r32_df = all_df[all_df["round_name"] == "Round of 32"]
    team_r32_date: dict[str, pd.Timestamp] = {}
    for _, row in r32_df.iterrows():
        for team in (row["home_norm"], row["away_norm"]):
            if pd.notna(team) and team not in team_r32_date:
                team_r32_date[team] = row["match_date"]

    # Long-form: (team, date) for all non-R32 matches
    pre_rows: list[tuple[str, pd.Timestamp]] = []
    for _, row in all_df[all_df["round_name"] != "Round of 32"].iterrows():
        dt = row["match_date"]
        if pd.notna(row["home_norm"]):
            pre_rows.append((row["home_norm"], dt))
        if pd.notna(row["away_norm"]):
            pre_rows.append((row["away_norm"], dt))

    if not pre_rows:
        logger.info("Rest adjustment: no pre-R32 matches found — skipping.")
        return {}

    hist = pd.DataFrame(pre_rows, columns=["team", "match_date"])

    adjustments: dict[str, float] = {}
    for team in bracket_order:
        r32_date = team_r32_date.get(team)
        if r32_date is None:
            continue
        prev = hist[(hist["team"] == team) & (hist["match_date"] < r32_date)]
        if prev.empty:
            continue
        last_date = prev["match_date"].max()
        rest_days = int((r32_date - last_date).days)
        delta = -0.10 * max(0, 3 - rest_days)
        if delta != 0.0:
            adjustments[team] = delta
            logger.info(
                "Rest adj: %-28s  rest=%dd  delta=%.2f", team, rest_days, delta
            )
        else:
            logger.debug("Rest adj: %-28s  rest=%dd  delta=0.00 (no penalty)", team, rest_days)

    return adjustments


# ---------------------------------------------------------------------------
# Load completed R32 results for lock-in
# ---------------------------------------------------------------------------

def _load_completed_r32(
    conn: duckdb.DuckDBPyConnection,
    bracket_order: list[str],
) -> dict[int, int]:
    """
    Return {sim_match_idx: winner_bracket_pos} for every completed R32 match.

    sim_match_idx is 0-15: match j involves bracket positions 2j (home) and
    2j+1 (away).  winner_bracket_pos is the bracket position (0-31) of the
    team that actually advanced.

    Draw outcomes (FT-Pens) are resolved via data/static/manual_winners.json.
    Unfinished matches are simply omitted — they will be simulated normally.
    """
    bronze    = Path(settings.parquet_bronze_dir)
    espn_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()

    manual_path = Path(__file__).parent.parent.parent / "data" / "static" / "manual_winners.json"
    manual_winners: dict[str, str] = {}
    try:
        raw = json.loads(manual_path.read_text(encoding="utf-8"))
        manual_winners = {str(k): v for k, v in raw.get("events", {}).items()}
    except Exception as exc:
        logger.warning("Could not load manual_winners.json: %s", exc)

    try:
        r32_df = conn.execute(f"""
            SELECT event_id, home_team_name, away_team_name,
                   home_score, away_score, is_completed
            FROM read_parquet('{espn_glob}', union_by_name=true)
            WHERE round_name = 'Round of 32' AND is_completed = TRUE
        """).df()
    except Exception as exc:
        logger.warning("Cannot load completed R32 results: %s — no lock-in.", exc)
        return {}

    if r32_df.empty:
        logger.info("No completed R32 matches — nothing to lock in.")
        return {}

    bracket_team_to_pos: dict[str, int] = {
        team: pos for pos, team in enumerate(bracket_order)
    }

    completed: dict[int, int] = {}
    for row in r32_df.itertuples(index=False):
        home_norm = _normalize(row.home_team_name)
        away_norm = _normalize(row.away_team_name)

        home_pos = bracket_team_to_pos.get(home_norm)
        away_pos = bracket_team_to_pos.get(away_norm)

        if home_pos is None or away_pos is None:
            logger.warning(
                "Cannot find bracket position for '%s' (pos=%s) vs '%s' (pos=%s) — skipping lock-in.",
                row.home_team_name, home_pos, row.away_team_name, away_pos,
            )
            continue

        # Bracket positions for R32 match j: 2j (home, even) and 2j+1 (away, odd).
        # min picks the even position; //2 gives the simulation match index.
        sim_match_idx = min(home_pos, away_pos) // 2

        ev_id = str(int(row.event_id))
        if row.home_score > row.away_score:
            winner_pos = home_pos
        elif row.away_score > row.home_score:
            winner_pos = away_pos
        else:
            # Equal score — FT-Pens or AET draw (resolve via manual_winners.json)
            manual_winner = manual_winners.get(ev_id)
            if not manual_winner:
                logger.warning(
                    "Completed draw in event %s (%s vs %s) has no manual winner — skipping.",
                    ev_id, row.home_team_name, row.away_team_name,
                )
                continue
            winner_norm = _normalize(manual_winner)
            if winner_norm == home_norm:
                winner_pos = home_pos
            elif winner_norm == away_norm:
                winner_pos = away_pos
            else:
                logger.warning(
                    "Manual winner '%s' doesn't match either team in event %s — skipping.",
                    manual_winner, ev_id,
                )
                continue

        completed[sim_match_idx] = winner_pos
        logger.info(
            "R32 lock-in: sim match %d — %s wins (bracket pos %d).",
            sim_match_idx, bracket_order[winner_pos], winner_pos,
        )

    logger.info("Locked %d completed R32 result(s) for simulation.", len(completed))
    return completed


def _load_completed_later_rounds(
    conn: duckdb.DuckDBPyConnection,
    bracket_order: list[str],
    r16_pairs: list[tuple[int, int]],
    completed_r32: dict[int, int],
) -> dict[str, dict[int, int]]:
    """
    Return lock-in dicts for R16, QF, SF, F completed matches.

    Each dict maps sim_match_idx → winner_original_bracket_pos (0-31),
    analogous to completed_r32.  Only called after _load_completed_r32 so
    we can resolve R32 winners into bracket positions first.

    Returns: {"R16": {...}, "QF": {...}, "SF": {...}, "F": {...}}
    """
    bronze    = Path(settings.parquet_bronze_dir)
    espn_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()

    manual_path = Path(__file__).parent.parent.parent / "data" / "static" / "manual_winners.json"
    manual_winners: dict[str, str] = {}
    try:
        raw = json.loads(manual_path.read_text(encoding="utf-8"))
        manual_winners = {str(k): v for k, v in raw.get("events", {}).items()}
    except Exception:
        pass

    round_map = {
        "Round of 16": "R16",
        "Quarterfinal": "QF",
        "Semifinal": "SF",
        "Final": "F",
    }

    try:
        later_df = conn.execute(f"""
            SELECT event_id, round_name, home_team_name, away_team_name,
                   home_score, away_score
            FROM read_parquet('{espn_glob}', union_by_name=true)
            WHERE round_name IN ('Round of 16','Quarterfinal','Semifinal','Final')
              AND is_completed = TRUE
        """).df()
    except Exception as exc:
        logger.warning("Cannot load completed R16+ results: %s", exc)
        return {}

    if later_df.empty:
        return {}

    # Map canonical name → original bracket position (0-31)
    team_to_bracket_pos: dict[str, int] = {
        team: pos for pos, team in enumerate(bracket_order)
    }

    result: dict[str, dict[int, int]] = {"R16": {}, "QF": {}, "SF": {}, "F": {}}

    # Build expected bracket-slot ordering for R16: slot j → (r32_a_idx, r32_b_idx)
    # r16_pairs[j] = (espn_r32_idx_a, espn_r32_idx_b); bracket positions for
    # slot j are (2j, 2j+1) in the bracket array after R32.
    # We need to map each completed R16 match to a slot index (0-7).
    #
    # Strategy: for each completed R16 row, look up BOTH teams' original bracket
    # positions, then derive which R16 slot that is.
    #
    # After R32, the surviving team from bracket match j occupies slot j in the
    # 16-team array.  R16 slot k contains bracket-level positions 2k and 2k+1
    # (one from each of the two R32 matches in r16_pairs[k]).

    # Build a helper: original bracket pos → R16 slot
    # R16 slot k contains R32 winners from r16_pairs[k] = (a, b).
    # R32 match a produces the winner from bracket positions 2a,2a+1.
    # In our bracket_order layout, r16_pairs[k] = (a, b) where a and b are
    # ESPN R32 match indices.  Bracket position for R32 match j is 2j/2j+1.
    # After lock-in, completed_r32[j] gives the winner bracket pos.
    # For unsimulated R32 matches (not in completed_r32), we don't know
    # the winner upfront — but we can still match by team name.

    for _, row in later_df.iterrows():
        rnd_code = round_map.get(row["round_name"])
        if rnd_code is None:
            continue

        home_norm = _normalize(str(row["home_team_name"]))
        away_norm = _normalize(str(row["away_team_name"]))

        home_bpos = team_to_bracket_pos.get(home_norm)
        away_bpos = team_to_bracket_pos.get(away_norm)

        if home_bpos is None or away_bpos is None:
            logger.warning(
                "%s lock-in: cannot map '%s' or '%s' to bracket position — skipping.",
                rnd_code, row["home_team_name"], row["away_team_name"],
            )
            continue

        # Determine winner
        ev_id = str(int(row["event_id"]))
        if float(row["home_score"]) > float(row["away_score"]):
            winner_bpos = home_bpos
        elif float(row["away_score"]) > float(row["home_score"]):
            winner_bpos = away_bpos
        else:
            manual_winner = manual_winners.get(ev_id)
            if not manual_winner:
                logger.warning(
                    "%s draw event %s (%s vs %s) has no manual winner — skipping.",
                    rnd_code, ev_id, row["home_team_name"], row["away_team_name"],
                )
                continue
            winner_norm = _normalize(manual_winner)
            winner_bpos = home_bpos if winner_norm == home_norm else (
                away_bpos if winner_norm == away_norm else None
            )
            if winner_bpos is None:
                continue

        # Derive sim_match_idx for this round.
        # In R16 (16 teams alive): slot k holds the two R32 winners from
        # r16_pairs[k].  Those winners came from bracket positions within
        # r16_pairs[k] sub-section: bracket positions 4k, 4k+1, 4k+2, 4k+3
        # in the original 32-slot bracket.
        # Slot k = home_bpos // 4  (both teams from same 4-slot section).
        if rnd_code == "R16":
            sim_match_idx = min(home_bpos, away_bpos) // 4
        elif rnd_code == "QF":
            sim_match_idx = min(home_bpos, away_bpos) // 8
        elif rnd_code == "SF":
            sim_match_idx = min(home_bpos, away_bpos) // 16
        else:  # Final
            sim_match_idx = 0

        result[rnd_code][sim_match_idx] = winner_bpos
        logger.info(
            "%s lock-in: slot %d — %s wins (bracket pos %d).",
            rnd_code, sim_match_idx, bracket_order[winner_bpos], winner_bpos,
        )

    for rnd, d in result.items():
        if d:
            logger.info("Locked %d completed %s result(s) for simulation.", len(d), rnd)

    return result


# ---------------------------------------------------------------------------
# Per-match Bradley-Terry probabilities
# ---------------------------------------------------------------------------

def _write_match_probs(
    conn: duckdb.DuckDBPyConnection,
    bracket_order: list[str],
    strengths: np.ndarray,
    scale: float,
    run_date: "date",
) -> None:
    """
    Compute and store the raw head-to-head BT probability for each R32 match.

    These are computed BEFORE the simulation and BEFORE any lock-in override,
    so they reflect the model's genuine prediction for each game regardless of
    whether the match has already been played.  export_json.py reads this table
    to display per-match model probabilities on the matchups page.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_probs (
            run_date   DATE    NOT NULL,
            team_left  VARCHAR NOT NULL,
            team_right VARCHAR NOT NULL,
            prob_left  DOUBLE  NOT NULL,
            prob_right DOUBLE  NOT NULL,
            PRIMARY KEY (run_date, team_left, team_right)
        )
    """)
    conn.execute("DELETE FROM match_probs WHERE run_date = ?", [str(run_date)])

    n_matches = len(strengths) // 2
    rows: list[tuple] = []
    for j in range(n_matches):
        s_l = float(strengths[2 * j])
        s_r = float(strengths[2 * j + 1])
        p_l = advance_prob(s_l, s_r, scale)
        rows.append((str(run_date), bracket_order[2 * j], bracket_order[2 * j + 1], p_l, 1.0 - p_l))

    conn.executemany(
        "INSERT INTO match_probs (run_date, team_left, team_right, prob_left, prob_right) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    logger.info("match_probs: wrote %d R32 BT probabilities for %s.", len(rows), run_date)


def _write_r16_match_probs(
    conn: duckdb.DuckDBPyConnection,
    bracket_order: list[str],
    strengths: np.ndarray,
    scale: float,
    run_date: "date",
    completed_r32: dict[int, int],
) -> None:
    """
    Compute and store the head-to-head BT probability for each R16 matchup.

    For R32 slots that have a confirmed winner, uses that team's strength.
    For pending R32 slots, uses the stronger of the two possible teams as
    the projected representative.

    Written to a separate match_probs_r16 table (same schema as match_probs).
    export_json.py reads this table so R16 completed matches show pre-kick
    probabilities instead of the post-lock-in 100%/0%.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_probs_r16 (
            run_date   DATE    NOT NULL,
            team_left  VARCHAR NOT NULL,
            team_right VARCHAR NOT NULL,
            prob_left  DOUBLE  NOT NULL,
            prob_right DOUBLE  NOT NULL,
            PRIMARY KEY (run_date, team_left, team_right)
        )
    """)
    conn.execute("DELETE FROM match_probs_r16 WHERE run_date = ?", [str(run_date)])

    rows: list[tuple] = []
    for k in range(8):
        # R16 slot k pairs the winners of R32 matches 2k (left) and 2k+1 (right).
        # R32 match j occupies bracket positions 2j and 2j+1.
        # So left R32 match 2k → bracket positions 4k, 4k+1.
        #    right R32 match 2k+1 → bracket positions 4k+2, 4k+3.

        r32_left = 2 * k
        if r32_left in completed_r32:
            pos_l = completed_r32[r32_left]
        else:
            p0, p1 = 4 * k, 4 * k + 1
            pos_l = p0 if strengths[p0] >= strengths[p1] else p1

        r32_right = 2 * k + 1
        if r32_right in completed_r32:
            pos_r = completed_r32[r32_right]
        else:
            p2, p3 = 4 * k + 2, 4 * k + 3
            pos_r = p2 if strengths[p2] >= strengths[p3] else p3

        s_l = float(strengths[pos_l])
        s_r = float(strengths[pos_r])
        p_l = advance_prob(s_l, s_r, scale)
        rows.append((str(run_date), bracket_order[pos_l], bracket_order[pos_r], p_l, 1.0 - p_l))

    conn.executemany(
        "INSERT INTO match_probs_r16 (run_date, team_left, team_right, prob_left, prob_right) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    logger.info("match_probs_r16: wrote %d R16 BT probabilities for %s.", len(rows), run_date)


# ---------------------------------------------------------------------------
# Vectorised single-elimination tournament
# ---------------------------------------------------------------------------

def _run_sim(
    strengths: np.ndarray,
    n_sim: int,
    scale: float,
    seed: int,
    completed_r32: dict[int, int] | None = None,
    completed_later: dict[str, dict[int, int]] | None = None,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """
    Pure NumPy vectorised Monte Carlo bracket.

    All n_sim tournaments run simultaneously — no Python loop over iterations.
    One Python loop over the 5 rounds (R32→R16→QF→SF→F→W) is unavoidable.

    Returns
    -------
    advance_counts : (n_teams, n_rounds) int64
        advance_counts[i, r] = # sims where team i reached round r.
        r=0 (R32) = n_sim for all; r=5 (W) = title count.
    slot_winners : dict[round_code → (n_sim, n_slots) int16]
        slot_winners["R32"][:, j] = team index that won R32 match j in each sim.
        slot_winners["R16"][:, j] = team index that won R16 match j in each sim.
        etc.  Used to build the joint bracket-slot distribution for PR4.
    """
    rng     = np.random.default_rng(seed)
    n_teams = len(strengths)
    n_rounds = len(ROUNDS)

    advance_counts = np.zeros((n_teams, n_rounds), dtype=np.int64)
    advance_counts[:, 0] = n_sim   # every team starts in R32

    slot_winners: dict[str, np.ndarray] = {}

    # current[sim, bracket_pos] = team index at that position
    current = np.broadcast_to(
        np.arange(n_teams, dtype=np.int32), (n_sim, n_teams)
    ).copy()

    for round_idx in range(1, n_rounds):
        n_alive  = current.shape[1]
        n_matches = n_alive // 2

        left  = current[:, 0::2]    # (n_sim, n_matches)
        right = current[:, 1::2]

        s_left  = strengths[left]   # NumPy fancy indexing → same shape
        s_right = strengths[right]

        p_left = advance_prob_vec(s_left, s_right, scale)
        rand   = rng.random((n_sim, n_matches))

        winners = np.where(rand < p_left, left, right)

        # Override with confirmed results so completed matches aren't re-simulated.
        # R32 (round_idx==1): team indices == bracket positions, direct assignment.
        # R16/QF/SF/F: winners array at this point holds original bracket positions
        # (team indices), so assigning winner_bracket_pos is equally valid.
        round_code = ROUNDS[round_idx - 1]
        if round_idx == 1 and completed_r32:
            for match_idx, winner_bracket_pos in completed_r32.items():
                winners[:, match_idx] = winner_bracket_pos
        elif completed_later:
            later = completed_later.get(round_code, {})
            for match_idx, winner_bracket_pos in later.items():
                if match_idx < winners.shape[1]:
                    winners[:, match_idx] = winner_bracket_pos

        current = winners

        # Store who wins each match slot for this round (int16 saves ~50% memory vs int32)
        # ROUNDS[round_idx - 1] is the round whose matches just finished.
        # (round_idx=1 plays R32 matches → slot_winners["R32"])
        slot_winners[ROUNDS[round_idx - 1]] = winners.astype(np.int16)

        flat   = winners.ravel()
        counts = np.bincount(flat, minlength=n_teams)
        advance_counts[:, round_idx] = counts

    return advance_counts, slot_winners


# ---------------------------------------------------------------------------
# Bracket-slot distribution builder  (PR4)
# ---------------------------------------------------------------------------

def _compute_bracket_slots(
    slot_winners: dict[str, np.ndarray],
    bracket_order: list[str],
    n_sim: int,
    run_date: date,
    r16_pairs: list[tuple[int, int]],
) -> dict:
    """
    Convert per-sim slot-winner arrays into a JSON-serialisable distribution.

    For each (round, slot_idx) returns the top team plus up to 4 alternates
    with their probability of winning that specific match slot.  The frontend
    uses this to fix the Colombia-over-Argentina bracket-coherence bug.

    R32 slots are exported using ESPN chronological match indices so they align
    with the matchups API response (r32.matches[j]).  R16+ slots use the
    natural bracket slot indices (already sequential).

    Also exports `pairings` so the frontend can correctly pair R32 matches
    into R16 slots without assuming sequential ESPN order.

    Output shape
    ------------
    {
      "run_date": "2026-06-30",
      "slots": [...],
      "pairings": {
        "R16": [[0,2],[3,5],...],   # ESPN R32 match indices feeding each R16 slot
        "QF":  [[0,1],[2,3],[4,5],[6,7]],
        "SF":  [[0,1],[2,3]],
        "F":   [[0,1]]
      }
    }
    """
    # Map bracket_match_j → espn_match_idx for R32
    # bracket match 2i and 2i+1 come from r16_pairs[i] = (a, b)
    bracket_to_espn: dict[int, int] = {}
    for i, (a, b) in enumerate(r16_pairs):
        bracket_to_espn[2 * i]     = a
        bracket_to_espn[2 * i + 1] = b

    n_teams = len(bracket_order)
    slots: list[dict] = []

    for round_code in ["R32", "R16", "QF", "SF", "F"]:
        sw = slot_winners.get(round_code)
        if sw is None:
            continue
        n_slots = sw.shape[1]
        for slot_j in range(n_slots):
            counts = np.bincount(sw[:, slot_j].astype(np.intp), minlength=n_teams)
            sorted_idx = np.argsort(-counts)
            entries = [
                {"team": bracket_order[int(t)], "prob": round(float(counts[t]) / n_sim, 4)}
                for t in sorted_idx
                if counts[t] > 0
            ]
            if entries:
                # R32: export by ESPN chronological index so the frontend's
                # r32.matches[j] aligns with slotMap["R32:j"] without remapping.
                export_idx = bracket_to_espn.get(slot_j, slot_j) if round_code == "R32" else slot_j
                slots.append({
                    "round":    round_code,
                    "slot_idx": int(export_idx),
                    "top":      entries[0],
                    "alt":      entries[1:5],   # up to 4 alternates
                })

    pairings = {
        "R16": [[a, b] for a, b in r16_pairs],  # ESPN R32 match indices
        "QF":  [[0, 1], [2, 3], [4, 5], [6, 7]],
        "SF":  [[0, 1], [2, 3]],
        "F":   [[0, 1]],
    }

    return {"run_date": str(run_date), "slots": slots, "pairings": pairings}


# ---------------------------------------------------------------------------
# Build results DataFrame
# ---------------------------------------------------------------------------

def _build_results(
    bracket_order: list[str],
    advance_counts: np.ndarray,
    n_sim: int,
    run_date: date,
) -> pd.DataFrame:
    title_counts = advance_counts[:, -1]
    rows: list[dict] = []
    for pos, team in enumerate(bracket_order):
        tp = float(title_counts[pos] / n_sim)
        for r_idx, rnd in enumerate(ROUNDS):
            rows.append({
                "run_date":     run_date,
                "round":        rnd,
                "team_id":      team,
                "advance_prob": float(advance_counts[pos, r_idx] / n_sim),
                "title_prob":   tp,
                "n_iterations": n_sim,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# DuckDB write
# ---------------------------------------------------------------------------

def _write_simulations(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    today = str(df["run_date"].iloc[0])
    conn.execute("DELETE FROM simulations WHERE run_date = ?", [today])
    conn.register("_sim_results", df)
    conn.execute("""
        INSERT INTO simulations
        SELECT run_date, round, team_id, advance_prob, title_prob, n_iterations
        FROM _sim_results
    """)
    conn.unregister("_sim_results")
    n_total = conn.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
    logger.info("simulations: %d rows total after upsert.", n_total)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(
    bracket_order: list[str],
    results: pd.DataFrame,
    strengths_map: dict[str, float],
) -> None:
    # Print actual R32 matchups so the user can verify against the real bracket
    logger.info("=== R32 matchups being simulated ===")
    for i in range(0, 32, 2):
        home = bracket_order[i]
        away = bracket_order[i + 1]
        sh = strengths_map.get(home, float("nan"))
        sa = strengths_map.get(away, float("nan"))
        logger.info("  M%02d: %-28s (%.3f) vs %-28s (%.3f)", i // 2 + 1, home, sh, away, sa)

    title_rows = (
        results[results["round"] == "W"][["team_id", "title_prob"]]
        .sort_values("title_prob", ascending=False)
    )
    logger.info("=== Top-10 title probabilities ===")
    for _, row in title_rows.head(10).iterrows():
        logger.info("  %-28s  %.1f%%", row["team_id"], row["title_prob"] * 100)

    total = title_rows["title_prob"].sum()
    logger.info("Title prob sum = %.6f (expect 1.0)", total)
    if abs(total - 1.0) > 0.005:
        raise RuntimeError(f"Title probs sum to {total:.4f} — check simulation logic.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Monte Carlo WC bracket sim.")
    parser.add_argument("--validate", action="store_true",
                        help="Dry-run: print results but skip DB write.")
    parser.add_argument("--scale",  type=float, default=None,
                        help="Logistic scale override (default: load from model_params or 1.0).")
    parser.add_argument("--n-sim",  type=int,   default=N_SIM)
    parser.add_argument("--seed",   type=int,   default=SEED)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    conn = duckdb.connect(str(settings.duckdb_path), read_only=args.validate)

    if args.scale is None:
        args.scale = load_fitted_scale(conn)

    try:
        t0 = time.perf_counter()

        # 1. Load actual bracket from Bronze
        bracket_order, r16_pairs = _load_bracket(conn)

        # 2. Team strengths from player_ratings
        strengths_map, strength_df = _build_team_strengths(conn)

        # 3. Coverage check — replace any NaN entries (AVG returned NULL when
        #    posterior_mean was all-NaN), then fill teams absent from the map.
        _fb = fallback_strength(conn)
        strengths_map = {
            t: (v if np.isfinite(v) else _fb)
            for t, v in strengths_map.items()
        }

        missing = [t for t in bracket_order if t not in strengths_map]
        if missing:
            logger.warning(
                "%d bracket team(s) not in player_ratings — using fallback=%.4f: %s",
                len(missing), _fb, missing,
            )
            for t in missing:
                strengths_map[t] = _fb

        # 3c. Rest/travel penalty  (PR5b.1)
        rest_adj = _compute_rest_adjustments(conn, bracket_order)
        if rest_adj:
            for team, delta in rest_adj.items():
                if team in strengths_map:
                    strengths_map[team] = max(1.0, strengths_map[team] + delta)
            logger.info("Applied rest adjustments to %d team(s).", len(rest_adj))
        else:
            logger.info("No rest adjustments applied (3+ rest days for all teams).")

        # 4. Ordered strength vector
        strengths_vec = np.array(
            [strengths_map[t] for t in bracket_order], dtype=np.float64
        )

        # 4b. Load completed R32 results so the sim locks in actual winners
        completed_r32 = _load_completed_r32(conn, bracket_order)

        # 4b2. Load completed R16/QF/SF/F results for lock-in
        completed_later = _load_completed_later_rounds(
            conn, bracket_order, r16_pairs, completed_r32
        )

        # 4c. Persist per-match BT probabilities BEFORE simulation and lock-in.
        #     export_json.py reads these to display what the model predicted for
        #     each game, so completed matches don't show 100%/0%.
        if not args.validate:
            _write_match_probs(conn, bracket_order, strengths_vec, args.scale, date.today())
            _write_r16_match_probs(conn, bracket_order, strengths_vec, args.scale, date.today(), completed_r32)

        # 5. Simulate
        logger.info(
            "Running %d iterations (scale=%.2f, seed=%d) ...",
            args.n_sim, args.scale, args.seed,
        )
        advance_counts, slot_winners = _run_sim(
            strengths=strengths_vec,
            n_sim=args.n_sim,
            scale=args.scale,
            seed=args.seed,
            completed_r32=completed_r32,
            completed_later=completed_later,
        )
        elapsed = time.perf_counter() - t0
        logger.info("Simulation complete in %.2fs.", elapsed)

        # 6. Build marginal results + bracket slot distributions
        today = date.today()
        results = _build_results(
            bracket_order=bracket_order,
            advance_counts=advance_counts,
            n_sim=args.n_sim,
            run_date=today,
        )
        bracket_slots_data = _compute_bracket_slots(
            slot_winners=slot_winners,
            bracket_order=bracket_order,
            n_sim=args.n_sim,
            run_date=today,
            r16_pairs=r16_pairs,
        )

        # 7. Validate
        _validate(bracket_order, results, strengths_map)

        # 8. Write or print
        if args.validate:
            logger.info("--validate: skipping DB write.")
            print("\n=== Strength table (bracket teams only) ===")
            bracket_strength = strength_df[
                strength_df["team"].isin(bracket_order)
            ].sort_values("strength", ascending=False)
            print(bracket_strength.to_string(index=False))
            print("\n=== R16 bracket pairings (R32 ESPN match indices) ===")
            for i, (a, b) in enumerate(r16_pairs):
                print(f"  R16[{i}]: R32[{a}] ({bracket_order[2*i]}) vs R32[{b}] ({bracket_order[2*i+1]})")
            print(f"\n  pairings.R16 = {bracket_slots_data['pairings']['R16']}")
            print("\n=== Advance probabilities by round ===")
            pivot = (
                results.pivot(index="team_id", columns="round", values="advance_prob")
                [ROUNDS]
                .sort_values("W", ascending=False)
            )
            pivot.columns.name = None
            print(pivot.round(3).to_string())
        else:
            _write_simulations(conn, results)
            # Write bracket_slots.json to Silver directory (loaded by export_json.py)
            bracket_slots_path = Path(settings.parquet_silver_dir) / "bracket_slots.json"
            bracket_slots_path.write_text(
                json.dumps(bracket_slots_data, ensure_ascii=False), encoding="utf-8"
            )
            logger.info(
                "Done. run_date=%s | %d teams | %d rows written | bracket_slots.json: %d slots.",
                today, len(bracket_order), len(results), len(bracket_slots_data["slots"]),
            )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
