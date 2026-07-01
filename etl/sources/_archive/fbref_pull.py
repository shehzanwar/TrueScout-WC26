"""
etl/sources/fbref_pull.py — FBref club priors via curl_cffi.

Replaces soccerdata's FBref network layer, which is blocked by Cloudflare's JS
challenge.  curl_cffi with chrome TLS impersonation bypasses the challenge using
the same approach as sofascore_pull.py.

Fetches the Big-5 European Leagues combined stats pages directly, parses HTML
tables with pandas.read_html(), and extracts 8-char hex fbref_id from player
href attributes via BeautifulSoup.

Stat types covered (soccerdata was limited to 5; we cover all 9):
  standard, shooting, passing, gca, defense, possession, misc, keeper, keepersadv

This means ALL club_priors schema columns are populated — including the columns
that were NULL in the old soccerdata approach:
  sca_per_90, gca_per_90, key_passes_per_90, pass_completion_pct,
  carries_into_final_third_per_90, pressures_per_90, pressure_success_pct,
  tackles_per_90, tackle_success_pct, interceptions_per_90, psxg_minus_ga_per_90

Player IDs use the FBref 8-char hex (e.g. "fb-dc7f8a28") — stable across club
moves and directly joinable with the reep identity bridge in Phase 2.

Output:
  Bronze:  data/bronze/fbref/raw_{season_label}_{stat_type}.parquet
           data/bronze/fbref/club_priors.parquet
  DuckDB:  players, club_priors tables

Run:
  python -m etl.sources.fbref_pull --all-seasons       # full sweep (~10 min)
  python -m etl.sources.fbref_pull --season 2024-2025  # one season only
  python -m etl.sources.fbref_pull --validate          # fetch one page, no write
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from bs4 import BeautifulSoup

from config import settings
from etl.db.connection import write_conn
from etl.db.init_db import init_schema, refresh_parquet_views

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# curl_cffi impersonation — same resolution pattern as sofascore_pull
# ---------------------------------------------------------------------------

_IMPERSONATE_PREFERRED = "chrome136"
_IMPERSONATE_FALLBACKS = ["chrome124", "chrome120", "chrome116", "chrome110"]


def _resolve_impersonate(preferred: str) -> str:
    try:
        from curl_cffi.requests import BrowserType
        available = {b.value for b in BrowserType}
        if preferred in available:
            return preferred
        for fb in _IMPERSONATE_FALLBACKS:
            if fb in available:
                logger.warning("Impersonate '%s' not available; using '%s'", preferred, fb)
                return fb
        fallback = next(iter(available))
        logger.warning("No preferred target found; using '%s'", fallback)
        return fallback
    except Exception:
        return preferred


IMPERSONATE: str = _resolve_impersonate(_IMPERSONATE_PREFERRED)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BRONZE_FBREF: Path = Path(settings.parquet_bronze_dir) / "fbref"

# (internal_code, fbref_season_string)
SEASONS: list[tuple[str, str]] = [
    ("2425", "2024-2025"),
    ("2526", "2025-2026"),
]
SEASON_LABELS: dict[str, str] = {"2425": "2024-25", "2526": "2025-26"}
SEASON_WINDOW = "2024-25+2025-26"

MIN_CAREER_90S: float = 4.5   # ~405 min across both seasons; sparser players excluded
RATE_LIMIT_S: float = 7.0     # FBref bans IPs that exceed ~10 req/min

# (internal_key, URL slug, HTML table id)
_STAT_CONFIGS: list[tuple[str, str, str]] = [
    ("standard",   "stats",      "stats_standard"),
    ("shooting",   "shooting",   "stats_shooting"),
    ("passing",    "passing",    "stats_passing"),
    ("gca",        "gca",        "stats_gca"),
    ("defense",    "defense",    "stats_defense"),
    ("possession", "possession", "stats_possession"),
    ("misc",       "misc",       "stats_misc"),
    ("keeper",     "keepers",    "stats_keeper"),
    ("keepersadv", "keepersadv", "stats_keepersadv"),
]

# Maps FBref Comp strings to our canonical league IDs
_LEAGUE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"premier.league", re.I), "eng-premier-league"),
    (re.compile(r"la.liga",        re.I), "esp-la-liga"),
    (re.compile(r"bundesliga",     re.I), "ger-bundesliga"),
    (re.compile(r"serie.a",        re.I), "ita-serie-a"),
    (re.compile(r"ligue.1",        re.I), "fra-ligue-1"),
]

# ---------------------------------------------------------------------------
# PyArrow schema — must match init_db.py club_priors table exactly
# ---------------------------------------------------------------------------

CLUB_PRIORS_SCHEMA = pa.schema([
    pa.field("player_id",                        pa.string()),
    pa.field("season_window",                    pa.string()),
    pa.field("club_team_id",                     pa.string()),
    pa.field("league_id",                        pa.string()),
    pa.field("matches_played",                   pa.float64()),
    pa.field("minutes_played",                   pa.float64()),
    pa.field("goals_per_90",                     pa.float64()),
    pa.field("assists_per_90",                   pa.float64()),
    pa.field("xg_per_90",                        pa.float64()),
    pa.field("xa_per_90",                        pa.float64()),
    pa.field("npxg_per_90",                      pa.float64()),
    pa.field("shots_per_90",                     pa.float64()),
    pa.field("shots_on_target_pct",              pa.float64()),
    pa.field("sca_per_90",                       pa.float64()),
    pa.field("gca_per_90",                       pa.float64()),
    pa.field("key_passes_per_90",                pa.float64()),
    pa.field("pass_completion_pct",              pa.float64()),
    pa.field("progressive_passes_per_90",        pa.float64()),
    pa.field("progressive_carries_per_90",       pa.float64()),
    pa.field("carries_into_final_third_per_90",  pa.float64()),
    pa.field("pressures_per_90",                 pa.float64()),
    pa.field("pressure_success_pct",             pa.float64()),
    pa.field("tackles_per_90",                   pa.float64()),
    pa.field("tackle_success_pct",               pa.float64()),
    pa.field("interceptions_per_90",             pa.float64()),
    pa.field("clearances_per_90",                pa.float64()),
    pa.field("aerials_won_pct",                  pa.float64()),
    pa.field("save_pct",                         pa.float64()),
    pa.field("psxg_minus_ga_per_90",             pa.float64()),
    pa.field("clean_sheet_pct",                  pa.float64()),
    pa.field("data_source",                      pa.string()),
    pa.field("fetched_at",                       pa.timestamp("us", tz="UTC")),
])

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

# First-request headers (no Referer, Sec-Fetch-Site=none — matches a fresh browser tab)
_HEADERS_COLD = {
    "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language":           "en-US,en;q=0.9",
    "Accept-Encoding":           "gzip, deflate, br",
    "Connection":                "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":            "document",
    "Sec-Fetch-Mode":            "navigate",
    "Sec-Fetch-Site":            "none",
    "Sec-Fetch-User":            "?1",
    "Cache-Control":             "max-age=0",
    "DNT":                       "1",
}

# Subsequent page headers (navigating within fbref.com)
_HEADERS_NAV = {
    **_HEADERS_COLD,
    "Referer":        "https://fbref.com/",
    "Sec-Fetch-Site": "same-origin",
}

_fetch_count = 0   # module-level: tracks calls so we sleep before every fetch after the first


def _fbref_url(season_str: str, slug: str) -> str:
    return (
        f"https://fbref.com/en/comps/Big5/{season_str}"
        f"/{slug}/players/Big-5-European-Leagues-Stats"
    )


def _warmup(session) -> bool:
    """
    Fetch the FBref homepage to establish a session and pick up any Cloudflare
    cookies (cf_clearance, __cf_bm) before hitting stats pages.
    Only called when no browser cookies have been injected.
    """
    logger.info("Warming up via fbref.com homepage...")
    try:
        resp = session.get("https://fbref.com/", headers=_HEADERS_COLD, timeout=30)
        logger.info("  Homepage HTTP %d (%d bytes)", resp.status_code, len(resp.text))
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("  Warm-up failed: %s", exc)
        return False


def _fetch_page(session, url: str) -> str | None:
    """Fetch one FBref stats page with rate limiting between calls."""
    global _fetch_count
    if _fetch_count > 0:
        logger.info("Sleeping %.0fs to respect FBref rate limits...", RATE_LIMIT_S)
        time.sleep(RATE_LIMIT_S)
    _fetch_count += 1

    logger.info("GET %s", url)
    try:
        resp = session.get(url, headers=_HEADERS_NAV, timeout=45)
    except Exception as exc:
        logger.error("Request failed for %s: %s", url, exc)
        return None

    if resp.status_code != 200:
        logger.warning("HTTP %d for %s", resp.status_code, url)
        return None

    html = resp.text
    if "<table" not in html:
        logger.warning("Response contains no <table> (len=%d) — possible CAPTCHA page", len(html))
        return None

    logger.info("  %d bytes received", len(html))
    return html

# ---------------------------------------------------------------------------
# FBref ID extraction
# ---------------------------------------------------------------------------

_FBREF_ID_RE = re.compile(r"/en/players/([a-f0-9]{8})/")


def extract_fbref_ids(html: str, table_id: str) -> list[str | None]:
    """
    Extract 8-char hex FBref player IDs from the href attributes in the player
    column of the specified HTML table.  Skips FBref's repeated sub-header rows
    (which have class='thead' on <tr>).

    Returns a list aligned row-for-row with parse_table() output.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id=table_id)
    if table is None:
        logger.warning("Table id='%s' not found in HTML", table_id)
        return []

    tbody = table.find("tbody")
    if tbody is None:
        return []

    ids: list[str | None] = []
    for tr in tbody.find_all("tr"):
        if "thead" in tr.get("class", []):
            continue
        td = tr.find("td", {"data-stat": "player"})
        if td is None:
            continue
        a = td.find("a", href=True)
        if a:
            m = _FBREF_ID_RE.search(a["href"])
            ids.append(m.group(1) if m else None)
        else:
            ids.append(None)

    return ids

