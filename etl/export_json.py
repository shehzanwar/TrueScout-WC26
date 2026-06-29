"""
Export DuckDB tables to static JSON files for Vercel frontend consumption.

Runs after run_nightly.py completes — this is the final step of the pipeline.

    python etl/export_json.py

Output: frontend/public/data/{players,simulations,matchups,brier}.json

All four files mirror the shapes returned by the FastAPI endpoints so that
frontend/lib/server-data.ts can drop-in replace the API calls.
"""
import json
import math
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

from config import settings  # noqa: E402 — after sys.path fix
from etl.db.connection import get_write_conn  # noqa: E402

OUTPUT_DIR = ROOT_DIR / "frontend" / "public" / "data"

ROUND_ORDER = ["R32", "R16", "QF", "SF", "F", "W"]
ROUND_LABELS = {
    "R32": "Round of 32",
    "R16": "Round of 16",
    "QF":  "Quarterfinal",
    "SF":  "Semifinal",
    "F":   "Final",
    "W":   "Champion",
}
ROUND_MAP = {
    "R32": "Round of 32",
    "R16": "Round of 16",
    "QF":  "Quarterfinal",
    "SF":  "Semifinal",
    "F":   "Final",
}
NEXT_ROUND = {"R32": "R16", "R16": "QF", "QF": "SF", "SF": "F", "F": "W"}
NAME_ALIASES = {
    "Bosnia-Herzegovina":     "Bosnia & Herzegovina",
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Cabo Verde":             "Cape Verde",
    "Côte d'Ivoire":          "Ivory Coast",
    "Cote d'Ivoire":          "Ivory Coast",
    "DR Congo":               "Congo DR",
    "USA":                    "United States",
}
COIN_BRIER   = 0.25
COIN_LOGLOSS = math.log(2)  # ≈ 0.6931


