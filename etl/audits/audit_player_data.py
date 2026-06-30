"""
etl/audits/audit_player_data.py — Data-quality diagnostic for PR 5a.

Surfaces four classes of known bugs so they can be fixed via:
  • data/static/position_overrides.json  (position contradictions)
  • etl/utils/team_aliases.py            (nationality variant mismatches)

Run:
    python -m etl.audits.audit_player_data

Writes a report to stdout and optionally to logs/audit_player_data.txt.
Exit 0 always — this is a diagnostic, not a gate.

Checks
------
1. Position contradictions: players whose position_micro (Reep position_detail)
   is inconsistent with position_macro (bucket logic).
2. Nationality mismatches: players whose Reep `nationality` differs from their
   modal Sofascore team (national_team derived from lineups).
3. Completed matches with NULL market_advance_prob in the current matchups.json.
4. Stars with suspicious position assignments (saves/xg thresholds).
"""
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from config import settings
from etl.db.connection import get_write_conn
from etl.utils.team_aliases import normalize

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger("audit_player_data")


# ---------------------------------------------------------------------------
# Known mapping: position_micro strings → expected position_macro bucket
# ---------------------------------------------------------------------------

_MICRO_TO_MACRO: dict[str, str] = {
    # GK
    "goalkeeper": "GK",
    # DEF
    "centre-back": "DEF", "centre back": "DEF", "center back": "DEF",
    "right back": "DEF", "left back": "DEF", "full-back": "DEF", "full back": "DEF",
    "wing-back": "DEF", "wing back": "DEF", "sweeper": "DEF", "stopper": "DEF",
    # MID
    "midfielder": "MID", "central midfielder": "MID", "defensive midfielder": "MID",
    "attacking midfielder": "MID", "wide midfielder": "MID",
    "winger": "MID", "left winger": "MID", "right winger": "MID",
    "inside forward": "MID", "wing half": "MID",
    # FWD
    "forward": "FWD", "centre-forward": "FWD", "centre forward": "FWD",
    "striker": "FWD", "second striker": "FWD", "false 9": "FWD",
}

# Stars to spot-check by position (reep_id → expected bucket)
# Populate this with known IDs from the live players.json after a pipeline run.
_STAR_CHECKS: dict[str, str] = {
    # Format: "reep_p<hash>": "FWD"
    # These are populated from the audit — see check_stars() below
}


# ---------------------------------------------------------------------------
# Check 1 — position contradictions
# ---------------------------------------------------------------------------

def check_position_contradictions(conn) -> list[dict]:
    """Find players where position_micro contradicts position_macro."""
    try:
        rows = conn.execute("""
            SELECT pr.reep_id, ip.name, pr.position_macro, pr.position_micro,
                   ip.position_detail
            FROM player_ratings pr
            LEFT JOIN identity_players ip ON pr.reep_id = ip.reep_id
            WHERE pr.position_micro IS NOT NULL
        """).fetchall()
    except Exception as exc:
        logger.error("position contradiction query failed: %s", exc)
        return []

    issues = []
    for reep_id, name, macro, micro, detail in rows:
        if not micro:
            continue
        expected = _MICRO_TO_MACRO.get(str(micro).strip().lower())
        if expected and expected != macro:
            issues.append({
                "reep_id":       reep_id,
                "name":          name,
                "position_macro": macro,
                "position_micro": micro,
                "position_detail": detail,
                "expected_macro": expected,
            })
    return issues


# ---------------------------------------------------------------------------
# Check 2 — nationality mismatches vs Sofascore-derived national_team
# ---------------------------------------------------------------------------

