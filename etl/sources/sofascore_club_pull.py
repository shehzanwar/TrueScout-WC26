"""
etl/sources/sofascore_club_pull.py — Pull club season stats from Sofascore.

Target: WC 2026 players who lack an Understat club prior (non-big-5 leagues:
Saudi Pro, MLS, J.League, Brasileirao, Eredivisie, etc.).  Sofascore has
broad league coverage via its season-statistics endpoint.

Endpoint
--------
GET /player/{key_sofascore}/statistics/seasons
Returns all club-competition seasons for a player with aggregate stats
(appearances, minutes, goals, assists, Sofascore avg rating).

Challenge-auth note
-------------------
Sofascore's player PROFILE endpoint (/player/{id}) has been locked since
~2026-07 with `reason: "challenge"`.  This script targets the STATISTICS
sub-path (/player/{id}/statistics/seasons), which may or may not share the
same auth gate.  A challenge 403 on the FIRST call triggers an immediate
abort — existing Bronze Parquet is preserved and the script exits cleanly.

Output
------
data/bronze/sofascore/club_stats.parquet
Schema (per season row):
  reep_id, key_sofascore,
  season_id, season_name, season_year,
  unique_tournament_id, unique_tournament_name,
  team_id, team_name,
  appearances, minutes_played,
  goals, assists, goals_per_90, assists_per_90,
  rating, fetched_at

Usage
-----
    py -m etl.sources.sofascore_club_pull           # no-prior WC players
    py -m etl.sources.sofascore_club_pull --all     # all WC players (incl. big-5)
    py -m etl.sources.sofascore_club_pull --refresh # re-fetch already-stored
"""

from __future__ import annotations

import argparse
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from config import settings
from etl.sources.sofascore_pull import (
    BlockedError,
    NotFoundError,
    SofascoreClient,
    _fetch_url,
)

logger = logging.getLogger(__name__)

DB_PATH       = Path("data/truescout.duckdb")
FEATURES_PATH = Path(settings.parquet_silver_dir) / "player_stats" / "features.parquet"
LINEUPS_GLOB  = (Path(settings.parquet_bronze_dir) / "sofascore" / "lineups" / "*.parquet").as_posix()

CLUB_STATS_PARQUET = Path(settings.parquet_bronze_dir) / "sofascore" / "club_stats.parquet"

# Filter to the two most recent league seasons by Sofascore season year
RECENT_SEASON_COUNT = 2

# Minimum appearances — skip very-short loan stints
MIN_APPEARANCES = 3

# Inter-request sleep (stay well below Sofascore's rate limit)
_SLEEP_MIN = 1.5
_SLEEP_MAX = 2.5


