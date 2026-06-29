"""
GET /api/v1/players/{reep_id}

Returns a player's full profile for the frontend player card:
  - Bio (name, nationality, position) from identity_players
  - Bayesian posterior (mean, std, HDI, shrinkage) from player_ratings
  - Archetype cluster from archetypes
  - Radar chart pre-scaled metrics (all values 0–1)
"""
import math
import logging

import duckdb
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/players", tags=["players"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class RadarMetrics(BaseModel):
    """Five 0–1 scaled dimensions for the frontend radar / pizza chart."""
    posterior_pct:  float   # percentile_rank within position_micro group
    wc_experience:  float   # min(wc_minutes / 270, 1.0) — 270 = 3 full group-stage games
    confidence:     float   # confidence_score (already 0–1)
    prior_pct:      float   # PERCENT_RANK of prior_mean within position_macro
    wc_dominance:   float   # 1 – shrinkage_weight: how much WC data drives the posterior


class PlayerResponse(BaseModel):
    reep_id:          str
    name:             str | None
    nationality:      str | None
    position_detail:  str | None   # granular reep label (e.g. "Attacking Midfielder")
    position_macro:   str          # GK / DEF / MID / FWD
    position_micro:   str | None   # reep position_detail used for percentile grouping
    cluster_id:       int
    cluster_label:    str | None
    position_bucket:  str          # GK / DEF / MID / FWD (archetype bucket)
    # Bayesian posterior
    prior_mean:       float
    posterior_mean:   float
    posterior_std:    float
    hdi_low:          float
    hdi_high:         float
    shrinkage_weight: float
    wc_minutes:       float
    confidence_score: float
    percentile_rank:  float
    # Radar
    radar:            RadarMetrics

    @field_validator("name", "nationality", "position_detail",
                     "position_micro", "cluster_label", mode="before")
    @classmethod
    def none_for_nan(cls, v):
        if v is None:
            return None
        try:
            if math.isnan(float(v)):
                return None
        except (TypeError, ValueError):
            pass
        return v


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_PLAYER_SQL = """
WITH prior_rank AS (
    SELECT
        reep_id,
        PERCENT_RANK() OVER (
            PARTITION BY position_macro ORDER BY prior_mean
        ) AS prior_pct
    FROM player_ratings
)
SELECT
    pr.reep_id,
    ip.name,
    ip.nationality,
    ip.position_detail,
    pr.position_macro,
    pr.position_micro,
    pr.cluster_id,
    arc.cluster_label,
    arc.position_bucket,
    pr.prior_mean,
    pr.posterior_mean,
    pr.posterior_std,
    pr.hdi_low,
    pr.hdi_high,
    pr.shrinkage_weight,
    pr.wc_minutes,
    pr.confidence_score,
    pr.percentile_rank,
    rk.prior_pct
FROM player_ratings pr
LEFT JOIN identity_players ip  ON pr.reep_id = ip.reep_id
LEFT JOIN archetypes       arc ON pr.reep_id = arc.reep_id
JOIN      prior_rank        rk ON pr.reep_id = rk.reep_id
WHERE pr.reep_id = $1
"""


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/{reep_id}", response_model=PlayerResponse)
def get_player(
    reep_id: str,
    db: duckdb.DuckDBPyConnection = Depends(get_db),
) -> PlayerResponse:
    """
    Full player profile for the player-card page.

    Includes Bayesian posterior, archetype cluster, and five pre-scaled radar
    dimensions ready for the Next.js pizza/radar chart component.
    """
    rows = db.execute(_PLAYER_SQL, [reep_id]).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Player not found: {reep_id}")

    row = rows[0]
    (
        reep_id_, name, nationality, position_detail,
        position_macro, position_micro,
        cluster_id, cluster_label, position_bucket,
        prior_mean, posterior_mean, posterior_std,
        hdi_low, hdi_high, shrinkage_weight, wc_minutes,
        confidence_score, percentile_rank, prior_pct,
    ) = row

    radar = RadarMetrics(
        posterior_pct = float(percentile_rank),
        wc_experience = min(float(wc_minutes) / 270.0, 1.0),
        confidence    = float(confidence_score),
        prior_pct     = float(prior_pct),
        wc_dominance  = 1.0 - float(shrinkage_weight),
    )

    return PlayerResponse(
        reep_id         = reep_id_,
        name            = name,
        nationality     = nationality,
        position_detail = position_detail,
        position_macro  = position_macro,
        position_micro  = position_micro,
        cluster_id      = int(cluster_id),
        cluster_label   = cluster_label,
        position_bucket = position_bucket,
        prior_mean      = float(prior_mean),
        posterior_mean  = float(posterior_mean),
        posterior_std   = float(posterior_std),
        hdi_low         = float(hdi_low),
        hdi_high        = float(hdi_high),
        shrinkage_weight= float(shrinkage_weight),
        wc_minutes      = float(wc_minutes),
        confidence_score= float(confidence_score),
        percentile_rank = float(percentile_rank),
        radar           = radar,
    )
