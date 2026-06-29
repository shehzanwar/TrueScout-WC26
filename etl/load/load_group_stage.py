"""
etl/load/load_group_stage.py — Bronze → DuckDB promotion for group-stage matches.

Reads from v_bronze_espn_matches (the lazy Parquet view over espn/matches/*.parquet)
and upserts into two DuckDB tables:

  1. teams   — national teams discovered from ESPN home/away fields
  2. matches — one row per completed group-stage match

ID policy (Phase 1)
────────────────────
Cross-source ID resolution (ESPN ↔ Sofascore ↔ FBref) is a Phase 2 task in
etl/matching/.  Until that runs, every team gets an 'espn-{espn_id}' internal
ID and every match gets an 'espn-{event_id}' internal ID.  These are
deliberately prefixed so Phase 2 can overwrite them once canonical IDs exist.

Run:
    python -m etl.load.load_group_stage
"""
from __future__ import annotations

import logging
import re
from typing import Any

import duckdb
import pandas as pd

from config import settings
from etl.db.connection import write_conn
from etl.db.init_db import init_schema

logger = logging.getLogger(__name__)

# Matches v_bronze_espn_matches round_name → canonical matches.round values
_GROUP_RE = re.compile(r"^group\s+[a-z]+$", re.IGNORECASE)

_ROUND_MAP: dict[str, str] = {
    "round of 32": "round_of_32",
    "round of 16": "round_of_16",
    "quarterfinal": "quarter_final",
    "quarter-final": "quarter_final",
    "quarter final": "quarter_final",
    "semifinal": "semi_final",
    "semi-final": "semi_final",
    "semi final": "semi_final",
    "third place": "third_place",
    "3rd place": "third_place",
    "final": "final",
}


def _normalize_round(round_name: str | None) -> str:
    if round_name is None:
        return "group_stage"
    rn = round_name.strip()
    if _GROUP_RE.match(rn):
        return "group_stage"
    lower = rn.lower()
    for pattern, canonical in _ROUND_MAP.items():
        if pattern in lower:
            return canonical
    # Unknown round — preserve the raw value so we can diagnose later
    return rn


def _int_or_none(val: Any) -> int | None:
    try:
        return int(val) if pd.notna(val) else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Team upsert
# ---------------------------------------------------------------------------


