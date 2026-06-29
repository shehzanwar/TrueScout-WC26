"""
etl/sources/soccerdata_pull.py — Phase 1 ingestion.

Pulls two data sets via the `soccerdata` library:

  1. Club Elo ratings (all clubs worldwide, as of WC-start date)
     → derives elo_strength_coef per league
     → Bronze:  data/bronze/club_elo/league_elo_{date}.parquet
     → DuckDB:  leagues table

  2. FBref player season stats (Big-5 European leagues, 2 seasons)
     → Bronze:  data/bronze/fbref/player_stats_{season}_{stat_type}.parquet
                data/bronze/fbref/club_priors.parquet   (aggregated, schema-aligned)
     → DuckDB:  teams, players, club_priors tables

Coverage note
─────────────
soccerdata v1.9 FBref supports only 5 stat types:
    standard, shooting, keeper, misc, playing_time

The following club_priors schema columns will be NULL because the required
stat types (passing, gca, defense, possession, keeper_adv) are not available:
    sca_per_90, gca_per_90, key_passes_per_90, pass_completion_pct,
    carries_into_final_third_per_90, pressures_per_90, pressure_success_pct,
    tackles_per_90, tackle_success_pct, interceptions_per_90, psxg_minus_ga_per_90

Players from leagues outside the Big-5 will have NULL FBref stats.
Their low confidence_score routes them to the "Traditional Scout" LLM path (Phase 3).

Run:
    py -m etl.sources.soccerdata_pull
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import soccerdata as sd
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

from config import settings
from etl.db.connection import write_conn
from etl.db.init_db import refresh_parquet_views

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level paths (must be at top so functions can reference them)
# ---------------------------------------------------------------------------

BRONZE_FBREF: Path = Path(settings.parquet_bronze_dir) / "fbref"
BRONZE_ELO: Path = Path(settings.parquet_bronze_dir) / "club_elo"

# ---------------------------------------------------------------------------
# Pull configuration
# ---------------------------------------------------------------------------

# Season codes for FBref European (MULTI_YEAR) leagues: "YYZZ" = 20YY–20ZZ
SEASONS: list[str] = ["2425", "2526"]  # 2024-25 and 2025-26
SEASON_LABELS: dict[str, str] = {"2425": "2024-25", "2526": "2025-26"}

# Human-readable label for the 2-season aggregate window (PK in club_priors)
SEASON_WINDOW = "2024-25+2025-26"

# Leagues with built-in soccerdata FBref support.
# To add more (Eredivisie, Primeira Liga, MLS, Brasileirão, etc.) create:
#   C:\Users\{user}\soccerdata\config\league_dict.json
# following the format in soccerdata._config.LEAGUE_DICT.
FBREF_LEAGUES: list[str] = [
    "ENG-Premier League",
    "ESP-La Liga",
    "GER-Bundesliga",
    "ITA-Serie A",
    "FRA-Ligue 1",
]

# All stat types supported by soccerdata FBref reader v1.9
STAT_TYPES: list[str] = ["standard", "shooting", "keeper", "misc", "playing_time"]

# Club Elo snapshot date — WC 2026 opening day
ELO_DATE: str = "2026-06-10"

# Drop players with fewer total 90s than this across both seasons (too sparse)
MIN_CAREER_90S: float = 4.5  # ~405 min total

# Pause between per-league FBref fetches to respect rate limits
INTER_LEAGUE_SLEEP_S: float = 15.0

# ---------------------------------------------------------------------------
# PyArrow schemas for Bronze Parquet output
# ---------------------------------------------------------------------------

LEAGUE_ELO_SCHEMA = pa.schema(
    [
        pa.field("league_id", pa.string()),
        pa.field("league_name", pa.string()),
        pa.field("country", pa.string()),
        pa.field("level", pa.int64()),
        pa.field("avg_elo", pa.float64()),
        pa.field("n_clubs", pa.int64()),
        pa.field("elo_strength_coef", pa.float64()),
        pa.field("snapshot_date", pa.string()),
    ]
)

CLUB_PRIORS_SCHEMA = pa.schema(
    [
        pa.field("player_id", pa.string()),
        pa.field("season_window", pa.string()),
        pa.field("club_team_id", pa.string()),
        pa.field("league_id", pa.string()),
        # Volume
        pa.field("matches_played", pa.float64()),
        pa.field("minutes_played", pa.float64()),
        # Attacking (per 90)
        pa.field("goals_per_90", pa.float64()),
        pa.field("assists_per_90", pa.float64()),
        pa.field("xg_per_90", pa.float64()),
        pa.field("xa_per_90", pa.float64()),
        pa.field("npxg_per_90", pa.float64()),
        pa.field("shots_per_90", pa.float64()),
        pa.field("shots_on_target_pct", pa.float64()),
        # Creation — NULL: requires 'gca' stat type (unsupported in v1.9)
        pa.field("sca_per_90", pa.float64()),
        pa.field("gca_per_90", pa.float64()),
        pa.field("key_passes_per_90", pa.float64()),
        # Passing — NULL: requires 'passing' stat type (unsupported in v1.9)
        pa.field("pass_completion_pct", pa.float64()),
        pa.field("progressive_passes_per_90", pa.float64()),
        # Carries — progressive_carries available from standard 'Progression' group
        pa.field("progressive_carries_per_90", pa.float64()),
        pa.field("carries_into_final_third_per_90", pa.float64()),  # NULL: needs 'possession'
        # Defending — NULL: requires 'defense' stat type (unsupported in v1.9)
        pa.field("pressures_per_90", pa.float64()),
        pa.field("pressure_success_pct", pa.float64()),
        pa.field("tackles_per_90", pa.float64()),
        pa.field("tackle_success_pct", pa.float64()),
        pa.field("interceptions_per_90", pa.float64()),
        pa.field("clearances_per_90", pa.float64()),  # available from 'misc'
        pa.field("aerials_won_pct", pa.float64()),    # available from 'misc'
        # GK-specific
        pa.field("save_pct", pa.float64()),            # from 'keeper'
        pa.field("psxg_minus_ga_per_90", pa.float64()),  # NULL: needs 'keeper_adv'
        pa.field("clean_sheet_pct", pa.float64()),     # from 'keeper'
        # Metadata
        pa.field("data_source", pa.string()),
        pa.field("fetched_at", pa.timestamp("us", tz="UTC")),
    ]
)

# Columns that are always NULL in v1.9 (logged once at startup, not per-row)
_NULL_COLS: list[str] = [
    "sca_per_90", "gca_per_90", "key_passes_per_90",
    "pass_completion_pct", "carries_into_final_third_per_90",
    "pressures_per_90", "pressure_success_pct",
    "tackles_per_90", "tackle_success_pct", "interceptions_per_90",
    "psxg_minus_ga_per_90",
]

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_col(
    df: pd.DataFrame,
    *key: str,
    numeric: bool = True,
) -> pd.Series:
    """
    Access a MultiIndex column from a soccerdata FBref DataFrame.
    Returns a NaN Series if the column does not exist.

    soccerdata FBref DataFrames use a 2-level MultiIndex:
      level 0 — FBref stat group:  "Playing Time", "Performance", "Expected", …
      level 1 — stat name:         "MP", "Gls", "xG", "90s", …

    Ungrouped identity columns (Nation, Pos, Age) appear as ("Nation", "") etc.
    """
    try:
        col = df[key] if len(key) > 1 else df[key[0]]
        return pd.to_numeric(col, errors="coerce") if numeric else col
    except KeyError:
        logger.debug("Column not found: %s", key)
        return pd.Series(dtype=float if numeric else object, index=df.index)


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """Element-wise division; NaN where denominator is 0 or NaN."""
    return (num / den.replace(0, float("nan"))).astype(float)


def _slugify(text: str) -> str:
    """Turn a display name into a URL-safe lowercase slug."""
    return (
        str(text)
        .lower()
        .replace(" ", "-")
        .replace("_", "-")
        .replace("'", "")
        .replace(".", "")
        .replace("/", "-")
        .replace("(", "")
        .replace(")", "")
    )


def _log_columns(df: pd.DataFrame, label: str) -> None:
    """Log the first 30 MultiIndex columns for debugging when -v is used."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("[%s] columns (%d total): %s …", label, len(df.columns), list(df.columns[:30]))


