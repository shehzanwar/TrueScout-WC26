"""
Run this in Google Colab (or any non-blocked environment) to fetch market values.

Setup in Colab:
    !pip install curl_cffi tenacity
    # Upload mv_ids.csv when prompted

Then run this script. It outputs mv_results.csv — download and bring back locally.
"""

import csv, random, time, json
from pathlib import Path

# ── In Colab, upload mv_ids.csv first ─────────────────────────────────────────
try:
    from google.colab import files
    print("Upload mv_ids.csv now...")
    uploaded = files.upload()
    ids_path = next(iter(uploaded))
except Exception:
    ids_path = "mv_ids.csv"   # running locally or file already present

with open(ids_path, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

print(f"Loaded {len(rows)} players to fetch")

# ── Fetch ──────────────────────────────────────────────────────────────────────
from curl_cffi.requests import Session as CurlSession

HEADERS = {
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

session = CurlSession(impersonate="chrome124")

results = []
errors  = 0

for i, row in enumerate(rows):
    reep_id = row["reep_id"]
    ss_id   = row["sofascore_id"]
    mv      = None

    for base in ("https://api.sofascore.com/api/v1/player",
                 "https://api.sofascore.app/api/v1/player"):
        try:
            resp = session.get(f"{base}/{ss_id}", headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("player", {})
                raw  = data.get("proposedMarketValueRaw")
                mv   = int(raw["value"]) if raw and "value" in raw else 0
                break
            elif resp.status_code == 404:
                mv = 0
                break
        except Exception as e:
            print(f"  Error {ss_id}: {e}")
            errors += 1

    results.append({"reep_id": reep_id, "sofascore_id": ss_id, "market_value_eur": mv if mv is not None else ""})
    time.sleep(random.uniform(1.2, 2.0))

    if (i + 1) % 100 == 0:
        filled = sum(1 for r in results if r["market_value_eur"] != "")
        print(f"  {i+1}/{len(rows)} done — {filled} with values, {errors} errors")

# ── Write results ──────────────────────────────────────────────────────────────
out_path = "mv_results.csv"
with open(out_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["reep_id", "sofascore_id", "market_value_eur"])
    writer.writeheader()
    writer.writerows(results)

print(f"\nDone — {len(results)} rows written to {out_path}")
print(f"Errors: {errors}")

# ── Download in Colab ──────────────────────────────────────────────────────────
try:
    from google.colab import files
    files.download(out_path)
except Exception:
    print(f"Download {out_path} manually.")
