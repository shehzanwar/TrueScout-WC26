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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Position mapping
# ---------------------------------------------------------------------------

# Reep uses full English words with many historical variants.
_REEP_BUCKET: dict[str, str] = {
    "goalkeeper": "GK",
    # Defenders
    "defender": "DEF", "full-back": "DEF", "centre-back": "DEF",
    "stopper": "DEF", "sweeper": "DEF", "wing half": "DEF",
    "right back": "DEF", "left back": "DEF",
    # Midfielders
    "midfielder": "MID", "central midfielder": "MID",
    "defensive midfielder": "MID", "attacking midfielder": "MID",
    "wide midfielder": "MID", "winger": "MID",
    "left winger": "MID", "right winger": "MID",
    "inside forward": "MID",
    # Forwards
    "forward": "FWD", "attacker": "FWD", "centre-forward": "FWD",
    "striker": "FWD",
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
        return _US_FIRST.get(first, "MID")
    return "MID"


# ---------------------------------------------------------------------------
# WC aggregation
# ---------------------------------------------------------------------------

_WC_AGG_SQL = """
SELECT
    CAST(player_id AS VARCHAR)          AS sofascore_id,
    ANY_VALUE(player_name)              AS wc_player_name,
    ANY_VALUE(position)                 AS wc_sc_position,
    COUNT(*)                            AS wc_matches,
    SUM(minutes_played)                 AS wc_minutes,
    SUM(COALESCE(goals, 0))             AS wc_goals_raw,
    SUM(COALESCE(assists, 0))           AS wc_assists_raw,
    SUM(xg)                             AS wc_xg_raw,
    SUM(xa)                             AS wc_xa_raw,
    SUM(COALESCE(shots, 0))             AS wc_shots_raw,
    SUM(COALESCE(shots_on_target, 0))   AS wc_sot_raw,
    SUM(COALESCE(key_passes, 0))        AS wc_key_passes_raw,
    SUM(COALESCE(tackles, 0))           AS wc_tackles_raw,
    SUM(COALESCE(interceptions, 0))     AS wc_interceptions_raw,
    SUM(COALESCE(clearances, 0))        AS wc_clearances_raw,
    SUM(COALESCE(saves, 0))             AS wc_saves_raw,
    AVG(rating)                         AS wc_rating_avg
FROM read_parquet('{lineup_glob}', union_by_name=true)
WHERE minutes_played > 0
GROUP BY player_id
"""

_PER90_STATS = [
    "goals", "assists", "xg", "xa", "shots", "sot",
    "key_passes", "tackles", "interceptions", "clearances", "saves",
]


def _per90(df: pd.DataFrame) -> pd.DataFrame:
    """Add per-90 WC columns, computed from raw sums and total minutes."""
    mins = df["wc_minutes"].clip(lower=1e-6)
    for stat in _PER90_STATS:
        raw = df.get(f"wc_{stat}_raw")
        if raw is not None:
            df[f"wc_{stat}_per_90"] = raw / (mins / 90.0)
    return df


# Columns produced by _WC_AGG_SQL — used to build the schema-correct empty
# DataFrame when Sofascore Parquets are absent (e.g. GitHub Actions CI).
_WC_AGG_COLS = [
    "sofascore_id", "wc_player_name", "wc_sc_position", "wc_matches",
    "wc_minutes", "wc_goals_raw", "wc_assists_raw", "wc_xg_raw", "wc_xa_raw",
    "wc_shots_raw", "wc_sot_raw", "wc_key_passes_raw", "wc_tackles_raw",
    "wc_interceptions_raw", "wc_clearances_raw", "wc_saves_raw", "wc_rating_avg",
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
        wc = conn.execute(_WC_AGG_SQL.format(lineup_glob=lineup_glob)).df()
    finally:
        conn.close()

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

    # Parquets store player_id as int64; identity_players.key_sofascore is VARCHAR.
    # Cast both sides to str so pandas merge matches them correctly.
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

    # Data presence flags
    features["has_wc_data"] = features["wc_minutes"].notna() & (features["wc_minutes"] > 0)
    features["has_prior"]   = features["prior_xg_per_90"].notna()
    features["wc_low_data"] = features["wc_low_data"].fillna(True)  # no WC data = data-sparse

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
