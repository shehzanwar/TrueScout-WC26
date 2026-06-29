"""
Reep identity bridge -- canonical cross-source player and team IDs.

The reep register (github.com/withqwerty/reep) is an open, crowd-maintained
identity table mapping 50+ external IDs per player/team to a single
`reep_id` slug.  We use it as the canonical PK for all Bronze/Silver/Gold
layers so that Understat, Sofascore, and ESPN data can be joined without
fuzzy name-matching.

Key mappings used by TrueScout:
    Understat   -> key_understat -> reep_id
    Sofascore   -> key_sofascore -> reep_id
    ESPN        -> key_espn      -> reep_id
    FotMob      -> key_fotmob    -> reep_id  (future)
    FBref       -> key_fbref     -> reep_id  (future)

Writes Bronze Parquet and populates DuckDB tables:
    data/bronze/reep/people/people.parquet  -> identity_players table
    data/bronze/reep/teams/teams.parquet    -> identity_teams table
    data/bronze/reep/names/names.parquet    -> identity_names table (alias lookup)

Usage:
    python -m etl.sources.reep_pull             # full pull + load
    python -m etl.sources.reep_pull --validate  # count rows only, no write
"""
import argparse
import logging
from pathlib import Path

import duckdb

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import settings
from etl.db.init_db import refresh_parquet_views

logger = logging.getLogger(__name__)

PEOPLE_URL = "https://raw.githubusercontent.com/withqwerty/reep/main/data/people.csv"
TEAMS_URL  = "https://raw.githubusercontent.com/withqwerty/reep/main/data/teams.csv"
NAMES_URL  = "https://raw.githubusercontent.com/withqwerty/reep/main/data/names.csv"

BRONZE_DIR = Path(settings.parquet_bronze_dir) / "reep"

# ---------------------------------------------------------------------------
# DuckDB helpers
# ---------------------------------------------------------------------------

def _open_conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(Path(settings.duckdb_path)))
    for ext in ("httpfs", "json"):
        try:
            conn.execute(f"INSTALL {ext}; LOAD {ext};")
        except Exception:
            pass
    return conn


def _parquet_path(name: str) -> Path:
    return BRONZE_DIR / name / f"{name}.parquet"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_csv_to_parquet(conn: duckdb.DuckDBPyConnection, url: str, out: Path) -> int:
    """
    Stream a CSV from URL via DuckDB httpfs and write a Bronze Parquet file.
    All columns are read as VARCHAR to preserve hex IDs (e.g. key_fbref).
    Returns row count.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s ...", url.split("/")[-1])
    conn.execute(f"""
        COPY (
            SELECT *
            FROM read_csv_auto(
                '{url}',
                all_varchar = true,
                ignore_errors = true
            )
        ) TO '{out.as_posix()}' (FORMAT PARQUET)
    """)
    n = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
    logger.info("  -> %s  (%d rows)", out.name, n)
    return n


# ---------------------------------------------------------------------------
# Identity table creation
# ---------------------------------------------------------------------------

_IDENTITY_PLAYERS_DDL = """
CREATE OR REPLACE TABLE identity_players AS
SELECT
    reep_id,
    "name"        AS name,
    full_name,
    CASE
        WHEN date_of_birth IS NOT NULL AND date_of_birth != ''
        THEN TRY_CAST(date_of_birth AS DATE)
    END                    AS date_of_birth,
    nationality,
    "position"             AS position,
    position_detail,
    TRY_CAST(height_cm AS DOUBLE) AS height_cm,
    key_fbref,
    key_sofascore,
    key_espn,
    key_understat,
    key_fotmob,
    key_transfermarkt,
    key_wyscout,
    key_whoscored,
    key_opta,
    key_wikidata
FROM read_parquet('{people_parquet}')
WHERE "type" = 'player'
  AND reep_id IS NOT NULL
  AND reep_id != ''
"""

_IDENTITY_TEAMS_DDL = """
CREATE OR REPLACE TABLE identity_teams AS
SELECT
    reep_id,
    "name"          AS name,
    country,
    founded,
    stadium,
    key_espn,
    key_sofascore,
    key_fbref,
    key_fotmob,
    key_understat,
    key_transfermarkt,
    key_clubelo,
    key_opta,
    key_wikidata
FROM read_parquet('{teams_parquet}')
WHERE reep_id IS NOT NULL
  AND reep_id != ''