def check_nationality_mismatches(conn) -> list[dict]:
    """
    Find players whose Reep `nationality` doesn't match their modal Sofascore team.
    Returns cases with meaningful discrepancy (after alias normalisation).
    """
    lineup_dir = Path(settings.parquet_bronze_dir) / "sofascore" / "lineups"
    events_dir = Path(settings.parquet_bronze_dir) / "sofascore" / "events"

    if not (lineup_dir.is_dir() and list(lineup_dir.glob("*.parquet"))):
        logger.warning("Sofascore lineups absent — skipping nationality check")
        return []

    lineup_glob = (lineup_dir / "*.parquet").as_posix()
    events_glob = (events_dir / "*.parquet").as_posix()

    try:
        bridge_rows = conn.execute("""
            SELECT CAST(key_sofascore AS VARCHAR), reep_id
            FROM identity_players
            WHERE key_sofascore IS NOT NULL
        """).fetchall()
    except Exception:
        return []
    sc_to_reep = {str(sc): str(r) for sc, r in bridge_rows}

    import duckdb as _duckdb
    tmp = _duckdb.connect()
    try:
        lineups = tmp.execute(f"""
            SELECT CAST(player_id AS VARCHAR) AS sofascore_id,
                   CAST(event_id AS BIGINT) AS event_id, team_side
            FROM read_parquet('{lineup_glob}', union_by_name=true)
        """).df()
        events = tmp.execute(f"""
            SELECT CAST(event_id AS BIGINT) AS event_id,
                   home_team_name, away_team_name
            FROM read_parquet('{events_glob}', union_by_name=true)
        """).df()
    except Exception as exc:
        logger.warning("Sofascore query failed: %s", exc)
        return []
    finally:
        tmp.close()

    if lineups.empty or events.empty:
        return []

    merged = lineups.merge(events, on="event_id", how="left")
    merged["team_name"] = np.where(
        merged["team_side"] == "home",
        merged["home_team_name"], merged["away_team_name"]
    )
    merged["reep_id"] = merged["sofascore_id"].map(sc_to_reep)
    merged = merged.dropna(subset=["reep_id", "team_name"])

    # Reep nationality lookup
    try:
        nat_rows = conn.execute("""
            SELECT reep_id, name, nationality FROM identity_players
        """).fetchall()
    except Exception:
        return []
    reep_nat = {str(r): (str(n) if n else None, str(nat) if nat else None)
                for r, n, nat in nat_rows}

    issues = []
    for rid, grp in merged.groupby("reep_id"):
        modal = grp["team_name"].mode()
        if modal.empty:
            continue
        sc_team   = normalize(str(modal.iloc[0])) or str(modal.iloc[0])
        name, nat = reep_nat.get(str(rid), (None, None))
        reep_norm = normalize(nat) if nat else None

        if nat and reep_norm != sc_team:
            issues.append({
                "reep_id":       str(rid),
                "name":          name,
                "reep_nationality": nat,
                "sofascore_team": sc_team,
                "alias_suggestion": f'"{nat}": "{sc_team}"' if nat != reep_norm else None,
            })
    return issues


# ---------------------------------------------------------------------------
# Check 3 — completed matches missing market odds
# ---------------------------------------------------------------------------

