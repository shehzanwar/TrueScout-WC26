"""
Silver Feature Matrix — WC likelihood × Club priors.

Joins:
  Bronze Sofascore lineups  (player-level WC stats, per match)
  Bronze Understat priors   (club_priors_agg.parquet, 2-yr weighted avg)
  DuckDB identity_players   (sofascore_id → reep_id, reep position)

Key design choices:
  - WC per-90s use the raw stat SUMS across all matches, then divide by total
    minutes.  This avoids averaging volatile single-match per-90s.
  - Players with wc_minutes < 90 are flagged wc_low_data=True.  The Bayesian
    model should weight their prior heavier when wc_low_data is set.
  - Position bucket (GK/DEF/MID/FWD) comes from the reep register; falls back
    to Sofascore lineup position.
  - Only players with at least one data source (WC or club prior) are retained.

Output: data/silver/player_stats/features.parquet
"""
import logging
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings
from etl.db.connection import get_read_conn

# Opponent-strength adjustment exponent (mirrors OPPONENT_ALPHA in bayesian_ratings)
_OPPONENT_ALPHA: float = settings.opponent_alpha
# Fallback global mean when player_ratings is empty (first run or CI)
_GLOBAL_MEAN_RATING: float = 6.8

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Position mapping
# ---------------------------------------------------------------------------

# Reep uses full English words with many historical variants.
_REEP_BUCKET: dict[str, str] = {
    "goalkeeper": "GK",
    # Defenders
    "defender": "DEF", "full-back": "DEF", "centre-back": "DEF",
    "centre back": "DEF", "center back": "DEF",
    "stopper": "DEF", "sweeper": "DEF",
    "wing back": "DEF", "wing-back": "DEF",
    # "wing half" is a historical midfield role (holding/box-to-box in old 4-4-2)
    "wing half": "MID",
    "right back": "DEF", "left back": "DEF",
    # Midfielders
    "midfielder": "MID", "central midfielder": "MID",
    "defensive midfielder": "MID", "attacking midfielder": "MID",
    "wide midfielder": "MID", "winger": "MID",
    "left winger": "MID", "right winger": "MID",
    "inside forward": "MID",
    # Forwards
    "forward": "FWD", "attacker": "FWD", "centre-forward": "FWD",
    "striker": "FWD", "second striker": "FWD",
    "false 9": "FWD", "false nine": "FWD",
}

# Sofascore one-letter codes (from lineup position column)
_SC_BUCKET: dict[str, str] = {"G": "GK", "D": "DEF", "M": "MID", "F": "FWD"}

# Understat position strings are space-separated; first letter is primary.
_US_FIRST: dict[str, str] = {"G": "GK", "D": "DEF", "M": "MID", "F": "FWD", "S": "FWD"}


def _map_position(reep_pos: str | None, sc_pos: str | None, us_pos: str | None) -> str:
    if reep_pos:
        bucket = _REEP_BUCKET.get(str(reep_pos).strip().lower())
        if bucket:
            return bucket
    if sc_pos:
        bucket = _SC_BUCKET.get(str(sc_pos).strip().upper())
        if bucket:
            return bucket
    if us_pos:
        first = str(us_pos).strip().split()[0].upper() if us_pos else ""
        return _US_FIRST.get(first, "UNK")
    return "UNK"


def _position_source(reep_pos: str | None, sc_pos: str | None, us_pos: str | None) -> str:
    """Track which source determined the position bucket (for audit)."""
    if reep_pos and _REEP_BUCKET.get(str(reep_pos).strip().lower()):
        return "reep"
    if sc_pos and _SC_BUCKET.get(str(sc_pos).strip().upper()):
        return "sofascore_modal"
    if us_pos:
        first = str(us_pos).strip().split()[0].upper() if us_pos else ""
        if first in _US_FIRST:
            return "understat"
    return "unknown"


# ---------------------------------------------------------------------------
# WC aggregation
# ---------------------------------------------------------------------------

