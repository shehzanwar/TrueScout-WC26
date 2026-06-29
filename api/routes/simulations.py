"""
GET /api/v1/simulations

Returns the latest Monte Carlo bracket simulation results formatted for
the frontend knockout-tree component.

Response groups all 32 teams by round so the frontend can render:
  - R32  : all 32 teams (advance_prob = 1.0)
  - R16  : 32 teams × P(reached R16)    — sorted by advance_prob
  - QF   : 32 teams × P(reached QF)
  - SF   : 32 teams × P(reached SF)
  - F    : 32 teams × P(reached Final)
  - W    : 32 teams × title_prob         — the championship winner distribution

Teams are sorted within each round by advance_prob descending so the
frontend can render a clean ranked list without extra sorting.
"""
import logging
from typing import Any

import duckdb
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/simulations", tags=["simulations"])

ROUND_ORDER = ["R32", "R16", "QF", "SF", "F", "W"]

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class SimTeam(BaseModel):
    team_id:      str
    advance_prob: float   # P(team reached this round)
    title_prob:   float   # P(team wins tournament)


class SimRound(BaseModel):
    round:       str           # "R32" | "R16" | "QF" | "SF" | "F" | "W"
    round_label: str           # human-readable, e.g. "Round of 32"
    teams:       list[SimTeam] # sorted by advance_prob DESC


class SimulationsResponse(BaseModel):
    run_date:     str
    n_iterations: int
    rounds:       list[SimRound]


_ROUND_LABELS: dict[str, str] = {
    "R32": "Round of 32",
    "R16": "Round of 16",
    "QF":  "Quarterfinal",
    "SF":  "Semifinal",
    "F":   "Final",
    "W":   "Champion",
}

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_SIM_SQL = """
SELECT
    run_date,
    round,
    team_id,
    advance_prob,
    title_prob,
    n_iterations
FROM simulations
WHERE run_date = (SELECT MAX(run_date) FROM simulations)
ORDER BY round, advance_prob DESC
"""

# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/", response_model=SimulationsResponse)
def get_simulations(
    db: duckdb.DuckDBPyConnection = Depends(get_db),
) -> SimulationsResponse:
    """
    Latest Monte Carlo knockout-bracket simulation.

    Returns all 32 teams × 6 rounds (192 rows) grouped by round.
    advance_prob[R32] = 1.0 for all teams (everyone starts in R32).
    advance_prob[W]   = title_prob = P(win tournament).
    """
    rows = db.execute(_SIM_SQL).fetchall()

    if not rows:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="No simulation results found. Run: python -m etl.models.monte_carlo_sim",
        )

    # Extract metadata from first row
    run_date_val   = str(rows[0][0])
    n_iterations   = int(rows[0][5])

    # Group by round maintaining ROUND_ORDER sequence
    by_round: dict[str, list[SimTeam]] = {r: [] for r in ROUND_ORDER}
    for run_date, rnd, team_id, advance_prob, title_prob, n_iter in rows:
        if rnd in by_round:
            by_round[rnd].append(SimTeam(
                team_id=team_id,
                advance_prob=round(float(advance_prob), 4),
                title_prob=round(float(title_prob), 4),
            ))

    rounds: list[SimRound] = [
        SimRound(
            round=rnd,
            round_label=_ROUND_LABELS.get(rnd, rnd),
            teams=by_round[rnd],
        )
        for rnd in ROUND_ORDER
        if by_round[rnd]
    ]

    return SimulationsResponse(
        run_date=run_date_val,
        n_iterations=n_iterations,
        rounds=rounds,
    )
