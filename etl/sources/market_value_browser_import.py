"""
Import mv_results.json (produced by sofascore_browser_fetch.js) into Bronze Parquet.

Expected JSON format:
  { "reep_<id>": { "ss_id": "...", "market_value": <int EUR>, "currency": "EUR" }, ... }

Output: data/bronze/market_values.parquet  (reep_id, market_value_eur, fetched_at)
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

JSON_PATH   = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("C:/Users/couga/Downloads/mv_results.json")
OUT_PARQUET = Path("data/bronze/market_values.parquet")

raw = json.loads(JSON_PATH.read_text(encoding="utf-8"))

rows = []
for reep_id, v in raw.items():
    if "error" in v:
        continue
    mv = v.get("market_value")
    if mv is None:
        continue
    rows.append({
        "reep_id":         reep_id,
        "market_value_eur": int(mv),
        "fetched_at":      datetime.now(tz=timezone.utc),
    })

df = pd.DataFrame(rows)
log.info("Parsed %d valid market values (of %d total entries)", len(df), len(raw))

if df.empty:
    log.error("No valid rows — aborting")
    sys.exit(1)

log.info("MV range: €%.1fM – €%.1fM  |  median €%.1fM",
         df["market_value_eur"].min() / 1e6,
         df["market_value_eur"].max() / 1e6,
         df["market_value_eur"].median() / 1e6)

# Merge with any existing parquet (upsert by reep_id)
if OUT_PARQUET.exists():
    existing = pd.read_parquet(OUT_PARQUET)
    before   = len(existing)
    existing = existing[~existing["reep_id"].isin(df["reep_id"])]
    df       = pd.concat([existing, df], ignore_index=True)
    log.info("Merged: had %d rows, replaced/added %d, now %d", before, before - len(existing), len(df))

OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(OUT_PARQUET, index=False)
log.info("Written: %s", OUT_PARQUET)
