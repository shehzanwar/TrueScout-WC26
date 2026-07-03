"""
etl/sources/fbref_intl_pull.py — FBref international tournament / qualifying form.

Pulls player standard stats from completed international competitions and
WC 2026 qualifying rounds.  Extracts FBref 8-char hex player IDs (joinable
with identity_players.key_fbref) and per-90 attacking rates.

Competitions pulled (all completed as of WC 2026 start):
  • UEFA Euro 2024
  • Copa América 2024
  • Africa Cup of Nations 2023 (played Jan-Feb 2024)
  • UEFA Nations League A 2024-25
  • AFC Asian Cup 2023
  • CONCACAF Gold Cup 2023
  • WC 2026 Qualification UEFA  (2025-26 cycle)
  • WC 2026 Qualification CONMEBOL
  • WC 2026 Qualification CAF
  • WC 2026 Qualification AFC
  • WC 2026 Qualification CONCACAF

Output
------
data/bronze/fbref/intl_form.parquet
Schema:
  fbref_id            str   — 8-char hex from FBref href (joins key_fbref)
  player_name         str
  competition         str   — human-readable label
  comp_id             int   — FBref competition ID
  season              str   — "2024", "2024-2025", etc.
  minutes             float
  goals               float
  assists             float
  xg                  float
  xa                  float
  npxg                float
  fetched_at          datetime[UTC]

Run
---
  py -m etl.sources.fbref_intl_pull              # all competitions
  py -m etl.sources.fbref_intl_pull --refresh    # re-fetch even if parquet exists
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BRONZE_FBREF = Path("data/bronze/fbref")
INTL_PARQUET = BRONZE_FBREF / "intl_form.parquet"

RATE_LIMIT_S = 8.0   # FBref rate limit: ~7-8s between requests

# ---------------------------------------------------------------------------
# Competition catalogue
# (label, comp_id, season_str, url_suffix)
# URL: https://fbref.com/en/comps/{comp_id}/{season}/stats/{url_suffix}
# ---------------------------------------------------------------------------
COMPETITIONS: list[tuple[str, int, str, str]] = [
    # Major tournaments
    (
        "UEFA Euro 2024", 676, "2024",
        "2024-UEFA-European-Championship-Stats",
    ),
    (
        "Copa America 2024", 685, "2024",
        "2024-Copa-America-Stats",
    ),
    (
        "Africa Cup of Nations 2023", 656, "2023",
        "2023-Africa-Cup-of-Nations-Stats",
    ),
    (
        "UEFA Nations League A 2024-25", 701, "2024-2025",
        "2024-2025-UEFA-Nations-League-A-Stats",
    ),
    (
        "AFC Asian Cup 2023", 659, "2023",
        "2023-AFC-Asian-Cup-Stats",
    ),
    (
        "CONCACAF Gold Cup 2023", 687, "2023",
        "2023-CONCACAF-Gold-Cup-Stats",
    ),
    # WC 2026 qualifying (completed rounds)
    (
        "WC 2026 Qual UEFA", 684, "2025-2026",
        "2025-2026-WC-Qualification-UEFA-Stats",
    ),
    (
        "WC 2026 Qual CONMEBOL", 681, "2026",
        "2026-WC-Qualification-CONMEBOL-Stats",
    ),
    (
        "WC 2026 Qual CAF", 682, "2026",
        "2026-WC-Qualification-CAF-Stats",
    ),
    (
        "WC 2026 Qual AFC", 683, "2026",
        "2026-WC-Qualification-AFC-Stats",
    ),
    (
        "WC 2026 Qual CONCACAF", 685, "2025-2026",
        "2025-2026-WC-Qualification-CONCACAF-Stats",
    ),
]

FBREF_BASE = "https://fbref.com"

# ---------------------------------------------------------------------------
# curl_cffi session setup (same pattern as fbref_pull / sofascore_pull)
# ---------------------------------------------------------------------------

def _make_session():
    try:
        import curl_cffi.requests as req
        sess = req.Session(impersonate="chrome136")
    except Exception:
        try:
            import curl_cffi.requests as req
            sess = req.Session(impersonate="chrome124")
        except Exception:
            import requests as req
            sess = req.Session()
            logger.warning("curl_cffi unavailable — falling back to requests (may be blocked)")
    return sess


_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "DNT":             "1",
    "Sec-CH-UA":       '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest":  "document",
    "Sec-Fetch-Mode":  "navigate",
    "Sec-Fetch-Site":  "none",
    "Sec-Fetch-User":  "?1",
    "Cache-Control":   "max-age=0",
    "Upgrade-Insecure-Requests": "1",
}

# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

_FBREF_ID_RE = re.compile(r"/players/([0-9a-f]{8})/")


def _extract_player_id(href: str | None) -> str | None:
    if not href:
        return None
    m = _FBREF_ID_RE.search(href)
    return m.group(1) if m else None


def _parse_stats_page(html: str, label: str) -> pd.DataFrame:
    """
    Parse an FBref combined stats page and return a tidy DataFrame.

    FBref stats tables have a two-row header; pandas.read_html handles the
    MultiIndex automatically.  Player hrefs live in <td data-append-csv="...">
    or in the <a> tag inside the player <td>.

    Returns columns: fbref_id, player_name, minutes, goals, assists, xg, xa, npxg
    (all numeric columns are NaN where FBref shows "-" or blank).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Find the standard stats table
    table = soup.find("table", id="stats_standard")
    if table is None:
        # Some pages use a slightly different id
        table = soup.find("table", {"id": re.compile(r"stats_standard")})
    if table is None:
        logger.warning("[%s] Could not find stats_standard table", label)
        return pd.DataFrame()

    # Extract FBref player IDs from <td> data-append-csv attribute or <a> hrefs
    # Build a mapping: row_index → fbref_id
    fbref_ids: list[str | None] = []
    player_names: list[str] = []

    tbody = table.find("tbody")
    if tbody is None:
        return pd.DataFrame()

    for tr in tbody.find_all("tr"):
        if "thead" in tr.get("class", []) or "spacer" in tr.get("class", []):
            continue
        td = tr.find("td", {"data-stat": "player"})
        if td is None:
            fbref_ids.append(None)
            player_names.append("")
            continue
        a_tag = td.find("a")
        if a_tag:
            fbref_ids.append(_extract_player_id(a_tag.get("href", "")))
            player_names.append(a_tag.get_text(strip=True))
        else:
            fbref_ids.append(None)
            player_names.append(td.get_text(strip=True))

    # Use pandas to parse the numeric table (flattens MultiIndex headers)
    try:
        dfs = pd.read_html(str(table), header=[0, 1])
        if not dfs:
            return pd.DataFrame()
        df = dfs[0]
    except Exception as exc:
        logger.warning("[%s] pd.read_html failed: %s", label, exc)
        return pd.DataFrame()

    # Flatten MultiIndex columns: ("Playing Time", "Min") → "playing_time_min"
    df.columns = [
        "_".join(str(p).strip().lower().replace(" ", "_") for p in col if str(p).strip() and str(p) != "Unnamed: 0_level_0")
        if isinstance(col, tuple) else str(col).strip().lower()
        for col in df.columns
    ]

    # Drop separator rows (FBref inserts rows where player name is "Player")
    if "player" in df.columns:
        df = df[df["player"].astype(str).str.strip().ne("Player")].copy()
    elif "player_player" in df.columns:
        df = df[df["player_player"].astype(str).str.strip().ne("Player")].copy()

    df = df.reset_index(drop=True)

    # Trim fbref_ids to match the parsed row count (some rows may be header dupes)
    n = len(df)
    ids_trimmed   = fbref_ids[:n]   if len(fbref_ids)   >= n else fbref_ids   + [None] * (n - len(fbref_ids))
    names_trimmed = player_names[:n] if len(player_names) >= n else player_names + [""]  * (n - len(player_names))

    df["fbref_id"]    = ids_trimmed
    df["player_name"] = names_trimmed

    # Extract the stats we care about — column names vary slightly by FBref version
    def _get(*candidates: str) -> pd.Series:
        for c in candidates:
            if c in df.columns:
                return pd.to_numeric(df[c], errors="coerce")
        return pd.Series(dtype=float, index=df.index)

    out = pd.DataFrame({
        "fbref_id":    df["fbref_id"],
        "player_name": df["player_name"],
        "minutes":     _get("playing_time_min", "min", "playing_time_min"),
        "goals":       _get("performance_gls", "gls", "performance_gls"),
        "assists":     _get("performance_ast", "ast"),
        "xg":          _get("expected_xg", "xg"),
        "xa":          _get("expected_xag", "xa", "expected_xa"),
        "npxg":        _get("expected_npxg", "npxg"),
    })

    out = out[out["fbref_id"].notna()].copy()
    out = out[out["minutes"].fillna(0) > 0].copy()

    logger.info("[%s] Parsed %d player rows", label, len(out))
    return out