_WC_AGG_SQL = """
SELECT
    CAST(player_id AS VARCHAR)              AS sofascore_id,
    ANY_VALUE(player_name)                  AS wc_player_name,
    COUNT(*)                                AS wc_matches,
    SUM(minutes_played)                     AS wc_minutes,
    SUM(COALESCE(goals, 0))                 AS wc_goals_raw,
    SUM(COALESCE(assists, 0))               AS wc_assists_raw,
    SUM(xg)                                 AS wc_xg_raw,
    SUM(xa)                                 AS wc_xa_raw,
    SUM(COALESCE(shots, 0))                 AS wc_shots_raw,
    SUM(COALESCE(shots_on_target, 0))       AS wc_sot_raw,
    SUM(COALESCE(key_passes, 0))            AS wc_key_passes_raw,
    SUM(COALESCE(tackles, 0))               AS wc_tackles_raw,
    SUM(COALESCE(interceptions, 0))         AS wc_interceptions_raw,
    SUM(COALESCE(clearances, 0))            AS wc_clearances_raw,
    SUM(COALESCE(saves, 0))                 AS wc_saves_raw,
    SUM(COALESCE(passes_completed, 0))      AS wc_passes_completed_raw,
    SUM(COALESCE(passes_attempted, 0))      AS wc_passes_attempted_raw,
    AVG(rating)                             AS wc_rating_avg
FROM read_parquet('{lineup_glob}', union_by_name=true)
WHERE minutes_played > 0
GROUP BY player_id
"""

# Modal Sofascore position — only trust it when the same letter (G/D/M/F)
# appears in ≥60% of a player's lineup rows.  ANY_VALUE picks an arbitrary row
# which is wrong for players who switch roles across matches.
_WC_POS_SQL = """
SELECT
    sofascore_id,
    CASE WHEN cnt * 1.0 / total >= 0.6 THEN position ELSE NULL END AS wc_sc_position
FROM (
    SELECT
        CAST(player_id AS VARCHAR)                                   AS sofascore_id,
        position,
        COUNT(*)                                                     AS cnt,
        SUM(COUNT(*)) OVER (PARTITION BY player_id)                  AS total,
        ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY COUNT(*) DESC) AS rn
    FROM read_parquet('{lineup_glob}', union_by_name=true)
    WHERE minutes_played > 0
    GROUP BY player_id, position
) t
WHERE rn = 1
"""

_PER90_STATS = [
    "goals", "assists", "xg", "xa", "shots", "sot",
    "key_passes", "tackles", "interceptions", "clearances", "saves",
    "passes_completed",
]


_PER90_CAPS: dict[str, float] = {
    "xg": 1.8, "goals": 2.5, "assists": 2.5, "xa": 1.8,
    "shots": 12.0, "sot": 8.0, "key_passes": 8.0,
    "tackles": 10.0, "interceptions": 10.0, "clearances": 15.0, "saves": 8.0,
    "passes_completed": 120.0,
}


def _per90(df: pd.DataFrame) -> pd.DataFrame:
    """Add per-90 WC columns, computed from raw sums and total minutes.

    Caps prevent sub-3-minute appearances from producing physically impossible
    per-90 values (e.g. a player scoring once in 1 min → xg_per_90 ≈ 90).
    Also computes wc_pass_completion_pct from raw sums.
    """
    mins = df["wc_minutes"].clip(lower=1e-6)
    for stat in _PER90_STATS:
        raw = df.get(f"wc_{stat}_raw")
        if raw is not None:
            val = raw / (mins / 90.0)
            cap = _PER90_CAPS.get(stat)
            if cap is not None:
                val = val.clip(upper=cap)
            df[f"wc_{stat}_per_90"] = val

    # Pass completion % — derived from cumulative raw sums (not per-90)
    if "wc_passes_completed_raw" in df.columns and "wc_passes_attempted_raw" in df.columns:
        attempted = df["wc_passes_attempted_raw"].replace(0, float("nan"))
        df["wc_pass_completion_pct"] = (
            df["wc_passes_completed_raw"] / attempted * 100.0
        ).clip(lower=0.0, upper=100.0)

    return df


