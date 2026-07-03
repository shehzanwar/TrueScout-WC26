"""
Import fbref_intl_form_results.json (browser console fetch from fbref.com)
into data/bronze/fbref/intl_form.parquet.

Expected JSON format (from fbref_browser_fetch.js):
  {
    "UEFA Euro 2024": [
      { "fbref_id": "abc12345", "player_name": "...", "minutes": 450,
        "goals": 2, "assists": 1, "xg": 1.8, "xa": 0.9, "npxg": 1.5 },
      ...
    ],
    ...
  }

Schema written (same as fbref_intl_pull.py output):
  fbref_id, player_name, competition, minutes, goals, assists, xg, xa, npxg, fetched_at

Run:
  py -m etl.sources.fbref_intl_import                                 # default path
  py -m etl.sources.fbref_intl_import C:/path/to/fbref_intl_form_results.json
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

JSON_PATH   = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("C:/Users/couga/Downloads/fbref_intl_form_results.json")
OUT_PARQUET = Path("data/bronze/fbref/intl_form.parquet")

raw = json.loads(JSON_PATH.read_bytes().decode("utf-8"))
fetch_ts = datetime.now(tz=timezone.utc)

rows = []
for competition, players in raw.items():
    if not players:
        log.warning("No data for %s — skipping", competition)
        continue
    for p in players:
        fbref_id = p.get("fbref_id")
        mins     = p.get("minutes") or 0
        if not fbref_id or mins <= 0:
            continue
        rows.append({
            "fbref_id":    fbref_id,
            "player_name": p.get("player_name", ""),
            "competition": competition,
            "minutes":     float(mins),
            "goals":       p.get("goals"),
            "assists":     p.get("assists"),
            "xg":          p.get("xg"),
            "xa":          p.get("xa"),
            "npxg":        p.get("npxg"),
            "fetched_at":  fetch_ts,
        })

df = pd.DataFrame(rows)
log.info("Parsed %d rows across %d competitions", len(df), df["competition"].nunique() if not df.empty else 0)

if df.empty:
    log.error("No valid rows — aborting")
    sys.exit(1)

has_xg = df["xg"].notna().mean() * 100
log.info("xG coverage: %.0f%%  |  unique FBref IDs: %d", has_xg, df["fbref_id"].nunique())

# Merge with existing (upsert by competition — replace any previously fetched competition)
OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
if OUT_PARQUET.exists():
    existing = pd.read_parquet(OUT_PARQUET)
    new_comps = set(df["competition"].unique())
    kept = existing[~existing["competition"].isin(new_comps)]
    df   = pd.concat([kept, df], ignore_index=True)
    log.info("Merged: %d competitions total, %d unique FBref IDs",
             df["competition"].nunique(), df["fbref_id"].nunique())

df.to_parquet(OUT_PARQUET, index=False)
log.info("Written: %s  (%d rows)", OUT_PARQUET, len(df))

# Summary per competition
for comp, grp in df.groupby("competition"):
    log.info("  %-40s  %4d players  %.0f–%.0f min",
             comp, len(grp), grp["minutes"].min(), grp["minutes"].max())