def _sleep() -> None:
    time.sleep(random.uniform(_SLEEP_MIN, _SLEEP_MAX))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_targets(all_players: bool = False, refresh: bool = False) -> list[tuple[str, str]]:
    """
    Return (reep_id, key_sofascore) pairs to fetch.

    Without --all: only WC players who have no Understat club prior.
    With --all: all WC players who have a key_sofascore.
    Without --refresh: skip reep_ids already in the club_stats parquet.
    """
    # Who is in the WC squad (any lineups appearance)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        wc_ids = con.execute(f"""
            SELECT DISTINCT CAST(player_id AS VARCHAR)
            FROM read_parquet('{LINEUPS_GLOB}', union_by_name=true)
        """).fetchall()
        wc_reep_ids = {r[0] for r in wc_ids}

        if not FEATURES_PATH.exists():
            logger.warning("features.parquet not found — targeting all WC players")
            no_prior_ids = wc_reep_ids
        elif all_players:
            no_prior_ids = wc_reep_ids
        else:
            feat = pd.read_parquet(FEATURES_PATH)[["reep_id", "has_prior"]]
            no_prior_ids = set(feat.loc[~feat["has_prior"], "reep_id"]) & wc_reep_ids

        # Map to key_sofascore
        if no_prior_ids:
            ph = ",".join(f"'{r}'" for r in no_prior_ids)
            rows = con.execute(f"""
                SELECT reep_id, CAST(key_sofascore AS VARCHAR)
                FROM identity_players
                WHERE reep_id IN ({ph})
                  AND key_sofascore IS NOT NULL
            """).fetchall()
        else:
            rows = []
    finally:
        con.close()

    # Exclude already-fetched players unless refresh
    if not refresh and CLUB_STATS_PARQUET.exists():
        existing = set(pd.read_parquet(CLUB_STATS_PARQUET)["reep_id"].tolist())
        rows = [(r, ss) for r, ss in rows if r not in existing]

    logger.info(
        "Targets: %d players  (all=%s, refresh=%s)",
        len(rows), all_players, refresh,
    )
    return rows


# ---------------------------------------------------------------------------
# API fetch + parse
# ---------------------------------------------------------------------------

def _fetch_player_stats(client: SofascoreClient, ss_id: str) -> list[dict] | None:
    """
    Fetch all season-level club stats for a Sofascore player ID.

    Returns a list of season dicts (each is one tournament-season stint),
    or None if the endpoint is blocked / the player has no data.
    Sets client._challenge_abort=True on challenge 403 for early loop exit.
    """
    path = f"/player/{ss_id}/statistics/seasons"
    try:
        data = client.get(path, f"player-{ss_id}")
    except Exception:
        return None

    if data is None:
        return None

    # Detect challenge-auth JSON error (returned with HTTP 200 but wrapped)
    if "error" in data:
        reason = (data["error"] or {}).get("reason", "")
        code   = (data["error"] or {}).get("code", 0)
        if code == 403 and reason == "challenge":
            logger.error(
                "Sofascore player stats endpoint requires challenge auth (ss=%s). "
                "Aborting — existing Bronze Parquet preserved.",
                ss_id,
            )
            client._challenge_abort = True  # type: ignore[attr-defined]
            return None
        logger.warning("Sofascore API error for ss=%s: %s", ss_id, data["error"])
        return None

    # Response: {"statistics": {"seasons": [...]}}
    outer = data.get("statistics") or {}
    seasons = outer.get("seasons") or []
    return seasons


def _parse_seasons(
    reep_id: str,
    ss_id: str,
    raw_seasons: list[dict],
    fetch_ts: datetime,
) -> pd.DataFrame:
    """
    Flatten raw Sofascore season objects into a tidy DataFrame.

    Sofascore response structure (per season):
      {
        "seasonId": 12345,
        "season": {"id": 12345, "name": "24/25", "year": 2024},
        "uniqueTournament": {"id": 34, "name": "Ligue 1"},
        "team": {"id": 5678, "name": "PSG"},
        "statistics": {
          "appearances": 30,
          "minutesPlayed": 2560,
          "goals": 10,
          "goalAssist": 8,
          "rating": 7.23,
          ...
        }
      }

    Only includes club-league seasons (filters out minor cups / friendlies
    by requiring appearances >= MIN_APPEARANCES).
    """
    rows: list[dict] = []
    for s in raw_seasons:
        stats: dict = s.get("statistics") or {}
        season: dict = s.get("season") or {}
        ut: dict    = s.get("uniqueTournament") or {}
        team: dict  = s.get("team") or {}

        appearances = int(stats.get("appearances") or 0)
        if appearances < MIN_APPEARANCES:
            continue

        minutes = int(stats.get("minutesPlayed") or 0) or None
        goals   = int(stats.get("goals") or 0)
        assists = int(stats.get("goalAssist") or stats.get("assists") or 0)

        g90 = (goals   / minutes * 90) if minutes else None
        a90 = (assists / minutes * 90) if minutes else None

        rating_raw = stats.get("rating") or stats.get("averageRating")
        try:
            rating = float(rating_raw) if rating_raw is not None else None
        except (TypeError, ValueError):
            rating = None

        rows.append({
            "reep_id":                  reep_id,
            "key_sofascore":            ss_id,
            "season_id":                int(s.get("seasonId") or season.get("id") or 0),
            "season_name":              str(season.get("name") or ""),
            "season_year":              int(season.get("year") or 0),
            "unique_tournament_id":     int(ut.get("id") or 0),
            "unique_tournament_name":   str(ut.get("name") or ""),
            "team_id":                  int(team.get("id") or 0),
            "team_name":                str(team.get("name") or ""),
            "appearances":              appearances,
            "minutes_played":           minutes,
            "goals":                    goals,
            "assists":                  assists,
            "goals_per_90":             g90,
            "assists_per_90":           a90,
            "rating":                   rating,
            "fetched_at":               fetch_ts,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(all_players: bool = False, refresh: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("=== sofascore_club_pull  (all=%s, refresh=%s) ===", all_players, refresh)

    targets = _load_targets(all_players=all_players, refresh=refresh)
    if not targets:
        logger.info("Nothing to fetch.")
        return

    # Load existing parquet for merge (even if refresh=False, we still concat)
    if CLUB_STATS_PARQUET.exists():
        existing_df = pd.read_parquet(CLUB_STATS_PARQUET)
    else:
        existing_df = pd.DataFrame()

    new_frames: list[pd.DataFrame] = []
    errors = done = 0
    fetch_ts = datetime.now(tz=timezone.utc)

    with SofascoreClient() as client:
        client._challenge_abort = False  # type: ignore[attr-defined]

        for reep_id, ss_id in targets:
            _sleep()

            raw_seasons = _fetch_player_stats(client, ss_id)

            if getattr(client, "_challenge_abort", False):
                logger.warning(
                    "Stopped after %d/%d — Sofascore player stats endpoint requires "
                    "challenge auth.  Existing Bronze Parquet preserved.",
                    done, len(targets),
                )
                break

            done += 1
            if raw_seasons is None:
                errors += 1
                continue

            df = _parse_seasons(reep_id, ss_id, raw_seasons, fetch_ts)
            if not df.empty:
                new_frames.append(df)

            if done % 50 == 0:
                logger.info(
                    "  Progress %d/%d  (new frames=%d, errors=%d)",
                    done, len(targets), len(new_frames), errors,
                )

    if new_frames:
        new_df = pd.concat(new_frames, ignore_index=True)

        if not existing_df.empty and not refresh:
            # Keep existing rows for players we didn't re-fetch; new rows override
            kept = existing_df[~existing_df["reep_id"].isin(new_df["reep_id"])]
            merged = pd.concat([kept, new_df], ignore_index=True)
        else:
            merged = new_df

        CLUB_STATS_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(CLUB_STATS_PARQUET, index=False)
        logger.info(
            "Written: %s  (%d rows, %d unique players)",
            CLUB_STATS_PARQUET,
            len(merged),
            merged["reep_id"].nunique(),
        )
    else:
        logger.info("No new data fetched — Bronze Parquet unchanged.")

    logger.info(
        "=== Done: %d fetched, %d errors, %d new players ===",
        done, errors, len(new_frames),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Sofascore club stats for WC players.")
    parser.add_argument("--all",     dest="all_players", action="store_true",
                        help="Fetch all WC players, not just those without Understat priors.")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch players already in the Bronze Parquet.")
    args = parser.parse_args()
    main(all_players=args.all_players, refresh=args.refresh)