# ---------------------------------------------------------------------------
# HTML table parsing
# ---------------------------------------------------------------------------

_UNNAMED_RE = re.compile(r"^unnamed", re.IGNORECASE)
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def _flatten_col(col: tuple | str) -> str:
    """Sanitise a MultiIndex column tuple into a flat snake_case name."""
    if not isinstance(col, tuple):
        return str(col).lower().strip()
    parts = [str(p).strip() for p in col if str(p).strip() and not _UNNAMED_RE.match(str(p).strip())]
    joined = "_".join(parts) if parts else str(col[-1]).strip()
    result = (
        joined.lower()
        .replace(" ", "_")
        .replace("/", "_per_")
        .replace("%", "_pct")
        .replace("+/-", "_plus_minus")
        .replace("+", "_plus_")
        .replace("-", "_")
        .replace(".", "_")
    )
    return _MULTI_UNDERSCORE_RE.sub("_", result).strip("_")


def parse_table(html: str, table_id: str) -> pd.DataFrame | None:
    """
    Parse an FBref Big5 stats HTML table using pandas.read_html with 2-level
    headers, then flatten the MultiIndex columns to snake_case.

    Filters FBref's repeated sub-header rows (where 'player' == 'Player' etc.)
    and empty trailing rows.  Returns None if the table cannot be parsed.
    """
    try:
        dfs = pd.read_html(html, attrs={"id": table_id}, header=[0, 1], flavor="lxml")
    except Exception as exc:
        logger.warning("read_html failed for '%s': %s", table_id, exc)
        return None

    if not dfs:
        return None

    df = dfs[0].copy()
    df.columns = [_flatten_col(c) for c in df.columns]

    # FBref injects repeated header rows every ~50 data rows inside <tbody>
    if "player" in df.columns:
        is_repeat = df["player"].astype(str).str.strip().isin(
            {"Player", "Rk", "Nation", "Pos", "Squad", "Comp", "Age", "", "nan"}
        )
        df = df[~is_repeat]

    if "player" in df.columns:
        df = df[df["player"].notna() & (df["player"].astype(str).str.strip() != "")]

    return df.reset_index(drop=True)

