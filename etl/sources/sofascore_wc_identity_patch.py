"""
etl/sources/sofascore_wc_identity_patch.py

Finds WC lineup players with no identity_players link (key_sofascore missing),
fetches their Sofascore profile, and upserts them into identity_players so that
downstream steps (build_features → bayesian_ratings → monte_carlo_sim) can join
their WC match ratings into the team-strength calculation.

Why this matters
----------------
_build_team_strengths() joins WC lineups to identity_players via key_sofascore.
Any player whose Sofascore ID isn't in identity_players is silently excluded from
their national team's strength average. For teams like Morocco whose key players
(Bounou, Rahimi, El Kaabi) are absent, this understates team quality significantly.

What it does
------------
1. Queries all WC lineup players missing a key_sofascore match.
2. For each, fetches GET /api/v1/player/{id} from Sofascore.
3. Fuzzy-matches by name against existing identity_players to avoid duplicates.
4. If a strong name match is found: updates key_sofascore on the existing row.
5. If no match: inserts a new row with a deterministic reep_id derived from the
   Sofascore ID so the record is stable across re-runs.
6. Writes a JSON report to data/static/identity_patch_report.json.

Run after any new WC round is ingested:
    python -m etl.sources.sofascore_wc_identity_patch

Then re-run the full nightly pipeline:
    python run_nightly.py
"""
import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import duckdb
from curl_cffi.requests import Session as CurlSession
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REQUEST_SLEEP_MIN = 1.2
REQUEST_SLEEP_MAX = 2.2
TIMEOUT_S         = 20
IMPERSONATE       = "chrome136"

# How similar names must be (0–1) to be considered the same player.
# SequenceMatcher ratio: 1.0 = identical, 0.85 catches minor diacritics/abbreviation differences.
NAME_MATCH_THRESHOLD = 0.82

REPORT_PATH = Path(__file__).parent.parent.parent / "data" / "static" / "identity_patch_report.json"

# ---------------------------------------------------------------------------
# reep_id generation
# We use a deterministic hash of "ss:{sofascore_id}" so re-runs are idempotent
# and the generated IDs don't collide with the REEP register's own hash space
# (which hashes player names + DOBs).
# ---------------------------------------------------------------------------

def _make_reep_id(sofascore_id: str) -> str:
    digest = hashlib.sha256(f"ss:{sofascore_id}".encode()).hexdigest()[:8]
    return f"reep_p{digest}"


# ---------------------------------------------------------------------------
# Sofascore player profile fetch
# ---------------------------------------------------------------------------