# ---------------------------------------------------------------------------
# 1. Club Elo — league strength coefficients
# ---------------------------------------------------------------------------

def pull_club_elo(date_str: str = ELO_DATE) -> pd.DataFrame:
    """
    Fetch Club Elo ratings for all clubs as of `date_str` and compute a
    normalised elo_strength_coef for every recognised league.

    Output schema matches LEAGUE_ELO_SCHEMA.
    Also writes Bronze Parquet:  data/bronze/club_elo/league_elo_{date}.parquet

    elo_strength_coef: max league (highest avg Elo) = 1.0; others are scaled
    proportionally.  Players from weaker leagues have their club stats shrunk
    toward the archetype mean in Phase 2.

    Returns:
        pd.DataFrame with LEAGUE_ELO_SCHEMA columns, or empty DataFrame on failure.
    """
    logger.info("Club Elo — pulling ratings as of %s …", date_str)
    elo_reader = sd.ClubElo(no_cache=False, no_store=False)

    # read_by_date returns a DataFrame indexed by 'team' (club name) with columns:
    #   rank, country, level, elo, from, to, url, league
    # 'league' is translated to the soccerdata key where recognised
    # (e.g. "ENG_1" → "ENG-Premier League").
    raw: pd.DataFrame = elo_reader.read_by_date(date_str)
    logger.info("Club Elo raw: %d clubs across all leagues.", len(raw))

    # Coerce and filter
    raw = raw.copy()
    raw["level"] = pd.to_numeric(raw.get("level"), errors="coerce")
    raw["elo"] = pd.to_numeric(raw.get("elo"), errors="coerce")
    raw = raw.dropna(subset=["level", "elo"])
    raw = raw[raw["level"] <= 2].copy()  # top-flight + second tier only

    # Aggregate per league
    agg = (
        raw.groupby("league", observed=True)
        .agg(
            country=("country", "first"),
            level=("level", "first"),
            avg_elo=("elo", "mean"),
            n_clubs=("elo", "count"),
        )
        .reset_index()
        .rename(columns={"league": "league_id"})
    )

    if agg.empty:
        logger.error("Club Elo aggregation produced no rows.")
        return pd.DataFrame()

    # Normalise
    max_elo = float(agg["avg_elo"].max())
    agg["elo_strength_coef"] = (agg["avg_elo"] / max_elo).round(6)
    agg["league_name"] = agg["league_id"]
    agg["snapshot_date"] = date_str

    top = agg.loc[agg["elo_strength_coef"].idxmax(), "league_id"]
    logger.info(
        "League Elo coefficients: %d leagues | top: %s (coef=1.000)",
        len(agg), top,
    )

    # Write Bronze Parquet
    BRONZE_ELO.mkdir(parents=True, exist_ok=True)
    out_path = BRONZE_ELO / f"league_elo_{date_str}.parquet"
    out_cols = ["league_id", "league_name", "country", "level", "avg_elo",
                "n_clubs", "elo_strength_coef", "snapshot_date"]
    table = pa.Table.from_pandas(
        agg[out_cols], schema=LEAGUE_ELO_SCHEMA, preserve_index=False
    )
    pq.write_table(table, out_path, compression="snappy")
    logger.info("Club Elo Bronze -> %s (%d rows)", out_path.name, len(agg))

    return agg[out_cols]