# ---------------------------------------------------------------------------
# Column access helpers
# ---------------------------------------------------------------------------

def _get_col(df: pd.DataFrame, *candidates: str) -> pd.Series:
    """Return the first matching candidate as a numeric Series, or all-NaN."""
    for col in candidates:
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce")
    logger.debug("None of %s found in columns (sample: %s)", candidates, list(df.columns[:15]))
    return pd.Series(float("nan"), index=df.index, dtype=float)


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den.replace(0, float("nan"))).astype(float)


def _slugify(text: str) -> str:
    return (
        str(text).lower()
        .replace(" ", "-").replace("_", "-")
        .replace("'", "").replace(".", "").replace("/", "-")
        .replace("(", "").replace(")", "")
    )


def _parse_league(comp_str: str) -> str:
    s = str(comp_str)
    for pattern, league_id in _LEAGUE_PATTERNS:
        if pattern.search(s):
            return league_id
    return _slugify(s)

# ---------------------------------------------------------------------------
# Per-stat-type extractors
# Each returns a dict of { schema_column | internal_column → pd.Series }
# Internal columns (prefixed _) are totals used for per-90 computation later.
# ---------------------------------------------------------------------------

def _extract_standard(df: pd.DataFrame) -> dict[str, pd.Series]:
    nineties = _get_col(df, "playing_time_90s", "90s")
    prgc = _get_col(df, "progression_prgc", "prgc")
    prgp = _get_col(df, "progression_prgp", "prgp")
    return {
        "matches_played":            _get_col(df, "playing_time_mp", "mp"),
        "minutes_played":            _get_col(df, "playing_time_min", "min"),
        "_90s":                      nineties,
        "goals_per_90":              _get_col(df, "per_90_minutes_gls"),
        "assists_per_90":            _get_col(df, "per_90_minutes_ast"),
        "xg_per_90":                 _get_col(df, "per_90_minutes_xg"),
        "xa_per_90":                 _get_col(df, "per_90_minutes_xag"),
        "npxg_per_90":               _get_col(df, "per_90_minutes_npxg"),
        "progressive_carries_per_90": _safe_div(prgc, nineties),
        "progressive_passes_per_90": _safe_div(prgp, nineties),
        "_pos":   df["pos"].astype(str)   if "pos"   in df.columns else pd.Series("", index=df.index),
        "_squad": df["squad"].astype(str) if "squad" in df.columns else pd.Series("", index=df.index),
        "_comp":  df["comp"].astype(str)  if "comp"  in df.columns else pd.Series("", index=df.index),
        "_name":  df["player"].astype(str) if "player" in df.columns else pd.Series("", index=df.index),
    }