def load_teams(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """
    Upsert every unique national team present in the Bronze matches DataFrame.

    Team ID is 'espn-{espn_id}' until Phase 2 ID resolution runs.
    Only fills columns that ESPN provides; remaining fields stay NULL.
    """
    home = df[["home_team_id", "home_team_name", "home_team_abbrev"]].rename(
        columns={
            "home_team_id": "espn_id",
            "home_team_name": "name",
            "home_team_abbrev": "abbrev",
        }
    )
    away = df[["away_team_id", "away_team_name", "away_team_abbrev"]].rename(
        columns={
            "away_team_id": "espn_id",
            "away_team_name": "name",
            "away_team_abbrev": "abbrev",
        }
    )

    teams = (
        pd.concat([home, away], ignore_index=True)
        .drop_duplicates(subset="espn_id")
        .copy()
    )
    teams["id"] = "espn-" + teams["espn_id"].astype(str)
    teams["short_name"] = teams["abbrev"]
    teams["is_national"] = True

    stage = teams[["id", "name", "short_name", "is_national", "espn_id"]].copy()
    conn.register("_stage_teams", stage)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO teams (id, name, short_name, is_national, espn_id)
            SELECT id, name, short_name, is_national, espn_id
            FROM _stage_teams
        """)
    finally:
        conn.unregister("_stage_teams")

    logger.info("Teams upserted: %d rows → teams", len(stage))
    return len(stage)


# ---------------------------------------------------------------------------
# Match upsert
# ---------------------------------------------------------------------------


def load_matches(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """
    Upsert all completed group-stage matches from the Bronze DataFrame.

    Derives result_after_90, winner_team_id, and result_final from home/away
    scores.  For group-stage draws, result_final is NULL (no knockout winner).
    """
    rows: list[dict] = []

    for _, row in df.iterrows():
        home_score = _int_or_none(row["home_score"])
        away_score = _int_or_none(row["away_score"])

        if home_score is not None and away_score is not None:
            if home_score > away_score:
                result_after_90 = "home"
                winner_id = f"espn-{row['home_team_id']}"
                result_final = "home"
            elif away_score > home_score:
                result_after_90 = "away"
                winner_id = f"espn-{row['away_team_id']}"
                result_final = "away"
            else:
                result_after_90 = "draw"
                winner_id = None
                result_final = None   # group-stage draw: no knockout winner
        else:
            result_after_90 = None
            winner_id = None
            result_final = None

        rows.append({
            "id":               f"espn-{row['event_id']}",
            "tournament":       "FIFA World Cup 2026",
            "round":            _normalize_round(row.get("round_name")),
            "home_team_id":     f"espn-{row['home_team_id']}",
            "away_team_id":     f"espn-{row['away_team_id']}",
            "match_date":       row.get("start_time_utc"),
            "venue":            row.get("venue_name"),
            "home_score":       home_score,
            "away_score":       away_score,
            "result_after_90":  result_after_90,
            "result_final":     result_final,
            "winner_team_id":   winner_id,
            "espn_id":          str(row["event_id"]),
            "is_completed":     True,
            "fetched_at":       row.get("fetched_at"),
        })

    matches_df = pd.DataFrame(rows)
    conn.register("_stage_matches", matches_df)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO matches (
                id, tournament, round,
                home_team_id, away_team_id,
                match_date, venue,
                home_score, away_score,
                result_after_90, result_final, winner_team_id,
                espn_id, is_completed, fetched_at
            )
            SELECT
                id, tournament, round,
                home_team_id, away_team_id,
                TRY_CAST(match_date AS TIMESTAMP), venue,
                home_score, away_score,
                result_after_90, result_final, winner_team_id,
                espn_id, is_completed,
                TRY_CAST(fetched_at AS TIMESTAMP)
            FROM _stage_matches
        """)
    finally:
        conn.unregister("_stage_matches")

    logger.info("Matches upserted: %d rows → matches", len(matches_df))
    return len(matches_df)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("=== TrueScout group-stage loader ===")

    with write_conn() as conn:
        # Idempotent: creates tables + refreshes Parquet views for any source
        # that already has files (v_bronze_espn_matches should appear here).
        init_schema(conn)

        # ── Read Bronze ─────────────────────────────────────────────────────
        try:
            bronze_df: pd.DataFrame = conn.execute(
                "SELECT * FROM v_bronze_espn_matches WHERE is_completed = TRUE"
            ).df()
        except duckdb.CatalogException:
            logger.error(
                "v_bronze_espn_matches view not found. "
                "Run first:  python -m etl.sources.espn_pull --group-stage"
            )
            return

        if bronze_df.empty:
            logger.warning("No completed matches in Bronze — nothing to load.")
            return

        logger.info("Bronze rows (completed): %d", len(bronze_df))

        # ── Quick sanity check ───────────────────────────────────────────────
        rounds = bronze_df["round_name"].value_counts().to_dict()
        logger.info("Round breakdown: %s", rounds)

        # ── Upsert ──────────────────────────────────────────────────────────
        n_teams = load_teams(conn, bronze_df)
        n_matches = load_matches(conn, bronze_df)

        # ── Verify ──────────────────────────────────────────────────────────
        verify = conn.execute("""
            SELECT
                COUNT(*)                                            AS total_matches,
                COUNT(CASE WHEN result_after_90 = 'home' THEN 1 END) AS home_wins,
                COUNT(CASE WHEN result_after_90 = 'draw' THEN 1 END) AS draws,
                COUNT(CASE WHEN result_after_90 = 'away' THEN 1 END) AS away_wins
            FROM matches
            WHERE tournament = 'FIFA World Cup 2026'
              AND round = 'group_stage'
        """).fetchone()

        logger.info(
            "matches table — total=%d  home_wins=%d  draws=%d  away_wins=%d",
            *verify,
        )
        logger.info(
            "=== Loader complete: %d teams, %d matches upserted ===",
            n_teams, n_matches,
        )


if __name__ == "__main__":
    main()
