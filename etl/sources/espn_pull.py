"""
etl/sources/espn_pull.py — ESPN batch ingestion (Phase 1).

Fetches two data sets from ESPN's public (undocumented) Soccer API:

  1. Match results  → Bronze: data/bronze/espn/matches/matches_{context}.parquet
  2. Betting odds   → Bronze: data/bronze/espn/odds/odds_{context}.parquet

Purpose in TrueScout
────────────────────
  • Matches:  Fallback source when Sofascore fails.  Completed group-stage
              results are the *initial likelihood* for the Bayesian model.
  • Odds:     Pre-match moneyline probabilities from ESPN's odds provider.
              These become the *market baseline* for Brier-score tracking.

JSON schema validation (Pydantic v2)
─────────────────────────────────────
ESPN's API is undocumented and subject to silent schema drift.  Every event
is validated individually: a bad event is logged, its raw JSON saved to the
errors/ directory, and the batch continues.  The Pydantic models all use
`extra="ignore"` so new ESPN fields never break the parser.

American odds → implied probability
────────────────────────────────────
  Negative odds (e.g. -150):  prob = |odds| / (|odds| + 100)
  Positive odds (e.g. +200):  prob = 100 / (odds + 100)
  The three implied probs (home/draw/away) are then normalised to 1.0 to
  remove the bookmaker's over-round before writing to Parquet.

ID policy (Phase 1)
───────────────────
Only ESPN string IDs are written to Bronze.  Cross-source resolution
(ESPN team ID ↔ Sofascore team ID ↔ FBref team name) is a Phase 2 task in
etl/matching/.  This script does NOT touch the DuckDB tables directly.

Run:
    py -m etl.sources.espn_pull --date 2026-06-29
    py -m etl.sources.espn_pull --group-stage
    py -m etl.sources.espn_pull --group-stage --league fifa.world
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings
from etl.db.connection import write_conn
from etl.db.init_db import refresh_parquet_views

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BRONZE_ESPN: Path = Path(settings.parquet_bronze_dir) / "espn"
BRONZE_ESPN_MATCHES: Path = _BRONZE_ESPN / "matches"
BRONZE_ESPN_ODDS: Path = _BRONZE_ESPN / "odds"
BRONZE_ESPN_ERRORS: Path = _BRONZE_ESPN / "errors"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ESPN Soccer league slug for FIFA World Cup.  Change to e.g. "eng.1" (Premier
# League) if you want to pull other competitions.
DEFAULT_LEAGUE_SLUG: str = "fifa.world"

# WC 2026 group stage date range (inclusive, both ends)
GROUP_STAGE_START: str = "2026-06-11"
GROUP_STAGE_END: str = "2026-07-02"

# WC 2026 knockout stage: R32 (Jun 28–Jul 3) + R16 (Jul 4–7) + QF (Jul 9–12) + SF (Jul 14–15) + F (Jul 19)
KNOCKOUT_START: str = "2026-06-28"
KNOCKOUT_END:   str = "2026-07-19"

TIMEOUT_S: int = 30
REQUEST_SLEEP_S: float = 0.8   # ESPN is less aggressive than Sofascore; shorter sleep

HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
}

# ---------------------------------------------------------------------------
# Custom exceptions for tenacity routing
# ---------------------------------------------------------------------------


class EspnRateLimitError(Exception):
    """429 Too Many Requests — retryable."""


class EspnServerError(Exception):
    """5xx Server Error — retryable."""


class EspnClientError(Exception):
    """4xx (non-429) — not retryable."""


# ---------------------------------------------------------------------------
# Pydantic v2 models
#
# All models use extra="ignore" — unknown ESPN fields are silently dropped.
# Fields that ESPN occasionally omits are typed Optional (default None).
# ---------------------------------------------------------------------------


class EspnTeam(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    displayName: str
    abbreviation: str | None = None
    shortDisplayName: str | None = None


class EspnAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")
    city: str | None = None
    state: str | None = None
    country: str | None = None


class EspnVenue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    fullName: str | None = None
    displayName: str | None = None   # event-level venue uses this instead of fullName
    # city/country are nested under "address" in competition-level venue
    address: EspnAddress | None = None
    # kept for any ESPN response that does put them at top level
    city: str | None = None
    country: str | None = None

    @property
    def resolved_name(self) -> str | None:
        return self.fullName or self.displayName

    @property
    def resolved_city(self) -> str | None:
        return self.city or (self.address.city if self.address else None)

    @property
    def resolved_country(self) -> str | None:
        return self.country or (self.address.country if self.address else None)


class EspnStatusType(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    state: str                 # "pre" | "in" | "post"
    completed: bool = False
    description: str | None = None
    detail: str | None = None  # e.g. "Final", "HT"


class EspnStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: EspnStatusType


class EspnTeamOdds(BaseModel):
    """Odds for one side of a match (home, away, or draw) — legacy ESPN format."""
    model_config = ConfigDict(extra="ignore")

    moneyLine: float | None = None
    # ESPN sometimes provides this directly (0–100 scale, pre-calculated)
    winPercentage: float | None = None


class EspnOddsProvider(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str | None = None
    priority: int | None = None


# ---------------------------------------------------------------------------
# ESPN 2026 moneyline widget — odds stored as strings, e.g. "-135" or "+400"
# The new structure is: odds_entry.moneyline.home.close.odds (string)
# ---------------------------------------------------------------------------

class EspnOddsLine(BaseModel):
    """A single open/close odds line in the new ESPN widget format."""
    model_config = ConfigDict(extra="ignore")
    odds: str | None = None


class EspnMoneylineSide(BaseModel):
    """One side (home/away/draw) of the ESPN moneyline widget (2026 format)."""
    model_config = ConfigDict(extra="ignore")
    close: EspnOddsLine | None = None
    open:  EspnOddsLine | None = None


class EspnMoneylineWidget(BaseModel):
    """ESPN structured 3-way moneyline block — replaces homeTeamOdds in 2026 API."""
    model_config = ConfigDict(extra="ignore")
    home: EspnMoneylineSide | None = None
    away: EspnMoneylineSide | None = None
    draw: EspnMoneylineSide | None = None


class EspnOddsEntry(BaseModel):
    """One odds snapshot from one provider."""
    model_config = ConfigDict(extra="ignore")

    provider: EspnOddsProvider | None = None
    # New ESPN 2026 format: all three sides in a structured moneyline widget
    moneyline: EspnMoneylineWidget | None = None
    # Legacy ESPN format (pre-2026): separate homeTeamOdds / awayTeamOdds / drawOdds
    homeTeamOdds: EspnTeamOdds | None = None
    awayTeamOdds: EspnTeamOdds | None = None
    drawOdds: EspnTeamOdds | None = None
    # Composite field ESPN sometimes includes
    details: str | None = None


class EspnCompetitor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    homeAway: str              # "home" | "away"
    score: str | None = None   # string integer, e.g. "2"; None for upcoming
    team: EspnTeam


class EspnCompetition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    date: str | None = None
    competitors: list[EspnCompetitor]
    status: EspnStatus
    venue: EspnVenue | None = None
    # ESPN returns [null] when no odds are available — strip nulls before validating
    odds: list[EspnOddsEntry] | None = None
    # round/group label: ESPN puts it here (e.g. "FIFA World Cup, Group B")
    altGameNote: str | None = None
    # older ESPN responses used a notes array; kept for backward compat
    notes: list[dict[str, Any]] | None = None

    @field_validator("odds", mode="before")
    @classmethod
    def strip_null_odds(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [item for item in v if item is not None]
        return v


class EspnEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    shortName: str | None = None
    date: str | None = None
    competitions: list[EspnCompetition]
    status: EspnStatus


class EspnScoreboardPage(BaseModel):
    """Top-level scoreboard response (only the fields we use)."""
    model_config = ConfigDict(extra="ignore")

    events: list[dict[str, Any]] | None = None   # raw dicts; validated per-event below


# ---------------------------------------------------------------------------
# PyArrow schemas
# ---------------------------------------------------------------------------

MATCHES_SCHEMA = pa.schema([
    pa.field("event_id", pa.string()),
    pa.field("match_date", pa.string()),        # YYYY-MM-DD (UTC)
    pa.field("start_time_utc", pa.string()),    # ISO 8601 from ESPN
    pa.field("league_slug", pa.string()),
    pa.field("round_name", pa.string()),        # "Group A", "Round of 32", …
    pa.field("home_team_id", pa.string()),
    pa.field("home_team_name", pa.string()),
    pa.field("home_team_abbrev", pa.string()),
    pa.field("away_team_id", pa.string()),
    pa.field("away_team_name", pa.string()),
    pa.field("away_team_abbrev", pa.string()),
    pa.field("home_score", pa.int64()),
    pa.field("away_score", pa.int64()),
    pa.field("status_state", pa.string()),      # "post" | "in" | "pre"
    pa.field("status_detail", pa.string()),     # "Final", "HT", …
    pa.field("is_completed", pa.bool_()),
    pa.field("venue_name", pa.string()),
    pa.field("venue_city", pa.string()),
    pa.field("venue_country", pa.string()),
    pa.field("fetched_at", pa.timestamp("us", tz="UTC")),
])

ODDS_SCHEMA = pa.schema([
    pa.field("event_id", pa.string()),
    pa.field("match_date", pa.string()),
    pa.field("provider_name", pa.string()),
    # Raw American moneyline values as returned by ESPN
    pa.field("home_moneyline", pa.float64()),
    pa.field("draw_moneyline", pa.float64()),
    pa.field("away_moneyline", pa.float64()),
    # Implied probabilities (from moneyLine or winPercentage), not yet normalised
    pa.field("home_implied_raw", pa.float64()),
    pa.field("draw_implied_raw", pa.float64()),
    pa.field("away_implied_raw", pa.float64()),
    # Normalised to 1.0 (vig removed) — use these as the Brier market baseline
    pa.field("home_win_prob", pa.float64()),
    pa.field("draw_prob", pa.float64()),
    pa.field("away_win_prob", pa.float64()),
    pa.field("fetched_at", pa.timestamp("us", tz="UTC")),
])

# ---------------------------------------------------------------------------
# Error payload helper
# ---------------------------------------------------------------------------


def _save_error_json(payload: Any, context: str, date_str: str) -> None:
    """Persist a raw JSON payload that failed validation to the errors/ directory."""
    BRONZE_ESPN_ERRORS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%H%M%S")
    safe_ctx = context.replace("/", "_").replace(" ", "_")
    fname = BRONZE_ESPN_ERRORS / f"{date_str}_{safe_ctx}_{ts}.json"
    try:
        fname.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.warning("Error payload saved → %s", fname.name)
    except Exception as exc:
        logger.error("Could not save error payload: %s", exc)


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=10, max=60),
    retry=retry_if_exception_type((EspnRateLimitError, EspnServerError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _get(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> dict:
    """
    Perform a single GET request against the ESPN API.

    Raises:
        EspnRateLimitError  — 429; tenacity will retry
        EspnServerError     — 5xx; tenacity will retry
        EspnClientError     — other 4xx; caller should skip
    """
    resp = client.get(url, params=params, headers=HEADERS, timeout=TIMEOUT_S)

    if resp.status_code == 429:
        raise EspnRateLimitError(f"429 rate-limited: {url}")
    if resp.status_code >= 500:
        raise EspnServerError(f"{resp.status_code} server error: {url}")
    if resp.status_code != 200:
        raise EspnClientError(f"{resp.status_code} client error: {url}")

    try:
        return resp.json()
    except Exception as exc:
        raise EspnServerError(f"JSON parse failure for {url}: {exc}") from exc


# ---------------------------------------------------------------------------
# Per-event Pydantic validation
# ---------------------------------------------------------------------------


def _validate_event(raw: dict[str, Any], date_str: str) -> EspnEvent | None:
    """
    Validate a single raw ESPN event dict.

    Returns EspnEvent on success; logs a warning + saves the raw payload and
    returns None on ValidationError.  This keeps one bad event from aborting
    an entire date's batch.
    """
    try:
        return EspnEvent.model_validate(raw)
    except ValidationError as exc:
        event_id = raw.get("id", "unknown")
        logger.warning(
            "Validation failed for event %s (%d error(s)) — saving raw payload.",
            event_id, exc.error_count(),
        )
        logger.debug("Validation errors: %s", exc.errors())
        _save_error_json(raw, f"event_{event_id}", date_str)
        return None


# ---------------------------------------------------------------------------
# Scoreboard fetch
# ---------------------------------------------------------------------------


def fetch_scoreboard(
    client: httpx.Client,
    date_str: str,
    league_slug: str = DEFAULT_LEAGUE_SLUG,
    completed_only: bool = True,
) -> list[EspnEvent]:
    """
    Fetch the ESPN scoreboard for a single date and return validated events.

    Endpoint:
        GET {espn_soccer_base_url}/{league_slug}/scoreboard
        ?dates=YYYYMMDD&limit=50

    Args:
        date_str:       Calendar date in YYYY-MM-DD format.
        completed_only: When True (default), skip non-finished events.
                        Set False for knockout-stage pulls where we need
                        upcoming fixture team names even without scores.
    """
    date_compact = date_str.replace("-", "")
    url = f"{settings.espn_soccer_base_url}/{league_slug}/scoreboard"
    params: dict[str, Any] = {"dates": date_compact, "limit": 50}

    logger.info("ESPN scoreboard → %s / %s", league_slug, date_str)

    try:
        raw = _get(client, url, params)
    except EspnClientError as exc:
        logger.warning("ESPN scoreboard skipped (%s): %s", date_str, exc)
        return []
    except Exception as exc:
        logger.error("ESPN scoreboard failed (%s): %s", date_str, exc)
        _save_error_json({"url": url, "params": params, "error": str(exc)}, "scoreboard", date_str)
        return []

    # Validate the top-level shape (only checks that `events` key exists)
    try:
        page = EspnScoreboardPage.model_validate(raw)
    except ValidationError as exc:
        logger.error("Top-level scoreboard schema failed for %s: %s", date_str, exc)
        _save_error_json(raw, "scoreboard_toplevel", date_str)
        return []

    raw_events: list[dict] = page.events or []
    logger.info("  Raw events: %d (all statuses)", len(raw_events))

    valid: list[EspnEvent] = []
    for raw_event in raw_events:
        event = _validate_event(raw_event, date_str)
        if event is None:
            continue
        if completed_only and not event.status.type.completed:
            logger.debug("  Skipping non-completed event %s", event.id)
            continue
        valid.append(event)

    label = "completed" if completed_only else "all"
    logger.info("  %s valid events: %d", label, len(valid))
    return valid


# ---------------------------------------------------------------------------
# Parsers  (EspnEvent → flat dicts → DataFrame)
# ---------------------------------------------------------------------------


def _extract_round(competition: EspnCompetition) -> str | None:
    """
    Pull the group/round label from a competition.

    ESPN uses two different locations depending on the API version:
      - competition.altGameNote: "FIFA World Cup, Group B"   ← observed in 2026 response
      - competition.notes[].headline: "Group A"              ← older ESPN format
    """
    # Primary: altGameNote (e.g. "FIFA World Cup, Group B" → strip the tournament prefix)
    if competition.altGameNote:
        note = competition.altGameNote
        # Strip leading "FIFA World Cup, " if present to get just "Group B"
        for prefix in ("FIFA World Cup, ", "FIFA World Cup ", "World Cup "):
            if note.startswith(prefix):
                return note[len(prefix):]
        return note

    # Fallback: notes array (older ESPN format)
    for note in competition.notes or []:
        for key in ("headline", "text", "value"):
            if val := note.get(key):
                return str(val)
    return None


def parse_matches(
    events: list[EspnEvent],
    date_str: str,
    league_slug: str,
    fetch_ts: datetime,
) -> pd.DataFrame:
    """
    Flatten validated EspnEvent objects into a DataFrame matching MATCHES_SCHEMA.

    Uses `competitions[0]` (soccer events have exactly one competition).
    """
    rows: list[dict] = []
    for event in events:
        if not event.competitions:
            logger.debug("Event %s has no competitions — skipping.", event.id)
            continue

        comp = event.competitions[0]

        home = next((c for c in comp.competitors if c.homeAway == "home"), None)
        away = next((c for c in comp.competitors if c.homeAway == "away"), None)

        if home is None or away is None:
            logger.warning("Event %s missing home/away competitor — skipping.", event.id)
            continue

        venue = comp.venue or EspnVenue()
        status = comp.status.type

        rows.append({
            "event_id": event.id,
            "match_date": date_str,
            "start_time_utc": event.date or comp.date,
            "league_slug": league_slug,
            "round_name": _extract_round(comp),
            "home_team_id": home.team.id,
            "home_team_name": home.team.displayName,
            "home_team_abbrev": home.team.abbreviation,
            "away_team_id": away.team.id,
            "away_team_name": away.team.displayName,
            "away_team_abbrev": away.team.abbreviation,
            "home_score": _int_score(home.score),
            "away_score": _int_score(away.score),
            "status_state": status.state,
            "status_detail": status.detail or status.description,
            "is_completed": status.completed,
            # venue.resolved_* handles both top-level and nested address fields
            "venue_name": venue.resolved_name,
            "venue_city": venue.resolved_city,
            "venue_country": venue.resolved_country,
            "fetched_at": fetch_ts,
        })

    return pd.DataFrame(rows)


def parse_odds(
    events: list[EspnEvent],
    date_str: str,
    fetch_ts: datetime,
) -> pd.DataFrame:
    """
    Extract pre-match betting odds from each event's first competition.

    Odds are only present for matches where ESPN has an odds provider.
    Completed group-stage matches typically retain the pre-match odds snapshot.

    Probability conversion:
      1. Prefer `winPercentage` if ESPN provides it (already a % 0–100).
      2. Otherwise convert American moneyLine to implied probability.
      3. Normalise all three (home/draw/away) to sum to 1.0 (removes vig).
    """
    rows: list[dict] = []
    for event in events:
        if not event.competitions:
            continue

        comp = event.competitions[0]
        odds_list = comp.odds or []

        if not odds_list:
            logger.debug("Event %s has no odds data.", event.id)
            continue

        for odds_entry in odds_list:
            provider_name = (odds_entry.provider.name if odds_entry.provider else None) or "ESPN"

            # ── Moneyline extraction ──────────────────────────────────────
            # New ESPN 2026 format: moneyline.home/away/draw.close.odds (string)
            # Old ESPN format: homeTeamOdds.moneyLine / drawOdds.moneyLine / awayTeamOdds.moneyLine (float)
            if odds_entry.moneyline:
                ml = odds_entry.moneyline
                home_ml = _odds_str_to_float(
                    ml.home.close.odds if (ml.home and ml.home.close) else None
                )
                away_ml = _odds_str_to_float(
                    ml.away.close.odds if (ml.away and ml.away.close) else None
                )
                draw_ml = _odds_str_to_float(
                    ml.draw.close.odds if (ml.draw and ml.draw.close) else None
                )
                # New format has no winPercentage
                home_pct = draw_pct = away_pct = None
            else:
                # Legacy format
                home_ml = (odds_entry.homeTeamOdds.moneyLine if odds_entry.homeTeamOdds else None)
                draw_ml = (odds_entry.drawOdds.moneyLine    if odds_entry.drawOdds    else None)
                away_ml = (odds_entry.awayTeamOdds.moneyLine if odds_entry.awayTeamOdds else None)
                home_pct = (odds_entry.homeTeamOdds.winPercentage if odds_entry.homeTeamOdds else None)
                draw_pct = (odds_entry.drawOdds.winPercentage    if odds_entry.drawOdds    else None)
                away_pct = (odds_entry.awayTeamOdds.winPercentage if odds_entry.awayTeamOdds else None)

            # ── Convert to implied probability ────────────────────────────
            if home_pct is not None:
                home_implied = home_pct / 100.0
            else:
                home_implied = _moneyline_to_implied(home_ml)

            if draw_pct is not None:
                draw_implied = draw_pct / 100.0
            else:
                draw_implied = _moneyline_to_implied(draw_ml)

            if away_pct is not None:
                away_implied = away_pct / 100.0
            else:
                away_implied = _moneyline_to_implied(away_ml)

            home_norm, draw_norm, away_norm = _normalize_probs(home_implied, draw_implied, away_implied)

            rows.append({
                "event_id": event.id,
                "match_date": date_str,
                "provider_name": provider_name,
                "home_moneyline": home_ml,
                "draw_moneyline": draw_ml,
                "away_moneyline": away_ml,
                "home_implied_raw": home_implied,
                "draw_implied_raw": draw_implied,
                "away_implied_raw": away_implied,
                "home_win_prob": home_norm,
                "draw_prob": draw_norm,
                "away_win_prob": away_norm,
                "fetched_at": fetch_ts,
            })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Probability helpers
# ---------------------------------------------------------------------------


def _moneyline_to_implied(moneyline: float | None) -> float | None:
    """
    Convert American-format moneyline to implied probability.

    Negative odds (favourite, e.g. -150):  |ml| / (|ml| + 100)
    Positive odds (underdog, e.g. +250):   100  / (ml  + 100)
    Returns None if moneyline is None or zero (undefined).
    """
    if moneyline is None or moneyline == 0:
        return None
    if moneyline < 0:
        return abs(moneyline) / (abs(moneyline) + 100.0)
    return 100.0 / (moneyline + 100.0)


def _normalize_probs(
    home: float | None,
    draw: float | None,
    away: float | None,
) -> tuple[float | None, float | None, float | None]:
    """
    Normalise implied probabilities to sum to 1.0 (removes bookmaker's vig).

    Handles both 3-way (home/draw/away) and 2-way (home/away, draw=None) markets.
    Returns the original values unchanged if insufficient data is present.
    """
    if home is not None and away is not None and draw is None:
        # 2-way market (no draw offered — e.g. to-advance, halftime result)
        total = home + away
        if total <= 0:
            return None, None, None
        return home / total, None, away / total

    if home is None or draw is None or away is None:
        return home, draw, away

    total = home + draw + away
    if total <= 0:
        return None, None, None
    return home / total, draw / total, away / total


def _odds_str_to_float(s: str | None) -> float | None:
    """Parse a string American moneyline (e.g. '-135', '+400') to float."""
    if not s:
        return None
    try:
        return float(s.strip())
    except (ValueError, TypeError):
        return None


def _int_score(score_str: str | None) -> int | None:
    if score_str is None:
        return None
    try:
        return int(score_str)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Parquet writer
# ---------------------------------------------------------------------------


def _write_parquet(df: pd.DataFrame, schema: pa.Schema, path: Path) -> None:
    """Enforce schema, fill missing columns with None, write Snappy Parquet."""
    if df.empty:
        logger.info("Skipping empty DataFrame → %s", path.name)
        return

    schema_cols = [f.name for f in schema]
    missing = set(schema_cols) - set(df.columns)
    if missing:
        logger.debug("Filling %d absent columns with None: %s", len(missing), sorted(missing))
        for col in missing:
            df[col] = None

    df = df.reindex(columns=schema_cols)
    path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    pq.write_table(table, path, compression="snappy")
    logger.info("Bronze → %-55s (%d rows)", path.name, len(df))


# ---------------------------------------------------------------------------
# Date range iterator
# ---------------------------------------------------------------------------


def _date_range(start: str, end: str) -> list[str]:
    """Return YYYY-MM-DD strings from start to end (inclusive)."""
    start_dt = date.fromisoformat(start)
    end_dt = date.fromisoformat(end)
    days: list[str] = []
    current = start_dt
    while current <= end_dt:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def main(
    date_str: str | None,
    group_stage: bool,
    knockout: bool = False,
    league_slug: str = DEFAULT_LEAGUE_SLUG,
) -> None:
    """
    End-to-end ESPN batch pull.

    Modes:
      Single date    (--date YYYY-MM-DD):  fetch + write one Parquet pair.
      Group stage    (--group-stage):      iterate GROUP_STAGE_START→END,
                                           completed events only.
      Knockout stage (--knockout):         iterate KNOCKOUT_START→END,
                                           includes pre-match (scheduled)
                                           events so bracket team names are
                                           captured before matches are played.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("=== TrueScout ESPN pull | league=%s ===", league_slug)

    completed_only = True  # default: only write results we can use for scoring

    if group_stage:
        dates = _date_range(GROUP_STAGE_START, GROUP_STAGE_END)
        logger.info(
            "Group-stage sweep: %s → %s (%d dates)",
            GROUP_STAGE_START, GROUP_STAGE_END, len(dates),
        )
    elif knockout:
        dates = _date_range(KNOCKOUT_START, KNOCKOUT_END)
        completed_only = False   # include scheduled fixtures for bracket data
        logger.info(
            "Knockout sweep (R32→F): %s → %s (%d dates, includes pre-match)",
            KNOCKOUT_START, KNOCKOUT_END, len(dates),
        )
    elif date_str:
        dates = [date_str]
    else:
        raise ValueError("Provide --date, --group-stage, or --knockout.")

    total_matches = 0
    total_odds = 0

    with httpx.Client() as client:
        for idx, pull_date in enumerate(dates, start=1):
            if len(dates) > 1:
                logger.info("[%d/%d] Pulling %s …", idx, len(dates), pull_date)

            fetch_ts = datetime.now(tz=timezone.utc)

            # ── Fetch ──────────────────────────────────────────────────────
            events = fetch_scoreboard(client, pull_date, league_slug, completed_only)

            if not events:
                logger.info("  No completed events for %s — skipping Parquet write.", pull_date)
                if idx < len(dates):
                    time.sleep(REQUEST_SLEEP_S)
                continue

            # ── Parse ──────────────────────────────────────────────────────
            matches_df = parse_matches(events, pull_date, league_slug, fetch_ts)
            odds_df = parse_odds(events, pull_date, fetch_ts)

            # ── Write Bronze Parquet ───────────────────────────────────────
            _write_parquet(
                matches_df, MATCHES_SCHEMA,
                BRONZE_ESPN_MATCHES / f"matches_{pull_date}.parquet",
            )
            _write_parquet(
                odds_df, ODDS_SCHEMA,
                BRONZE_ESPN_ODDS / f"odds_{pull_date}.parquet",
            )

            total_matches += len(matches_df)
            total_odds += len(odds_df)

            if idx < len(dates):
                time.sleep(REQUEST_SLEEP_S)

    # ── Refresh DuckDB Parquet views ─────────────────────────────────────────
    try:
        with write_conn() as conn:
            refresh_parquet_views(conn)
    except Exception as exc:
        logger.error("refresh_parquet_views failed: %s", exc)

    logger.info(
        "=== ESPN pull complete: %d match rows | %d odds rows across %d dates ===",
        total_matches, total_odds, len(dates),
    )


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TrueScout — ESPN batch pull (matches + odds).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full group-stage history
  py -m etl.sources.espn_pull --group-stage

  # Knockout R32→F fixtures (includes pre-match for bracket team names)
  py -m etl.sources.espn_pull --knockout

  # Single date
  py -m etl.sources.espn_pull --date 2026-07-04
        """,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Single date to pull.",
    )
    mode_group.add_argument(
        "--group-stage",
        action="store_true",
        help=f"Pull {GROUP_STAGE_START} to {GROUP_STAGE_END} (completed only).",
    )
    mode_group.add_argument(
        "--knockout",
        action="store_true",
        help=f"Pull {KNOCKOUT_START} to {KNOCKOUT_END} (R32→F fixtures, includes pre-match).",
    )

    parser.add_argument(
        "--league",
        default=DEFAULT_LEAGUE_SLUG,
        metavar="SLUG",
        help=f"ESPN league slug (default: '{DEFAULT_LEAGUE_SLUG}').",
    )

    args = parser.parse_args()
    main(
        date_str=args.date,
        group_stage=args.group_stage,
        knockout=args.knockout,
        league_slug=args.league,
    )
