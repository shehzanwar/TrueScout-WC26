"""
etl/sources/sofascore_pull.py — Phase 1 Sofascore batch ingestion.

Fetches three data sets for a given calendar date:

  1. Scheduled events  → Bronze: data/bronze/sofascore/events/events_{date}.parquet
  2. Per-event lineups → Bronze: data/bronze/sofascore/lineups/lineups_{date}.parquet
  3. Per-event stats   → Bronze: data/bronze/sofascore/statistics/statistics_{date}.parquet

TLS spoofing
────────────
Sofascore returns 403 on raw requests (Cloudflare JA3/TLS fingerprint check).
curl_cffi impersonates a real Chrome TLS handshake, bypassing this without
any API key.  Primary domain: api.sofascore.com.  Falls back to api.sofascore.app
if the primary returns 403 or times out on a given path.

Rate limiting
─────────────
A jittered sleep of 1.5–2.5 s between every sub-request keeps us well below
Sofascore's observed rate limit (~30 req/min).  tenacity retries handle
transient 429 / 5xx responses with exponential back-off.

ID policy (Phase 1)
───────────────────
Only Sofascore integer IDs are written to Bronze Parquet.  Cross-source name→ID
reconciliation (FBref player name ↔ Sofascore player ID) is a Phase 2 task in
etl/matching/.  This script does NOT touch the DuckDB tables directly.

Run:
    py -m etl.sources.sofascore_pull --date 2026-06-28
    py -m etl.sources.sofascore_pull --date 2026-06-28 --tournament "FIFA World Cup"
    py -m etl.sources.sofascore_pull --date 2026-06-28 --no-filter  # all football
"""
import argparse
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from curl_cffi.requests import Session as CurlSession
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

_BRONZE_SS: Path = Path(settings.parquet_bronze_dir) / "sofascore"
BRONZE_SS_EVENTS: Path = _BRONZE_SS / "events"
BRONZE_SS_LINEUPS: Path = _BRONZE_SS / "lineups"
BRONZE_SS_STATS: Path = _BRONZE_SS / "statistics"
BRONZE_SS_ERRORS: Path = _BRONZE_SS / "errors"

# ---------------------------------------------------------------------------
# Request configuration
# ---------------------------------------------------------------------------

# Preferred curl_cffi impersonation target — resolved at import time against the
# installed build; falls back gracefully so the script never errors on import.
# If a BlockedError (403) persists across all targets, the next escalation is
# the `wreq` Python package (BoringSSL / JA4 fingerprinting) — swap in
# `__enter__` + `_fetch_url` only; the rest of the pipeline is unchanged.
_IMPERSONATE_PREFERRED: str = "chrome136"
_IMPERSONATE_FALLBACKS: list[str] = ["chrome131", "chrome124", "chrome120"]


def _resolve_impersonate(preferred: str) -> str:
    try:
        from curl_cffi.requests import BrowserType
        valid = {b.value for b in BrowserType}
        if preferred in valid:
            return preferred
        for fb in _IMPERSONATE_FALLBACKS:
            if fb in valid:
                logger.warning(
                    "IMPERSONATE=%r not in this curl_cffi build; using %r", preferred, fb
                )
                return fb
    except Exception:
        pass
    return preferred  # let curl_cffi raise at use-time if still wrong


IMPERSONATE: str = _resolve_impersonate(_IMPERSONATE_PREFERRED)

TIMEOUT_S: int = 30

# Jitter between calls prevents rate-limit pattern detection
REQUEST_SLEEP_MIN: float = 1.5
REQUEST_SLEEP_MAX: float = 2.5

# Sleep after hitting a 429 before tenacity's own back-off kicks in
RATE_LIMIT_PAUSE_S: float = 30.0

# WC 2026 Sofascore tournament identifiers (confirmed via DevTools on sofascore.com)
# Endpoint: /unique-tournament/{id}/season/{season_id}/events/round/{round_number}
WC_TOURNAMENT_ID: int = 16
WC_SEASON_ID: int = 58210

