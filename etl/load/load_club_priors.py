"""
Silver-layer load: Understat Bronze --> club_priors DuckDB table.

This is the Phase 2 counterpart to understat_pull.py (which writes Bronze).
It joins the Bronze aggregate on players.understat_id to resolve the
'us-{understat_id}' Bronze key to the canonical players.id, then upserts
into the club_priors table.

ID-resolution strategy (in order):
  1. Exact match on players.understat_id  (populated when a player was
     first seen in Sofascore lineups and their Understat ID was added
     manually or via the etl/matching/ reconciliation pass).
  2. Fuzzy name + team fallback (logs a warning; requires human review).
  3. Unresolved rows are written to data/silver/club_priors/unmatched.parquet
     for the reep reconciliation pass -- NOT silently dropped.

Run AFTER:
    python -m etl.sources.understat_pull        (Bronze populated)
    python -m etl.matching.resolve_understat    (players.understat_id populated)

Usage:
    python -m etl.load.load_club_priors
    python -m etl.load.load_club_priors --dry-run
"""
import argparse
import logging
from pathlib import Path

import duckdb
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import settings

logger = logging.getLogger(__name__)

BRONZE_AGG  = Path(settings.parquet_bronze_dir) / "understat" / "club_priors_agg.parquet"
UNMATCHED   = Path(settings.parquet_silver_dir) / "club_priors" / "unmatched.parquet"

SEASON_WINDOW = "2024-25+2025-26"


def load(conn: duckdb.DuckDBPyConnection, dry_run: bool = False) -> None:
    if not BRONZE_AGG.exists():
        logger.error(
            "Bronze aggregate not found: %s  -- run understat_pull.py first.", BRONZE_AGG
        )
        return

    bronze = pd.read_parquet(BRONZE_AGG)
    logger.info("Bronze rows: %d", len(bronze))

    # ── Step 1: resolve understat_id -> players.id ──────────────────────────
    player_map = conn.execute(
        "SELECT id AS player_id, understat_id FROM players WHERE understat_id IS NOT NULL"
    ).df()

    merged = bronze.merge(
        player_map,
        on="understat_id",
        how="left",
        suffixes=("_bronze", ""),
    )
    # player_id column from players table wins; Bronze 'us-xxx' column renamed
    merged = merged.rename(columns={"player_id_bronze": "bronze_key"})

    resolved   = merged[merged["player_id"].notna()].copy()
    unresolved = merged[merged["player_id"].isna()].copy()

    logger.info(
        "ID resolution: %d resolved / %d unmatched (%.1f%%)",
        len(resolved),
        len(unresolved),
        100 * len(unresolved) / max(len(merged), 1),
    )

    if not unresolved.empty:
        UNMATCHED.parent.mkdir(parents=True, exist_ok=True)
        unresolved.to_parquet(UNMATCHED, index=False)
        logger.warning(
            "%d players have no understat_id in players table -- "
            "written to %s for manual reconciliation via etl/matching/.",
            len(unresolved), UNMATCHED,
        )

    if resolved.empty:
        logger.error("Zero resolved players -- nothing to write.")
        return

    # ── Step 2: build club_priors rows ───────────────────────────────────────
    cols = [
        "player_id", "season_window",
        "matches_played", "minutes_played",
        "goals_per_90", "assists_per_90", "xg_per_90", "xa_per_90",
        "npxg_per_90", "shots_per_90", "key_passes_per_90",
        "shots_on_target_pct", "sca_per_90", "gca_per_90",
        "pass_completion_pct", "progressive_passes_per_90",
        "progressive_carries_per_90", "carries_into_final_third_per_90",
        "pressures_per_90", "pressure_success_pct",
        "tackles_per_90", "tackle_success_pct",
        "interceptions_per_90", "clearances_per_90", "aerials_won_pct",
        "save_pct", "psxg_minus_ga_per_90", "clean_sheet_pct",
        "data_source", "fetched_at",
    ]
    resolved["season_window"] = SEASON_WINDOW
    # Keep only columns that exist in the Bronze aggregate
    out = resolved[[c for c in cols if c in resolved.columns]]
    # Add any columns the Bronze doesn't carry (fill with NULL)
    for c in cols:
        if c not in out.columns:
            out[c] = None

    out = out[cols]
    logger.info("Rows to upsert: %d", len(out))

    if dry_run:
        logger.info("DRY RUN -- skipping write.\n%s", out.head(5).to_string(index=False))
        return

    # ── Step 3: upsert (INSERT OR REPLACE) ───────────────────────────────────
    conn.register("_cp_stage", out)
    conn.execute("""
        INSERT OR REPLACE INTO club_priors
        SELECT * FROM _cp_stage
    """)
    n = conn.execute(
        "SELECT COUNT(*) FROM club_priors WHERE data_source = 'understat'"
    ).fetchone()[0]
    logger.info("club_priors rows with data_source='understat': %d", n)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    ap = argparse.ArgumentParser(description="Load Understat Bronze -> club_priors Silver.")
    ap.add_argument("--dry-run", action="store_true", help="Print plan, do not write.")
    args = ap.parse_args()

    conn = duckdb.connect(str(Path(settings.duckdb_path)))
    try:
        load(conn, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
