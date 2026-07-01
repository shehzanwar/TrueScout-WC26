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

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

from config import settings  # noqa: E402 — after sys.path fix
from etl.db.connection import get_write_conn  # noqa: E402
from etl.utils.team_aliases import TEAM_ALIASES, normalize as _norm_team  # noqa: E402

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
NAME_ALIASES = TEAM_ALIASES
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
                "advance_prob": _safe_float(advance_prob),
                "title_prob":   _safe_float(title_prob),
            })

    rounds = [
        {"round": rnd, "round_label": ROUND_LABELS.get(rnd, rnd), "teams": by_round[rnd]}
        for rnd in ROUND_ORDER
        if by_round[rnd]
    ]

    # Merge per-slot joint distributions and pairings from monte_carlo_sim.py
    bracket_slots_path = Path(settings.parquet_silver_dir) / "bracket_slots.json"
    bracket_slots = None
    pairings = None
    if bracket_slots_path.exists():
        bracket_slots_raw = json.loads(bracket_slots_path.read_text(encoding="utf-8"))
        bracket_slots = bracket_slots_raw.get("slots")
        pairings = bracket_slots_raw.get("pairings")

    out: dict = {"run_date": run_date, "n_iterations": n_iterations, "rounds": rounds}
    if bracket_slots is not None:
        out["bracket_slots"] = bracket_slots
    if pairings is not None:
        out["pairings"] = pairings
    return out