# These headers supplement the browser fingerprint set by curl_cffi
HEADERS: dict[str, str] = {
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

# status.type values that indicate a fully completed result
COMPLETED_STATUSES: frozenset[str] = frozenset({
    "finished",
    "afterextratime",
    "afterpenalties",
})

# Default tournament substring filter (case-insensitive)
DEFAULT_TOURNAMENT_FILTER: str = "FIFA World Cup"

# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------


class _SofascoreHTTPError(Exception):
    """Carries the HTTP status code for routing decisions."""
    def __init__(self, status_code: int, url: str, content: bytes = b""):
        self.status_code = status_code
        self.url = url
        self.content = content
        super().__init__(f"HTTP {status_code}: {url}")


class RateLimitError(_SofascoreHTTPError):
    """429 Too Many Requests — retryable with back-off."""


class ServerError(_SofascoreHTTPError):
    """5xx Server Error — retryable."""


class BlockedError(_SofascoreHTTPError):
    """403 Forbidden (Cloudflare TLS block) — try fallback domain."""


class NotFoundError(_SofascoreHTTPError):
    """404 Not Found — no data for this event/path; skip gracefully."""


# ---------------------------------------------------------------------------
# PyArrow schemas
# ---------------------------------------------------------------------------

EVENTS_SCHEMA = pa.schema([
    pa.field("event_id", pa.int64()),
    pa.field("tournament_name", pa.string()),
    pa.field("unique_tournament_id", pa.int64()),
    pa.field("unique_tournament_name", pa.string()),
    pa.field("season_id", pa.int64()),
    pa.field("round_name", pa.string()),
    pa.field("home_team_id", pa.int64()),
    pa.field("home_team_name", pa.string()),
    pa.field("away_team_id", pa.int64()),
    pa.field("away_team_name", pa.string()),
    pa.field("start_timestamp", pa.int64()),
    pa.field("match_date", pa.string()),
    pa.field("status", pa.string()),
    pa.field("home_score", pa.int64()),
    pa.field("away_score", pa.int64()),
    pa.field("home_score_et", pa.int64()),
    pa.field("away_score_et", pa.int64()),
    pa.field("home_score_penalties", pa.int64()),
    pa.field("away_score_penalties", pa.int64()),
    pa.field("went_to_extra_time", pa.bool_()),
    pa.field("went_to_penalties", pa.bool_()),
    pa.field("venue_name", pa.string()),
    pa.field("venue_city", pa.string()),
    pa.field("fetched_at", pa.timestamp("us", tz="UTC")),
])

LINEUPS_SCHEMA = pa.schema([
    pa.field("event_id", pa.int64()),
    pa.field("team_id", pa.int64()),
    pa.field("team_side", pa.string()),        # "home" | "away"
    pa.field("player_id", pa.int64()),
    pa.field("player_name", pa.string()),
    pa.field("shirt_number", pa.int64()),
    pa.field("position", pa.string()),
    pa.field("substitute", pa.bool_()),
    pa.field("minutes_played", pa.int64()),
    pa.field("goals", pa.int64()),
    pa.field("assists", pa.int64()),
    pa.field("yellow_cards", pa.int64()),
    pa.field("red_cards", pa.int64()),
    pa.field("rating", pa.float64()),          # Sofascore match rating 0–10
    pa.field("xg", pa.float64()),
    pa.field("xa", pa.float64()),
    pa.field("shots", pa.int64()),
    pa.field("shots_on_target", pa.int64()),
    pa.field("passes_completed", pa.int64()),
    pa.field("passes_attempted", pa.int64()),
    pa.field("key_passes", pa.int64()),
    pa.field("tackles", pa.int64()),
    pa.field("interceptions", pa.int64()),
    pa.field("clearances", pa.int64()),
    pa.field("saves", pa.int64()),             # GK only; NULL for outfield
    pa.field("fetched_at", pa.timestamp("us", tz="UTC")),
])

STATISTICS_SCHEMA = pa.schema([
    # Team-level match stats in long/tidy format (one row per metric per period)
    pa.field("event_id", pa.int64()),
    pa.field("period", pa.string()),           # "ALL" | "1ST" | "2ND"
    pa.field("group_name", pa.string()),       # "Match overview", "Shots", …
    pa.field("stat_name", pa.string()),        # "Ball possession", "Expected goals", …
    pa.field("home_value", pa.string()),       # raw string as returned
    pa.field("away_value", pa.string()),
    pa.field("fetched_at", pa.timestamp("us", tz="UTC")),
])

# ---------------------------------------------------------------------------
# Error payload save helper
# ---------------------------------------------------------------------------


def _save_error_payload(path: str, content: bytes, date_str: str) -> None:
    """Persist a raw error response or debug blob to the errors/ directory."""
    BRONZE_SS_ERRORS.mkdir(parents=True, exist_ok=True)
    safe_name = path.strip("/").replace("/", "_")
    ts = datetime.now(tz=timezone.utc).strftime("%H%M%S")
    fname = BRONZE_SS_ERRORS / f"{date_str}_{safe_name}_{ts}.bin"
    fname.write_bytes(content)
    logger.warning("Error payload saved → %s", fname.name)


# ---------------------------------------------------------------------------
# HTTP layer — module-level so tenacity can decorate cleanly
# ---------------------------------------------------------------------------


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=8, max=90),
    retry=retry_if_exception_type((RateLimitError, ServerError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _fetch_url(session: CurlSession, url: str) -> dict:
    """
    GET url using the curl_cffi session and return parsed JSON.

    Raises:
        RateLimitError   — 429; tenacity will retry
        ServerError      — 5xx; tenacity will retry
        BlockedError     — 403; caller should try the fallback domain
        NotFoundError    — 404; caller should skip this path gracefully
    """
    resp = session.get(url, headers=HEADERS, timeout=TIMEOUT_S)

    if resp.status_code == 429:
        logger.warning("429 rate-limited — pausing %.0fs before tenacity back-off", RATE_LIMIT_PAUSE_S)
        time.sleep(RATE_LIMIT_PAUSE_S)
        raise RateLimitError(429, url, resp.content)

    if resp.status_code == 403:
        raise BlockedError(403, url, resp.content)

    if resp.status_code == 404:
        raise NotFoundError(404, url, resp.content)

    if resp.status_code >= 500:
        raise ServerError(resp.status_code, url, resp.content)

    resp.raise_for_status()

    try:
        return resp.json()
    except Exception as exc:
        raise ServerError(0, url, resp.content) from exc  # treat parse failure as retryable


# ---------------------------------------------------------------------------
# Sofascore HTTP client
# ---------------------------------------------------------------------------


class SofascoreClient:
    """
    Context-managed curl_cffi session with primary → fallback domain routing.

    Usage:
        with SofascoreClient() as client:
            data = client.get("/sport/football/scheduled-events/2026-06-28", date_str)
    """

    def __init__(self, impersonate: str = IMPERSONATE) -> None:
        self._impersonate = impersonate
        self._session: CurlSession | None = None

    def __enter__(self) -> "SofascoreClient":
        self._session = CurlSession(impersonate=self._impersonate)
        logger.debug("curl_cffi session opened (impersonate=%s)", self._impersonate)
        return self

    def __exit__(self, *_args: object) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def get(self, path: str, date_str: str = "") -> dict | None:
        """
        Try the primary Sofascore domain, fall back to the secondary on 403/404/error.

        Cloudflare sometimes returns a fake 404 instead of 403 to defeat
        BlockedError routing, so we always try the fallback rather than
        exiting on the first domain's 404.

        Returns:
            Parsed JSON dict on success.
            None after all domains are exhausted (404 / 403 / error on all).
        """
        assert self._session is not None, "Use SofascoreClient as a context manager"

        domains = [settings.sofascore_base_url, settings.sofascore_fallback_url]
        last_error_content: bytes = b""
        all_404 = True  # track whether every domain returned 404

        for base_url in domains:
            url = f"{base_url}{path}"
            try:
                return _fetch_url(self._session, url)
            except BlockedError as exc:
                all_404 = False
                logger.warning("403 blocked at %s — trying fallback domain", base_url)
                last_error_content = exc.content
                continue
            except NotFoundError as exc:
                # Don't bail immediately: Cloudflare fakes 404s to defeat BlockedError routing.
                # Save the body so we can inspect if it's a CF challenge vs a real 404.
                logger.warning("404 at %s%s — trying next domain", base_url, path)
                if exc.content:
                    _save_error_payload(path + f"_{base_url.split('//')[1].split('/')[0]}", exc.content, date_str)
                continue
            except Exception as exc:
                all_404 = False
                logger.error("Permanent failure at %s: %s", url, exc)
                content = getattr(exc, "content", str(exc).encode())
                last_error_content = content or str(exc).encode()
                _save_error_payload(path, last_error_content, date_str)
                continue

        if all_404:
            logger.warning("All domains returned 404 for path: %s (no data / IP blocked)", path)
        else:
            _save_error_payload(path, last_error_content or b"all_domains_failed", date_str)
            logger.error("All Sofascore domains failed for path: %s", path)
        return None


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


def fetch_rounds(client: SofascoreClient) -> list[int]:
    """
    Return all available round numbers for WC 2026.

    Endpoint: /unique-tournament/{id}/season/{season_id}/rounds
    Response:  {"rounds": [{"round": 1, "name": "1"}, ...], "currentRound": {...}}
    """
    path = f"/unique-tournament/{WC_TOURNAMENT_ID}/season/{WC_SEASON_ID}/rounds"
    data = client.get(path, "rounds")
    if data is None:
        logger.error("Could not fetch rounds list.")
        return []
    rounds_raw = data.get("rounds", [])
    available = sorted({r["round"] for r in rounds_raw if isinstance(r.get("round"), int)})
    logger.info("Available rounds: %s", available)
    return available


def fetch_events_by_date(
    client: SofascoreClient,
    date_str: str,
) -> list[dict]:
    """
    Fetch completed WC 2026 events for a calendar date via the scheduled-events endpoint.

    Endpoint: /sport/football/scheduled-events/{date_str}
    Filters to: unique_tournament_id == WC_TOURNAMENT_ID, completed status.

    Use this for knockout rounds (R32, R16, …) which return 404 from /events/round/{N}.
    """
    path = f"/sport/football/scheduled-events/{date_str}"
    data = client.get(path, f"date-{date_str}")
    if data is None:
        logger.error("No response for date %s.", date_str)
        return []

    events: list[dict] = data.get("events", []) or []
    wc_completed = [
        e for e in events
        if (
            ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id") == WC_TOURNAMENT_ID
            and (e.get("status") or {}).get("type") in COMPLETED_STATUSES
        )
    ]
    logger.info(
        "Date %s: %d total events / %d WC completed",
        date_str, len(events), len(wc_completed),
    )
    return wc_completed


def fetch_cuptrees_events(client: SofascoreClient) -> list[tuple[str, list[int]]]:
    """
    Fetch the WC 2026 knockout bracket via the cuptrees endpoint and return
    (round_name, [event_id, ...]) for every finished round.

    Endpoint: /unique-tournament/{id}/season/{season_id}/cuptrees
    This works where /events/round/{N} returns 404 for knockout rounds.
    """
    path = f"/unique-tournament/{WC_TOURNAMENT_ID}/season/{WC_SEASON_ID}/cuptrees"
    data = client.get(path, "cuptrees")
    if not data:
        return []

    trees = data.get("cupTrees") or []
    if not trees:
        logger.warning("cuptrees response had no cupTrees array.")
        return []

    result: list[tuple[str, list[int]]] = []
    for rnd in trees[0].get("rounds") or []:
        round_name: str = rnd.get("description", "Knockout")
        finished_ids: list[int] = []
        for block in rnd.get("blocks") or []:
            for raw_ev in block.get("events") or []:
                eid = raw_ev if isinstance(raw_ev, int) else (raw_ev.get("id") if isinstance(raw_ev, dict) else None)
                if eid and block.get("finished"):
                    finished_ids.append(int(eid))
        if finished_ids:
            logger.info("cuptrees: %s — %d finished events", round_name, len(finished_ids))
            result.append((round_name, finished_ids))

    return result


def fetch_event_metadata(client: SofascoreClient, event_id: int) -> dict | None:
    """
    Fetch full event metadata for a single match by ID.

    Endpoint: /event/{event_id}
    Returns the event dict suitable for passing to parse_events().
    """
    data = client.get(f"/event/{event_id}", "event")
    if not data:
        return None
    return data.get("event")


def pull_round_events(
    client: SofascoreClient,
    round_number: int,
) -> list[dict]:
    """
    Fetch all completed WC 2026 events for `round_number`.

    Endpoint: /unique-tournament/{id}/season/{season_id}/events/round/{round_number}
    Returns completed events only (status.type in COMPLETED_STATUSES).
    """
    path = (
        f"/unique-tournament/{WC_TOURNAMENT_ID}"
        f"/season/{WC_SEASON_ID}"
        f"/events/round/{round_number}"
    )
    data = client.get(path, f"round-{round_number}")
    if data is None:
        logger.error("No response for round %d.", round_number)
        return []

    events: list[dict] = data.get("events", []) or []
    completed = [
        e for e in events
        if (e.get("status") or {}).get("type") in COMPLETED_STATUSES
    ]
    logger.info("Round %d: %d total / %d completed", round_number, len(events), len(completed))
    return completed


# ---------------------------------------------------------------------------
# JSON parsers — raw Sofascore dicts → flat DataFrames
# ---------------------------------------------------------------------------


def parse_events(
    raw_events: list[dict],
    date_str: str,
    fetch_ts: datetime,
) -> pd.DataFrame:
    """
    Flatten Sofascore event objects into a DataFrame matching EVENTS_SCHEMA.

    Score breakdown:
      homeScore.current      = final score (including ET/penalties if applicable)
      homeScore.normaltime   = 90-min score (preferred); falls back to .current
      homeScore.extra1/2     = goals scored in extra-time periods
      homeScore.penalties    = penalty shootout tally
    """
    rows: list[dict] = []
    for e in raw_events:
        hs = e.get("homeScore") or {}
        as_ = e.get("awayScore") or {}
        status_type: str = (e.get("status") or {}).get("type", "")
        venue: dict = e.get("venue") or {}
        tournament: dict = e.get("tournament") or {}
        ut: dict = tournament.get("uniqueTournament") or {}
        season: dict = e.get("season") or {}
        round_info: dict = e.get("roundInfo") or {}

        went_to_et = status_type in ("afterextratime", "afterpenalties")
        went_to_penalties = status_type == "afterpenalties"

        # Extra-time goals: period3 + period4 are the ET halves on Sofascore
        home_et = (hs.get("period3") or 0) + (hs.get("period4") or 0)
        away_et = (as_.get("period3") or 0) + (as_.get("period4") or 0)

        # 90-min score: normaltime is explicit; fall back to current if absent
        home_90 = hs.get("normaltime", hs.get("current", 0))
        away_90 = as_.get("normaltime", as_.get("current", 0))

        rows.append({
            "event_id": int(e["id"]),
            "tournament_name": tournament.get("name"),
            "unique_tournament_id": _int(ut.get("id")),
            "unique_tournament_name": ut.get("name"),
            "season_id": _int(season.get("id")),
            "round_name": round_info.get("name") or str(round_info.get("round", "")),
            "home_team_id": _int((e.get("homeTeam") or {}).get("id")),
            "home_team_name": (e.get("homeTeam") or {}).get("name"),
            "away_team_id": _int((e.get("awayTeam") or {}).get("id")),
            "away_team_name": (e.get("awayTeam") or {}).get("name"),
            "start_timestamp": _int(e.get("startTimestamp")),
            "match_date": (
                datetime.fromtimestamp(int(e["startTimestamp"]), tz=timezone.utc).strftime("%Y-%m-%d")
                if e.get("startTimestamp") else date_str
            ),
            "status": status_type,
            "home_score": _int(home_90),
            "away_score": _int(away_90),
            "home_score_et": _int(home_et) if went_to_et else None,
            "away_score_et": _int(away_et) if went_to_et else None,
            "home_score_penalties": _int(hs.get("penalties")) if went_to_penalties else None,
            "away_score_penalties": _int(as_.get("penalties")) if went_to_penalties else None,
            "went_to_extra_time": went_to_et,
            "went_to_penalties": went_to_penalties,
            "venue_name": (venue.get("stadium") or {}).get("name"),
            "venue_city": (venue.get("city") or {}).get("name"),
            "fetched_at": fetch_ts,
        })

    return pd.DataFrame(rows)


def parse_lineups(
    event_id: int,
    raw: dict,
    home_team_id: int | None,
    away_team_id: int | None,
    fetch_ts: datetime,
) -> pd.DataFrame:
    """
    Flatten Sofascore lineups response into a DataFrame matching LINEUPS_SCHEMA.

    Each player record includes match statistics if Sofascore has computed them
    (usually available within minutes of full-time).

    Sofascore statistics field mapping:
      minutesPlayed       → minutes_played
      goals               → goals
      goalAssist          → assists
      yellowCards         → yellow_cards
      redCards            → red_cards
      rating              → rating  (0–10, Sofascore proprietary)
      expectedGoals       → xg
      expectedAssists     → xa
      onTargetScoringAttempt → shots_on_target
      shotOffTarget       → (shots - shots_on_target component)
      accuratePass        → passes_completed
      totalPass           → passes_attempted
      keyPass             → key_passes
      totalTackle         → tackles
      interceptionWon     → interceptions
      totalClearance      → clearances  (fallback: clearanceOffLine)
      saves               → saves  (GK only)
    """
    fallback_ids = {"home": home_team_id, "away": away_team_id}
    rows: list[dict] = []

    for side in ("home", "away"):
        side_data: dict = raw.get(side) or {}
        players: list[dict] = side_data.get("players") or []

        # Team ID: from each player entry's teamId, or fall back to event data
        side_team_id = fallback_ids.get(side)

        for p in players:
            player: dict = p.get("player") or {}
            stats: dict = p.get("statistics") or {}

            player_id = _int(player.get("id"))
            if player_id is None:
                continue

            team_id = _int(p.get("teamId")) or side_team_id

            on_target = _int(stats.get("onTargetScoringAttempt"), 0)
            off_target = _int(stats.get("shotOffTarget"), 0)
            total_shots = (on_target or 0) + (off_target or 0) or None

            clearances = _int(stats.get("totalClearance")) or _int(stats.get("clearanceOffLine"))

            rows.append({
                "event_id": event_id,
                "team_id": team_id,
                "team_side": side,
                "player_id": player_id,
                "player_name": player.get("name"),
                "shirt_number": _int(p.get("jerseyNumber")) or _int(p.get("shirtNumber")),
                "position": p.get("position") or player.get("position"),
                "substitute": bool(p.get("substitute", False)),
                "minutes_played": _int(stats.get("minutesPlayed")),
                "goals": _int(stats.get("goals"), 0),
                "assists": _int(stats.get("goalAssist"), 0),
                "yellow_cards": _int(stats.get("yellowCards"), 0),
                "red_cards": _int(stats.get("redCards"), 0),
                "rating": _float(stats.get("rating")),
                "xg": _float(stats.get("expectedGoals")),
                "xa": _float(stats.get("expectedAssists")),
                "shots": _int(total_shots),
                "shots_on_target": _int(on_target),
                "passes_completed": _int(stats.get("accuratePass")),
                "passes_attempted": _int(stats.get("totalPass")),
                "key_passes": _int(stats.get("keyPass")),
                "tackles": _int(stats.get("totalTackle")),
                "interceptions": _int(stats.get("interceptionWon")),
                "clearances": clearances,
                "saves": _int(stats.get("saves")),
                "fetched_at": fetch_ts,
            })

    return pd.DataFrame(rows)


def parse_statistics(
    event_id: int,
    raw: dict,
    fetch_ts: datetime,
) -> pd.DataFrame:
    """
    Flatten Sofascore match statistics into long/tidy format.

    The statistics endpoint returns team-level aggregates (possession, shots,
    xG, fouls, etc.) broken out by period ("ALL", "1ST", "2ND").
    Long format is chosen because the set of stat names varies between
    match types and Sofascore API versions.
    """
    rows: list[dict] = []
    for period_block in raw.get("statistics") or []:
        period: str = period_block.get("period", "ALL")
        for group in period_block.get("groups") or []:
            group_name: str = group.get("groupName", "")
            for item in group.get("statisticsItems") or []:
                rows.append({
                    "event_id": event_id,
                    "period": period,
                    "group_name": group_name,
                    "stat_name": item.get("name"),
                    "home_value": str(item.get("home", "")),
                    "away_value": str(item.get("away", "")),
                    "fetched_at": fetch_ts,
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Type coercion helpers (return None on falsy / non-numeric values)
# ---------------------------------------------------------------------------


def _int(val: object, default: int | None = None) -> int | None:
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _float(val: object) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Parquet writer
# ---------------------------------------------------------------------------


def _write_parquet(df: pd.DataFrame, schema: pa.Schema, path: Path) -> None:
    """Enforce schema, fill missing columns, write Snappy-compressed Parquet."""
    if df.empty:
        logger.warning("Skipping empty DataFrame → %s", path.name)
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
# Main orchestrator
# ---------------------------------------------------------------------------


def diagnose() -> None:
    """
    Hit the WC 2026 rounds endpoint on every domain and print:
      - HTTP status code
      - Content-Type header
      - First 300 bytes of body

    Expected: HTTP 200, application/json, body starts with '{"rounds":['
    Saves the full body to errors/ for deeper inspection.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    path = f"/unique-tournament/{WC_TOURNAMENT_ID}/season/{WC_SEASON_ID}/rounds"
    domains = [settings.sofascore_base_url, settings.sofascore_fallback_url]
    ctx = "diagnose"

    for base_url in domains:
        url = f"{base_url}{path}"
        print(f"\n── {url}")
        try:
            with CurlSession(impersonate=IMPERSONATE) as s:
                resp = s.get(url, headers=HEADERS, timeout=TIMEOUT_S)
            ct = resp.headers.get("content-type", "N/A")
            print(f"  Status:       {resp.status_code}")
            print(f"  Content-Type: {ct}")
            preview = resp.content[:300]
            try:
                print(f"  Body (300B):  {preview.decode('utf-8', errors='replace')}")
            except Exception:
                print(f"  Body (300B):  {preview!r}")
            host_slug = base_url.split("//")[1].split("/")[0].replace(".", "_")
            _save_error_payload(f"{path}_diagnose_{host_slug}", resp.content, ctx)
        except Exception as exc:
            print(f"  ERROR: {exc}")

    print(
        "\nExpected healthy response: HTTP 200, application/json, "
        "body starts with '{\"rounds\":['  or '{\"currentRound\":'"
    )


def main(
    round_numbers: list[int],
    all_rounds: bool,
    dates: list[str] | None = None,
    knockout: bool = False,
) -> None:
    """
    End-to-end Sofascore batch pull.

    Modes:
      --round N [N …]   Pull specific round(s) via /events/round/{N}.
      --all-rounds      Fetch the rounds list then sweep every round.
      --date DATE …     Pull events for calendar date(s) via the scheduled-events
                        endpoint (returns 404 for most dates — prefer --knockout).
      --knockout        Fetch the cuptrees bracket, extract all finished R32/R16/QF/SF/F
                        event IDs, then pull lineups + stats per event.

    Parquet files are named by round (events_round_001.parquet …) or by
    knockout round slug (events_kt_round-of-32.parquet …) so re-runs are idempotent.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info(
        "=== TrueScout Sofascore pull | tournament=%d season=%d ===",
        WC_TOURNAMENT_ID, WC_SEASON_ID,
    )

    total_events = total_players = total_stat_rows = 0

    with SofascoreClient() as client:
        # ── Knockout bracket mode (cuptrees) ────────────────────────────────
        if knockout:
            kt_rounds = fetch_cuptrees_events(client)
            if not kt_rounds:
                logger.error("cuptrees returned no finished rounds — aborting.")
                return

            for round_name, event_ids in kt_rounds:
                round_slug = round_name.lower().replace(" ", "-").replace("/", "-")
                logger.info("── Knockout: %s (%d events) ──", round_name, len(event_ids))
                fetch_ts = datetime.now(tz=timezone.utc)

                raw_events: list[dict] = []
                all_lineups: list[pd.DataFrame] = []
                all_statistics: list[pd.DataFrame] = []

                for idx, event_id in enumerate(event_ids, start=1):
                    logger.info("  [%d/%d] event_id=%d", idx, len(event_ids), event_id)

                    # Full event metadata (for events parquet)
                    _sleep()
                    ev_meta = fetch_event_metadata(client, event_id)
                    if ev_meta:
                        raw_events.append(ev_meta)
                        home_team_id = _int((ev_meta.get("homeTeam") or {}).get("id"))
                        away_team_id = _int((ev_meta.get("awayTeam") or {}).get("id"))
                        label = (
                            f"{(ev_meta.get('homeTeam') or {}).get('name', '?')} vs "
                            f"{(ev_meta.get('awayTeam') or {}).get('name', '?')}"
                        )
                        logger.info("    %s", label)
                    else:
                        home_team_id = away_team_id = None

                    _sleep()
                    raw_lineups = client.get(f"/event/{event_id}/lineups", f"kt-{round_slug}")
                    if raw_lineups:
                        ldf = parse_lineups(event_id, raw_lineups, home_team_id, away_team_id, fetch_ts)
                        if not ldf.empty:
                            logger.info("    lineups: %d players", len(ldf))
                            all_lineups.append(ldf)

                    _sleep()
                    raw_stats = client.get(f"/event/{event_id}/statistics", f"kt-{round_slug}")
                    if raw_stats:
                        sdf = parse_statistics(event_id, raw_stats, fetch_ts)
                        if not sdf.empty:
                            logger.info("    statistics: %d metric rows", len(sdf))
                            all_statistics.append(sdf)

                if raw_events:
                    events_df = parse_events(raw_events, round_slug, fetch_ts)
                    _write_parquet(
                        events_df, EVENTS_SCHEMA,
                        BRONZE_SS_EVENTS / f"events_kt_{round_slug}.parquet",
                    )
                if all_lineups:
                    _write_parquet(
                        pd.concat(all_lineups, ignore_index=True), LINEUPS_SCHEMA,
                        BRONZE_SS_LINEUPS / f"lineups_kt_{round_slug}.parquet",
                    )
                if all_statistics:
                    _write_parquet(
                        pd.concat(all_statistics, ignore_index=True), STATISTICS_SCHEMA,
                        BRONZE_SS_STATS / f"statistics_kt_{round_slug}.parquet",
                    )

                total_events += len(raw_events)
                total_players += sum(len(df) for df in all_lineups)
                total_stat_rows += sum(len(df) for df in all_statistics)

            try:
                with write_conn() as conn:
                    refresh_parquet_views(conn)
            except Exception as exc:
                logger.error("refresh_parquet_views failed: %s", exc)

            logger.info(
                "=== Sofascore knockout pull complete: %d events | %d player rows | %d stat rows ===",
                total_events, total_players, total_stat_rows,
            )
            return

        # ── Date-based mode (knockout rounds) ───────────────────────────────
        if dates:
            for date_str in dates:
                logger.info("── Date %s ──", date_str)
                fetch_ts = datetime.now(tz=timezone.utc)

                raw_events = fetch_events_by_date(client, date_str)
                if not raw_events:
                    logger.info("  No completed WC events for %s — skipping.", date_str)
                    continue

                events_df = parse_events(raw_events, date_str, fetch_ts)
                _write_parquet(
                    events_df, EVENTS_SCHEMA,
                    BRONZE_SS_EVENTS / f"events_date_{date_str}.parquet",
                )

                all_lineups: list[pd.DataFrame] = []
                all_statistics: list[pd.DataFrame] = []

                for idx, event in enumerate(raw_events, start=1):
                    event_id: int = int(event["id"])
                    home_team_id = _int((event.get("homeTeam") or {}).get("id"))
                    away_team_id = _int((event.get("awayTeam") or {}).get("id"))
                    label = (
                        f"{(event.get('homeTeam') or {}).get('name', '?')} vs "
                        f"{(event.get('awayTeam') or {}).get('name', '?')}"
                    )
                    logger.info("  [%d/%d] Event %d — %s", idx, len(raw_events), event_id, label)

                    _sleep()
                    raw_lineups = client.get(f"/event/{event_id}/lineups", f"date-{date_str}")
                    if raw_lineups:
                        ldf = parse_lineups(event_id, raw_lineups, home_team_id, away_team_id, fetch_ts)
                        if not ldf.empty:
                            logger.info("    lineups: %d players", len(ldf))
                            all_lineups.append(ldf)

                    _sleep()
                    raw_stats = client.get(f"/event/{event_id}/statistics", f"date-{date_str}")
                    if raw_stats:
                        sdf = parse_statistics(event_id, raw_stats, fetch_ts)
                        if not sdf.empty:
                            logger.info("    statistics: %d metric rows", len(sdf))
                            all_statistics.append(sdf)

                if all_lineups:
                    _write_parquet(
                        pd.concat(all_lineups, ignore_index=True), LINEUPS_SCHEMA,
                        BRONZE_SS_LINEUPS / f"lineups_date_{date_str}.parquet",
                    )
                if all_statistics:
                    _write_parquet(
                        pd.concat(all_statistics, ignore_index=True), STATISTICS_SCHEMA,
                        BRONZE_SS_STATS / f"statistics_date_{date_str}.parquet",
                    )

                total_events += len(raw_events)
                total_players += sum(len(df) for df in all_lineups)
                total_stat_rows += sum(len(df) for df in all_statistics)

            # Refresh views once after all date pulls
            try:
                with write_conn() as conn:
                    refresh_parquet_views(conn)
            except Exception as exc:
                logger.error("refresh_parquet_views failed: %s", exc)

            logger.info(
                "=== Sofascore date pull complete: %d events | %d player rows | %d stat rows ===",
                total_events, total_players, total_stat_rows,
            )
            return

        # ── Round-based mode (group stage) ──────────────────────────────────
        if all_rounds:
            rounds_to_pull = fetch_rounds(client)
            if not rounds_to_pull:
                logger.error("Could not fetch rounds list — aborting.")
                return
            logger.info("Sweeping %d rounds.", len(rounds_to_pull))
        else:
            rounds_to_pull = sorted(set(round_numbers))

        for round_num in rounds_to_pull:
            logger.info("── Round %d ──", round_num)
            fetch_ts = datetime.now(tz=timezone.utc)

            raw_events = pull_round_events(client, round_num)
            if not raw_events:
                logger.info("  No completed events for round %d — skipping.", round_num)
                continue

            # ── Events Parquet ───────────────────────────────────────────────
            events_df = parse_events(raw_events, f"round-{round_num}", fetch_ts)
            _write_parquet(
                events_df, EVENTS_SCHEMA,
                BRONZE_SS_EVENTS / f"events_round_{round_num:03d}.parquet",
            )

            # ── Per-event lineups + statistics ───────────────────────────────
            all_lineups: list[pd.DataFrame] = []
            all_statistics: list[pd.DataFrame] = []

            for idx, event in enumerate(raw_events, start=1):
                event_id: int = int(event["id"])
                home_team_id = _int((event.get("homeTeam") or {}).get("id"))
                away_team_id = _int((event.get("awayTeam") or {}).get("id"))
                label = (
                    f"{(event.get('homeTeam') or {}).get('name', '?')} vs "
                    f"{(event.get('awayTeam') or {}).get('name', '?')}"
                )
                logger.info("  [%d/%d] Event %d — %s", idx, len(raw_events), event_id, label)

                _sleep()
                raw_lineups = client.get(f"/event/{event_id}/lineups", f"round-{round_num}")
                if raw_lineups:
                    ldf = parse_lineups(event_id, raw_lineups, home_team_id, away_team_id, fetch_ts)
                    if not ldf.empty:
                        logger.info("    lineups: %d players", len(ldf))
                        all_lineups.append(ldf)
                    else:
                        logger.warning("    lineups: 0 players parsed for event %d", event_id)
                else:
                    logger.warning("    lineups: no data for event %d", event_id)

                _sleep()
                raw_stats = client.get(f"/event/{event_id}/statistics", f"round-{round_num}")
                if raw_stats:
                    sdf = parse_statistics(event_id, raw_stats, fetch_ts)
                    if not sdf.empty:
                        logger.info("    statistics: %d metric rows", len(sdf))
                        all_statistics.append(sdf)
                    else:
                        logger.warning("    statistics: 0 rows for event %d", event_id)
                else:
                    logger.warning("    statistics: no data for event %d", event_id)

            # ── Write combined Parquets for this round ───────────────────────
            if all_lineups:
                _write_parquet(
                    pd.concat(all_lineups, ignore_index=True), LINEUPS_SCHEMA,
                    BRONZE_SS_LINEUPS / f"lineups_round_{round_num:03d}.parquet",
                )
            else:
                logger.warning("  No lineup data for round %d.", round_num)

            if all_statistics:
                _write_parquet(
                    pd.concat(all_statistics, ignore_index=True), STATISTICS_SCHEMA,
                    BRONZE_SS_STATS / f"statistics_round_{round_num:03d}.parquet",
                )
            else:
                logger.warning("  No statistics data for round %d.", round_num)

            total_events += len(raw_events)
            total_players += sum(len(df) for df in all_lineups)
            total_stat_rows += sum(len(df) for df in all_statistics)

    # ── Refresh DuckDB Parquet views ─────────────────────────────────────────
    try:
        with write_conn() as conn:
            refresh_parquet_views(conn)
    except Exception as exc:
        logger.error("refresh_parquet_views failed: %s", exc)

    logger.info(
        "=== Sofascore pull complete: %d events | %d player rows | %d stat rows ===",
        total_events, total_players, total_stat_rows,
    )


def _sleep() -> None:
    """Jittered inter-request pause — avoids rate-limit pattern detection."""
    delay = random.uniform(REQUEST_SLEEP_MIN, REQUEST_SLEEP_MAX)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            f"TrueScout — Sofascore batch pull for WC 2026 "
            f"(tournament={WC_TOURNAMENT_ID}, season={WC_SEASON_ID})."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify connectivity before the first real pull
  python -m etl.sources.sofascore_pull --diagnose

  # Pull a single round
  python -m etl.sources.sofascore_pull --round 1

  # Pull multiple rounds
  python -m etl.sources.sofascore_pull --round 1 --round 2 --round 3

  # Sweep every available round (group stage)
  python -m etl.sources.sofascore_pull --all-rounds

  # Pull all finished knockout rounds (R32, R16, QF, SF, F) via the bracket tree
  python -m etl.sources.sofascore_pull --knockout
        """,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--round",
        dest="rounds",
        type=int,
        action="append",
        metavar="N",
        help="Round number to pull (repeatable: --round 1 --round 2).",
    )
    mode_group.add_argument(
        "--all-rounds",
        action="store_true",
        help="Fetch the rounds list then sweep every available round.",
    )
    mode_group.add_argument(
        "--date",
        dest="dates",
        action="append",
        metavar="YYYY-MM-DD",
        help=(
            "Pull WC events for a calendar date via the scheduled-events endpoint "
            "(repeatable: --date 2026-06-28 --date 2026-06-29). "
            "NOTE: this endpoint 404s — use --knockout instead for knockout rounds."
        ),
    )
    mode_group.add_argument(
        "--knockout",
        action="store_true",
        help=(
            "Fetch the cuptrees bracket to get all finished knockout event IDs "
            "(R32/R16/QF/SF/F), then pull lineups and statistics per event. "
            "Use this instead of --all-rounds for knockout rounds."
        ),
    )
    mode_group.add_argument(
        "--diagnose",
        action="store_true",
        help=(
            "Hit the rounds endpoint on each domain and print status/body "
            "to confirm connectivity before a real pull."
        ),
    )

    args = parser.parse_args()

    if args.diagnose:
        diagnose()
        return

    main(
        round_numbers=args.rounds or [],
        all_rounds=args.all_rounds,
        dates=args.dates or None,
        knockout=args.knockout,
    )


if __name__ == "__main__":
    _cli()
