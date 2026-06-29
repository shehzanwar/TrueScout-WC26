"""
GET /api/v1/brier

Returns the calibration log comparing TrueScout model predictions against
ESPN market odds and a 50/50 coin-flip baseline.

Each entry is one completed knockout match. The summary block aggregates
across all graded matches so the frontend Brier-tracker panel can display
a running calibration score without doing any maths client-side.

Coin-flip reference values (invariant):
    Brier   = 0.25        (= (0.5 - o)^2, outcome ∈ {0,1})
    LogLoss = ln(2) ≈ 0.6931
"""
import math
import logging

import duckdb
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/brier", tags=["brier"])

COIN_BRIER   = 0.25
COIN_LOGLOSS = math.log(2)   # ≈ 0.6931

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class BrierEntry(BaseModel):
    event_id:        str
    run_date:        str
    round:           str
    home_team:       str
    away_team:       str
    advanced_team:   str
    model_prob:      float | None    # P(home advances) from model
    market_prob:     float | None    # P(home advances) from market odds
    brier_model:     float | None
    brier_market:    float | None
    log_loss_model:  float | None
    log_loss_market: float | None


class BrierSummary(BaseModel):
    n_matches:           int
    n_with_market:       int
    avg_brier_model:     float | None
    avg_brier_market:    float | None
    avg_log_loss_model:  float | None
    avg_log_loss_market: float | None
    coin_flip_brier:     float
    coin_flip_log_loss:  float
    # Skill scores: 1 – (model / baseline)  positive = better than baseline
    brier_skill_vs_coin:   float | None   # vs coin-flip
    brier_skill_vs_market: float | None   # vs market (None until market data exists)


class BrierResponse(BaseModel):
    summary: BrierSummary
    entries: list[BrierEntry]


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_BRIER_SQL = """
SELECT
    event_id,
    CAST(run_date AS VARCHAR) AS run_date,
    round,
    home_team,
    away_team,
    advanced_team,
    model_prob,
    market_prob,
    brier_model,
    brier_market,
    log_loss_model,
    log_loss_market
FROM brier_log
ORDER BY run_date DESC, logged_at DESC
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _skill_score(model: float | None, baseline: float) -> float | None:
    """Brier Skill Score = 1 – (model_brier / baseline_brier). Positive is better."""
    if model is None or baseline == 0:
        return None
    return round(1.0 - model / baseline, 4)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/", response_model=BrierResponse)
def get_brier(
    db: duckdb.DuckDBPyConnection = Depends(get_db),
) -> BrierResponse:
    """
    Calibration log: TrueScout vs market odds vs coin-flip baseline.

    One row per completed knockout match.  Summary includes Brier Skill Scores
    (positive = beating the baseline, negative = worse than baseline).
    """
    rows = db.execute(_BRIER_SQL).fetchall()

    entries: list[BrierEntry] = []
    for row in rows:
        (
            event_id, run_date, rnd, home_team, away_team, advanced_team,
            model_prob, market_prob,
            brier_model, brier_market,
            log_loss_model, log_loss_market,
        ) = row

        entries.append(BrierEntry(
            event_id       = str(event_id),
            run_date       = str(run_date),
            round          = rnd,
            home_team      = home_team,
            away_team      = away_team,
            advanced_team  = advanced_team,
            model_prob     = _safe_float(model_prob),
            market_prob    = _safe_float(market_prob),
            brier_model    = _safe_float(brier_model),
            brier_market   = _safe_float(brier_market),
            log_loss_model = _safe_float(log_loss_model),
            log_loss_market= _safe_float(log_loss_market),
        ))

    # ── Aggregate summary ─────────────────────────────────────────────────
    n_total  = len(entries)
    n_market = sum(1 for e in entries if e.market_prob is not None)

    brier_vals  = [e.brier_model    for e in entries if e.brier_model    is not None]
    ll_vals     = [e.log_loss_model for e in entries if e.log_loss_model is not None]
    brier_m_vals= [e.brier_market   for e in entries if e.brier_market   is not None]
    ll_m_vals   = [e.log_loss_market for e in entries if e.log_loss_market is not None]

    avg_brier_model  = round(sum(brier_vals)   / len(brier_vals),   4) if brier_vals  else None
    avg_ll_model     = round(sum(ll_vals)      / len(ll_vals),      4) if ll_vals     else None
    avg_brier_market = round(sum(brier_m_vals) / len(brier_m_vals), 4) if brier_m_vals else None
    avg_ll_market    = round(sum(ll_m_vals)    / len(ll_m_vals),    4) if ll_m_vals   else None

    summary = BrierSummary(
        n_matches           = n_total,
        n_with_market       = n_market,
        avg_brier_model     = avg_brier_model,
        avg_brier_market    = avg_brier_market,
        avg_log_loss_model  = avg_ll_model,
        avg_log_loss_market = avg_ll_market,
        coin_flip_brier     = COIN_BRIER,
        coin_flip_log_loss  = round(COIN_LOGLOSS, 4),
        brier_skill_vs_coin   = _skill_score(avg_brier_model,  COIN_BRIER),
        brier_skill_vs_market = _skill_score(avg_brier_model,  avg_brier_market) if avg_brier_market else None,
    )

    return BrierResponse(summary=summary, entries=entries)