def _extract_shooting(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "shots_per_90":        _get_col(df, "standard_sh_per_90", "sh_per_90"),
        "shots_on_target_pct": _get_col(df, "standard_sot_pct", "sot_pct"),
    }


def _extract_passing(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "pass_completion_pct": _get_col(df, "total_cmp_pct", "cmp_pct"),
        "_kp_total":           _get_col(df, "kp"),
    }


def _extract_gca(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "sca_per_90": _get_col(df, "sca_sca90", "sca90"),
        "gca_per_90": _get_col(df, "gca_gca90", "gca90"),
    }


def _extract_defense(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "_tackles_total":    _get_col(df, "tackles_tkl"),
        "tackle_success_pct": _get_col(df, "challenges_tkl_pct", "tkl_pct"),
        "_pressures_total":  _get_col(df, "pressures_press", "press"),
        "pressure_success_pct": _get_col(df, "pressures_pct", "pressures_succ_pct"),
        "_int_total":        _get_col(df, "int"),
        "_clr_total":        _get_col(df, "clr"),
    }


def _extract_possession(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "_carries_f3_total": _get_col(df, "carries_1_per_3", "1_per_3"),
    }


def _extract_misc(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "aerials_won_pct": _get_col(df, "aerial_duels_won_pct", "won_pct"),
    }


def _extract_keeper(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "save_pct":       _get_col(df, "performance_save_pct", "save_pct"),
        "clean_sheet_pct": _get_col(df, "performance_cs_pct", "cs_pct"),
    }


def _extract_keepersadv(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        # FBref keepersadv: "Expected Goals" group, "/90" column = PSxG+/- per 90
        "psxg_minus_ga_per_90": _get_col(df, "expected_goals_per_90", "per_90"),
    }


_EXTRACTORS: dict[str, Callable[[pd.DataFrame], dict[str, pd.Series]]] = {
    "standard":   _extract_standard,
    "shooting":   _extract_shooting,
    "passing":    _extract_passing,
    "gca":        _extract_gca,
    "defense":    _extract_defense,
    "possession": _extract_possession,
    "misc":       _extract_misc,
    "keeper":     _extract_keeper,
    "keepersadv": _extract_keepersadv,
}