# Columns present in the final wc DataFrame (after merging _WC_AGG_SQL + _WC_POS_SQL).
# Used to create a schema-correct empty DataFrame when Sofascore Parquets are absent.
_WC_AGG_COLS = [
    "sofascore_id", "wc_player_name", "wc_matches",
    "wc_minutes", "wc_goals_raw", "wc_assists_raw", "wc_xg_raw", "wc_xa_raw",
    "wc_shots_raw", "wc_sot_raw", "wc_key_passes_raw", "wc_tackles_raw",
    "wc_interceptions_raw", "wc_clearances_raw", "wc_saves_raw",
    "wc_passes_completed_raw", "wc_passes_attempted_raw",
    "wc_rating_avg",
    "wc_sc_position",  # added by _WC_POS_SQL merge
]


def load_wc_features() -> pd.DataFrame:
    """Aggregate WC player stats from all Sofascore lineup Parquets.

    Returns an empty DataFrame with the correct column schema when the Parquet
    directory is missing or empty — this happens in GitHub Actions CI where
    Sofascore is blocked by Cloudflare and Parquets are committed to git by
    the developer.  Downstream steps (build_features, bayesian_ratings) handle
    0-row WC data gracefully: the model falls back to club-prior-only ratings.
    """
    lineup_dir   = Path(settings.parquet_bronze_dir) / "sofascore" / "lineups"
    parquet_files = list(lineup_dir.glob("*.parquet")) if lineup_dir.is_dir() else []

    if not parquet_files:
        logger.warning(
            "Sofascore lineup Parquets not found at %s — "
            "WC aggregation skipped; model will run on club priors only.",
            lineup_dir,
        )
        # Return a schema-correct empty DataFrame so _per90() and the outer
        # merge in build_features() do not raise KeyError.
        return pd.DataFrame(columns=_WC_AGG_COLS)

    lineup_glob = (lineup_dir / "*.parquet").as_posix()
    conn = duckdb.connect()
    try:
        wc  = conn.execute(_WC_AGG_SQL.format(lineup_glob=lineup_glob)).df()
        pos = conn.execute(_WC_POS_SQL.format(lineup_glob=lineup_glob)).df()
    finally:
        conn.close()

    # Attach modal position (NULL when no single position reaches 60% of appearances)
    wc = wc.merge(pos, on="sofascore_id", how="left")
    wc = _per90(wc)
    wc["wc_low_data"] = wc["wc_minutes"] < 90
    logger.info("WC aggregation: %d unique players", len(wc))
    return wc


# ---------------------------------------------------------------------------
# Club priors
# ---------------------------------------------------------------------------

def load_club_priors() -> pd.DataFrame:
    """Load Understat 2-yr weighted aggregate and rename columns with 'prior_' prefix."""
    path = Path(settings.parquet_bronze_dir) / "understat" / "club_priors_agg.parquet"
    priors = pd.read_parquet(path)

    # Rename per-90 stats to prior_ prefix to avoid collision after merge
    rename = {
        "xg_per_90":        "prior_xg_per_90",
        "xa_per_90":        "prior_xa_per_90",
        "npxg_per_90":      "prior_npxg_per_90",
        "goals_per_90":     "prior_goals_per_90",
        "assists_per_90":   "prior_assists_per_90",
        "shots_per_90":     "prior_shots_per_90",
        "key_passes_per_90":"prior_key_passes_per_90",
        "minutes_played":   "prior_minutes",
        "matches_played":   "prior_matches",
        "position":         "prior_us_position",
        "player_name":      "prior_player_name",
    }
    priors = priors.rename(columns=rename)

    # A player with multiple Understat IDs across different league stints can
    # resolve to the same reep_id (e.g. Naby Keïta: EPL + Serie A entries).
    # Keep the row with the most prior_minutes so the dominant stint wins.
    if priors["player_id"].duplicated().any():
        n_before = len(priors)
        priors = (
            priors.sort_values("prior_minutes", ascending=False)
            .drop_duplicates(subset=["player_id"], keep="first")
        )
        logger.warning(
            "Deduped %d duplicate reep_id rows in club_priors_agg (kept highest-minute stint)",
            n_before - len(priors),
        )

    logger.info("Club priors: %d players (reep_id linked)", len(priors))
    return priors


# ---------------------------------------------------------------------------
# Bridge: sofascore_id → reep_id
# ---------------------------------------------------------------------------