# ---------------------------------------------------------------------------
# 2. FBref — raw per-(league, season, stat_type) pulls
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=12, max=90),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _fetch_with_retry(fbref: sd.FBref, stat_type: str) -> pd.DataFrame:
    """Call fbref.read_player_season_stats with up to 3 retries on failure."""
    return fbref.read_player_season_stats(stat_type)


def pull_fbref_stats(
    leagues: list[str] = FBREF_LEAGUES,
    seasons: list[str] = SEASONS,
) -> dict[str, pd.DataFrame]:
    """
    Pull all 5 supported FBref stat types for each league across both seasons.

    Failures for a single (league, stat_type) pair are caught and logged;
    other combinations continue. soccerdata caches HTML to disk so repeated
    runs do not re-scrape FBref.

    Returns:
        dict[stat_type → DataFrame] with (league, season, team, player) MultiIndex.

    Side effects:
        Writes one Parquet file per (season, stat_type) to Bronze:
            data/bronze/fbref/player_stats_{season}_{stat_type}.parquet
    """
    BRONZE_FBREF.mkdir(parents=True, exist_ok=True)
    combined: dict[str, list[pd.DataFrame]] = {st: [] for st in STAT_TYPES}

    for league in leagues:
        logger.info("FBref league: '%s'", league)
        try:
            fbref = sd.FBref(leagues=[league], seasons=seasons, no_cache=False, no_store=False)
        except Exception as exc:
            logger.warning("Could not initialise FBref for '%s': %s", league, exc)
            continue

        for stat_type in STAT_TYPES:
            try:
                df = _fetch_with_retry(fbref, stat_type)
                _log_columns(df, f"{league}/{stat_type}")
                combined[stat_type].append(df)
                logger.info("  OK %-15s / %-12s  %d player-season rows", league, stat_type, len(df))
            except Exception as exc:
                logger.warning("  ✗ %-15s / %-12s failed: %s", league, stat_type, exc)

        logger.debug("Sleeping %.0fs before next league …", INTER_LEAGUE_SLEEP_S)
        time.sleep(INTER_LEAGUE_SLEEP_S)

    # Merge across leagues and write per-season Bronze Parquet
    result: dict[str, pd.DataFrame] = {}
    for stat_type, dfs in combined.items():
        if not dfs:
            logger.warning("No data collected for stat_type='%s'.", stat_type)
            continue

        merged = pd.concat(dfs)
        merged = merged[~merged.index.duplicated(keep="first")]
        result[stat_type] = merged

        for season in seasons:
            label = SEASON_LABELS.get(season, season)
            mask = merged.index.get_level_values("season") == season
            season_df = merged[mask]
            if season_df.empty:
                continue
            # Flatten MultiIndex columns for Parquet compatibility
            flat = season_df.copy().reset_index()
            flat.columns = [
                "_".join(str(p).strip() for p in col if str(p).strip()).lower().replace(" ", "_")
                if isinstance(col, tuple) else str(col).lower()
                for col in flat.columns
            ]
            fname = f"player_stats_{label.replace('-', '_')}_{stat_type}.parquet"
            out_path = BRONZE_FBREF / fname
            flat.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)
            logger.info("  Bronze -> %-55s (%d rows)", fname, len(flat))

    return result