# ---------------------------------------------------------------------------
# Main fetch loop
# ---------------------------------------------------------------------------

def fetch_intl_form(refresh: bool = False) -> pd.DataFrame:
    """
    Fetch all competitions in COMPETITIONS, soft-failing per entry.
    Returns combined DataFrame with competition metadata columns.
    """
    BRONZE_FBREF.mkdir(parents=True, exist_ok=True)

    existing: pd.DataFrame = pd.DataFrame()
    if INTL_PARQUET.exists() and not refresh:
        existing = pd.read_parquet(INTL_PARQUET)
        done_comps = set(zip(existing["comp_id"].astype(str), existing["season"]))
        logger.info(
            "Existing intl_form.parquet: %d rows across %d competitions",
            len(existing), existing["competition"].nunique() if not existing.empty else 0,
        )
    else:
        done_comps: set = set()

    fetch_ts = datetime.now(tz=timezone.utc)
    frames: list[pd.DataFrame] = []

    with _make_session() as sess:
        for label, comp_id, season, url_suffix in COMPETITIONS:
            key = (str(comp_id), season)
            if key in done_comps:
                logger.info("[%s] Already in parquet — skipping", label)
                continue

            url = f"{FBREF_BASE}/en/comps/{comp_id}/{season}/stats/{url_suffix}"
            logger.info("[%s] GET %s", label, url)

            try:
                resp = sess.get(url, headers=_HEADERS, timeout=30)
            except Exception as exc:
                logger.warning("[%s] Request failed: %s — skipping", label, exc)
                time.sleep(RATE_LIMIT_S)
                continue

            if resp.status_code == 404:
                logger.warning("[%s] 404 — competition/season not on FBref yet", label)
                time.sleep(RATE_LIMIT_S)
                continue

            if resp.status_code != 200:
                logger.warning("[%s] HTTP %d — skipping", label, resp.status_code)
                time.sleep(RATE_LIMIT_S)
                continue

            df = _parse_stats_page(resp.text, label)
            if df.empty:
                logger.warning("[%s] No data parsed — skipping", label)
                time.sleep(RATE_LIMIT_S)
                continue

            df["competition"] = label
            df["comp_id"]     = comp_id
            df["season"]      = season
            df["fetched_at"]  = fetch_ts
            frames.append(df)

            logger.info(
                "[%s] OK — %d players, %.0f–%.0f min",
                label, len(df),
                df["minutes"].min(), df["minutes"].max(),
            )
            time.sleep(RATE_LIMIT_S)

    if not frames and existing.empty:
        logger.warning("No data fetched and no existing parquet.")
        return pd.DataFrame()

    if frames:
        new_df = pd.concat(frames, ignore_index=True)
        if not existing.empty:
            # Drop old rows for competitions we just re-fetched, append new
            refetched = {(str(r["comp_id"]), r["season"]) for _, r in new_df.iterrows()}
            kept = existing[
                ~existing.apply(lambda r: (str(r["comp_id"]), r["season"]) in refetched, axis=1)
            ]
            combined = pd.concat([kept, new_df], ignore_index=True)
        else:
            combined = new_df

        combined.to_parquet(INTL_PARQUET, index=False)
        logger.info(
            "Written: %s  (%d rows, %d players, %d competitions)",
            INTL_PARQUET,
            len(combined),
            combined["fbref_id"].nunique(),
            combined["competition"].nunique(),
        )
        return combined

    return existing


def main(refresh: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("=== fbref_intl_pull  (%d competitions) ===", len(COMPETITIONS))
    df = fetch_intl_form(refresh=refresh)
    if df.empty:
        logger.warning("No data written.")
        return
    logger.info(
        "=== Done: %d rows | %d unique FBref IDs | %d competitions ===",
        len(df), df["fbref_id"].nunique(), df["competition"].nunique(),
    )
    # Summary per competition
    for comp, grp in df.groupby("competition"):
        logger.info("  %-40s  %4d players  %.0f–%.0f min",
                    comp, len(grp), grp["minutes"].min(), grp["minutes"].max())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch all competitions even if already in parquet")
    args = parser.parse_args()
    main(refresh=args.refresh)
