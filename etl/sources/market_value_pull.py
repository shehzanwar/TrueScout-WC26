"""
etl/sources/market_value_pull.py — Fetch Sofascore market values for WC players.

Sofascore's public /api/v1/player/{id} endpoint returns proposedMarketValueRaw
= {"value": <int EUR>, "currency": "EUR"}, sourced from Transfermarkt.

Cloudflare protects the endpoint with a JS challenge that requires a real browser.
This script uses botasaurus (headless Edge/Chrome) to pass the challenge reliably.
Target: www.sofascore.com/api/v1/player (NOT api.sofascore.com — that endpoint
returns application-level 403 regardless of browser since ~2026-07).

NOTE (2026-07-03): Sofascore added server-side challenge auth to the player
endpoint (reason="challenge"). All requests currently return 403. Existing
Bronze Parquet values are preserved; no new values can be fetched until the
endpoint is reopened or an alternative source is wired.

Output
------
Writes (or updates) data/bronze/market_values.parquet
Schema: reep_id (str), market_value_eur (int), fetched_at (datetime)

The parquet is committed to git so it survives DuckDB recreation by load_identity.
bayesian_ratings.py reads from this file directly — NOT from identity_players.

Usage
-----
    py -m etl.sources.market_value_pull            # players without a value
    py -m etl.sources.market_value_pull --refresh  # re-fetch all
"""

import argparse
import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
from botasaurus.browser import browser, Driver

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH   = Path("data/truescout.duckdb")
API_BASE  = "https://www.sofascore.com/api/v1/player"
MV_PARQUET = Path("data/bronze/market_values.parquet")

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
_CHROME_EXE = EDGE_PATH if Path(EDGE_PATH).exists() else None

BATCH_SIZE = 50


def _load_existing() -> pd.DataFrame:
    """Load existing market values from Bronze Parquet (empty DF if not exists)."""
    if MV_PARQUET.exists():
        return pd.read_parquet(MV_PARQUET)
    return pd.DataFrame(columns=["reep_id", "market_value_eur", "fetched_at"])


def _fetch_batch(driver: Driver, rows: list[tuple[str, str]]) -> list[tuple[str, str, int | None]]:
    """Fetch market values for a batch of players in a single browser session."""
    results = []
    for reep_id, ss_id in rows:
        url = f"{API_BASE}/{ss_id}"
        try:
            driver.get(url)
            text = driver.page_text
            data = json.loads(text)
            if "error" in data:
                code   = data["error"].get("code", 0)
                reason = data["error"].get("reason", "")
                if code == 404:
                    results.append((reep_id, ss_id, 0))
                elif code == 403 and reason == "challenge":
                    log.error(
                        "Sofascore player endpoint requires challenge auth (ss=%s). "
                        "Aborting — existing Bronze Parquet values are preserved.",
                        ss_id,
                    )
                    results.append((reep_id, ss_id, "CHALLENGE_ABORT"))
                    return results
                else:
                    log.warning("API error %d for ss=%s", code, ss_id)
                    results.append((reep_id, ss_id, None))
                continue
            player = data.get("player", {})
            raw = player.get("proposedMarketValueRaw")
            mv  = int(raw["value"]) if raw and "value" in raw else 0
            results.append((reep_id, ss_id, mv))
        except Exception as exc:
            log.warning("Failed ss=%s: %s", ss_id, exc)
            results.append((reep_id, ss_id, None))
        time.sleep(random.uniform(0.8, 1.5))
    return results


def main(refresh: bool = False) -> None:
    con = duckdb.connect(str(DB_PATH))

    bronze      = Path("data/bronze")
    lineup_glob = (bronze / "sofascore" / "lineups" / "*.parquet").as_posix()

    existing = _load_existing()
    existing_ids = set(existing["reep_id"].tolist()) if not existing.empty else set()

    wc_filter = f"""
        SELECT DISTINCT CAST(player_id AS VARCHAR)
        FROM read_parquet('{lineup_glob}', union_by_name=true)
        WHERE minutes_played > 0
    """

    if refresh:
        null_filter = "1=1"
    else:
        # Fetch only players not already in the parquet
        if existing_ids:
            ph = ",".join(f"'{r}'" for r in existing_ids)
            null_filter = f"ip.reep_id NOT IN ({ph})"
        else:
            null_filter = "1=1"

    rows = con.execute(f"""
        SELECT ip.reep_id, ip.key_sofascore
        FROM identity_players ip
        WHERE ip.key_sofascore IS NOT NULL
          AND ip.key_sofascore IN ({wc_filter})
          AND {null_filter}
    """).fetchall()
    con.close()

    log.info(
        "Fetching market values for %d players (refresh=%s, existing=%d in parquet)",
        len(rows), refresh, len(existing_ids),
    )
    if not rows:
        log.info("Nothing to fetch — all players already in Bronze Parquet.")
        return

    batches = [rows[i:i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
    new_rows: list[dict] = []
    errors = 0
    done   = 0

    chrome_kwargs = {"chrome_executable_path": _CHROME_EXE} if _CHROME_EXE else {}

    for b_idx, batch in enumerate(batches):
        log.info("Batch %d/%d (%d players) …", b_idx + 1, len(batches), len(batch))

        @browser(
            headless=True,
            block_images_and_css=True,
            output=None,
            create_error_logs=False,
            **chrome_kwargs,
        )
        def run_batch(driver: Driver, data):
            return _fetch_batch(driver, data)

        results = run_batch([batch])[0]

        challenge_abort = False
        for reep_id, ss_id, mv in results:
            if mv == "CHALLENGE_ABORT":
                challenge_abort = True
                break
            if mv is None:
                errors += 1
            else:
                new_rows.append({
                    "reep_id":          reep_id,
                    "market_value_eur": mv,
                    "fetched_at":       datetime.now(),
                })
            done += 1

        log.info("  Progress: %d/%d done (%d new, %d errors)", done, len(rows), len(new_rows), errors)

        if challenge_abort:
            log.warning("Stopped early — Sofascore player endpoint requires challenge auth.")
            break

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        # Merge: new values override existing for the same reep_id
        if not existing.empty:
            merged = (
                pd.concat([existing, new_df], ignore_index=True)
                .sort_values("fetched_at", ascending=False)
                .drop_duplicates(subset=["reep_id"], keep="first")
            )
        else:
            merged = new_df

        MV_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(MV_PARQUET, index=False)
        log.info("Written: %s  (%d players total)", MV_PARQUET, len(merged))
    else:
        log.info("No new values fetched — Bronze Parquet unchanged.")

    log.info("Done — %d new values, %d errors", len(new_rows), errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch all WC players, not just those missing from the parquet")
    args = parser.parse_args()
    main(refresh=args.refresh)