# ---------------------------------------------------------------------------
# Per-season fetch
# ---------------------------------------------------------------------------

def _align_ids(ids: list[str | None], df: pd.DataFrame) -> tuple[list[str | None], pd.DataFrame]:
    """Trim ids list and DataFrame to the same length when they diverge."""
    n = min(len(ids), len(df))
    if len(ids) != len(df):
        logger.warning("ID count (%d) != row count (%d) — trimming to %d", len(ids), len(df), n)
    return ids[:n], df.iloc[:n].copy()


def fetch_season(session, season_code: str, season_str: str) -> pd.DataFrame:
    """
    Fetch all 9 stat types for one season.  Merges by fbref_id into a single
    per-player DataFrame with all columns needed for club_priors.

    Returns an empty DataFrame if the standard stats page cannot be fetched.
    """
    season_label = SEASON_LABELS.get(season_code, season_code)
    logger.info("=== Season %s (%s) ===", season_label, season_str)
    BRONZE_FBREF.mkdir(parents=True, exist_ok=True)

    # ── Standard first — provides _90s + identity columns ───────────────────
    std_url = _fbref_url(season_str, "stats")
    std_html = _fetch_page(session, std_url)
    if std_html is None:
        logger.error("Cannot fetch standard page for %s — aborting season.", season_str)
        return pd.DataFrame()

    std_ids = extract_fbref_ids(std_html, "stats_standard")
    std_df = parse_table(std_html, "stats_standard")
    if std_df is None or not std_ids:
        logger.error("Failed to parse standard table for %s.", season_str)
        return pd.DataFrame()

    std_ids, std_df = _align_ids(std_ids, std_df)
    std_df["fbref_id"] = std_ids
    std_df = std_df[std_df["fbref_id"].notna()].reset_index(drop=True)

    # Validate extraction
    n_valid = std_df["fbref_id"].notna().sum()
    logger.info(
        "Standard: %d rows | fbref_id populated %d / %d (%.0f%%)",
        len(std_df), n_valid, len(std_df),
        100 * n_valid / len(std_df) if len(std_df) else 0,
    )

    # Build base season DataFrame from standard
    std_extracted = _extract_standard(std_df)
    season_df = pd.DataFrame(std_extracted, index=std_df.index)
    season_df["fbref_id"]      = std_df["fbref_id"].values
    season_df["_season_code"]  = season_code

    # Write raw standard Parquet
    _write_raw(std_df, season_label, "standard")

    # ── Remaining stat types ─────────────────────────────────────────────────
    for key, slug, table_id in _STAT_CONFIGS[1:]:
        url = _fbref_url(season_str, slug)
        html = _fetch_page(session, url)
        if html is None:
            logger.warning("Skipping stat type '%s' for %s (fetch failed).", key, season_str)
            continue

        ids = extract_fbref_ids(html, table_id)
        df = parse_table(html, table_id)
        if df is None or not ids:
            logger.warning("Could not parse '%s' table for %s.", table_id, season_str)
            continue

        ids, df = _align_ids(ids, df)
        df["fbref_id"] = ids
        df = df[df["fbref_id"].notna()].reset_index(drop=True)

        extracted = _EXTRACTORS[key](df)
        extra_df = pd.DataFrame(extracted, index=df.index)
        extra_df["fbref_id"] = df["fbref_id"].values

        # Left-join onto season_df on fbref_id
        extra_df = extra_df.drop(columns=[c for c in extra_df.columns if c == "_90s"], errors="ignore")
        season_df = season_df.merge(extra_df, on="fbref_id", how="left", suffixes=("", f"_{key}"))
        logger.info("  Merged %-12s: %d rows", key, len(extra_df))

        _write_raw(df, season_label, key)

    # ── Compute per-90 rates from totals (requires _90s from standard) ───────
    nineties = season_df["_90s"]
    _compute_per_90 = [
        ("_kp_total",        "key_passes_per_90"),
        ("_tackles_total",   "tackles_per_90"),
        ("_pressures_total", "pressures_per_90"),
        ("_int_total",       "interceptions_per_90"),
        ("_clr_total",       "clearances_per_90"),
        ("_carries_f3_total","carries_into_final_third_per_90"),
    ]
    for total_col, rate_col in _compute_per_90:
        if total_col in season_df.columns:
            season_df[rate_col] = _safe_div(season_df[total_col], nineties)

    # ── Null GK-only stats for outfield players ──────────────────────────────
    if "_pos" in season_df.columns:
        is_gk = season_df["_pos"].astype(str).str.upper().str.startswith("GK")
        for gk_col in ("save_pct", "clean_sheet_pct", "psxg_minus_ga_per_90"):
            if gk_col in season_df.columns:
                season_df.loc[~is_gk, gk_col] = float("nan")

    logger.info("Season %s complete: %d players", season_label, len(season_df))
    return season_df


