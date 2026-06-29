"""
etl/load/load_identity.py — Reep Bronze register → identity_players DuckDB table.

Reads: data/bronze/reep/people/people.parquet
Writes: identity_players (bulk upsert — INSERT OR REPLACE on reep_id PK)

Why this step exists
--------------------
identity_players is the reep_id ↔ external-key crosswalk (sofascore, understat,
espn …).  Every downstream math step depends on it:

  • build_features.build_sofascore_bridge()    — reep_id ↔ key_sofascore
  • monte_carlo_sim._build_team_strengths()    — same join
  • export_json.export_players()               — player name / nationality

The DuckDB file is .gitignored (rebuilt from scratch on every CI run).  Without
this step running in CI, identity_players stays empty, WC Parquets can't be
bridged to player_ratings, and team-strength queries return 0 teams → every
bracket team gets FALLBACK_STRENGTH and the sim becomes a coin-flip.

Run:
    python -m etl.load.load_identity
"""
import logging
from pathlib import Path

from config import settings
from etl.db.connection import write_conn

logger = logging.getLogger(__name__)

_PEOPLE_PARQUET = Path(settings.parquet_bronze_dir) / "reep" / "people" / "people.parquet"


def load_identity() -> int:
    """
    Bulk-upsert identity_players from the Reep people Parquet.

    Filters to rows where key_sofascore IS NOT NULL OR key_understat IS NOT NULL
    (~84 K rows) — the only rows the pipeline actually needs.  All casts are
    explicit so type mismatches in the Parquet don't silently drop rows.

    Returns the number of rows now in identity_players with key_sofascore.
    """
    if not _PEOPLE_PARQUET.exists():
        logger.error(
            "people.parquet not found at %s — "
            "identity_players will stay empty; pipeline falls back to prior-only.",
            _PEOPLE_PARQUET,
        )
        return 0

    parquet_path = _PEOPLE_PARQUET.as_posix()

    with write_conn() as conn:
        # Stage the incoming rows in a temp table (single Parquet read).
        # Cannot use INSERT OR REPLACE directly because the local DuckDB may
        # have been created before the PRIMARY KEY constraint was added to the
        # DDL (IF NOT EXISTS skips DDL changes on existing tables).
        conn.execute(f"""
            CREATE OR REPLACE TEMP TABLE _id_stage AS
            SELECT
                CAST(reep_id            AS VARCHAR) AS reep_id,
                CAST(name               AS VARCHAR) AS name,
                CAST(full_name          AS VARCHAR) AS full_name,
                TRY_CAST(date_of_birth  AS DATE)    AS date_of_birth,
                CAST(nationality        AS VARCHAR) AS nationality,
                CAST(position           AS VARCHAR) AS position,
                CAST(position_detail    AS VARCHAR) AS position_detail,
                TRY_CAST(height_cm      AS DOUBLE)  AS height_cm,
                CAST(key_fbref          AS VARCHAR) AS key_fbref,
                CAST(key_sofascore      AS VARCHAR) AS key_sofascore,
                CAST(key_espn           AS VARCHAR) AS key_espn,
                CAST(key_understat      AS VARCHAR) AS key_understat,
                CAST(key_fotmob         AS VARCHAR) AS key_fotmob,
                CAST(key_transfermarkt  AS VARCHAR) AS key_transfermarkt,
                CAST(key_wyscout        AS VARCHAR) AS key_wyscout,
                CAST(key_whoscored      AS VARCHAR) AS key_whoscored,
                CAST(key_opta           AS VARCHAR) AS key_opta,
                CAST(key_wikidata       AS VARCHAR) AS key_wikidata
            FROM read_parquet('{parquet_path}')
            WHERE key_sofascore IS NOT NULL
               OR key_understat IS NOT NULL
        """)

        # Remove any rows that will be replaced so we can re-insert cleanly.
        conn.execute("""
            DELETE FROM identity_players
            WHERE reep_id IN (SELECT reep_id FROM _id_stage)
        """)

        conn.execute("""
            INSERT INTO identity_players (
                reep_id, name, full_name, date_of_birth,
                nationality, position, position_detail, height_cm,
                key_fbref, key_sofascore, key_espn, key_understat,
                key_fotmob, key_transfermarkt, key_wyscout,
                key_whoscored, key_opta, key_wikidata
            )
            SELECT
                reep_id, name, full_name, date_of_birth,
                nationality, position, position_detail, height_cm,
                key_fbref, key_sofascore, key_espn, key_understat,
                key_fotmob, key_transfermarkt, key_wyscout,
                key_whoscored, key_opta, key_wikidata
            FROM _id_stage
        """)

        total, with_sc = conn.execute("""
            SELECT
                COUNT(*)                                                AS total,
                COUNT(CASE WHEN key_sofascore IS NOT NULL THEN 1 END)  AS with_sc
            FROM identity_players
        """).fetchone()

    logger.info(
        "identity_players: %d total rows  (%d with key_sofascore)", total, with_sc
    )
    return with_sc


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    logger.info("=== TrueScout load_identity ===")
    load_identity()
    logger.info("=== load_identity complete ===")


if __name__ == "__main__":
    main()
