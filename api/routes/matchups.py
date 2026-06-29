"""
GET /api/v1/matchups?round=R32

Returns scheduled knockout fixtures with:
  - Team names, abbreviations, scores (if completed)
  - Market advance probability (vig-removed ESPN 3-way odds collapsed to 2-way)
  - Model advance probability sourced from the simulations table
    (for R32: P(home advances) = simulations[R16].advance_prob)

Round query param maps:
    R32 → "Round of 32"   R16 → "Round of 16"
    QF  → "Quarterfinal"  SF  → "Semifinal"    F → "Final"

Market probability note
-----------------------
ESPN offers 3-way 90-min W/D/L odds.  For knockout fixtures these are
collapsed to a 2-way "to advance" probability using:
    P(home advances) = P(H) + P(D) * 0.5
We use 0.5 for the ET/pens bias here (neutral, no team-strength info in
this endpoint) rather than the model-biased 0.55/0.45 from brier_tracker.
The matchups display is informational, not a graded prediction.
"""
import logging
from pathlib import Path

import duckdb
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.deps import get_db
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/matchups", tags=["matchups"])

# ---------------------------------------------------------------------------
# Round name mapping
# ---------------------------------------------------------------------------

_ROUND_MAP: dict[str, str] = {
    "R32": "Round of 32",
    "R16": "Round of 16",
    "QF":  "Quarterfinal",
    "SF":  "Semifinal",
    "F":   "Final",
}

# Round following the requested one — used to pull P(team advances past this round)
# from the simulations table
_NEXT_ROUND: dict[str, str] = {
    "R32": "R16",
    "R16": "QF",
    "QF":  "SF",
    "SF":  "F",
    "F":   "W",
}

# Team name aliases (ESPN displayName → canonical simulations.team_id)
_NAME_ALIASES: dict[str, str] = {
    "Bosnia-Herzegovina":           "Bosnia & Herzegovina",
    "Bosnia and Herzegovina":       "Bosnia & Herzegovina",
    "Cabo Verde":                   "Cape Verde",
    "Côte d'Ivoire":                "Ivory Coast",
    "Cote d'Ivoire":                "Ivory Coast",
    "DR Congo":                     "Congo DR",
    "USA":                          "United States",
}


def _norm(name: str | None) -> str | None:
    if name is None:
        return None
    return _NAME_ALIASES.get(name, name)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MatchupTeam(BaseModel):
    name:               str
    abbrev:             str | None
    score:              int | None
    model_advance_prob: float | None   # P(this team advances past this round)
    market_advance_prob:float | None   # vig-removed ESPN 2-way advance prob


class Matchup(BaseModel):
    event_id:    str
    match_date:  str
    round:       str           # canonical ESPN round_name
    is_completed:bool
    home:        MatchupTeam
    away:        MatchupTeam


class MatchupsResponse(BaseModel):
    round_code:  str           # e.g. "R32"
    round_name:  str           # e.g. "Round of 32"
    n_matches:   int
    matches:     list[Matchup]


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def _fixtures_sql(matches_glob: str, odds_glob: str) -> str:
    return f"""
    SELECT
        m.event_id,
        m.match_date,
        m.round_name,
        m.home_team_name,
        m.home_team_abbrev,
        m.away_team_name,
        m.away_team_abbrev,
        m.home_score,
        m.away_score,
        m.is_completed,
        -- vig-removed 3-way 90-min probabilities
        o.home_win_prob,
        o.draw_prob,
        o.away_win_prob
    FROM read_parquet('{matches_glob}', union_by_name=true) m
    LEFT JOIN read_parquet('{odds_glob}', union_by_name=true) o
        ON m.event_id = o.event_id
    WHERE m.round_name = $1
    ORDER BY m.match_date, CAST(m.event_id AS BIGINT)
    """


_SIM_SQL = """
SELECT team_id, advance_prob
FROM simulations
WHERE round = $1
  AND run_date = (SELECT MAX(run_date) FROM simulations)
"""


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/", response_model=MatchupsResponse)
def get_matchups(
    round_param: str = Query(default="R32", alias="round", description="Round code: R32 | R16 | QF | SF | F"),
    db: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MatchupsResponse:
    """
    Scheduled knockout fixtures for the requested round with model + market probabilities.

    Model advance probabilities are sourced from the most recent Monte Carlo run.
    Market probabilities are derived from ESPN pre-match 3-way odds collapsed to 2-way.
    """
    round_code = round_param.upper()
    round_name = _ROUND_MAP.get(round_code)
    if round_name is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"Invalid round '{round}'. Use one of: {list(_ROUND_MAP)}",
        )

    bronze       = Path(settings.parquet_bronze_dir)
    matches_glob = (bronze / "espn" / "matches" / "*.parquet").as_posix()
    odds_glob    = (bronze / "espn" / "odds"    / "*.parquet").as_posix()

    # ── Fixtures + odds ────────────────────────────────────────────────────
    fixture_rows = db.execute(
        _fixtures_sql(matches_glob, odds_glob), [round_name]
    ).fetchall()

    if not fixture_rows:
        return MatchupsResponse(
            round_code=round_code, round_name=round_name, n_matches=0, matches=[]
        )

    # ── Simulation advance probabilities ──────────────────────────────────
    next_round = _NEXT_ROUND.get(round_code, "W")
    sim_rows   = db.execute(_SIM_SQL, [next_round]).fetchall()
    # team_id → advance_prob from simulations (P of advancing past this round)
    sim_map: dict[str, float] = {team: prob for team, prob in sim_rows}

    # ── Build response ────────────────────────────────────────────────────
    matches: list[Matchup] = []
    for row in fixture_rows:
        (
            event_id, match_date, round_name_val,
            h_name, h_abbrev, a_name, a_abbrev,
            h_score, a_score, is_completed,
            home_win_prob, draw_prob, away_win_prob,
        ) = row

        h_name_norm = _norm(h_name) or h_name
        a_name_norm = _norm(a_name) or a_name

        # ── Market 2-way collapse ─────────────────────────────────────────
        # P(home advances) = P(H) + P(D) * 0.5 (neutral ET/pens split)
        market_home: float | None = None
        market_away: float | None = None
        if home_win_prob is not None and away_win_prob is not None:
            try:
                hw = float(home_win_prob)
                dp = float(draw_prob) if draw_prob is not None else 0.0
                aw = float(away_win_prob)
                if not (hw != hw or aw != aw):  # NaN check
                    market_home = round(hw + dp * 0.5, 4)
                    market_away = round(1.0 - market_home, 4)
            except (TypeError, ValueError):
                pass

        # ── Model advance probs from simulations ──────────────────────────
        model_home = sim_map.get(h_name_norm)
        model_away = sim_map.get(a_name_norm)
        if model_home is not None:
            model_home = round(float(model_home), 4)
        if model_away is not None:
            model_away = round(float(model_away), 4)

        matches.append(Matchup(
            event_id    = str(event_id),
            match_date  = str(match_date),
            round       = round_name_val,
            is_completed= bool(is_completed),
            home=MatchupTeam(
                name               = h_name_norm,
                abbrev             = h_abbrev,
                score              = int(h_score) if h_score is not None else None,
                model_advance_prob = model_home,
                market_advance_prob= market_home,
            ),
            away=MatchupTeam(
                name               = a_name_norm,
                abbrev             = a_abbrev,
                score              = int(a_score) if a_score is not None else None,
                model_advance_prob = model_away,
                market_advance_prob= market_away,
            ),
        ))

    return MatchupsResponse(
        round_code=round_code,
        round_name=round_name,
        n_matches=len(matches),
        matches=matches,
    )