def _write_raw(df: pd.DataFrame, season_label: str, stat_type: str) -> None:
    """Write a raw per-stat-type DataFrame to Bronze Parquet for debugging."""
    fname = f"raw_{season_label.replace('-', '_')}_{stat_type}.parquet"
    out_path = BRONZE_FBREF / fname
    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)

# ---------------------------------------------------------------------------
# 2-season aggregation
# ---------------------------------------------------------------------------

_RATE_COLS = [
    "goals_per_90", "assists_per_90", "xg_per_90", "xa_per_90", "npxg_per_90",
    "shots_per_90", "progressive_carries_per_90", "progressive_passes_per_90",
    "sca_per_90", "gca_per_90", "key_passes_per_90", "pressures_per_90",
    "tackles_per_90", "interceptions_per_90", "clearances_per_90",
    "carries_into_final_third_per_90", "psxg_minus_ga_per_90",
]
_PCT_COLS = [
    "shots_on_target_pct", "pass_completion_pct", "pressure_success_pct",
    "tackle_success_pct", "aerials_won_pct", "save_pct", "clean_sheet_pct",
]


def _weighted_mean(grp: pd.DataFrame, col: str, weight_col: str = "_90s") -> float:
    if col not in grp.columns:
        return float("nan")
    vals = pd.to_numeric(grp[col], errors="coerce")
    weights = grp[weight_col].fillna(0).values
    valid = (weights > 0) & vals.notna()
    if not valid.any():
        return float("nan")
    return float((vals[valid] * weights[valid]).sum() / weights[valid].sum())