"""


def build_identity_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Recreate identity_players and identity_teams from Bronze Parquet."""
    people_p = _parquet_path("people")
    teams_p  = _parquet_path("teams")

    logger.info("Building identity_players ...")
    conn.execute(_IDENTITY_PLAYERS_DDL.format(people_parquet=people_p.as_posix()))
    n_players = conn.execute("SELECT COUNT(*) FROM identity_players").fetchone()[0]
    logger.info("  -> identity_players: %d rows", n_players)

    logger.info("Building identity_teams ...")
    conn.execute(_IDENTITY_TEAMS_DDL.format(teams_parquet=teams_p.as_posix()))
    n_teams = conn.execute("SELECT COUNT(*) FROM identity_teams").fetchone()[0]
    logger.info("  -> identity_teams: %d rows", n_teams)

    # Coverage stats for our primary sources
    for src, col in [
        ("Understat", "key_understat"),
        ("Sofascore", "key_sofascore"),
        ("ESPN",      "key_espn"),
        ("FotMob",    "key_fotmob"),
        ("FBref",     "key_fbref"),
    ]:
        n = conn.execute(f"""
            SELECT COUNT(*) FROM identity_players
            WHERE {col} IS NOT NULL AND {col} != ''
        """).fetchone()[0]
        logger.info("    %s (key_%s) coverage: %d players", src, col.split("_",1)[1], n)


_IDENTITY_NAMES_DDL = """
CREATE OR REPLACE TABLE identity_names AS
SELECT
    n.reep_id,
    n.name,
    n.alias,
    n.key_wikidata
FROM read_parquet('{names_parquet}') n
WHERE n.reep_id IS NOT NULL AND n.reep_id != ''
  AND n.alias   IS NOT NULL AND n.alias   != ''
  AND n.reep_id IN (SELECT reep_id FROM identity_players)
"""


def build_identity_names(conn: duckdb.DuckDBPyConnection) -> None:
    """Recreate identity_names alias table from Bronze Parquet (players only)."""
    names_p = _parquet_path("names")
    if not names_p.exists():
        logger.warning("names.parquet not found -- skipping identity_names build.")
        return
    logger.info("Building identity_names ...")
    conn.execute(_IDENTITY_NAMES_DDL.format(names_parquet=names_p.as_posix()))
    n = conn.execute("SELECT COUNT(*) FROM identity_names").fetchone()[0]
    logger.info("  -> identity_names: %d alias rows (player aliases only)", n)


# ---------------------------------------------------------------------------
# Validation query
# ---------------------------------------------------------------------------

VALIDATION_QUERY = """
-- Verify cross-source ID linkage for well-known WC players.
-- Run after reep_pull.py: python -m etl.sources.reep_pull
SELECT
    ip.reep_id,
    ip.name,
    ip.nationality,
    ip.position,
    ip.key_understat   AS understat_id,
    ip.key_sofascore   AS sofascore_id,
    ip.key_espn        AS espn_id,
    ip.key_fotmob      AS fotmob_id
FROM identity_players ip
WHERE ip.name ILIKE '%Haaland%'
   OR ip.name ILIKE '%Mohamed Salah%'
   OR ip.name ILIKE '%Vinicius%'
   OR ip.name ILIKE '%Mbappe%'
ORDER BY ip.name;
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Pull reep identity register into Bronze Parquet and DuckDB."
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Count rows in existing Bronze files only; do not re-download.",
    )
    args = parser.parse_args()

    logger.info("=== TrueScout Phase 1: reep_pull ===")

    conn = _open_conn()
    try:
        if args.validate:
            for name in ("people", "teams", "names"):
                p = _parquet_path(name)
                if p.exists():
                    n = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{p.as_posix()}')").fetchone()[0]
                    logger.info("%s: %d rows", p.name, n)
                else:
                    logger.warning("%s not found -- run without --validate first.", p.name)
            # Run validation query if tables exist
            try:
                result = conn.execute(VALIDATION_QUERY).df()
                if not result.empty:
                    logger.info("Sample linkage:\n%s", result.to_string(index=False))
                else:
                    logger.warning("No matching rows -- identity_players may be empty.")
            except duckdb.CatalogException:
                logger.warning("identity_players table not found -- run without --validate first.")
            return

        # Full pull
        people_p = _parquet_path("people")
        teams_p  = _parquet_path("teams")
        names_p  = _parquet_path("names")

        download_csv_to_parquet(conn, PEOPLE_URL, people_p)
        download_csv_to_parquet(conn, TEAMS_URL,  teams_p)
        download_csv_to_parquet(conn, NAMES_URL,  names_p)

        build_identity_tables(conn)
        build_identity_names(conn)
        refresh_parquet_views(conn)

        logger.info("=== Reep pull complete ===")
        logger.info("Validation query (copy-paste into DuckDB shell):\n%s", VALIDATION_QUERY)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