# ---------------------------------------------------------------------------
# Rest-days helper for matchups (PR5b.1)
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two (lat, lon) points."""
    R = 6_371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _venue_coords() -> dict[str, tuple[float, float]]:
    """Load venues_2026.json and return {venue_name_lower: (lat, lon)}."""
    venues_path = ROOT_DIR / "data" / "static" / "venues_2026.json"
    try:
        raw = json.loads(venues_path.read_text(encoding="utf-8"))
        return {
            k.lower(): (float(v["lat"]), float(v["lon"]))
            for k, v in raw.get("venues", {}).items()
        }
    except Exception as exc:
        print(f"Warning: could not load venues_2026.json: {exc}", file=sys.stderr)
        return {}


def _build_travel_km(matches_glob: str) -> dict[str, tuple[int | None, int | None]]:
    """
    For every match in Bronze, compute how far each team travelled since their
    previous match (great-circle distance between venue coordinates).

    Returns: {event_id_str: (home_travel_km, away_travel_km)}
    Either element is None when the team's previous venue is unknown or the
    current venue could not be resolved.
    """
    coords = _venue_coords()
    if not coords:
        return {}

    import duckdb as _duckdb
    try:
        tmp = _duckdb.connect()
        df = tmp.execute(f"""
            SELECT
                CAST(event_id AS VARCHAR) AS event_id,
                home_team_name, away_team_name,
                CAST(match_date AS DATE) AS match_date,
                venue_name
            FROM read_parquet('{matches_glob}', union_by_name=true)
            WHERE match_date IS NOT NULL
            ORDER BY match_date
        """).df()
        tmp.close()
    except Exception:
        return {}

    if df.empty:
        return {}

    def _resolve_venue(name: str | None) -> tuple[float, float] | None:
        if not name:
            return None
        key = name.lower().strip()
        if key in coords:
            return coords[key]
        # Partial-match fallback: pick the venue whose name is a substring of the ESPN name
        for venue_key, latlon in coords.items():
            if venue_key in key or key in venue_key:
                return latlon
        return None

    df["match_date"] = pd.to_datetime(df["match_date"])
    df["home_norm"]  = df["home_team_name"].map(lambda n: _norm_team(n) or n)
    df["away_norm"]  = df["away_team_name"].map(lambda n: _norm_team(n) or n)

    # Track last venue coords per team (in match_date order)
    team_last_venue: dict[str, tuple[float, float] | None] = {}
    result: dict[str, tuple[int | None, int | None]] = {}

    for _, row in df.sort_values("match_date").iterrows():
        ev          = str(row["event_id"])
        h_name      = str(row["home_norm"])
        a_name      = str(row["away_norm"])
        venue_latlon = _resolve_venue(row.get("venue_name"))

        def _travel(team: str) -> int | None:
            if venue_latlon is None:
                return None
            prev = team_last_venue.get(team)
            if prev is None:
                return None
            km = _haversine_km(prev[0], prev[1], venue_latlon[0], venue_latlon[1])
            return int(round(km))

        result[ev] = (_travel(h_name), _travel(a_name))

        # Update last venue for both teams after processing this match
        if venue_latlon is not None:
            team_last_venue[h_name] = venue_latlon
            team_last_venue[a_name] = venue_latlon

    return result


def _build_rest_days(matches_glob: str) -> dict[str, tuple[int | None, int | None]]:
    """
    For every match in Bronze, compute how many days each team rested since
    their previous match.

    Returns: {event_id_str: (home_rest_days, away_rest_days)}
    Either element may be None if no previous match can be found for that team.
    """
    import duckdb as _duckdb
    try:
        tmp = _duckdb.connect()
        df = tmp.execute(f"""
            SELECT
                CAST(event_id AS VARCHAR) AS event_id,
                home_team_name, away_team_name,
                CAST(match_date AS DATE) AS match_date
            FROM read_parquet('{matches_glob}', union_by_name=true)
            WHERE match_date IS NOT NULL
            ORDER BY match_date
        """).df()
        tmp.close()
    except Exception:
        return {}

    if df.empty:
        return {}

    df["match_date"] = pd.to_datetime(df["match_date"])
    df["home_norm"]  = df["home_team_name"].map(lambda n: _norm_team(n) or n)
    df["away_norm"]  = df["away_team_name"].map(lambda n: _norm_team(n) or n)

    # Build chronological list of (team, date, event_id)
    events: list[tuple[str, pd.Timestamp, str]] = []
    for _, row in df.iterrows():
        events.append((row["home_norm"], row["match_date"], row["event_id"]))
        events.append((row["away_norm"], row["match_date"], row["event_id"]))

    # For each (team, event) find the most recent prior event date
    # (sort by date; for each entry, look backwards in team's history)
    team_history: dict[str, list[pd.Timestamp]] = {}
    event_map: dict[str, dict[str, int | None]] = {}  # event_id → {team → rest_days}

    for team, dt, ev in sorted(events, key=lambda x: x[1]):
        prev_dates = team_history.get(team, [])
        if prev_dates:
            last_dt   = max(d for d in prev_dates if d < dt) if any(d < dt for d in prev_dates) else None
            rest_days = int((dt - last_dt).days) if last_dt is not None else None
        else:
            rest_days = None
        event_map.setdefault(ev, {})[team] = rest_days
        team_history.setdefault(team, []).append(dt)

    result: dict[str, tuple[int | None, int | None]] = {}
    for _, row in df.iterrows():
        ev = row["event_id"]
        h  = row["home_norm"]
        a  = row["away_norm"]
        em = event_map.get(ev, {})
        result[ev] = (em.get(h), em.get(a))

    return result


# ---------------------------------------------------------------------------
# Matchups  (all rounds in one object keyed by round code)
# ---------------------------------------------------------------------------

def _populate_market_odds_archive(conn, odds_glob: str) -> int:
    """
    Read all Bronze ESPN odds Parquets and INSERT OR IGNORE into market_odds_archive.

    Uses "first seen wins" semantics — once odds are recorded for an event they
    are never overwritten, so pre-match odds survive even if ESPN later strips them.
    Returns the count of new rows inserted.
    """
    import duckdb as _duckdb
    # Check if any odds parquets exist
    odds_dir = Path(odds_glob.replace("/*.parquet", ""))
    if not odds_dir.is_dir() or not list(odds_dir.glob("*.parquet")):
        return 0
    try:
        result = conn.execute(f"""
            INSERT OR IGNORE INTO market_odds_archive
                (event_id, first_seen, home_win_prob, draw_prob, away_win_prob, fetched_at)
            SELECT
                CAST(o.event_id AS VARCHAR),
                CAST(o.match_date AS DATE),
                o.home_win_prob,
                o.draw_prob,
                o.away_win_prob,
                COALESCE(CAST(o.fetched_at AS TIMESTAMP), now())
            FROM read_parquet('{odds_glob}', union_by_name=true) o
            WHERE o.home_win_prob IS NOT NULL
              AND o.event_id IS NOT NULL
        """)
        return result.rowcount if hasattr(result, "rowcount") else 0
    except Exception as exc:
        print(f"Warning: market_odds_archive populate failed: {exc}", file=sys.stderr)
        return 0


def export_matchups(conn) -> dict:
    bronze       = Path(settings.parquet_bronze_dir)
    matches_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()
    odds_glob    = (bronze / "espn" / "odds"    / "*.parquet").as_posix()

    # Snapshot all Bronze odds into the archive before reading (first-seen-wins)
    _populate_market_odds_archive(conn, odds_glob)

    # Pre-compute rest days and travel km for every match (PR5b.1 / PR5c.5)
    rest_days_map  = _build_rest_days(matches_glob)
    travel_km_map  = _build_travel_km(matches_glob)

    # Build fallback odds maps for matches where live ESPN odds were stripped:
    #   1. market_odds_archive — first-seen snapshot from any historical fetch
    #   2. brier_log — market prob logged at match grading time
    archive_odds: dict[str, tuple[float | None, float | None]] = {}
    try:
        arch_rows = conn.execute("""
            SELECT event_id, home_win_prob, draw_prob, away_win_prob
            FROM market_odds_archive
        """).fetchall()
        for ev, hw, dp, aw in arch_rows:
            if ev is not None and hw is not None and aw is not None:
                dp_f = float(dp) if dp is not None else 0.0
                market_home = round(float(hw) + dp_f * 0.5, 4)
                archive_odds[str(ev)] = (market_home, round(1.0 - market_home, 4))
    except Exception:
        pass

    brier_odds: dict[str, tuple[float | None, float | None]] = {}
    try:
        brier_rows = conn.execute("""
            SELECT event_id, model_prob AS home_adv, market_prob
            FROM brier_log
            WHERE market_prob IS NOT NULL
        """).fetchall()
        for ev, home_adv, mkt in brier_rows:
            if ev is not None and mkt is not None:
                brier_odds[str(ev)] = (float(mkt), round(1.0 - float(mkt), 4))
    except Exception:
        pass

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
                    o.home_win_prob, o.draw_prob, o.away_win_prob,
                    m.venue_name, m.venue_city
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
             home_win_prob, draw_prob, away_win_prob,
             venue_name, venue_city) = row

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

            # Backfill from archive then brier_log when ESPN stripped live odds
            ev_str = str(event_id)
            if market_home is None and ev_str in archive_odds:
                market_home, market_away = archive_odds[ev_str]
            if market_home is None and ev_str in brier_odds:
                market_home, market_away = brier_odds[ev_str]

            model_home = sim_map.get(h_norm)
            model_away = sim_map.get(a_norm)
            if model_home is not None:
                model_home = round(model_home, 4)
            if model_away is not None:
                model_away = round(model_away, 4)

            h_rest, a_rest   = rest_days_map.get(str(event_id), (None, None))
            h_km,   a_km     = travel_km_map.get(str(event_id), (None, None))

            venue = str(venue_city or venue_name) if (venue_city or venue_name) else None
            matches.append({
                "event_id":    str(event_id),
                "match_date":  str(match_date),
                "round":       round_name_val,
                "is_completed": bool(is_completed),
                "venue":       venue,
                "home": {
                    "name":               h_norm,
                    "abbrev":             h_abbrev,
                    "score":              int(h_score) if h_score is not None else None,
                    "model_advance_prob": model_home,
                    "market_advance_prob": market_home,
                    "rest_days":          h_rest,
                    "travel_km":          h_km,
                },
                "away": {
                    "name":               a_norm,
                    "abbrev":             a_abbrev,
                    "score":              int(a_score) if a_score is not None else None,
                    "model_advance_prob": model_away,
                    "market_advance_prob": market_away,
                    "rest_days":          a_rest,
                    "travel_km":          a_km,
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
# FM-style radar  (3.3 — position-aware axes + GK remapping)
# ---------------------------------------------------------------------------

# Position-specific axis weights for the overall composite
# [shooting_pct, creativity_pct, defending_pct, wc_form_pct]
_POS_WEIGHTS: dict[str, list[float]] = {
    "FWD": [0.60, 0.25, 0.05, 0.10],
    "MID": [0.25, 0.45, 0.20, 0.10],
    "DEF": [0.10, 0.20, 0.60, 0.10],
    "GK":  [0.80, 0.00, 0.00, 0.20],  # GK "shooting" slot = shot-stopping (remapped below)
}
_DEFAULT_WEIGHTS: list[float] = [0.25, 0.25, 0.25, 0.25]

# Position-specific axis labels (5 items: shooting, creativity, defending, wc_form, overall)
_RADAR_AXES: dict[str, list[str]] = {
    "GK":  ["Shot Stopping", "Distribution", "Defending",  "WC Form", "Overall"],
    "DEF": ["Shooting",      "Playmaking",   "Defending",  "WC Form", "Overall"],
    "MID": ["Shooting",      "Playmaking",   "Defending",  "WC Form", "Overall"],
    "FWD": ["Shooting",      "Playmaking",   "Defending",  "WC Form", "Overall"],
}
_DEFAULT_AXES: list[str] = ["Shooting", "Playmaking", "Defending", "WC Form", "Overall"]


# ---------------------------------------------------------------------------
# FIFA-style 0-99 score  (PR6)
# ---------------------------------------------------------------------------

# Band thresholds and labels (highest first for easy lookup)
_FIFA_BANDS: list[tuple[int, str]] = [
    (90, "World Class"),
    (85, "Elite"),
    (80, "Top Tier"),
    (75, "Quality"),
    (70, "Good"),
    (65, "Decent"),
    (0,  "Squad"),
]


def _fifa_score(
    posterior_mean: float | None,
    percentile_rank: float | None,
    pos_mean: float = 6.8,
    pos_std: float = 0.25,
) -> int | None:
    """
    Blend position-normalised absolute skill + relative rank into a FIFA-style 0-99 integer.
    60% absolute + 40% relative (percentile 0-1 → 10-99).

    Absolute: baseline uses pos_mean as a reference on the 1-10 scale (anchors the
    position group at its natural level), then adds a z-score nudge (±1 sigma = ±5 pts)
    so players above/below their position average are rewarded/penalised relative to peers.
    This fixes the CB bias: a CB and a FWD at the same within-position percentile get
    the same absolute component, regardless of their raw posterior level.
    """
    if posterior_mean is None or percentile_rank is None:
        return None
    baseline = 10 + (pos_mean - 1.0) * (89.0 / 9.0)
    z = (posterior_mean - pos_mean) / max(pos_std, 0.05)
    z = max(-3.0, min(3.0, z))
    absolute = baseline + z * (89.0 / 18.0)   # ±1 sigma = ±4.9 pts; ±3 sigma = ±14.8 pts
    relative = 10 + percentile_rank * 89.0
    return int(round(max(10.0, min(99.0, 0.60 * absolute + 0.40 * relative))))


def _fifa_band(score: int | None) -> str:
    if score is None:
        return "Squad"
    for threshold, label in _FIFA_BANDS:
        if score >= threshold:
            return label
    return "Squad"


def _fifa_attrs(fm: dict, pos: str) -> dict[str, int | None]:
    """
    Convert per-axis percentiles (0-1) to 10-99 FIFA sub-attribute integers.
    Outfield: SHO, PAS, DEF, WC_FORM
    GK: DIV (shot-stopping), HAN (handling/defending), POS (positioning/WC form), KIC (kicking/creativity)
    """
    def pct_to_score(p: float | None) -> int | None:
        if p is None:
            return None
        return int(round(max(10.0, min(99.0, 10 + p * 89.0))))

    sho = pct_to_score(fm.get("shooting"))
    pas = pct_to_score(fm.get("creativity"))
    dfe = pct_to_score(fm.get("defending"))
    wcf = pct_to_score(fm.get("wc_form"))

    if pos == "GK":
        return {"DIV": sho, "HAN": dfe, "POS": wcf, "KIC": pas}
    return {"SHO": sho, "PAS": pas, "DEF": dfe, "WC_FORM": wcf}


def _load_fm_radar(silver_dir: str) -> dict[str, dict]:
    """
    Load features.parquet and compute 5 FM-style attribute percentiles.
    Includes position-aware overall composite and GK axis remapping.
    Returns {} when features.parquet is absent (safe fallback).
    """
    features_path = Path(silver_dir) / "player_stats" / "features.parquet"
    if not features_path.exists():
        return {}
    try:
        df = pd.read_parquet(features_path)
    except Exception as exc:
        print(f"Warning: could not load features.parquet for FM radar: {exc}", file=sys.stderr)
        return {}
    if df.empty or "reep_id" not in df.columns or "position_bucket" not in df.columns:
        return {}

    # Weighted stat buckets — cols absent from df are skipped silently.
    BUCKETS: dict[str, list[tuple[str, float]]] = {
        "shooting": [
            ("wc_xg_per_90",       1.2),
            ("wc_goals_per_90",    1.5),
            ("wc_shots_per_90",    0.6),
            ("prior_xg_per_90",    1.0),
            ("prior_npxg_per_90",  1.0),
            ("prior_goals_per_90", 1.2),
        ],
        "creativity": [
            ("wc_xa_per_90",            1.2),
            ("wc_key_passes_per_90",    0.8),
            ("wc_assists_per_90",       1.5),
            ("prior_xa_per_90",         1.0),
            ("prior_key_passes_per_90", 0.8),
            ("prior_assists_per_90",    1.2),
        ],
        "defending": [
            ("wc_tackles_per_90",       1.2),
            ("wc_interceptions_per_90", 1.2),
            ("wc_clearances_per_90",    0.8),
            ("wc_saves_per_90",         1.5),  # GK-specific; near-zero for outfield
        ],
        "wc_form": [
            ("wc_rating_avg", 1.0),
        ],
    }

    work = df[["reep_id", "position_bucket"]].copy()

    for bucket, stat_weights in BUCKETS.items():
        available = [(col, w) for col, w in stat_weights if col in df.columns]
        if not available:
            work[bucket] = np.nan
            continue

        zscores, weights = [], []
        for col, w in available:
            z = df.groupby("position_bucket")[col].transform(
                lambda s: (s - s.mean()) / s.std()
                if s.std() > 1e-8 else pd.Series(0.0, index=s.index)
            )
            zscores.append(z.values)
            weights.append(w)

        z_mat    = np.column_stack(zscores).astype(float)
        w_arr    = np.array(weights, dtype=float)
        nan_mask = np.isnan(z_mat)
        w_eff    = np.where(nan_mask, 0.0, w_arr)
        sum_w    = w_eff.sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            composite = np.where(
                sum_w > 0,
                (np.where(nan_mask, 0.0, z_mat) * w_eff).sum(axis=1) / sum_w,
                np.nan,
            )
        work[bucket] = composite

    for bucket in BUCKETS:
        work[f"{bucket}_pct"] = work.groupby("position_bucket")[bucket].rank(pct=True)

    # 3.3 — GK axis remap: override "shooting_pct" for GKs to use saves percentile.
    # GKs' xG/goals are near-zero; saves represent their primary on-ball contribution.
    if "wc_saves_per_90" in df.columns:
        gk_mask = (work["position_bucket"] == "GK").values
        if gk_mask.any():
            saves_vals = df.loc[gk_mask, "wc_saves_per_90"].copy()
            if saves_vals.std() > 1e-8:
                # Recompute shooting Z-score for GKs using saves instead of xg/goals
                saves_z = (saves_vals - saves_vals.mean()) / saves_vals.std()
                work.loc[gk_mask, "shooting"]     = saves_z.values
                work.loc[gk_mask, "shooting_pct"] = saves_z.rank(pct=True).values

    # 3.3 — Position-aware overall composite
    pct_cols   = ["shooting_pct", "creativity_pct", "defending_pct", "wc_form_pct"]
    pct_mat    = work[pct_cols].values.astype(float)
    w_mat      = np.vstack([
        _POS_WEIGHTS.get(str(pos), _DEFAULT_WEIGHTS)
        for pos in work["position_bucket"]
    ])
    nan_mask   = np.isnan(pct_mat)
    w_eff      = np.where(nan_mask, 0.0, w_mat)
    sum_w      = w_eff.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        work["overall_composite"] = np.where(
            sum_w > 0,
            (np.where(nan_mask, 0.0, pct_mat) * w_eff).sum(axis=1) / sum_w,
            np.nan,
        )

    result: dict[str, dict] = {}
    for _, row in work.iterrows():
        rid = row["reep_id"]
        if pd.isna(rid):
            continue
        pos = str(row.get("position_bucket", ""))
        result[str(rid)] = {
            b: (float(row[f"{b}_pct"]) if pd.notna(row.get(f"{b}_pct")) else None)
            for b in BUCKETS
        } | {
            "overall":     float(row["overall_composite"]) if pd.notna(row.get("overall_composite")) else None,
            "radar_axes":  _RADAR_AXES.get(pos, _DEFAULT_AXES),
        }
    return result


# ---------------------------------------------------------------------------
# Raw stats lookup  (3.4 — populates RawStats.tsx panel)
# ---------------------------------------------------------------------------

_RAW_STAT_COLS: list[str] = [
    "wc_matches", "wc_goals_raw", "wc_assists_raw", "wc_xg_raw", "wc_xa_raw",
    "wc_shots_raw", "wc_sot_raw", "wc_key_passes_raw",
    "wc_tackles_raw", "wc_interceptions_raw", "wc_clearances_raw", "wc_saves_raw",
    "wc_passes_completed_raw", "wc_passes_attempted_raw",
    "wc_goals_per_90", "wc_assists_per_90", "wc_xg_per_90", "wc_xa_per_90",
    "wc_shots_per_90", "wc_sot_per_90", "wc_key_passes_per_90",
    "wc_tackles_per_90", "wc_interceptions_per_90", "wc_clearances_per_90",
    "wc_saves_per_90", "wc_passes_completed_per_90", "wc_pass_completion_pct",
    "wc_rating_adjusted",
    "has_prior", "prior_goals_per_90", "prior_assists_per_90",
    "prior_xg_per_90", "prior_xa_per_90", "prior_shots_per_90",
    "prior_key_passes_per_90", "prior_minutes",
    "position_source", "league",
]


def _load_raw_stats(silver_dir: str) -> dict[str, dict]:
    """
    Load features.parquet and return a dict keyed by reep_id containing all
    raw WC stats and club-prior stats for the RawStats.tsx panel.
    """
    features_path = Path(silver_dir) / "player_stats" / "features.parquet"
    if not features_path.exists():
        return {}
    try:
        df = pd.read_parquet(features_path)
    except Exception as exc:
        print(f"Warning: could not load features.parquet for raw stats: {exc}", file=sys.stderr)
        return {}
    if df.empty or "reep_id" not in df.columns:
        return {}

    result: dict[str, dict] = {}
    for _, row in df.iterrows():
        rid = row.get("reep_id")
        if pd.isna(rid):
            continue
        entry: dict = {}
        for col in _RAW_STAT_COLS:
            if col not in row.index:
                continue
            val = row[col]
            if col == "has_prior":
                entry[col] = bool(val) if pd.notna(val) else False
            elif isinstance(val, (bool, np.bool_)):
                entry[col] = bool(val)
            elif isinstance(val, str):
                entry[col] = val if val and val.lower() not in ("nan", "none", "") else None
            else:
                entry[col] = _safe_float(val)
        result[str(rid)] = entry
    return result


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# National team derivation  (5a.1 — modal Sofascore team per reep_id)
# ---------------------------------------------------------------------------

def _build_national_teams(conn) -> dict[str, str]:
    """
    Derive the authoritative national team for each WC player from Sofascore
    lineup data — more reliable than Reep's `nationality` field, which contains
    historical / bio nationality (e.g. Wissa = "France" bio; plays for Congo DR).

    Returns dict: reep_id → canonical national team name.
    Falls back to empty dict when Bronze Parquets are absent.
    """
    lineup_dir = Path(settings.parquet_bronze_dir) / "sofascore" / "lineups"
    events_dir = Path(settings.parquet_bronze_dir) / "sofascore" / "events"

    if not (lineup_dir.is_dir() and list(lineup_dir.glob("*.parquet"))):
        return {}
    if not (events_dir.is_dir() and list(events_dir.glob("*.parquet"))):
        return {}

    lineup_glob = (lineup_dir / "*.parquet").as_posix()
    events_glob = (events_dir / "*.parquet").as_posix()

    try:
        bridge_rows = conn.execute("""
            SELECT CAST(key_sofascore AS VARCHAR) AS sofascore_id, reep_id
            FROM identity_players
            WHERE key_sofascore IS NOT NULL AND key_sofascore != ''
        """).fetchall()
    except Exception:
        return {}
    sc_to_reep = {str(sc): str(r) for sc, r in bridge_rows}

    import duckdb as _duckdb
    tmp = _duckdb.connect()
    try:
        lineups = tmp.execute(f"""
            SELECT
                CAST(player_id AS VARCHAR) AS sofascore_id,
                CAST(event_id  AS BIGINT)  AS event_id,
                team_side
            FROM read_parquet('{lineup_glob}', union_by_name=true)
        """).df()

        events = tmp.execute(f"""
            SELECT
                CAST(event_id AS BIGINT) AS event_id,
                home_team_name,
                away_team_name
            FROM read_parquet('{events_glob}', union_by_name=true)
        """).df()
    except Exception as exc:
        print(f"Warning: national_team lookup failed: {exc}", file=sys.stderr)
        return {}
    finally:
        tmp.close()

    if lineups.empty or events.empty:
        return {}

    merged = lineups.merge(events, on="event_id", how="left")
    merged["team_name"] = np.where(
        merged["team_side"] == "home",
        merged["home_team_name"],
        merged["away_team_name"],
    )
    merged["reep_id"] = merged["sofascore_id"].map(sc_to_reep)

    result: dict[str, str] = {}
    for rid, grp in merged.dropna(subset=["reep_id", "team_name"]).groupby("reep_id"):
        modal = grp["team_name"].mode()
        if not modal.empty:
            raw = str(modal.iloc[0])
            result[str(rid)] = _norm_team(raw) or raw

    return result


# Per-match log builder  (3.4 — populates MatchTimeline.tsx)
# ---------------------------------------------------------------------------

_TEAM_CODE: dict[str, str] = {
    "Argentina": "ARG", "Australia": "AUS", "Austria": "AUT", "Belgium": "BEL",
    "Bolivia": "BOL", "Brazil": "BRA", "Cameroon": "CMR", "Canada": "CAN",
    "Chile": "CHI", "Colombia": "COL", "Costa Rica": "CRC", "Croatia": "CRO",
    "Denmark": "DEN", "Ecuador": "ECU", "Egypt": "EGY", "England": "ENG",
    "France": "FRA", "Germany": "GER", "Ghana": "GHA", "Honduras": "HON",
    "Hungary": "HUN", "Indonesia": "IDN", "Iran": "IRN", "Japan": "JPN",
    "Korea Republic": "KOR", "South Korea": "KOR", "Mexico": "MEX",
    "Morocco": "MAR", "Netherlands": "NED", "New Zealand": "NZL", "Nigeria": "NGA",
    "Panama": "PAN", "Paraguay": "PAR", "Peru": "PER", "Poland": "POL",
    "Portugal": "POR", "Qatar": "QAT", "Romania": "ROU", "Saudi Arabia": "KSA",
    "Scotland": "SCO", "Senegal": "SEN", "Serbia": "SRB", "Slovenia": "SVN",
    "Spain": "ESP", "Switzerland": "SUI", "Tunisia": "TUN", "Turkey": "TUR",
    "Türkiye": "TUR", "Ukraine": "UKR", "United States": "USA", "Uruguay": "URU",
    "Venezuela": "VEN", "Wales": "WAL", "USA": "USA",
}


def _build_match_logs(conn) -> dict[str, list[dict]]:
    """
    Build per-player per-match log entries by joining Sofascore lineup and
    events Parquets.  Returns {} when Parquets are absent (graceful fallback).
    """
    lineup_dir = Path(settings.parquet_bronze_dir) / "sofascore" / "lineups"
    events_dir = Path(settings.parquet_bronze_dir) / "sofascore" / "events"

    if not (lineup_dir.is_dir() and list(lineup_dir.glob("*.parquet"))):
        return {}
    if not (events_dir.is_dir() and list(events_dir.glob("*.parquet"))):
        return {}

    lineup_glob = (lineup_dir / "*.parquet").as_posix()
    events_glob = (events_dir / "*.parquet").as_posix()

    # Fetch sofascore_id → reep_id bridge from identity_players
    try:
        bridge_rows = conn.execute("""
            SELECT CAST(key_sofascore AS VARCHAR) AS sofascore_id, reep_id
            FROM identity_players
            WHERE key_sofascore IS NOT NULL AND key_sofascore != ''
        """).fetchall()
    except Exception:
        return {}
    sc_to_reep = {str(sc): str(r) for sc, r in bridge_rows}

    # Fetch yesterday's posteriors for opponent-strength adjustment
    try:
        ratings_rows = conn.execute(
            "SELECT reep_id, posterior_mean FROM player_ratings"
        ).fetchall()
    except Exception:
        ratings_rows = []
    existing_ratings: dict[str, float] = {str(r): float(p) for r, p in ratings_rows}
    global_mean = float(np.mean(list(existing_ratings.values()))) if existing_ratings else 6.8
    alpha = settings.opponent_alpha

    import duckdb as _duckdb
    tmp = _duckdb.connect()
    try:
        lineups = tmp.execute(f"""
            SELECT
                CAST(player_id AS VARCHAR)  AS sofascore_id,
                CAST(event_id  AS BIGINT)   AS event_id,
                team_side,
                COALESCE(minutes_played, 0) AS minutes_played,
                COALESCE(goals, 0)          AS goals,
                COALESCE(assists, 0)        AS assists,
                COALESCE(xg, 0.0)           AS xg,
                COALESCE(xa, 0.0)           AS xa,
                COALESCE(shots, 0)          AS shots,
                COALESCE(key_passes, 0)     AS key_passes,
                COALESCE(tackles, 0)        AS tackles,
                COALESCE(interceptions, 0)  AS interceptions,
                COALESCE(yellow_cards, 0)   AS yellow_cards,
                rating
            FROM read_parquet('{lineup_glob}', union_by_name=true)
            WHERE minutes_played > 0
        """).df()

        events = tmp.execute(f"""
            SELECT
                CAST(event_id AS BIGINT) AS event_id,
                home_team_name,
                away_team_name,
                CAST(home_score AS INTEGER) AS home_score,
                CAST(away_score AS INTEGER) AS away_score,
                match_date
            FROM read_parquet('{events_glob}', union_by_name=true)
        """).df()
    except Exception as exc:
        print(f"Warning: match log query failed: {exc}", file=sys.stderr)
        return {}
    finally:
        tmp.close()

    if lineups.empty or events.empty:
        return {}

    # Merge lineups with events
    merged = lineups.merge(events, on="event_id", how="left")

    # Determine opponent name and score string
    merged["opponent"] = np.where(
        merged["team_side"] == "home",
        merged["away_team_name"],
        merged["home_team_name"],
    )
    merged["score"] = np.where(
        merged["team_side"] == "home",
        merged["home_score"].astype(str) + "–" + merged["away_score"].astype(str),
        merged["away_score"].astype(str) + "–" + merged["home_score"].astype(str),
    )

    # Compute opponent-team strength per (event_id, team_side)
    merged["reep_id"] = merged["sofascore_id"].map(sc_to_reep)
    merged["opp_rating_lookup"] = merged["reep_id"].map(existing_ratings)

    team_strength: dict[tuple[int, str], float] = {}
    for (ev, side), grp in merged.groupby(["event_id", "team_side"]):
        top15 = grp.nlargest(15, "minutes_played")
        valid  = top15["opp_rating_lookup"].dropna()
        if not valid.empty:
            team_strength[(int(ev), str(side))] = float(valid.mean())

    opp_side_map = {"home": "away", "away": "home"}
    merged["opp_side"]     = merged["team_side"].map(opp_side_map)
    merged["opp_key"]      = list(zip(merged["event_id"].astype(int), merged["opp_side"]))
    merged["opp_strength"] = merged["opp_key"].map(team_strength).fillna(global_mean)
    merged["adjusted_rating"] = np.where(
        merged["rating"].notna(),
        merged["rating"] * (merged["opp_strength"] / global_mean) ** alpha,
        np.nan,
    )

    # Build per-player match log
    logs: dict[str, list[dict]] = {}
    for _, row in merged.iterrows():
        rid = row.get("reep_id")
        if pd.isna(rid):
            continue
        rid = str(rid)
        entry: dict = {
            "match_date":      str(row.get("match_date", "")),
            "opponent":        str(row["opponent"]) if pd.notna(row.get("opponent")) else "?",
            "opponent_code":   _TEAM_CODE.get(str(row.get("opponent", "")), "?"),
            "score":           str(row["score"]) if pd.notna(row.get("score")) else "?-?",
            "minutes":         int(row["minutes_played"]),
            "rating":          round(float(row["rating"]), 2) if pd.notna(row.get("rating")) else None,
            "adjusted_rating": round(float(row["adjusted_rating"]), 2) if pd.notna(row.get("adjusted_rating")) else None,
            "goals":           int(row["goals"]),
            "assists":         int(row["assists"]),
            "xg":              round(float(row["xg"]), 3) if pd.notna(row.get("xg")) else 0.0,
            "xa":              round(float(row["xa"]), 3) if pd.notna(row.get("xa")) else 0.0,
            "shots":           int(row["shots"]),
            "key_passes":      int(row["key_passes"]),
            "tackles":         int(row["tackles"]),
            "interceptions":   int(row["interceptions"]),
            "yellow_card":     bool(int(row["yellow_cards"]) > 0),
        }
        if rid not in logs:
            logs[rid] = []
        logs[rid].append(entry)

    # Sort each player's log chronologically
    for rid in logs:
        logs[rid].sort(key=lambda e: e["match_date"])

    return logs


# ---------------------------------------------------------------------------
# Players  (full profiles — used for search + player detail page)
# ---------------------------------------------------------------------------

def export_players(conn) -> list:
    fm_radar       = _load_fm_radar(settings.parquet_silver_dir)
    raw_stats      = _load_raw_stats(settings.parquet_silver_dir)
    match_logs     = _build_match_logs(conn)
    national_teams = _build_national_teams(conn)

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
            ip.date_of_birth,
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

    # Pre-compute posterior_mean mean/std per position_bucket for FIFA score normalisation.
    # Index 9 = position_bucket, index 11 = posterior_mean (matches SELECT order above).
    _pm_by_pos: dict[str, list[float]] = {}
    for _r in rows:
        _pos = str(_r[9] or "")
        _pm  = _r[11]
        if _pos and _pm is not None:
            _pm_by_pos.setdefault(_pos, []).append(float(_pm))
    pos_stats: dict[str, dict[str, float]] = {
        pos: {
            "mean": float(np.mean(vals)),
            "std":  float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.25,
        }
        for pos, vals in _pm_by_pos.items()
    }

    players = []
    WC_START = pd.Timestamp("2026-06-11")  # FIFA WC 2026 opening match

    for row in rows:
        (reep_id, name, nationality, date_of_birth, position_detail,
         position_macro, position_micro, cluster_id, cluster_label, position_bucket,
         prior_mean, posterior_mean, posterior_std, hdi_low, hdi_high,
         shrinkage_weight, wc_minutes, confidence_score, percentile_rank, prior_pct) = row

        sw  = _safe_float(shrinkage_weight)
        wm  = _safe_float(wc_minutes)
        fm  = fm_radar.get(reep_id, {})
        rs  = raw_stats.get(reep_id, {})
        log = match_logs.get(reep_id)
        nt  = national_teams.get(reep_id)

        # Age at tournament start
        age_at_wc: int | None = None
        age_cohort: str | None = None
        if date_of_birth is not None:
            try:
                dob = pd.Timestamp(date_of_birth)
                age_at_wc = int((WC_START - dob).days // 365.25)
                if age_at_wc <= 21:
                    age_cohort = "u21"
                elif age_at_wc <= 26:
                    age_cohort = "22-26"
                elif age_at_wc <= 31:
                    age_cohort = "27-31"
                else:
                    age_cohort = "32+"
            except Exception:
                pass

        p: dict = {
            "reep_id":          reep_id,
            "name":             _safe_str(name),
            "nationality":      _safe_str(nationality),
            "national_team":    nt,
            "age_at_wc":        age_at_wc,
            "age_cohort":       age_cohort,
            "position_detail":  _safe_str(position_detail),
            "position_macro":   position_macro,
            "position_micro":   _safe_str(position_micro),
            "cluster_id":       int(cluster_id) if cluster_id is not None else -1,
            "cluster_label":    _safe_str(cluster_label),
            "position_bucket":  position_bucket,
            "prior_mean":       _safe_float(prior_mean),
            "posterior_mean":   _safe_float(posterior_mean),
            "posterior_std":    _safe_float(posterior_std),
            "hdi_low":          _safe_float(hdi_low),
            "hdi_high":         _safe_float(hdi_high),
            "shrinkage_weight": sw,
            "wc_minutes":       wm,
            "confidence_score": _safe_float(confidence_score),
            "percentile_rank":  _safe_float(percentile_rank),
            # FM-style radar
            "radar": {
                "shooting":      _safe_float(fm.get("shooting")),
                "creativity":    _safe_float(fm.get("creativity")),
                "defending":     _safe_float(fm.get("defending")),
                "wc_form":       _safe_float(fm.get("wc_form")),
                # Position-aware overall composite (replaces posterior_pct as 5th axis)
                "overall":       _safe_float(fm.get("overall")),
                "radar_axes":    fm.get("radar_axes", _DEFAULT_AXES),
                # Bayesian dimensions (stats card / back-compat)
                "posterior_pct": _safe_float(percentile_rank),
                "wc_experience": _safe_float(
                    min(wm / 270.0, 1.0) if wm is not None else None
                ),
                "confidence":    _safe_float(confidence_score),
                "prior_pct":     _safe_float(prior_pct),
                "wc_dominance":  _safe_float(
                    1.0 - sw if sw is not None else None
                ),
            },
        }

        # FIFA-style 0-99 dual display (PR6)
        _ps = pos_stats.get(str(position_bucket or ""), {"mean": 6.8, "std": 0.25})
        fs = _fifa_score(
            _safe_float(posterior_mean),
            _safe_float(percentile_rank),
            pos_mean=_ps["mean"],
            pos_std=_ps["std"],
        )
        p["fifa"] = {
            "overall": fs,
            "band":    _fifa_band(fs),
            "attrs":   _fifa_attrs(fm, str(position_bucket or "")),
        }

        # Raw WC stats (from features.parquet — populated once WC Parquets exist)
        for col in _RAW_STAT_COLS:
            if col in rs:
                p[col] = rs[col]

        # Per-match timeline
        if log:
            p["match_log"] = log

        players.append(p)

    return players


# ---------------------------------------------------------------------------
# Insights  (Story of the day — top favorites, value picks, overnight deltas)
# ---------------------------------------------------------------------------

def export_insights(
    sims: dict,
    matchups: dict,
    players: list,
    prev_sims: dict | None = None,
) -> dict:
    """
    Build insights.json: a compact summary of the current tournament state for
    the home-page insight cards.

    Sections:
      - top_favorites:  top-5 teams by title_prob from the earliest sim round
      - value_picks:    up to 3 matchups where |model - market| >= 5pp (home advantage)
      - next_match:     the next scheduled (not yet completed) fixture
      - overnight:      list of biggest title_prob swings vs prev_sims (may be empty)
    """
    from datetime import datetime as _dt, timezone as _tz

    # ── Top favorites ────────────────────────────────────────────────────────
    first_round_teams: list[dict] = []
    if sims.get("rounds"):
        first_round_teams = sims["rounds"][0].get("teams", [])
    top_favorites = [
        {"team": t["team_id"], "title_prob": t["title_prob"]}
        for t in sorted(first_round_teams, key=lambda x: -(x.get("title_prob") or 0))
        if t.get("title_prob") is not None
    ][:5]

    # ── Value picks  (|model - market| >= 5pp on upcoming matches) ──────────
    value_picks: list[dict] = []
    for rnd_code, rnd in matchups.items():
        for m in rnd.get("matches", []):
            if m.get("is_completed"):
                continue
            h = m.get("home", {})
            a = m.get("away", {})
            mp = h.get("model_advance_prob")
            bk = h.get("market_advance_prob")
            if mp is None or bk is None:
                continue
            edge = round(mp - bk, 4)
            if abs(edge) >= 0.05:
                value_picks.append({
                    "event_id":    m["event_id"],
                    "match_date":  m["match_date"],
                    "home":        h.get("name"),
                    "away":        a.get("name"),
                    "model_home":  mp,
                    "market_home": bk,
                    "edge":        edge,
                })
    value_picks.sort(key=lambda x: -abs(x["edge"]))
    value_picks = value_picks[:3]

    # ── Next match ───────────────────────────────────────────────────────────
    next_match: dict | None = None
    upcoming = []
    for rnd_code, rnd in matchups.items():
        for m in rnd.get("matches", []):
            if not m.get("is_completed") and m.get("match_date"):
                upcoming.append(m)
    if upcoming:
        upcoming.sort(key=lambda m: m["match_date"])
        nm = upcoming[0]
        next_match = {
            "event_id":   nm["event_id"],
            "match_date": nm["match_date"],
            "home":       nm["home"].get("name"),
            "away":       nm["away"].get("name"),
        }

    # ── Top performers  (highest posterior_mean with ≥ 180 WC minutes) ──────
    top_performers = []
    eligible = [
        p for p in players
        if (p.get("wc_minutes") or 0) >= 180
        and p.get("posterior_mean") is not None
    ]
    eligible.sort(key=lambda p: -(p["posterior_mean"] or 0))
    for p in eligible[:5]:
        top_performers.append({
            "reep_id":       p["reep_id"],
            "name":          p.get("name"),
            "national_team": p.get("national_team") or p.get("nationality"),
            "position":      p.get("position_detail") or p.get("position_macro"),
            "rating":        p.get("posterior_mean"),
        })

    # ── Overnight deltas ─────────────────────────────────────────────────────
    overnight: list[dict] = []
    if prev_sims and prev_sims.get("rounds") and sims.get("rounds"):
        # Build prev title_prob map
        prev_map: dict[str, float] = {}
        for rnd in prev_sims.get("rounds", []):
            for t in rnd.get("teams", []):
                if t.get("title_prob") is not None:
                    prev_map[t["team_id"]] = float(t["title_prob"])

        curr_map: dict[str, float] = {}
        for rnd in sims.get("rounds", []):
            for t in rnd.get("teams", []):
                if t.get("title_prob") is not None:
                    curr_map.setdefault(t["team_id"], float(t["title_prob"]))

        for team_id, curr_tp in curr_map.items():
            prev_tp = prev_map.get(team_id)
            if prev_tp is not None:
                delta = round(curr_tp - prev_tp, 4)
                if abs(delta) >= 0.003:
                    overnight.append({"team": team_id, "delta": delta, "title_prob": curr_tp})
        overnight.sort(key=lambda x: -abs(x["delta"]))
        overnight = overnight[:5]

    return {
        "generated_at":   _dt.now(_tz.utc).isoformat(),
        "run_date":        sims.get("run_date", ""),
        "top_favorites":   top_favorites,
        "value_picks":     value_picks,
        "next_match":      next_match,
        "top_performers":  top_performers,
        "overnight":       overnight,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_write_conn()

    # Read current simulations.json BEFORE overwriting — used for overnight delta
    prev_sims: dict | None = None
    _prev_sims_path = OUTPUT_DIR / "simulations.json"
    if _prev_sims_path.exists():
        try:
            prev_sims = json.loads(_prev_sims_path.read_text(encoding="utf-8"))
        except Exception:
            pass

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

    print("Exporting insights.json …")
    insights = export_insights(sims, matchups, players, prev_sims=prev_sims)
    (OUTPUT_DIR / "insights.json").write_text(
        json.dumps(insights, separators=(",", ":")), encoding="utf-8"
    )
    n_deltas = len(insights.get("overnight", []))
    print(f"  ✓  {len(insights['top_favorites'])} favorites, {len(insights['value_picks'])} value picks, {n_deltas} overnight deltas")

    print("Export complete →", OUTPUT_DIR)


if __name__ == "__main__":
    main()