def build_sofascore_bridge() -> pd.DataFrame:
    """Query identity_players to map sofascore_id → reep_id + reep position."""
    conn = get_read_conn()
    try:
        bridge = conn.execute("""
            SELECT
                key_sofascore              AS sofascore_id,
                reep_id,
                position                   AS reep_position,
                nationality,
                name                       AS reep_name
            FROM identity_players
            WHERE key_sofascore IS NOT NULL AND key_sofascore != ''
        """).df()
    finally:
        conn.close()
    logger.info("Sofascore bridge: %d entries", len(bridge))
    return bridge


# ---------------------------------------------------------------------------
# Opponent-strength adjustment  (3.1)
# ---------------------------------------------------------------------------

def _load_existing_ratings() -> dict[str, float]:
    """Load previous nightly posterior means from player_ratings DuckDB table."""
    conn = get_read_conn()
    try:
        df = conn.execute("SELECT reep_id, posterior_mean FROM player_ratings").df()
        return dict(zip(df["reep_id"].astype(str), df["posterior_mean"].astype(float)))
    except Exception as exc:
        logger.info("Could not load existing player_ratings (%s) — first run or empty DB.", exc)
        return {}
    finally:
        conn.close()


def _apply_opponent_adjustment(wc: pd.DataFrame, bridge: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-player average opponent-strength-adjusted WC rating and add it
    as the column `wc_rating_adjusted`.

    Formula (Peña & Touchette, 2012):
        adj_rating = raw_rating × (opp_strength / global_mean) ** α

    Uses yesterday's player_ratings posteriors as proxy for team strength.
    Falls back to unadjusted wc_rating_avg when:
      - Sofascore events Parquets are missing
      - player_ratings table is empty (first nightly run)
      - The DuckDB JOIN fails for any reason
    """
    lineup_dir = Path(settings.parquet_bronze_dir) / "sofascore" / "lineups"
    events_dir = Path(settings.parquet_bronze_dir) / "sofascore" / "events"

    if not (lineup_dir.is_dir() and list(lineup_dir.glob("*.parquet"))):
        return wc  # no WC data yet — graceful skip
    if not (events_dir.is_dir() and list(events_dir.glob("*.parquet"))):
        logger.warning("No Sofascore events Parquets — opponent adjustment skipped.")
        return wc

    existing_ratings = _load_existing_ratings()
    if not existing_ratings:
        logger.info("player_ratings empty — opponent adjustment skipped (first run).")
        return wc

    lineup_glob = (lineup_dir / "*.parquet").as_posix()
    events_glob = (events_dir / "*.parquet").as_posix()

    conn = duckdb.connect()
    try:
        raw = conn.execute(f"""
            SELECT
                CAST(l.player_id AS VARCHAR) AS sofascore_id,
                CAST(l.event_id  AS BIGINT)  AS event_id,
                l.team_side,
                COALESCE(l.minutes_played, 0) AS minutes_played,
                l.rating
            FROM read_parquet('{lineup_glob}', union_by_name=true) l
            WHERE l.minutes_played > 0 AND l.rating IS NOT NULL
        """).df()

        events = conn.execute(f"""
            SELECT
                CAST(event_id AS BIGINT) AS event_id,
                home_team_id,
                away_team_id
            FROM read_parquet('{events_glob}', union_by_name=true)
        """).df()
    except Exception as exc:
        logger.warning("Opponent adjustment query failed (%s) — skipping.", exc)
        return wc
    finally:
        conn.close()

    if raw.empty or events.empty:
        return wc

    # Build sc_id → reep_id lookup
    sc_to_reep = dict(zip(bridge["sofascore_id"].astype(str), bridge["reep_id"].astype(str)))

    global_mean = float(np.mean(list(existing_ratings.values())))

    # Compute team strength per (event_id, team_side): mean posterior of top-15 by minutes
    raw["reep_id"] = raw["sofascore_id"].map(sc_to_reep)
    raw["opp_rating"] = raw["reep_id"].map(existing_ratings)

    team_strength: dict[tuple[int, str], float] = {}
    for (ev, side), grp in raw.groupby(["event_id", "team_side"]):
        top15 = grp.nlargest(15, "minutes_played")
        valid = top15["opp_rating"].dropna()
        if not valid.empty:
            team_strength[(int(ev), str(side))] = float(valid.mean())

    # For each player-match row, look up opponent-team strength
    opponent_side_map = {"home": "away", "away": "home"}
    raw["opp_side"] = raw["team_side"].map(opponent_side_map)
    raw["opp_key"] = list(zip(raw["event_id"].astype(int), raw["opp_side"]))
    raw["opp_strength"] = raw["opp_key"].map(team_strength).fillna(global_mean)

    # Adjusted rating per match row, then mean per player
    raw["adjusted_rating"] = raw["rating"] * (raw["opp_strength"] / global_mean) ** _OPPONENT_ALPHA
    adj = (
        raw.groupby("sofascore_id")["adjusted_rating"]
        .mean()
        .reset_index()
        .rename(columns={"adjusted_rating": "wc_rating_adjusted"})
    )

    wc = wc.merge(adj, on="sofascore_id", how="left")
    n_adj = wc["wc_rating_adjusted"].notna().sum()
    logger.info(
        "Opponent-strength adjustment (α=%.2f, global_mean=%.3f): %d players adjusted.",
        _OPPONENT_ALPHA, global_mean, n_adj,
    )
    return wc


# ---------------------------------------------------------------------------
# Defensive-action boost for DEF / GK  (Task 5)
# ---------------------------------------------------------------------------

def _apply_defensive_boost(features: pd.DataFrame) -> pd.DataFrame:
    """Boost wc_rating_adjusted for DEF/GK by their within-bucket defensive percentile.

    DEF: def_per_90 = (tackles + interceptions + clearances) / (minutes / 90)
    GK:  def_per_90 = saves / (minutes / 90)

    Boost = 0.3 × percentile (0.0–1.0), applied only to rows with valid WC data.
    Skipped entirely when wc_rating_adjusted hasn't been added yet (first run).
    """
    if "wc_rating_adjusted" not in features.columns:
        return features

    mins = features["wc_minutes"].clip(lower=1e-6)
    per90_div = mins / 90.0

    for bucket, stat_cols in [
        ("DEF", ["wc_tackles_raw", "wc_interceptions_raw", "wc_clearances_raw"]),
        ("GK",  ["wc_saves_raw"]),
    ]:
        mask = (
            (features["position_bucket"] == bucket)
            & features["wc_rating_adjusted"].notna()
            & (features["wc_minutes"].fillna(0) > 0)
        )
        idx = features.index[mask]
        if len(idx) < 2:
            continue

        available = [c for c in stat_cols if c in features.columns]
        if not available:
            continue

        def_raw   = features.loc[idx, available].fillna(0).sum(axis=1)
        def_per90 = def_raw / per90_div.loc[idx]
        pct       = def_per90.rank(pct=True, method="average")
        boost     = 0.3 * pct

        features.loc[idx, "wc_rating_adjusted"] = (
            features.loc[idx, "wc_rating_adjusted"] + boost
        )
        logger.info(
            "Defensive boost (%s): %d players — mean boost=+%.3f, max=+%.3f",
            bucket, len(idx), float(boost.mean()), float(boost.max()),
        )

    return features


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_features() -> pd.DataFrame:
    """
    Build the unified Silver feature matrix.

    Steps:
      1. Aggregate WC stats per player (Sofascore lineups).
      2. Join sofascore_id → reep_id via identity_players bridge.
      3. Load club priors (already keyed by reep_id).
      4. Outer-join WC + club priors on reep_id.
      5. Assign position bucket (reep > Sofascore > Understat).
      6. Drop players with neither WC data nor club prior.
    """
    wc     = load_wc_features()
    bridge = build_sofascore_bridge()
    priors = load_club_priors()

    # 3.1 — Opponent-strength adjustment (requires bridge for sc_id → reep_id mapping)
    if wc.shape[0] > 0:
        wc["sofascore_id"] = wc["sofascore_id"].astype(str)
        bridge["sofascore_id"] = bridge["sofascore_id"].astype(str)
        wc = _apply_opponent_adjustment(wc, bridge)

    # Parquets store player_id as int64; identity_players.key_sofascore is VARCHAR.
    # Both sides already cast to str above (after opponent adjustment). Guard in case
    # we skipped the adjustment block (wc was empty).
    wc["sofascore_id"]     = wc["sofascore_id"].astype(str)
    bridge["sofascore_id"] = bridge["sofascore_id"].astype(str)

    # Attach reep_id to WC rows
    wc_reep = wc.merge(bridge, on="sofascore_id", how="left")
    no_bridge = wc_reep["reep_id"].isna().sum()
    if no_bridge:
        logger.warning(
            "%d WC players could not be bridged to reep_id (sofascore_id not in identity_players).",
            no_bridge,
        )

    # Keep only bridged WC players for the join
    wc_bridged = wc_reep[wc_reep["reep_id"].notna()].copy()

    # Enrich priors with reep position so prior-only players (GKs etc.) get
    # their correct position bucket rather than falling back to "MID".
    bridge_pos = bridge[["reep_id", "reep_position", "nationality", "reep_name"]]
    priors_enriched = priors.merge(bridge_pos, on="reep_id", how="left")

    # Outer-join WC ↔ club priors on reep_id
    features = wc_bridged.merge(priors_enriched, on="reep_id", how="outer",
                                suffixes=("", "_prior"))

    # Coalesce reep identity fields: WC-side wins over prior-side for players
    # who appear in both; prior-side fills in for prior-only players.
    for _col in ("reep_position", "nationality", "reep_name"):
        _col_p = f"{_col}_prior"
        if _col_p in features.columns:
            features[_col] = features[_col].fillna(features[_col_p])
            features.drop(columns=[_col_p], inplace=True)

    # Resolve player name: WC name > reep name > prior name
    features["player_name"] = (
        features["wc_player_name"]
        .fillna(features["reep_name"])
        .fillna(features["prior_player_name"])
    )

    # Position bucket
    features["position_bucket"] = features.apply(
        lambda r: _map_position(
            r.get("reep_position"),
            r.get("wc_sc_position"),
            r.get("prior_us_position"),
        ),
        axis=1,
    )
    features["position_source"] = features.apply(
        lambda r: _position_source(
            r.get("reep_position"),
            r.get("wc_sc_position"),
            r.get("prior_us_position"),
        ),
        axis=1,
    )
    unk_n = (features["position_bucket"] == "UNK").sum()
    if unk_n:
        logger.warning(
            "%d players could not be position-bucketed (all 3 sources missing/unmapped); "
            "flagged UNK — excluded from percentile ranking.",
            unk_n,
        )

    # Data presence flags
    features["has_wc_data"] = features["wc_minutes"].notna() & (features["wc_minutes"] > 0)
    features["has_prior"]   = features["prior_xg_per_90"].notna()
    features["wc_low_data"] = features["wc_low_data"].fillna(True)  # no WC data = data-sparse

    # Task 5 — Defensive-action boost for DEF/GK
    features = _apply_defensive_boost(features)

    # Drop rows with no data at all
    has_any = features["has_wc_data"] | features["has_prior"]
    dropped = (~has_any).sum()
    if dropped:
        logger.info("Dropped %d rows with neither WC data nor club prior.", dropped)
    features = features[has_any].copy()

    logger.info(
        "Feature matrix: %d players  (WC only=%d  prior only=%d  both=%d)",
        len(features),
        (features["has_wc_data"] & ~features["has_prior"]).sum(),
        (~features["has_wc_data"] & features["has_prior"]).sum(),
        (features["has_wc_data"] & features["has_prior"]).sum(),
    )
    logger.info(
        "Position buckets: %s",
        features["position_bucket"].value_counts().to_dict(),
    )
    logger.info(
        "Position sources: %s",
        features["position_source"].value_counts().to_dict(),
    )
    return features


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    logger.info("=== TrueScout Phase 2: build_features ===")

    features = build_features()

    out = Path(settings.parquet_silver_dir) / "player_stats" / "features.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(out, index=False)
    logger.info("Written: %s  (%d rows, %d cols)", out.name, len(features), len(features.columns))

    # Quick sanity check
    for bucket in ["GK", "DEF", "MID", "FWD"]:
        n = (features["position_bucket"] == bucket).sum()
        both = ((features["position_bucket"] == bucket) & features["has_wc_data"] & features["has_prior"]).sum()
        logger.info("  %-4s: %4d players  (%d with both WC+prior)", bucket, n, both)


if __name__ == "__main__":
    main()