def aggregate_seasons(season_dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Combine per-season DataFrames into a single 2-season aggregate per player.

    Volume stats (matches_played, minutes_played): summed.
    Per-90 and percentage stats: 90s-weighted mean so high-minute seasons dominate.
    Players below MIN_CAREER_90S total are excluded.
    """
    if not season_dfs:
        logger.error("aggregate_seasons: no season data provided.")
        return pd.DataFrame()

    all_seasons = pd.concat(season_dfs, ignore_index=True)

    now = datetime.now(tz=timezone.utc)
    rows: list[dict[str, Any]] = []

    for fbref_id, grp in all_seasons.groupby("fbref_id", observed=True):
        total_90s = float(grp["_90s"].fillna(0).sum())
        if total_90s < MIN_CAREER_90S:
            continue

        # Use the most recent season for identity columns (last row after groupby)
        last = grp.sort_values("_season_code").iloc[-1]

        squad_raw = str(last.get("_squad", ""))
        comp_raw  = str(last.get("_comp", ""))

        row: dict[str, Any] = {
            "player_id":    f"fb-{fbref_id}",
            "_fbref_id":    fbref_id,
            "_player_name": str(last.get("_name", "")),
            "_pos":         str(last.get("_pos", "")),
            "season_window": SEASON_WINDOW,
            "club_team_id": f"club-{_slugify(squad_raw)}" if squad_raw else None,
            "league_id":    _parse_league(comp_raw),
            # Volume: sum
            "matches_played": float(grp["matches_played"].fillna(0).sum()),
            "minutes_played": float(grp["minutes_played"].fillna(0).sum()),
            "data_source": "fbref",
            "fetched_at":  now,
        }

        for col in _RATE_COLS + _PCT_COLS:
            row[col] = _weighted_mean(grp, col)

        rows.append(row)

    if not rows:
        logger.warning("aggregate_seasons: no players survived the %.1f 90s filter.", MIN_CAREER_90S)
        return pd.DataFrame()

    priors = pd.DataFrame(rows)
    logger.info(
        "Aggregated: %d players | %d leagues | 90s range %.0f-%.0f",
        len(priors),
        priors["league_id"].nunique(),
        priors["minutes_played"].min() / 90 if "minutes_played" in priors else 0,
        priors["minutes_played"].max() / 90 if "minutes_played" in priors else 0,
    )
    return priors

# ---------------------------------------------------------------------------
# Bronze Parquet write
# ---------------------------------------------------------------------------

def write_club_priors_parquet(priors: pd.DataFrame) -> Path:
    """Write the schema-aligned club_priors DataFrame to Bronze Parquet."""
    out_df = priors.drop(columns=["_fbref_id", "_player_name", "_pos"], errors="ignore")
    schema_cols = [f.name for f in CLUB_PRIORS_SCHEMA]

    missing = set(schema_cols) - set(out_df.columns)
    if missing:
        logger.warning("Filling %d missing schema columns with NaN: %s", len(missing), sorted(missing))
        for col in missing:
            out_df[col] = None

    out_df = out_df.reindex(columns=schema_cols)
    out_path = BRONZE_FBREF / "club_priors.parquet"
    table = pa.Table.from_pandas(out_df, schema=CLUB_PRIORS_SCHEMA, preserve_index=False)
    pq.write_table(table, out_path, compression="snappy")
    logger.info("club_priors Bronze -> %s (%d rows)", out_path.name, len(out_df))
    return out_path

# ---------------------------------------------------------------------------
# DuckDB upserts
# ---------------------------------------------------------------------------

def _upsert(conn: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame, label: str = "") -> None:
    if df.empty:
        logger.warning("Upsert skipped for '%s': empty DataFrame.", table)
        return
    view = f"_stage_{table}"
    conn.register(view, df)
    try:
        conn.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {view}")  # noqa: S608
        logger.info("Upserted %d rows -> %s%s", len(df), table, f" [{label}]" if label else "")
    finally:
        conn.unregister(view)


def upsert_players(conn: duckdb.DuckDBPyConnection, priors: pd.DataFrame) -> None:
    """Upsert player rows with fbref_id populated (8-char hex, not slugified name)."""
    if priors.empty or "_player_name" not in priors.columns:
        return
    players = (
        priors[["player_id", "_player_name", "club_team_id", "_pos", "_fbref_id"]]
        .drop_duplicates("player_id")
        .assign(
            id=lambda df: df["player_id"],
            name=lambda df: df["_player_name"],
            team_id=lambda df: df["club_team_id"],
            position=lambda df: df["_pos"],
            nationality=None,
            date_of_birth=None,
            age_at_wc2026=None,
            sofascore_id=None,
            fbref_id=lambda df: df["_fbref_id"],
            espn_id=None,
            updated_at=datetime.now(tz=timezone.utc),
        )
        [["id", "name", "team_id", "position", "nationality",
          "date_of_birth", "age_at_wc2026", "sofascore_id", "fbref_id",
          "espn_id", "updated_at"]]
    )
    _upsert(conn, "players", players, "from FBref")


def upsert_club_priors(conn: duckdb.DuckDBPyConnection, priors: pd.DataFrame) -> None:
    """Write the aggregated club_priors to the DuckDB table."""
    if priors.empty:
        return
    schema_cols = [f.name for f in CLUB_PRIORS_SCHEMA]
    out = priors.reindex(columns=schema_cols)
    _upsert(conn, "club_priors", out, "2-season FBref aggregate")

# ---------------------------------------------------------------------------
# Validation (--validate mode)
# ---------------------------------------------------------------------------

def validate(session) -> None:
    """
    Fetch one page (standard stats, 2024-2025), prove the pipeline works:
      1. HTTP 200 received
      2. Table parsed into DataFrame
      3. fbref_id column correctly populated
    Prints a 5-row sample.  Does NOT write Parquet or DuckDB.
    Cookie injection is handled by main() before this is called.
    """
    season_code, season_str = SEASONS[0]
    url = _fbref_url(season_str, "stats")
    logger.info("=== validate mode: fetching %s ===", url)

    html = _fetch_page(session, url)
    if html is None:
        logger.error("FAIL: Could not fetch page.")
        return

    ids = extract_fbref_ids(html, "stats_standard")
    df = parse_table(html, "stats_standard")

    if df is None:
        logger.error("FAIL: Table parse returned None.")
        return

    ids, df = _align_ids(ids, df)
    df["fbref_id"] = ids

    n_total = len(df)
    n_valid = df["fbref_id"].notna().sum()
    pct = 100 * n_valid / n_total if n_total else 0

    print(f"\n=== fbref_pull validate ===")
    print(f"URL:          {url}")
    print(f"HTTP:         200 OK")
    print(f"Rows parsed:  {n_total}")
    print(f"fbref_id:     {n_valid} / {n_total} populated ({pct:.1f}%)")

    extracted = _extract_standard(df)
    sample_df = pd.DataFrame(extracted, index=df.index)
    sample_df["fbref_id"] = df["fbref_id"].values

    display_cols = ["fbref_id", "_name", "_squad", "_comp", "_90s", "goals_per_90"]
    display_cols = [c for c in display_cols if c in sample_df.columns]
    print(f"\nFirst 5 rows:\n{sample_df[display_cols].head().to_string(index=False)}\n")

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def main(
    season_codes: list[str] | None = None,
    validate_only: bool = False,
    extra_cookies: dict[str, str] | None = None,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("=== TrueScout FBref pull | impersonate=%s ===", IMPERSONATE)

    from curl_cffi.requests import Session

    with Session(impersonate=IMPERSONATE) as session:
        if extra_cookies:
            # Inject browser cookies directly — skip warmup (cf_clearance overrides challenge)
            for name, value in extra_cookies.items():
                session.cookies.set(name, value, domain=".fbref.com")
            logger.info("Injected browser cookies: %s", list(extra_cookies))
        else:
            # No cookies: attempt homepage warmup to pick up any Cloudflare session cookies
            _warmup(session)

        if validate_only:
            validate(session)
            return

        target_seasons = [
            (code, s) for code, s in SEASONS
            if season_codes is None or code in season_codes or s in season_codes
        ]
        if not target_seasons:
            logger.error("No matching seasons found for: %s", season_codes)
            return

        season_dfs: list[pd.DataFrame] = []
        for season_code, season_str in target_seasons:
            df = fetch_season(session, season_code, season_str)
            if not df.empty:
                season_dfs.append(df)

    if not season_dfs:
        logger.error("No data collected — nothing to write.")
        return

    priors = aggregate_seasons(season_dfs)
    if priors.empty:
        logger.error("Aggregation produced no rows.")
        return

    write_club_priors_parquet(priors)

    with write_conn() as conn:
        init_schema(conn)
        upsert_players(conn, priors)
        upsert_club_priors(conn, priors)
        refresh_parquet_views(conn)

    logger.info(
        "=== FBref pull complete: %d players | %d leagues ===",
        len(priors), priors["league_id"].nunique(),
    )

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="TrueScout FBref club priors ingestion (curl_cffi edition)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--all-seasons", action="store_true",
        help="Pull all configured seasons (2024-2025 + 2025-2026)",
    )
    mode.add_argument(
        "--season", metavar="SEASON",
        help="Pull a single season (e.g. 2024-2025 or 2425)",
    )
    mode.add_argument(
        "--validate", action="store_true",
        help="Fetch one page, print first 5 rows + fbref_id population rate; no write",
    )
    parser.add_argument(
        "--cf-clearance", metavar="VALUE",
        help=(
            "Inject your browser's cf_clearance cookie to bypass Cloudflare. "
            "Get it from Chrome DevTools -> Application -> Cookies -> fbref.com -> cf_clearance. "
            "Copy only the Value column (not the name)."
        ),
    )
    args = parser.parse_args()

    extra_cookies: dict[str, str] | None = None
    if args.cf_clearance:
        extra_cookies = {"cf_clearance": args.cf_clearance.strip()}
        logger.info("cf_clearance cookie provided (%d chars)", len(args.cf_clearance))

    if args.validate:
        main(validate_only=True, extra_cookies=extra_cookies)
    elif args.all_seasons:
        main(season_codes=None, extra_cookies=extra_cookies)
    else:
        main(season_codes=[args.season], extra_cookies=extra_cookies)


if __name__ == "__main__":
    _cli()