# ---------------------------------------------------------------------------
# 3. Per-stat-type extractors
#    Each returns a DataFrame with the same MultiIndex as the input,
#    containing only the columns we care about mapped to schema names.
# ---------------------------------------------------------------------------

def _extract_standard(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract club_priors fields from the 'standard' FBref stat type.

    FBref MultiIndex structure (soccerdata v1.9):
      ("Playing Time", "MP")     matches played
      ("Playing Time", "Min")    minutes played
      ("Playing Time", "90s")    90-minute equivalents  ← weight for per-90 calcs
      ("Performance", "Gls")     goals (total)
      ("Performance", "Ast")     assists (total)
      ("Expected",    "xG")      expected goals
      ("Expected",    "xAG")     expected assisted goals (≈ xA)
      ("Expected",    "npxG")    non-penalty xG
      ("Progression", "PrgC")    progressive carries (total)
      ("Progression", "PrgP")    progressive passes (total)
      ("Per 90 Minutes", "Gls")  goals / 90  (pre-computed by FBref — preferred)
      ("Per 90 Minutes", "Ast")  assists / 90
      ("Per 90 Minutes", "xG")   xG / 90
      ("Per 90 Minutes", "xAG")  xAG / 90
      ("Per 90 Minutes", "npxG") npxG / 90
      ("Pos", "")                position string (e.g. "GK", "CB,CM")
    """
    nineties = _safe_col(df, "Playing Time", "90s")

    out = pd.DataFrame(index=df.index)
    out["matches_played"] = _safe_col(df, "Playing Time", "MP")
    out["minutes_played"] = _safe_col(df, "Playing Time", "Min")
    out["_90s"] = nineties  # internal weight column

    # Prefer FBref pre-computed per-90; fall back to total / 90s
    def _per90(per90_key: tuple, total_key: tuple) -> pd.Series:
        s = _safe_col(df, *per90_key)
        fallback_mask = s.isna()
        if fallback_mask.any():
            tot = _safe_col(df, *total_key)
            s = s.copy()
            s[fallback_mask] = _safe_div(tot[fallback_mask], nineties[fallback_mask])
        return s

    out["goals_per_90"] = _per90(("Per 90 Minutes", "Gls"), ("Performance", "Gls"))
    out["assists_per_90"] = _per90(("Per 90 Minutes", "Ast"), ("Performance", "Ast"))
    out["xg_per_90"] = _per90(("Per 90 Minutes", "xG"), ("Expected", "xG"))
    out["xa_per_90"] = _per90(("Per 90 Minutes", "xAG"), ("Expected", "xAG"))
    out["npxg_per_90"] = _per90(("Per 90 Minutes", "npxG"), ("Expected", "npxG"))

    # Progressive stats: totals only → compute per-90 ourselves
    out["progressive_carries_per_90"] = _safe_div(
        _safe_col(df, "Progression", "PrgC"), nineties
    )
    out["progressive_passes_per_90"] = _safe_div(
        _safe_col(df, "Progression", "PrgP"), nineties
    )

    # Position string (single row per player-season)
    out["_pos"] = _safe_col(df, "Pos", "", numeric=False)

    return out


def _extract_shooting(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract shooting stats.

    FBref 'shooting' groups:
      ("Standard", "Sh/90")  shots per 90  (pre-computed — preferred)
      ("Standard", "Sh")     total shots    (fallback for per-90)
      ("Standard", "SoT%")   shots on target %
    """
    out = pd.DataFrame(index=df.index)
    out["shots_per_90"] = _safe_col(df, "Standard", "Sh/90")
    out["shots_on_target_pct"] = _safe_col(df, "Standard", "SoT%")
    out["_shots_total"] = _safe_col(df, "Standard", "Sh")  # fallback for per-90
    return out


def _extract_keeper(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract GK-specific stats.

    FBref 'keeper' groups:
      ("Performance", "Save%")  save percentage
      ("Performance", "CS%")    clean sheet percentage
    """
    out = pd.DataFrame(index=df.index)
    out["save_pct"] = _safe_col(df, "Performance", "Save%")
    out["clean_sheet_pct"] = _safe_col(df, "Performance", "CS%")
    return out


def _extract_misc(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract miscellaneous stats.

    FBref 'misc' groups:
      ("Aerial Duels", "Won%")  aerial duel win %
      ("Performance",  "Clr")   clearances (total — we compute per-90 in the merge step)
    """
    out = pd.DataFrame(index=df.index)
    out["aerials_won_pct"] = _safe_col(df, "Aerial Duels", "Won%")
    out["_clr_total"] = _safe_col(df, "Performance", "Clr")
    return out


# playing_time stat type: only used as a minutes backup; not extracted separately
# because 'standard' already provides Playing Time / Min.

# ---------------------------------------------------------------------------
# 4. Aggregate extracted stats → club_priors schema
# ---------------------------------------------------------------------------

def build_club_priors(stat_dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Join all extracted stat types and aggregate across 2 seasons into a single
    row per player matching the club_priors DuckDB schema.

    Aggregation strategy:
    - Volume stats (matches, minutes, 90s): summed across seasons.
    - Per-90 rate stats: 90s-weighted mean so high-minutes seasons dominate.
    - Percentage stats: 90s-weighted mean.
    - NULL stats (unsupported stat types): set to NaN.

    Players below MIN_CAREER_90S total are excluded (too sparse to be useful).

    Returns:
        DataFrame with club_priors schema columns plus auxiliary columns
        _player_name and _pos (used for teams/players upsert; dropped before DuckDB write).
    """
    if "standard" not in stat_dfs:
        logger.error("Cannot build club_priors: 'standard' stat type is missing.")
        return pd.DataFrame()

    logger.info("NULL columns (unsupported stat types, will stay NaN): %s", _NULL_COLS)

    # Extract each stat type
    std = _extract_standard(stat_dfs["standard"])
    extras = [
        _extract_shooting(stat_dfs["shooting"]) if "shooting" in stat_dfs else None,
        _extract_keeper(stat_dfs["keeper"]) if "keeper" in stat_dfs else None,
        _extract_misc(stat_dfs["misc"]) if "misc" in stat_dfs else None,
    ]

    # Left-join extras onto the standard anchor
    combined = std.copy()
    for extra in extras:
        if extra is None:
            continue
        # Drop duplicate column names that might arise from shared internal cols
        new_cols = [c for c in extra.columns if c not in combined.columns]
        combined = combined.join(extra[new_cols], how="left")

    # Backfill shots_per_90 from total shots ÷ 90s where FBref didn't provide it
    if "_shots_total" in combined.columns:
        mask = combined["shots_per_90"].isna() & combined["_shots_total"].notna()
        combined.loc[mask, "shots_per_90"] = _safe_div(
            combined.loc[mask, "_shots_total"],
            combined.loc[mask, "_90s"],
        )

    # Clearances per 90 from misc totals ÷ standard 90s
    if "_clr_total" in combined.columns:
        combined["clearances_per_90"] = _safe_div(combined["_clr_total"], combined["_90s"])
    else:
        combined["clearances_per_90"] = float("nan")

    # Null-out GK-specific stats for outfield players
    if "_pos" in combined.columns:
        is_gk = combined["_pos"].astype(str).str.upper().str.startswith("GK")
        for gk_col in ["save_pct", "clean_sheet_pct"]:
            if gk_col in combined.columns:
                combined.loc[~is_gk, gk_col] = float("nan")

    # Reset index so we can groupby over (league, team, player)
    combined = combined.reset_index()  # columns now include league, season, team, player

    # Classify columns for aggregation
    cum_cols = ["matches_played", "minutes_played"]
    rate_cols = [
        "goals_per_90", "assists_per_90", "xg_per_90", "xa_per_90", "npxg_per_90",
        "shots_per_90", "progressive_carries_per_90", "progressive_passes_per_90",
        "clearances_per_90",
    ]
    pct_cols = ["shots_on_target_pct", "aerials_won_pct", "save_pct", "clean_sheet_pct"]

    agg_rows: list[dict[str, Any]] = []

    for (league, team, player), grp in combined.groupby(["league", "team", "player"], observed=True):
        total_90s = float(grp["_90s"].fillna(0).sum())
        if total_90s < MIN_CAREER_90S:
            logger.debug(
                "Skipping %s / %s: %.1f total 90s < threshold %.1f",
                player, team, total_90s, MIN_CAREER_90S,
            )
            continue

        weights = grp["_90s"].fillna(0).values

        row: dict[str, Any] = {
            "player_id": f"fb-{_slugify(player)}-{_slugify(team)}",
            "_player_name": str(player),  # retained for players table upsert
            "season_window": SEASON_WINDOW,
            # Slugified so this FK matches leagues.id written by upsert_leagues
            "league_id": _slugify(str(league)),
            "club_team_id": f"club-{_slugify(team)}",
            "_pos": grp["_pos"].dropna().iloc[0] if "_pos" in grp and grp["_pos"].notna().any() else None,
        }

        # Summed totals
        for col in cum_cols:
            if col in grp.columns:
                row[col] = float(grp[col].fillna(0).sum())
            else:
                row[col] = float("nan")

        # 90s-weighted mean for rate and percentage columns
        for col in rate_cols + pct_cols:
            if col not in grp.columns:
                row[col] = float("nan")
                continue
            vals = grp[col].values
            valid = (weights > 0) & pd.notna(vals)
            if not valid.any():
                row[col] = float("nan")
            else:
                row[col] = float((vals[valid] * weights[valid]).sum() / weights[valid].sum())

        # NULL columns (unsupported stat types)
        for col in _NULL_COLS:
            row[col] = float("nan")

        agg_rows.append(row)

    if not agg_rows:
        logger.warning("build_club_priors: no player survived the MIN_CAREER_90S filter.")
        return pd.DataFrame()

    priors = pd.DataFrame(agg_rows)
    priors["data_source"] = "fbref"
    priors["fetched_at"] = datetime.now(tz=timezone.utc)

    logger.info(
        "club_priors built: %d players across %d leagues, %.0f–%.0f 90s range.",
        len(priors),
        priors["league_id"].nunique(),
        priors["minutes_played"].min() / 90 if "minutes_played" in priors else 0,
        priors["minutes_played"].max() / 90 if "minutes_played" in priors else 0,
    )
    return priors


# ---------------------------------------------------------------------------
# 5. Write aggregated priors to Bronze Parquet
# ---------------------------------------------------------------------------

def write_club_priors_parquet(priors: pd.DataFrame) -> Path:
    """
    Write the schema-aligned club_priors DataFrame to Bronze Parquet.

    Drops auxiliary columns (_player_name, _pos) before writing.
    Fills any missing schema columns with NaN and logs a warning.
    """
    out_df = priors.drop(columns=["_player_name", "_pos"], errors="ignore")

    schema_cols = [f.name for f in CLUB_PRIORS_SCHEMA]
    missing = set(schema_cols) - set(out_df.columns)
    if missing:
        logger.warning(
            "club_priors Parquet: %d schema columns absent (filling NaN): %s",
            len(missing), sorted(missing),
        )
        for col in missing:
            out_df[col] = None

    out_df = out_df.reindex(columns=schema_cols)

    BRONZE_FBREF.mkdir(parents=True, exist_ok=True)
    out_path = BRONZE_FBREF / "club_priors.parquet"
    table = pa.Table.from_pandas(out_df, schema=CLUB_PRIORS_SCHEMA, preserve_index=False)
    pq.write_table(table, out_path, compression="snappy")
    logger.info("club_priors Bronze -> %s (%d rows)", out_path.name, len(out_df))
    return out_path


# ---------------------------------------------------------------------------
# 6. DuckDB upserts
# ---------------------------------------------------------------------------

def _upsert(conn: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame, label: str = "") -> None:
    """
    Bulk-upsert df into table using DuckDB's INSERT OR REPLACE.
    DuckDB registers df as a temporary view, avoids row-by-row binding overhead.
    """
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


def upsert_leagues(conn: duckdb.DuckDBPyConnection, elo_df: pd.DataFrame) -> None:
    """Write Club Elo league records to the DuckDB leagues table."""
    if elo_df.empty:
        return
    leagues = pd.DataFrame(
        {
            # Slugify so leagues.id matches the league_id written into club_priors
            "id": elo_df["league_id"].apply(_slugify),
            "name": elo_df["league_name"],
            "country": elo_df["country"],
            "elo_strength_coef": elo_df["elo_strength_coef"],
            "elo_rating": elo_df["avg_elo"],
            "updated_at": datetime.now(tz=timezone.utc),
        }
    )
    _upsert(conn, "leagues", leagues, "Club Elo")


def upsert_teams(conn: duckdb.DuckDBPyConnection, priors: pd.DataFrame) -> None:
    """
    Extract distinct club teams from priors and upsert into the teams table.

    Only club teams are created here. National teams are ingested during
    the Sofascore/ESPN pull (next Phase 1 task).
    """
    if priors.empty:
        return
    teams = (
        priors[["club_team_id", "league_id"]]
        .drop_duplicates("club_team_id")
        .assign(
            id=lambda df: df["club_team_id"],
            # Recover display name from slug: "club-manchester-city" → "Manchester City"
            name=lambda df: df["club_team_id"]
                .str.replace("^club-", "", regex=True)
                .str.replace("-", " ")
                .str.title(),
            short_name=None,
            is_national=False,
            sofascore_id=None,
            espn_id=None,
            fbref_id=None,
            updated_at=datetime.now(tz=timezone.utc),
        )
        [["id", "name", "short_name", "league_id", "is_national",
          "sofascore_id", "espn_id", "fbref_id", "updated_at"]]
    )
    _upsert(conn, "teams", teams, "club teams from FBref")


def upsert_players(conn: duckdb.DuckDBPyConnection, priors: pd.DataFrame) -> None:
    """
    Extract distinct players from priors and upsert into the players table.

    Position and national team linkage are left NULL here; they will be
    enriched by the Sofascore squad pull (next Phase 1 task).
    """
    if priors.empty or "_player_name" not in priors.columns:
        return
    players = (
        priors[["player_id", "_player_name", "club_team_id", "_pos"]]
        .drop_duplicates("player_id")
        .assign(
            id=lambda df: df["player_id"],
            name=lambda df: df["_player_name"],
            team_id=lambda df: df["club_team_id"],
            # Store raw FBref position; normalisation to GK/CB/FB/CM/AM/W/ST is Phase 2
            position=lambda df: df["_pos"],
            nationality=None,
            date_of_birth=None,
            age_at_wc2026=None,
            sofascore_id=None,
            fbref_id=None,
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
# 7. Main orchestrator
# ---------------------------------------------------------------------------

def main() -> None:
    """
    End-to-end Phase 1 soccerdata pull.

    Exit codes:
      0 — completed (partial failures are logged but do not abort)
      1 — fatal error prevented any data from being written
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("=== TrueScout Phase 1: soccerdata_pull (Club Elo only) ===")
    logger.info(
        "FBref ingestion has moved to etl/sources/fbref_pull.py (curl_cffi)."
        " Run:  python -m etl.sources.fbref_pull --all-seasons"
    )
    logger.info("Config: elo_date=%s", ELO_DATE)

    # ── 1. Club Elo ─────────────────────────────────────────────────────────
    elo_df = pd.DataFrame()
    try:
        elo_df = pull_club_elo(ELO_DATE)
    except Exception as exc:
        logger.error("Club Elo pull failed (non-fatal): %s", exc)

    # ── 2. DuckDB upsert ────────────────────────────────────────────────────
    with write_conn() as conn:
        if not elo_df.empty:
            try:
                upsert_leagues(conn, elo_df)
            except Exception as exc:
                logger.error("leagues upsert failed: %s", exc, exc_info=True)

        # ── 3. Refresh DuckDB Parquet views ─────────────────────────────────
        try:
            refresh_parquet_views(conn)
        except Exception as exc:
            logger.error("refresh_parquet_views failed: %s", exc)

    # ── Summary ─────────────────────────────────────────────────────────────
    logger.info(
        "=== Pull complete. Leagues written: %d ===",
        len(elo_df),
    )


if __name__ == "__main__":
    main()
