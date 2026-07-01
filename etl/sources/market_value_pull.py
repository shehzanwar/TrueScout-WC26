"""
etl/sources/market_value_pull.py — Fetch Sofascore market values for all
identity_players with a key_sofascore.

Sofascore's public /api/v1/player/{id} endpoint returns proposedMarketValueRaw
= {"value": <int EUR>, "currency": "EUR"}.  This is sourced from Transfermarkt.

Output
------
Writes (or updates) the column market_value_eur (BIGINT) in db.identity_players.

Usage
-----
    py -m etl.sources.market_value_pull            # all players without a value
    py -m etl.sources.market_value_pull --refresh  # re-fetch all

The script uses curl_cffi (Chrome TLS impersonation) + 1.5-2.5 s jitter to
stay well under Sofascore's rate limit.  Existing values are preserved unless
--refresh is passed.
"""

import argparse
import logging
import random
import time
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH = Path("data/truescout.duckdb")
BASE_URL = "https://api.sofascore.com/api/v1/player"
FALLBACK_URL = "https://api.sofascore.app/api/v1/player"

HEADERS: dict[str, str] = {
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


def make_session() -> CurlSession:
    return CurlSession(impersonate="chrome136")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def fetch_player(session: CurlSession, sofascore_id: str) -> dict | None:
    for base in (BASE_URL, FALLBACK_URL):
        resp = session.get(f"{base}/{sofascore_id}", headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("player", {})
        if resp.status_code == 404:
            return None  # player not found — skip silently
        if resp.status_code in (403, 429):
            raise Exception(f"HTTP {resp.status_code} from {base}")
        log.debug("Unexpected status %d for player %s from %s", resp.status_code, sofascore_id, base)
    return None


def main(refresh: bool = False) -> None:
    con = duckdb.connect(str(DB_PATH))

    # Ensure the column exists
    existing_cols = {row[0] for row in con.execute("DESCRIBE identity_players").fetchall()}
    if "market_value_eur" not in existing_cols:
        con.execute("ALTER TABLE identity_players ADD COLUMN market_value_eur BIGINT")
        log.info("Added market_value_eur column to identity_players")

    # Only fetch players who appear in WC lineup parquets — the full identity
    # table has 80k+ rows but squad-value prior only needs ~3k WC players.
    bronze       = Path("data/bronze")
    lineup_glob  = (bronze / "sofascore" / "lineups" / "*.parquet").as_posix()

    wc_id_filter = f"""
        SELECT DISTINCT CAST(player_id AS VARCHAR) AS key_sofascore
        FROM read_parquet('{lineup_glob}', union_by_name=true)
        WHERE minutes_played > 0
    """

    # Load players to fetch
    base_filter = "market_value_eur IS NULL" if not refresh else "1=1"
    rows = con.execute(f"""
        SELECT ip.reep_id, ip.key_sofascore
        FROM identity_players ip
        WHERE ip.key_sofascore IS NOT NULL
          AND ip.key_sofascore IN ({wc_id_filter})
          AND {base_filter}
    """).fetchall()

    log.info("Fetching market values for %d players (refresh=%s)", len(rows), refresh)

    session = make_session()
    updated = 0
    errors = 0

    for i, (reep_id, ss_id) in enumerate(rows):
        try:
            player = fetch_player(session, ss_id)
            if player is None:
                # 404 — mark as 0 so we don't retry every run
                con.execute(
                    "UPDATE identity_players SET market_value_eur = 0 WHERE reep_id = ?",
                    [reep_id],
                )
            else:
                raw = player.get("proposedMarketValueRaw")
                mv = int(raw["value"]) if raw and "value" in raw else 0
                con.execute(
                    "UPDATE identity_players SET market_value_eur = ? WHERE reep_id = ?",
                    [mv, reep_id],
                )
                updated += 1
        except Exception as exc:
            log.warning("Failed %s (ss=%s): %s", reep_id, ss_id, exc)
            errors += 1

        # Progress log every 100 players
        if (i + 1) % 100 == 0:
            log.info("  %d/%d done (%d updated, %d errors)", i + 1, len(rows), updated, errors)

        # Rate-limit jitter
        time.sleep(random.uniform(1.5, 2.5))

    log.info("Done — %d updated, %d errors", updated, errors)
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch all players, not just those with NULL market_value_eur",
    )
    args = parser.parse_args()
    main(refresh=args.refresh)
