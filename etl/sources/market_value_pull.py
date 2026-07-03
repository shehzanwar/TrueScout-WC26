"""
etl/sources/market_value_pull.py — Fetch Sofascore market values for WC players.

Sofascore's public /api/v1/player/{id} endpoint returns proposedMarketValueRaw
= {"value": <int EUR>, "currency": "EUR"}, sourced from Transfermarkt.

Cloudflare protects the endpoint with a JS challenge that requires a real browser.
This script uses botasaurus (headless Edge/Chrome) to pass the challenge reliably.

Output
------
Writes (or updates) market_value_eur (BIGINT) in db.identity_players.

Usage
-----
    py -m etl.sources.market_value_pull            # players without a value
    py -m etl.sources.market_value_pull --refresh  # re-fetch all
"""

import argparse
import logging
import random
import time
from pathlib import Path

import duckdb
from botasaurus.browser import browser, Driver

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH   = Path("data/truescout.duckdb")
API_BASE  = "https://api.sofascore.com/api/v1/player"

# Edge ships with Windows; Chrome works too — botasaurus auto-detects.
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
_CHROME_EXE = EDGE_PATH if Path(EDGE_PATH).exists() else None


def _fetch_batch(driver: Driver, rows: list[tuple[str, str]]) -> list[tuple[str, str, int | None]]:
    """Fetch market values for a batch of players in a single browser session.

    Returns list of (reep_id, ss_id, market_value_eur | None).
    None means the request failed and should be counted as an error.
    0 means player was found but has no market value (or 404).
    """
    results = []
    for reep_id, ss_id in rows:
        url = f"{API_BASE}/{ss_id}"
        try:
            driver.get(url)
            text = driver.page_text
            import json
            data = json.loads(text)
            if "error" in data:
                code = data["error"].get("code", 0)
                if code == 404:
                    results.append((reep_id, ss_id, 0))
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

    existing_cols = {r[0] for r in con.execute("DESCRIBE identity_players").fetchall()}
    if "market_value_eur" not in existing_cols:
        con.execute("ALTER TABLE identity_players ADD COLUMN market_value_eur BIGINT")
        log.info("Added market_value_eur column to identity_players")

    bronze      = Path("data/bronze")
    lineup_glob = (bronze / "sofascore" / "lineups" / "*.parquet").as_posix()

    wc_filter = f"""
        SELECT DISTINCT CAST(player_id AS VARCHAR)
        FROM read_parquet('{lineup_glob}', union_by_name=true)
        WHERE minutes_played > 0
    """
    null_filter = "market_value_eur IS NULL" if not refresh else "1=1"

    rows = con.execute(f"""
        SELECT ip.reep_id, ip.key_sofascore
        FROM identity_players ip
        WHERE ip.key_sofascore IS NOT NULL
          AND ip.key_sofascore IN ({wc_filter})
          AND {null_filter}
    """).fetchall()

    log.info("Fetching market values for %d players (refresh=%s)", len(rows), refresh)
    if not rows:
        log.info("Nothing to fetch.")
        con.close()
        return

    # Split into batches so we restart the browser every BATCH_SIZE requests.
    # This avoids memory buildup and session detection over a long run.
    BATCH_SIZE = 50
    batches = [rows[i:i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]

    updated = 0
    errors  = 0
    done    = 0

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

        # Wrap batch in a list so botasaurus calls run_batch once with the
        # full batch (it iterates the outer list, not the inner tuples).
        results = run_batch([batch])[0]

        for reep_id, ss_id, mv in results:
            if mv is None:
                errors += 1
            elif mv == 0:
                con.execute(
                    "UPDATE identity_players SET market_value_eur = 0 WHERE reep_id = ?",
                    [reep_id],
                )
            else:
                con.execute(
                    "UPDATE identity_players SET market_value_eur = ? WHERE reep_id = ?",
                    [mv, reep_id],
                )
                updated += 1
            done += 1

        log.info("  Progress: %d/%d done (%d updated, %d errors)", done, len(rows), updated, errors)

    log.info("Done — %d updated, %d errors", updated, errors)
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch all players, not just those with NULL market_value_eur")
    args = parser.parse_args()
    main(refresh=args.refresh)