class _HTTPError(Exception):
    def __init__(self, status_code: int, url: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {url}")


@retry(
    retry=retry_if_exception_type(_HTTPError),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _fetch_player(session: CurlSession, sofascore_id: str) -> dict | None:
    """Fetch /api/v1/player/{id} from Sofascore. Returns the player dict or None."""
    domains = [
        settings.sofascore_base_url,
        settings.sofascore_fallback_url,
    ]
    path = f"/api/v1/player/{sofascore_id}"
    headers = {
        "Referer": "https://www.sofascore.com/",
        "Origin": "https://www.sofascore.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    for base in domains:
        url = f"{base}{path}"
        try:
            resp = session.get(url, headers=headers, timeout=TIMEOUT_S)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("player")
            if resp.status_code == 404:
                logger.warning("404 for player %s — trying next domain", sofascore_id)
                continue
            if resp.status_code == 429:
                logger.warning("429 rate limit — pausing 30s")
                time.sleep(30.0)
                raise _HTTPError(429, url)
            if resp.status_code in (403, 503):
                logger.warning("%d at %s — trying fallback", resp.status_code, base)
                continue
            raise _HTTPError(resp.status_code, url)
        except _HTTPError:
            raise
        except Exception as exc:
            logger.error("Request failed for %s: %s", url, exc)
            continue
    return None


def _jitter_sleep():
    time.sleep(random.uniform(REQUEST_SLEEP_MIN, REQUEST_SLEEP_MAX))


# ---------------------------------------------------------------------------
# Name fuzzy-matching
# ---------------------------------------------------------------------------

def _name_similarity(a: str, b: str) -> float:
    """Case-insensitive SequenceMatcher ratio between two player names."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _find_existing_identity(
    conn: duckdb.DuckDBPyConnection,
    ss_name: str,
    nationality: str | None,
    dob: str | None,
) -> str | None:
    """
    Return the reep_id of an existing identity_players row that is likely this
    player, or None if no strong match exists.

    Strategy:
    1. Exact name match (case-insensitive) → accept immediately.
    2. DOB match + name similarity ≥ NAME_MATCH_THRESHOLD → accept.
    3. Name similarity ≥ 0.92 (high confidence, no DOB needed) → accept.
    """
    candidates = conn.execute("""
        SELECT reep_id, name, full_name, date_of_birth, nationality
        FROM identity_players
        WHERE key_sofascore IS NULL
    """).fetchall()

    best_reep_id = None
    best_score = 0.0

    for reep_id, name, full_name, dob_row, nat_row in candidates:
        for candidate_name in [name, full_name]:
            if not candidate_name:
                continue
            sim = _name_similarity(ss_name, candidate_name)

            # Exact match shortcut
            if sim >= 0.99:
                return reep_id

            # DOB + name
            if dob and dob_row and str(dob_row)[:10] == dob[:10] and sim >= NAME_MATCH_THRESHOLD:
                if sim > best_score:
                    best_score = sim
                    best_reep_id = reep_id

            # High-confidence name-only
            elif sim >= 0.92 and sim > best_score:
                best_score = sim
                best_reep_id = reep_id

    return best_reep_id


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def _find_unmatched_players(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
    """
    Return (sofascore_id, player_name, national_team) for every WC lineup player
    who has no key_sofascore entry in identity_players.
    """
    bronze      = Path(settings.parquet_bronze_dir)
    lineup_glob = (bronze / "sofascore" / "lineups" / "*.parquet").as_posix()
    events_glob = (bronze / "sofascore" / "events"  / "*.parquet").as_posix()

    rows = conn.execute(f"""
        WITH wc_players AS (
            SELECT DISTINCT
                CAST(l.player_id AS VARCHAR) AS sofascore_id,
                l.player_name,
                CASE l.team_side
                    WHEN 'home' THEN e.home_team_name
                    WHEN 'away' THEN e.away_team_name
                END AS national_team
            FROM read_parquet('{lineup_glob}', union_by_name=true) l
            JOIN read_parquet('{events_glob}', union_by_name=true) e
              ON CAST(l.event_id AS BIGINT) = CAST(e.event_id AS BIGINT)
        )
        SELECT wc.sofascore_id, wc.player_name, wc.national_team
        FROM wc_players wc
        LEFT JOIN identity_players ip ON wc.sofascore_id = ip.key_sofascore
        WHERE ip.reep_id IS NULL
        ORDER BY wc.national_team, wc.player_name
    """).fetchall()

    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


def _map_position(sofascore_pos: str | None) -> tuple[str, str]:
    """Map Sofascore position code to (position, position_detail)."""
    mapping = {
        "G":  ("GK",  "Goalkeeper"),
        "D":  ("DEF", "Defender"),
        "M":  ("MID", "Midfielder"),
        "F":  ("FWD", "Forward"),
        "GK": ("GK",  "Goalkeeper"),
    }
    if sofascore_pos:
        pos, det = mapping.get(sofascore_pos.upper(), ("MID", sofascore_pos))
        return pos, det
    return "MID", "Unknown"


def run_patch(dry_run: bool = False) -> dict:
    conn = duckdb.connect(str(settings.duckdb_path), read_only=False)
    report: dict = {
        "run_at": datetime.now(tz=timezone.utc).isoformat(),
        "dry_run": dry_run,
        "inserted": [],
        "updated": [],
        "fetch_failed": [],
        "skipped_already_linked": 0,
    }

    try:
        unmatched = _find_unmatched_players(conn)
        logger.info("Found %d unmatched WC players to process.", len(unmatched))

        with CurlSession(impersonate=IMPERSONATE) as session:
            for sofascore_id, lineup_name, national_team in unmatched:
                logger.info("Processing: %s (ss=%s, team=%s)", lineup_name, sofascore_id, national_team)

                profile = _fetch_player(session, sofascore_id)
                _jitter_sleep()

                if profile is None:
                    logger.warning("Could not fetch profile for ss=%s (%s)", sofascore_id, lineup_name)
                    report["fetch_failed"].append({
                        "sofascore_id": sofascore_id,
                        "lineup_name": lineup_name,
                        "national_team": national_team,
                    })
                    continue

                ss_name   = profile.get("name") or lineup_name
                short     = profile.get("shortName") or ss_name
                pos_code  = profile.get("position")
                position, position_detail = _map_position(pos_code)
                height_cm = profile.get("height")
                country   = (profile.get("country") or {}).get("name")

                # Date of birth from Unix timestamp
                dob_ts  = profile.get("dateOfBirthTimestamp")
                dob_str = None
                if dob_ts:
                    try:
                        dob_str = datetime.fromtimestamp(dob_ts, tz=timezone.utc).strftime("%Y-%m-%d")
                    except Exception:
                        pass

                # Check: does this player already have a key_sofascore in identity_players?
                existing_linked = conn.execute(
                    "SELECT reep_id FROM identity_players WHERE key_sofascore = ?",
                    [sofascore_id],
                ).fetchone()
                if existing_linked:
                    logger.info("  Already linked (reep=%s) — skipping.", existing_linked[0])
                    report["skipped_already_linked"] += 1
                    continue

                # Try to find an existing unlinked identity row
                existing_reep_id = _find_existing_identity(conn, ss_name, country, dob_str)

                if existing_reep_id:
                    # Update existing row with the Sofascore key
                    logger.info("  Matched existing identity %s → updating key_sofascore.", existing_reep_id)
                    if not dry_run:
                        conn.execute(
                            "UPDATE identity_players SET key_sofascore = ? WHERE reep_id = ?",
                            [sofascore_id, existing_reep_id],
                        )
                    report["updated"].append({
                        "reep_id": existing_reep_id,
                        "sofascore_id": sofascore_id,
                        "name": ss_name,
                        "national_team": national_team,
                        "action": "updated_existing",
                    })
                else:
                    # No existing row — create a new one
                    reep_id = _make_reep_id(sofascore_id)
                    logger.info("  No match found — inserting new identity %s for %s.", reep_id, ss_name)
                    if not dry_run:
                        already = conn.execute(
                            "SELECT 1 FROM identity_players WHERE reep_id = ?", [reep_id]
                        ).fetchone()
                        if not already:
                            conn.execute("""
                                INSERT INTO identity_players (
                                    reep_id, name, full_name, date_of_birth,
                                    nationality, position, position_detail,
                                    height_cm, key_sofascore
                                ) VALUES (?, ?, ?, TRY_CAST(? AS DATE), ?, ?, ?, ?, ?)
                            """, [
                            reep_id, ss_name, ss_name, dob_str,
                            country, position, position_detail,
                            float(height_cm) if height_cm else None,
                            sofascore_id,
                        ])
                    report["inserted"].append({
                        "reep_id": reep_id,
                        "sofascore_id": sofascore_id,
                        "name": ss_name,
                        "national_team": national_team,
                        "position": position,
                        "dob": dob_str,
                        "country": country,
                        "action": "inserted_new",
                    })

    finally:
        conn.close()

    logger.info(
        "Patch complete: %d inserted, %d updated, %d fetch_failed, %d already_linked.",
        len(report["inserted"]),
        len(report["updated"]),
        len(report["fetch_failed"]),
        report["skipped_already_linked"],
    )

    if not dry_run:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Report written to %s", REPORT_PATH)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    parser = argparse.ArgumentParser(description="Patch missing WC player identities from Sofascore.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and match but do not write to DuckDB.")
    args = parser.parse_args()

    report = run_patch(dry_run=args.dry_run)

    print("\n=== Summary ===")
    print(f"  Inserted (new identities): {len(report['inserted'])}")
    print(f"  Updated  (key_sofascore added to existing): {len(report['updated'])}")
    print(f"  Fetch failed: {len(report['fetch_failed'])}")
    print(f"  Already linked (skipped): {report['skipped_already_linked']}")

    if report["inserted"] or report["updated"]:
        print("\nNext step: re-run the nightly pipeline to propagate changes:")
        print("  python run_nightly.py")


if __name__ == "__main__":
    main()
