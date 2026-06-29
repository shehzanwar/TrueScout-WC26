"""
Understat Bronze ingestion -- per-player club-season xG / xA priors.

Understat provides xG/xA event data for 5 top European leagues, sourced from
the same StatsBomb feed that previously powered FBref before the Opta/Stats
Perform licensing blackout in January 2026.

Writes one Parquet per season plus a 90s-weighted 2-year aggregate:
    data/bronze/understat/players_2024.parquet     (raw 2024-25)
    data/bronze/understat/players_2025.parquet     (raw 2025-26)
    data/bronze/understat/club_priors_agg.parquet  (weighted aggregate; player_id = reep_id)

ID policy:
  - Per-season raw files: player_id = 'us-{understat_id}' (Bronze source ID)
  - Aggregate output:     player_id = reep_id from identity_players (canonical)
    If identity_players is missing, falls back to 'us-{understat_id}' with a warning.
  Run etl.sources.reep_pull BEFORE this script to enable reep resolution.

Usage:
    python -m etl.sources.understat_pull                   # both seasons, all leagues
    python -m etl.sources.understat_pull --season 2025     # single season
    python -m etl.sources.understat_pull --validate        # dry-run, no writes
"""
import argparse
import logging
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from understatapi import UnderstatClient

# Allow running as __main__ or as a module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import settings
from etl.db.init_db import refresh_parquet_views

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEAGUES = ["EPL", "La_Liga", "Bundesliga", "Serie_A", "Ligue_1"]

# Understat season key "2024" = 2024/25 season, "2025" = 2025/26 season.
SEASONS = ["2024", "2025"]

SEASON_LABEL: dict[str, str] = {
    "2024": "2024-25",
    "2025": "2025-26",
}

# Players with fewer minutes across the window are noise; skip them.
MIN_MINUTES = 90

# Understat has no published rate limit; 2 s between calls is conservative.
SLEEP_BETWEEN_CALLS = 2.0

BRONZE_DIR = Path(settings.parquet_bronze_dir) / "understat"