def check_missing_market_odds() -> list[dict]:
    """Read matchups.json and find completed matches with null market_advance_prob."""
    matchups_path = ROOT / "frontend" / "public" / "data" / "matchups.json"
    if not matchups_path.exists():
        logger.warning("matchups.json not found — skipping market odds check")
        return []

    try:
        data = json.loads(matchups_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("matchups.json read failed: %s", exc)
        return []

    missing = []
    for rnd, rnd_data in data.items():
        for m in rnd_data.get("matches", []):
            if m.get("is_completed") and m["home"].get("market_advance_prob") is None:
                missing.append({
                    "round":      rnd,
                    "event_id":   m["event_id"],
                    "home":       m["home"]["name"],
                    "away":       m["away"]["name"],
                    "match_date": m["match_date"],
                })
    return missing


# ---------------------------------------------------------------------------
# Check 4 — stars with suspicious positions
# ---------------------------------------------------------------------------

def check_suspicious_star_positions(conn) -> list[dict]:
    """
    Flag players with wc_saves_per_90 > 0.5 outside GK bucket, or
    wc_xg_per_90 > 0.4 in DEF/GK bucket.  These are strong indicators of
    position misclassification in high-profile players.
    """
    features_path = Path(settings.parquet_silver_dir) / "player_stats" / "features.parquet"
    if not features_path.exists():
        logger.warning("features.parquet absent — skipping suspicious positions check")
        return []

    try:
        df = pd.read_parquet(features_path)
    except Exception as exc:
        logger.error("features.parquet read failed: %s", exc)
        return []

    issues = []

    if "wc_saves_per_90" in df.columns and "position_bucket" in df.columns:
        mask = (df["wc_saves_per_90"] > 0.5) & (df["position_bucket"] != "GK")
        for _, row in df[mask].iterrows():
            issues.append({
                "check":    "saves_as_non_GK",
                "reep_id":  row.get("reep_id"),
                "bucket":   row.get("position_bucket"),
                "saves_90": round(float(row["wc_saves_per_90"]), 2),
            })

    if "wc_xg_per_90" in df.columns and "position_bucket" in df.columns:
        mask = (df["wc_xg_per_90"] > 0.4) & (df["position_bucket"].isin(["DEF", "GK"]))
        for _, row in df[mask].iterrows():
            issues.append({
                "check":  "high_xg_in_DEF_GK",
                "reep_id": row.get("reep_id"),
                "bucket":  row.get("position_bucket"),
                "xg_90":   round(float(row["wc_xg_per_90"]), 3),
            })

    return issues


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    conn = get_write_conn()

    sep = "─" * 60

    # ── Check 1 ─────────────────────────────────────────────────────────────
    print(f"\n{sep}")
    print("CHECK 1 — Position contradictions (position_micro vs position_macro)")
    print(sep)
    pos_issues = check_position_contradictions(conn)
    if pos_issues:
        for p in pos_issues:
            print(
                f"  {p['reep_id']}  {p['name'] or '?':30s}  "
                f"macro={p['position_macro']}  micro={p['position_micro']}  "
                f"→ expected {p['expected_macro']}"
            )
        print(f"\n  → Add to data/static/position_overrides.json:")
        for p in pos_issues:
            print(f'    "{p["reep_id"]}": {{"position_detail": "{p["position_detail"] or ""}"}}')
    else:
        print("  ✓ No contradictions found.")

    # ── Check 2 ─────────────────────────────────────────────────────────────
    print(f"\n{sep}")
    print("CHECK 2 — Nationality mismatches (Reep nationality vs Sofascore modal team)")
    print(sep)
    nat_issues = check_nationality_mismatches(conn)
    if nat_issues:
        for p in nat_issues:
            print(
                f"  {p['reep_id']}  {p['name'] or '?':30s}  "
                f"reep={p['reep_nationality']}  sc={p['sofascore_team']}"
            )
        alias_suggestions = [p["alias_suggestion"] for p in nat_issues if p["alias_suggestion"]]
        if alias_suggestions:
            print(f"\n  → Possible additions to etl/utils/team_aliases.py:")
            for s in alias_suggestions:
                print(f"    {s},")
    else:
        print("  ✓ No mismatches found.")

    # ── Check 3 ─────────────────────────────────────────────────────────────
    print(f"\n{sep}")
    print("CHECK 3 — Completed matches missing market odds")
    print(sep)
    odds_issues = check_missing_market_odds()
    if odds_issues:
        for m in odds_issues:
            print(f"  [{m['round']}] {m['home']} vs {m['away']} ({m['match_date'][:10]}) — event_id {m['event_id']}")
        print(f"\n  Total: {len(odds_issues)} match(es) missing bookies odds.")
    else:
        print("  ✓ All completed matches have market odds.")

    # ── Check 4 ─────────────────────────────────────────────────────────────
    print(f"\n{sep}")
    print("CHECK 4 — Stars with suspicious position assignments")
    print(sep)
    star_issues = check_suspicious_star_positions(conn)
    if star_issues:
        for p in star_issues:
            detail = f"saves/90={p.get('saves_90')}" if "saves_90" in p else f"xg/90={p.get('xg_90')}"
            print(f"  [{p['check']}]  {p['reep_id']}  bucket={p['bucket']}  {detail}")
    else:
        print("  ✓ No suspicious position assignments detected.")

    print(f"\n{sep}")
    total_issues = len(pos_issues) + len(nat_issues) + len(odds_issues) + len(star_issues)
    print(f"Audit complete — {total_issues} issue(s) found across 4 checks.")
    print(sep)


if __name__ == "__main__":
    main()
