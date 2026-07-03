"""
Import club_stats_p2_results.json (Phase 2 browser fetch) into Bronze Parquet.

Expected JSON (from sofascore_browser_fetch_p2.js):
  {
    "reep_xxx": {
      "ss_id": "...",
      "seasons": [
        {
          "ut_id": 52, "season_id": 77805,
          "ut_name": "Trendyol Süper Lig", "year": "25/26",
          "statistics": { "minutesPlayed": ..., "goals": ..., ... },
          "team": { "name": "..." }
        }
      ]
    }
  }

Output: data/bronze/sofascore/club_stats.parquet
Schema: reep_id, ss_id, unique_tournament_id, unique_tournament_name,
        season_id, season_year, appearances, minutes_played,
        goals_per_90, assists_per_90, rating, has_xg, fetched_at
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

JSON_PATH   = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("C:/Users/couga/Downloads/club_stats_p2_results.json")
OUT_PARQUET = Path("data/bronze/sofascore/club_stats.parquet")

MIN_APPEARANCES = 3
MIN_MINUTES     = 90

raw = json.loads(JSON_PATH.read_bytes().decode("utf-8"))
fetch_ts = datetime.now(tz=timezone.utc)

rows = []
for reep_id, v in raw.items():
    ss_id = v.get("ss_id", "")
    for s in v.get("seasons", []):
        stats = s.get("statistics") or {}
        mins  = stats.get("minutesPlayed") or 0
        apps  = stats.get("appearances")   or 0

        if apps < MIN_APPEARANCES or mins < MIN_MINUTES:
            continue

        # Prefer xG/xA; fall back to goals/assists
        xg  = stats.get("expectedGoals")
        xa  = stats.get("expectedAssists")
        g   = stats.get("goals")   or 0
        a   = stats.get("assists") or 0
        has_xg = xg is not None

        g90 = (xg if has_xg else g) / mins * 90
        a90 = (xa if xa is not None else a) / mins * 90

        rows.append({
            "reep_id":                reep_id,
            "ss_id":                  ss_id,
            "unique_tournament_id":   s.get("ut_id"),
            "unique_tournament_name": s.get("ut_name", ""),
            "season_id":              s.get("season_id"),
            "season_year":            s.get("year", ""),
            "appearances":            int(apps),
            "minutes_played":         float(mins),
            "goals_per_90":           round(g90, 4),
            "assists_per_90":         round(a90, 4),
            "rating":                 stats.get("rating"),
            "has_xg":                 has_xg,
            "fetched_at":             fetch_ts,
        })

df = pd.DataFrame(rows)
log.info("Parsed %d qualifying season rows for %d players", len(df), df["reep_id"].nunique())

if df.empty:
    log.error("No rows passed MIN_APPEARANCES=%d / MIN_MINUTES=%d — aborting", MIN_APPEARANCES, MIN_MINUTES)
    sys.exit(1)

has_xg_pct = df["has_xg"].mean() * 100
log.info("xG available: %.0f%% of rows", has_xg_pct)
log.info("Per-90 ranges — goals: %.2f–%.2f  assists: %.2f–%.2f",
         df["goals_per_90"].min(), df["goals_per_90"].max(),
         df["assists_per_90"].min(), df["assists_per_90"].max())

# Merge with existing parquet (upsert — replace rows for same reep_id)
OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
if OUT_PARQUET.exists():
    existing = pd.read_parquet(OUT_PARQUET)
    before   = existing["reep_id"].nunique()
    existing = existing[~existing["reep_id"].isin(df["reep_id"])]
    df       = pd.concat([existing, df], ignore_index=True)
    log.info("Merged: had %d players, now %d", before, df["reep_id"].nunique())

df.to_parquet(OUT_PARQUET, index=False)
log.info("Written: %s  (%d rows, %d players)", OUT_PARQUET, len(df), df["reep_id"].nunique())