# Columns that Understat cannot supply (FBref/tracking-only).  They land in
# the Bronze Parquet as NaN so the club_priors schema stays complete.
_NULL_COLS: list[str] = [
    "shots_on_target_pct",
    "sca_per_90",
    "gca_per_90",
    "pass_completion_pct",
    "progressive_passes_per_90",
    "progressive_carries_per_90",
    "carries_into_final_third_per_90",
    "pressures_per_90",
    "pressure_success_pct",
    "tackles_per_90",
    "tackle_success_pct",
    "interceptions_per_90",
    "clearances_per_90",
    "aerials_won_pct",
    "save_pct",
    "psxg_minus_ga_per_90",
    "clean_sheet_pct",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_name(s: str) -> str:
    """
    Deterministic name normalisation for reep identity matching.
    Strips diacritics (NFD + drop Mn category), treats hyphens as spaces,
    lowercases, collapses whitespace.  NOT fuzzy — exact match after transform.

    Examples:
        "Vinícius Júnior"   -> "vinicius junior"
        "Kylian Mbappe-Lottin" -> "kylian mbappe lottin"
        "Jude Bellingham"   -> "jude bellingham"
    """
    if not isinstance(s, str) or not s:
        return ""
    nfd = unicodedata.normalize("NFD", s)
    no_marks = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    no_marks = no_marks.replace("-", " ")
    return " ".join(no_marks.lower().split())


def _safe(val, default: float = float("nan")) -> float:
    """Coerce Understat string values to float; return default on failure."""
    try:
        return float(val) if val not in (None, "", "None") else default
    except (TypeError, ValueError):
        return default


def _per90(raw_val, minutes: float) -> float:
    if minutes < 1:
        return float("nan")
    raw = _safe(raw_val)
    if np.isnan(raw):
        return float("nan")
    return raw / (minutes / 90.0)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_season(league: str, season: str) -> list[dict]:
    """
    Pull all player data for one league-season from Understat.
    Returns a list of row dicts aligned with the club_priors Bronze schema.
    """
    logger.info("Fetching Understat  %s / %s ...", league, SEASON_LABEL[season])

    with UnderstatClient() as client:
        raw = client.league(league).get_player_data(season)

    time.sleep(SLEEP_BETWEEN_CALLS)

    # Defensive: understatapi may return a dict keyed by player_id on some
    # version/endpoint combinations.
    players_iter = raw.values() if isinstance(raw, dict) else raw

    rows: list[dict] = []
    for p in players_iter:
        mins = _safe(p.get("time"), 0.0)
        if mins < MIN_MINUTES:
            continue

        understat_id = str(p.get("id", ""))
        row: dict = {
            # --- Identity (Bronze-layer only) --------------------------------
            "player_id":    f"us-{understat_id}",
            "understat_id": understat_id,
            "player_name":  p.get("player_name", ""),
            "position":     p.get("position", ""),
            "team_name":    p.get("team_title", ""),
            "league":       league,
            "season":       season,
            # --- Volume ------------------------------------------------------
            "matches_played": _safe(p.get("games")),
            "minutes_played": mins,
            # --- Attacking (per 90) -----------------------------------------
            "goals_per_90":      _per90(p.get("goals"),      mins),
            "assists_per_90":    _per90(p.get("assists"),     mins),
            "xg_per_90":         _per90(p.get("xG"),         mins),
            "xa_per_90":         _per90(p.get("xA"),         mins),
            "npxg_per_90":       _per90(p.get("npxG"),       mins),
            "shots_per_90":      _per90(p.get("shots"),      mins),
            "key_passes_per_90": _per90(p.get("key_passes"), mins),
            # --- Metadata ----------------------------------------------------
            "data_source": "understat",
            "fetched_at":  datetime.now(),
        }
        # Fill FBref-only columns with NaN so schema stays aligned.
        for col in _NULL_COLS:
            row[col] = float("nan")

        rows.append(row)

    logger.info("  -> %d players (>= %d min)", len(rows), MIN_MINUTES)
    return rows


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def aggregate_seasons(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """
    90s-weighted mean across all supplied season DataFrames, grouped by
    player_id.  Players who appear in only one season get that data directly.
    """
    combined = pd.concat(frames, ignore_index=True)
    combined["_90s"] = combined["minutes_played"] / 90.0

    per90_cols = [
        "goals_per_90", "assists_per_90", "xg_per_90", "xa_per_90",
        "npxg_per_90", "shots_per_90", "key_passes_per_90",
    ]

    def _wmean(grp: pd.DataFrame) -> pd.Series:
        w = grp["_90s"]
        seasons_seen = sorted(grp["season"].unique())
        out: dict = {
            "understat_id":   grp["understat_id"].iloc[0],
            "player_name":    grp["player_name"].iloc[-1],
            "position":       grp["position"].iloc[-1],
            "team_name":      grp["team_name"].iloc[-1],
            "league":         grp["league"].iloc[-1],
            "season_window":  "+".join(SEASON_LABEL[s] for s in seasons_seen),
            "matches_played": grp["matches_played"].sum(),
            "minutes_played": grp["minutes_played"].sum(),
            "data_source":    "understat",
            "fetched_at":     grp["fetched_at"].max(),
        }
        for col in per90_cols:
            vals = grp[col]
            valid = ~vals.isna()
            if not valid.any():
                out[col] = float("nan")
            else:
                out[col] = float(np.average(vals[valid], weights=w[valid]))
        for col in _NULL_COLS:
            out[col] = float("nan")
        return pd.Series(out)

    agg = combined.groupby("player_id", sort=False).apply(_wmean, include_groups=False).reset_index()
    return agg


# ---------------------------------------------------------------------------
# Reep identity resolution
# ---------------------------------------------------------------------------

def resolve_reep_ids(df: pd.DataFrame) -> pd.DataFrame:
    """
    Three-pass Understat → reep_id resolution.

    Pass 1 — direct key_understat join (existing sparse coverage ~29%).
    Pass 2 — normalized name match: strip diacritics + hyphen→space, lowercase.
              Applied to identity_players.name AND identity_players.full_name.
              Only unambiguous matches accepted (exactly 1 reep_id per norm string).
    Pass 3 — same normalization against identity_names.alias (names.csv nicknames).
              Skipped gracefully if identity_names table doesn't exist yet.

    Players still unresolved after all passes are dropped with a WARNING.
    If identity_players doesn't exist (reep_pull not run), falls back to
    'us-{understat_id}' player_id with a single warning.
    """
    db = str(Path(settings.duckdb_path))
    conn = duckdb.connect(db, read_only=True)
    try:
        # Pass 1 mapping
        mapping: pd.DataFrame = conn.execute("""
            SELECT
                CAST(key_understat AS VARCHAR) AS understat_id,
                reep_id
            FROM identity_players
            WHERE key_understat IS NOT NULL AND key_understat != ''
        """).df()

        # All players for name-based fallback (pass 2)
        all_players: pd.DataFrame = conn.execute(
            "SELECT reep_id, name, full_name FROM identity_players"
        ).df()

        # Pass 3 aliases from names.csv (optional)
        try:
            alias_rows: pd.DataFrame = conn.execute("""
                SELECT reep_id, alias AS raw
                FROM identity_names
                WHERE alias IS NOT NULL AND alias != ''
            """).df()
            has_aliases = True
        except duckdb.CatalogException:
            alias_rows = pd.DataFrame(columns=["reep_id", "raw"])
            has_aliases = False

    except duckdb.CatalogException:
        logger.warning(
            "identity_players table not found. "
            "Run 'python -m etl.sources.reep_pull' first to enable reep resolution. "
            "Falling back to us-{understat_id} player_id."
        )
        return df
    finally:
        conn.close()

    before = len(df)
    df = df.copy()
    df["understat_id"] = df["understat_id"].astype(str).str.strip()
    mapping["understat_id"] = mapping["understat_id"].astype(str).str.strip()

    # --- Pass 1: direct key_understat ---
    merged = df.merge(mapping, on="understat_id", how="left")
    pass1 = merged["reep_id"].notna().sum()
    logger.info("Pass 1 (key_understat direct):   %4d / %d matched", pass1, before)

    # --- Build normalized name lookup for passes 2 & 3 ---
    name_entries = []
    for col in ("name", "full_name"):
        sub = all_players[["reep_id", col]].rename(columns={col: "raw"})
        sub = sub[sub["raw"].notna() & (sub["raw"] != "")]
        name_entries.append(sub)
    if has_aliases and not alias_rows.empty:
        name_entries.append(alias_rows)

    name_df = pd.concat(name_entries, ignore_index=True)
    name_df["norm"] = name_df["raw"].apply(_normalize_name)
    name_df = name_df[name_df["norm"] != ""][["reep_id", "norm"]].drop_duplicates()

    # Uniqueness gate: only keep norm strings that map to exactly 1 reep_id.
    # This prevents false positives from common names (e.g. "David Silva").
    counts = name_df.groupby("norm")["reep_id"].nunique()
    uniq_norms = counts[counts == 1].index
    name_lookup: pd.Series = (
        name_df[name_df["norm"].isin(uniq_norms)]
        .drop_duplicates("norm")
        .set_index("norm")["reep_id"]
    )

    # --- Pass 2 & 3: normalize unresolved Understat names ---
    unresolved_mask = merged["reep_id"].isna()
    if unresolved_mask.any():
        norm_series = merged.loc[unresolved_mask, "player_name"].apply(_normalize_name)
        resolved_via_name = norm_series.map(name_lookup)
        merged.loc[unresolved_mask, "reep_id"] = resolved_via_name.values

    pass2 = merged["reep_id"].notna().sum() - pass1
    logger.info(
        "Pass 2 (name normalize%s): +%4d matched",
        "+aliases" if has_aliases else "       ",
        pass2,
    )

    # --- Final: warn and drop still-unresolved ---
    still_missing = merged[merged["reep_id"].isna()]
    if not still_missing.empty:
        sample = still_missing.head(20)
        for _, row in sample.iterrows():
            logger.warning(
                "No reep_id for understat_id=%s (%s, %s) -- dropping prior",
                row["understat_id"], row.get("player_name", ""), row.get("league", ""),
            )
        remainder = len(still_missing) - 20
        if remainder > 0:
            logger.warning("... and %d more players dropped (no reep match).", remainder)

    resolved = merged[merged["reep_id"].notna()].copy()
    resolved["player_id"] = resolved["reep_id"]

    pct = 100 * len(resolved) / max(before, 1)
    logger.info(
        "Reep resolution total:           %4d / %d (%.0f%%)",
        len(resolved), before, pct,
    )
    return resolved


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    logger.info("Written: %s  (%d rows)", path.name, len(df))


def _refresh_views() -> None:
    conn = duckdb.connect(str(Path(settings.duckdb_path)))
    try:
        refresh_parquet_views(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Pull Understat club-priors into Bronze Parquet."
    )
    parser.add_argument(
        "--season",
        choices=SEASONS,
        help="Pull a single season (default: both).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Dry-run: fetch EPL 2025 only, print sample, do not write.",
    )
    args = parser.parse_args()

    logger.info("=== TrueScout Phase 1: understat_pull ===")
    logger.info("Leagues : %s", ", ".join(LEAGUES))

    if args.validate:
        logger.info("VALIDATE mode -- fetching EPL %s only", SEASONS[-1])
        rows = fetch_season("EPL", SEASONS[-1])
        if not rows:
            logger.error("No rows returned -- check network and understatapi version.")
            return
        sample = pd.DataFrame(rows[:5])[
            ["player_name", "team_name", "minutes_played", "xg_per_90", "xa_per_90"]
        ]
        logger.info("Sample:\n%s", sample.to_string(index=False))
        logger.info("Validation complete. Total players: %d", len(rows))
        return

    seasons_to_run = [args.season] if args.season else SEASONS
    logger.info("Seasons : %s", ", ".join(SEASON_LABEL[s] for s in seasons_to_run))

    season_frames: list[pd.DataFrame] = []

    for season in seasons_to_run:
        season_rows: list[dict] = []
        for league in LEAGUES:
            try:
                season_rows.extend(fetch_season(league, season))
            except Exception as exc:
                logger.warning(
                    "Failed %s / %s -- %s. Skipping; prior will be null for this cohort.",
                    league, SEASON_LABEL[season], exc,
                )

        if not season_rows:
            logger.warning("Season %s returned no rows -- skipping write.", season)
            continue

        df = pd.DataFrame(season_rows)
        out = BRONZE_DIR / f"players_{season}.parquet"
        _write_parquet(df, out)
        season_frames.append(df)
        logger.info(
            "Season %s: %d players across %d leagues",
            SEASON_LABEL[season], len(df), df["league"].nunique(),
        )

    # Write 90s-weighted aggregate only when we have data from all requested seasons.
    if len(season_frames) >= 1:
        logger.info("Aggregating %d season frame(s) ...", len(season_frames))
        agg = aggregate_seasons(season_frames)

        # Resolve understat_id -> reep_id (canonical player identifier).
        # Requires identity_players to be populated by etl.sources.reep_pull.
        logger.info("Resolving reep IDs ...")
        agg = resolve_reep_ids(agg)

        _write_parquet(agg, BRONZE_DIR / "club_priors_agg.parquet")
        logger.info(
            "Aggregate: %d unique players  season_window=%s",
            len(agg),
            agg["season_window"].value_counts().to_dict() if not agg.empty else {},
        )
        _refresh_views()

    total_players = sum(len(f) for f in season_frames)
    logger.info("=== Pull complete. Total player-season rows written: %d ===", total_players)


if __name__ == "__main__":
    main()
