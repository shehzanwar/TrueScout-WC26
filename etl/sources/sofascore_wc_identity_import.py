"""
etl/sources/sofascore_wc_identity_import.py

Reads player_profiles.json (downloaded from the browser via
data/bronze/sofascore_player_profile_fetch.js) and upserts the
player identities into the DuckDB identity_players table.

This is the browser-safe alternative to sofascore_wc_identity_patch.py,
which was blocked by Sofascore's anti-bot measures when run from Python.

Usage:
    # Default: looks for player_profiles.json in ~/Downloads
    python -m etl.sources.sofascore_wc_identity_import

    # Explicit path:
    python -m etl.sources.sofascore_wc_identity_import --json path/to/player_profiles.json

    # Preview without writing:
    python -m etl.sources.sofascore_wc_identity_import --dry-run

After running, re-run the full nightly pipeline:
    python run_nightly.py
"""
import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import duckdb

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_JSON_PATH = Path.home() / "Downloads" / "player_profiles.json"
REPORT_PATH = Path(__file__).parent.parent.parent / "data" / "static" / "identity_import_report.json"

# Fuzzy name match threshold (0–1).  0.82 catches diacritics / minor transliteration differences.
NAME_MATCH_THRESHOLD = 0.82


# ---------------------------------------------------------------------------
# Helpers (mirrors sofascore_wc_identity_patch.py)
# ---------------------------------------------------------------------------

def _make_reep_id(sofascore_id: str) -> str:
    digest = hashlib.sha256(f"ss:{sofascore_id}".encode()).hexdigest()[:8]
    return f"reep_p{digest}"


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _map_position(sofascore_pos: str | None) -> tuple[str, str]:
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


def _dob_from_timestamp(ts: int | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


def _find_existing_identity(
    conn: duckdb.DuckDBPyConnection,
    ss_name: str,
    nationality: str | None,
    dob: str | None,
) -> str | None:
    """
    Return reep_id of an existing unlinked identity row that matches this player,
    or None.  Mirrors the logic in sofascore_wc_identity_patch._find_existing_identity().
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

            if sim >= 0.99:
                return reep_id

            if dob and dob_row and str(dob_row)[:10] == dob[:10] and sim >= NAME_MATCH_THRESHOLD:
                if sim > best_score:
                    best_score = sim
                    best_reep_id = reep_id

            elif sim >= 0.92 and sim > best_score:
                best_score = sim
                best_reep_id = reep_id

    return best_reep_id


# ---------------------------------------------------------------------------
# Main import
# ---------------------------------------------------------------------------

def run_import(json_path: Path, dry_run: bool = False) -> dict:
    if not json_path.exists():
        raise FileNotFoundError(
            f"player_profiles.json not found at {json_path}\n"
            "Run sofascore_player_profile_fetch.js in your browser first."
        )

    profiles: dict = json.loads(json_path.read_text(encoding="utf-8"))
    logger.info("Loaded %d player profiles from %s", len(profiles), json_path)

    conn = duckdb.connect(str(settings.duckdb_path), read_only=False)
    report: dict = {
        "run_at": datetime.now(tz=timezone.utc).isoformat(),
        "dry_run": dry_run,
        "json_path": str(json_path),
        "inserted": [],
        "updated": [],
        "skipped_error": [],
        "skipped_already_linked": 0,
    }

    try:
        for sofascore_id, entry in profiles.items():
            lineup_name  = entry.get("lineup_name", sofascore_id)
            national_team = entry.get("national_team", "")

            if "error" in entry:
                logger.warning("Skipping %s (%s) — fetch error: %s", lineup_name, sofascore_id, entry["error"])
                report["skipped_error"].append({"sofascore_id": sofascore_id, "lineup_name": lineup_name, "error": entry["error"]})
                continue

            ss_name  = entry.get("name") or lineup_name
            position, position_detail = _map_position(entry.get("position"))
            height_cm = entry.get("height")
            country   = entry.get("country")
            dob_str   = _dob_from_timestamp(entry.get("dateOfBirthTimestamp"))

            # Skip if already linked
            existing_linked = conn.execute(
                "SELECT reep_id FROM identity_players WHERE key_sofascore = ?",
                [sofascore_id],
            ).fetchone()
            if existing_linked:
                logger.info("  %s already linked (reep=%s) — skipping.", ss_name, existing_linked[0])
                report["skipped_already_linked"] += 1
                continue

            # Try to find an existing unlinked row
            existing_reep_id = _find_existing_identity(conn, ss_name, country, dob_str)

            if existing_reep_id:
                logger.info("  Matched existing identity %s → updating key_sofascore for %s.", existing_reep_id, ss_name)
                if not dry_run:
                    conn.execute(
                        "UPDATE identity_players SET key_sofascore = ? WHERE reep_id = ?",
                        [sofascore_id, existing_reep_id],
                    )
                report["updated"].append({
                    "reep_id":       existing_reep_id,
                    "sofascore_id":  sofascore_id,
                    "name":          ss_name,
                    "national_team": national_team,
                    "action":        "updated_existing",
                })
            else:
                reep_id = _make_reep_id(sofascore_id)
                logger.info("  Inserting new identity %s for %s (%s).", reep_id, ss_name, national_team)
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
                    "reep_id":       reep_id,
                    "sofascore_id":  sofascore_id,
                    "name":          ss_name,
                    "national_team": national_team,
                    "position":      position,
                    "dob":           dob_str,
                    "country":       country,
                    "action":        "inserted_new",
                })

    finally:
        conn.close()

    logger.info(
        "Import complete: %d inserted, %d updated, %d skipped errors, %d already linked.",
        len(report["inserted"]),
        len(report["updated"]),
        len(report["skipped_error"]),
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    parser = argparse.ArgumentParser(
        description="Import Sofascore player profiles (from browser fetch) into identity_players."
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"Path to player_profiles.json (default: {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Match and report but do not write to DuckDB.",
    )
    args = parser.parse_args()

    report = run_import(args.json, dry_run=args.dry_run)

    print("\n=== Import Summary ===")
    print(f"  Inserted (new identities):          {len(report['inserted'])}")
    print(f"  Updated  (key_sofascore linked):    {len(report['updated'])}")
    print(f"  Skipped  (fetch errors in JSON):    {len(report['skipped_error'])}")
    print(f"  Skipped  (already linked):          {report['skipped_already_linked']}")

    if report["updated"]:
        print("\n  Updated rows:")
        for r in report["updated"]:
            print(f"    {r['name']:<30} (ss={r['sofascore_id']}) → {r['reep_id']}")

    if report["inserted"]:
        print("\n  Inserted rows:")
        for r in report["inserted"]:
            print(f"    {r['name']:<30} (ss={r['sofascore_id']}) {r['national_team']} {r['position']}")

    if not report["dry_run"] and (report["inserted"] or report["updated"]):
        print("\nNext step: re-run the nightly pipeline to propagate changes:")
        print("  python run_nightly.py")


if __name__ == "__main__":
    main()