def _safe_float(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


def _safe_str(v):
    """Return None for None/NaN, else str(v)."""
    if v is None:
        return None
    try:
        if math.isnan(float(v)):
            return None
    except (TypeError, ValueError):
        pass
    return str(v)


# ---------------------------------------------------------------------------
# Simulations
# ---------------------------------------------------------------------------

def export_simulations(conn) -> dict:
    rows = conn.execute("""
        SELECT run_date, round, team_id, advance_prob, title_prob, n_iterations
        FROM simulations
        WHERE run_date = (SELECT MAX(run_date) FROM simulations)
        ORDER BY round, advance_prob DESC
    """).fetchall()

    if not rows:
        return {"run_date": "", "n_iterations": 0, "rounds": []}

    run_date     = str(rows[0][0])
    n_iterations = int(rows[0][5])

    by_round: dict = {r: [] for r in ROUND_ORDER}
    for _, rnd, team_id, advance_prob, title_prob, _ in rows:
        if rnd in by_round:
            by_round[rnd].append({
                "team_id":      team_id,
                "advance_prob": round(float(advance_prob), 4),
                "title_prob":   round(float(title_prob), 4),
            })

    rounds = [
        {"round": rnd, "round_label": ROUND_LABELS.get(rnd, rnd), "teams": by_round[rnd]}
        for rnd in ROUND_ORDER
        if by_round[rnd]
    ]
    return {"run_date": run_date, "n_iterations": n_iterations, "rounds": rounds}


# ---------------------------------------------------------------------------
# Matchups  (all rounds in one object keyed by round code)
# ---------------------------------------------------------------------------

def export_matchups(conn) -> dict:
    bronze       = Path(settings.parquet_bronze_dir)
    matches_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()
    odds_glob    = (bronze / "espn" / "odds"    / "*.parquet").as_posix()

    result: dict = {}
    for round_code, round_name in ROUND_MAP.items():
        next_round = NEXT_ROUND.get(round_code, "W")
        sim_rows   = conn.execute("""
            SELECT team_id, advance_prob FROM simulations
            WHERE round = ?
              AND run_date = (SELECT MAX(run_date) FROM simulations)
        """, [next_round]).fetchall()
        sim_map = {team: float(prob) for team, prob in sim_rows}

        try:
            fixture_rows = conn.execute(f"""
                SELECT
                    m.event_id, m.match_date, m.round_name,
                    m.home_team_name, m.home_team_abbrev,
                    m.away_team_name, m.away_team_abbrev,
                    m.home_score, m.away_score, m.is_completed,
                    o.home_win_prob, o.draw_prob, o.away_win_prob
                FROM read_parquet('{matches_glob}', union_by_name=true) m
                LEFT JOIN read_parquet('{odds_glob}', union_by_name=true) o
                    ON m.event_id = o.event_id
                WHERE m.round_name = ?
                ORDER BY m.match_date, CAST(m.event_id AS BIGINT)
            """, [round_name]).fetchall()
        except Exception:
            fixture_rows = []

        matches = []
        for row in fixture_rows:
            (event_id, match_date, round_name_val,
             h_name, h_abbrev, a_name, a_abbrev,
             h_score, a_score, is_completed,
             home_win_prob, draw_prob, away_win_prob) = row

            h_norm = NAME_ALIASES.get(h_name, h_name) if h_name else h_name
            a_norm = NAME_ALIASES.get(a_name, a_name) if a_name else a_name

            market_home = market_away = None
            if home_win_prob is not None and away_win_prob is not None:
                try:
                    hw = float(home_win_prob)
                    dp = float(draw_prob) if draw_prob is not None else 0.0
                    aw = float(away_win_prob)
                    if hw == hw and aw == aw:  # NaN guard
                        market_home = round(hw + dp * 0.5, 4)
                        market_away = round(1.0 - market_home, 4)
                except (TypeError, ValueError):
                    pass

            model_home = sim_map.get(h_norm)
            model_away = sim_map.get(a_norm)
            if model_home is not None:
                model_home = round(model_home, 4)
            if model_away is not None:
                model_away = round(model_away, 4)

            matches.append({
                "event_id":    str(event_id),
                "match_date":  str(match_date),
                "round":       round_name_val,
                "is_completed": bool(is_completed),
                "home": {
                    "name":               h_norm,
                    "abbrev":             h_abbrev,
                    "score":              int(h_score) if h_score is not None else None,
                    "model_advance_prob": model_home,
                    "market_advance_prob": market_home,
                },
                "away": {
                    "name":               a_norm,
                    "abbrev":             a_abbrev,
                    "score":              int(a_score) if a_score is not None else None,
                    "model_advance_prob": model_away,
                    "market_advance_prob": market_away,
                },
            })

        result[round_code] = {
            "round_code": round_code,
            "round_name": round_name,
            "n_matches":  len(matches),
            "matches":    matches,
        }

    return result


# ---------------------------------------------------------------------------
# Brier calibration log
# ---------------------------------------------------------------------------

def export_brier(conn) -> dict:
    rows = conn.execute("""
        SELECT event_id, CAST(run_date AS VARCHAR), round,
               home_team, away_team, advanced_team,
               model_prob, market_prob, brier_model, brier_market,
               log_loss_model, log_loss_market
        FROM brier_log
        ORDER BY run_date DESC, logged_at DESC
    """).fetchall()

    entries = []
    for row in rows:
        (event_id, run_date, rnd, home_team, away_team, advanced_team,
         model_prob, market_prob, brier_model, brier_market,
         log_loss_model, log_loss_market) = row
        entries.append({
            "event_id":       str(event_id),
            "run_date":       str(run_date),
            "round":          rnd,
            "home_team":      home_team,
            "away_team":      away_team,
            "advanced_team":  advanced_team,
            "model_prob":     _safe_float(model_prob),
            "market_prob":    _safe_float(market_prob),
            "brier_model":    _safe_float(brier_model),
            "brier_market":   _safe_float(brier_market),
            "log_loss_model": _safe_float(log_loss_model),
            "log_loss_market":_safe_float(log_loss_market),
        })

    brier_vals   = [e["brier_model"]    for e in entries if e["brier_model"]    is not None]
    ll_vals      = [e["log_loss_model"] for e in entries if e["log_loss_model"] is not None]
    brier_m_vals = [e["brier_market"]   for e in entries if e["brier_market"]   is not None]
    ll_m_vals    = [e["log_loss_market"] for e in entries if e["log_loss_market"] is not None]

    avg_brier_model  = round(sum(brier_vals)   / len(brier_vals),   4) if brier_vals  else None
    avg_ll_model     = round(sum(ll_vals)      / len(ll_vals),      4) if ll_vals     else None
    avg_brier_market = round(sum(brier_m_vals) / len(brier_m_vals), 4) if brier_m_vals else None
    avg_ll_market    = round(sum(ll_m_vals)    / len(ll_m_vals),    4) if ll_m_vals   else None

    def _skill(model, baseline):
        if model is None or not baseline:
            return None
        return round(1.0 - model / baseline, 4)

    summary = {
        "n_matches":            len(entries),
        "n_with_market":        sum(1 for e in entries if e["market_prob"] is not None),
        "avg_brier_model":      avg_brier_model,
        "avg_brier_market":     avg_brier_market,
        "avg_log_loss_model":   avg_ll_model,
        "avg_log_loss_market":  avg_ll_market,
        "coin_flip_brier":      COIN_BRIER,
        "coin_flip_log_loss":   round(COIN_LOGLOSS, 4),
        "brier_skill_vs_coin":  _skill(avg_brier_model, COIN_BRIER),
        "brier_skill_vs_market": _skill(avg_brier_model, avg_brier_market) if avg_brier_market else None,
    }
    return {"summary": summary, "entries": entries}


# ---------------------------------------------------------------------------
# Players  (full profiles — used for search + player detail page)
# ---------------------------------------------------------------------------

def export_players(conn) -> list:
    rows = conn.execute("""
        WITH prior_rank AS (
            SELECT
                reep_id,
                PERCENT_RANK() OVER (
                    PARTITION BY position_macro ORDER BY prior_mean
                ) AS prior_pct
            FROM player_ratings
        )
        SELECT
            pr.reep_id,
            ip.name,
            ip.nationality,
            ip.position_detail,
            pr.position_macro,
            pr.position_micro,
            pr.cluster_id,
            arc.cluster_label,
            arc.position_bucket,
            pr.prior_mean,
            pr.posterior_mean,
            pr.posterior_std,
            pr.hdi_low,
            pr.hdi_high,
            pr.shrinkage_weight,
            pr.wc_minutes,
            pr.confidence_score,
            pr.percentile_rank,
            rk.prior_pct
        FROM player_ratings pr
        LEFT JOIN identity_players ip  ON pr.reep_id = ip.reep_id
        LEFT JOIN archetypes       arc ON pr.reep_id = arc.reep_id
        JOIN prior_rank             rk ON pr.reep_id = rk.reep_id
        ORDER BY pr.confidence_score DESC, pr.posterior_mean DESC
    """).fetchall()

    players = []
    for row in rows:
        (reep_id, name, nationality, position_detail,
         position_macro, position_micro, cluster_id, cluster_label, position_bucket,
         prior_mean, posterior_mean, posterior_std, hdi_low, hdi_high,
         shrinkage_weight, wc_minutes, confidence_score, percentile_rank, prior_pct) = row

        players.append({
            "reep_id":          reep_id,
            "name":             _safe_str(name),
            "nationality":      _safe_str(nationality),
            "position_detail":  _safe_str(position_detail),
            "position_macro":   position_macro,
            "position_micro":   _safe_str(position_micro),
            "cluster_id":       int(cluster_id),
            "cluster_label":    _safe_str(cluster_label),
            "position_bucket":  position_bucket,
            "prior_mean":       round(float(prior_mean), 4),
            "posterior_mean":   round(float(posterior_mean), 4),
            "posterior_std":    round(float(posterior_std), 4),
            "hdi_low":          round(float(hdi_low), 4),
            "hdi_high":         round(float(hdi_high), 4),
            "shrinkage_weight": round(float(shrinkage_weight), 4),
            "wc_minutes":       round(float(wc_minutes), 1),
            "confidence_score": round(float(confidence_score), 4),
            "percentile_rank":  round(float(percentile_rank), 4),
            "radar": {
                "posterior_pct": round(float(percentile_rank), 4),
                "wc_experience": round(min(float(wc_minutes) / 270.0, 1.0), 4),
                "confidence":    round(float(confidence_score), 4),
                "prior_pct":     round(float(prior_pct), 4),
                "wc_dominance":  round(1.0 - float(shrinkage_weight), 4),
            },
        })

    return players


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_write_conn()

    print("Exporting simulations.json …")
    sims = export_simulations(conn)
    (OUTPUT_DIR / "simulations.json").write_text(
        json.dumps(sims, separators=(",", ":")), encoding="utf-8"
    )
    print(f"  ✓  {len(sims['rounds'])} rounds")

    print("Exporting matchups.json …")
    matchups = export_matchups(conn)
    (OUTPUT_DIR / "matchups.json").write_text(
        json.dumps(matchups, separators=(",", ":")), encoding="utf-8"
    )
    total = sum(v["n_matches"] for v in matchups.values())
    print(f"  ✓  {total} total fixtures across {len(matchups)} rounds")

    print("Exporting brier.json …")
    brier = export_brier(conn)
    (OUTPUT_DIR / "brier.json").write_text(
        json.dumps(brier, separators=(",", ":")), encoding="utf-8"
    )
    print(f"  ✓  {brier['summary']['n_matches']} graded matches")

    print("Exporting players.json …")
    players = export_players(conn)
    (OUTPUT_DIR / "players.json").write_text(
        json.dumps(players, separators=(",", ":")), encoding="utf-8"
    )
    print(f"  ✓  {len(players)} players")

    print("Export complete →", OUTPUT_DIR)


if __name__ == "__main__":
    main()
