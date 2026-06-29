"""
POST /api/v1/narratives/{reep_id}

Generates a confidence-gated LLM scouting report for a player using OpenRouter.

Routing logic:
  confidence_score >= settings.narrative_confidence_threshold (0.7)
      → Data Analyst voice: cites Bayesian metrics directly
  confidence_score <  settings.narrative_confidence_threshold
      → Traditional Scout voice: qualitative only, forbidden from inventing stats
"""
import logging

import duckdb
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from openai import OpenAI

from api.deps import get_db
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/narratives", tags=["narratives"])


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class NarrativeResponse(BaseModel):
    narrative: str
    voice: str  # "data_analyst" | "traditional_scout"


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_NARRATIVE_SQL = """
SELECT
    pr.reep_id,
    ip.name,
    ip.nationality,
    ip.position_detail,
    pr.position_macro,
    pr.cluster_id,
    arc.cluster_label,
    pr.prior_mean,
    pr.posterior_mean,
    pr.posterior_std,
    pr.hdi_low,
    pr.hdi_high,
    pr.shrinkage_weight,
    pr.wc_minutes,
    pr.confidence_score,
    pr.percentile_rank
FROM player_ratings pr
LEFT JOIN identity_players ip  ON pr.reep_id = ip.reep_id
LEFT JOIN archetypes       arc ON pr.reep_id = arc.reep_id
WHERE pr.reep_id = $1
"""

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_DATA_ANALYST_SYSTEM = (
    "You are an elite Data Analyst scout for FIFA World Cup 2026. "
    "Write a concise tactical scouting report in 3–4 short paragraphs. "
    "Base your evaluation STRICTLY on the provided Bayesian metrics — cite the specific "
    "numbers to explain the player's strengths, weaknesses, and role. "
    "Be direct, professional, and data-driven. Do not invent any statistics not provided."
)

_TRADITIONAL_SCOUT_SYSTEM = (
    "You are a Traditional Scout for FIFA World Cup 2026. "
    "The quantitative data for this player is sparse or low-confidence. "
    "Write an impressionistic scouting report in 2–3 short paragraphs based on their "
    "position and archetype cluster. "
    "YOU ARE STRICTLY FORBIDDEN from inventing, hallucinating, or mentioning specific "
    "statistical numbers, xG values, percentiles, or ratings not explicitly provided. "
    "Focus on their typical tactical role and archetypal positional characteristics."
)

_FALLBACK_NARRATIVE = (
    "Scouting report temporarily unavailable. "
    "The AI narrative service could not be reached. Please try again later."
)

_ANTI_YAPPING_CONSTRAINT = (
    "\n\nCRITICAL FORMATTING RULE: Do NOT output your chain of thought, reasoning process, "
    "or internal monologue. Output ONLY the final scouting report in 2-3 concise paragraphs. "
    "Do not use introductory filler like 'Here is the scouting report' or 'Based on the data'. "
    "Just start the analysis directly with the player's name or tactical role."
)

# Then update your prompt variables:
_DATA_ANALYST_SYSTEM = (
    "You are an elite Data Analyst scout for FIFA World Cup 2026. "
    "Write a concise tactical scouting report in 3–4 short paragraphs. "
    "Base your evaluation STRICTLY on the provided Bayesian metrics — cite the specific "
    "numbers to explain the player's strengths, weaknesses, and role. "
    "Be direct, professional, and data-driven. Do not invent any statistics not provided."
    + _ANTI_YAPPING_CONSTRAINT
)

_TRADITIONAL_SCOUT_SYSTEM = (
    "You are a Traditional Scout for FIFA World Cup 2026. "
    "The quantitative data for this player is sparse or low-confidence. "
    "Write an impressionistic scouting report in 2–3 short paragraphs based on their "
    "position and archetype cluster. "
    "YOU ARE STRICTLY FORBIDDEN from inventing, hallucinating, or mentioning specific "
    "statistical numbers, xG values, percentiles, or ratings not explicitly provided. "
    "Focus on their typical tactical role and archetypal positional characteristics."
    + _ANTI_YAPPING_CONSTRAINT
)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/{reep_id}", response_model=NarrativeResponse)
def generate_narrative(
    reep_id: str,
    db: duckdb.DuckDBPyConnection = Depends(get_db),
) -> NarrativeResponse:
    """
    Generate a confidence-gated scouting report for a player.

    Requires OPENROUTER_API_KEY in .env — returns a graceful fallback if
    the key is missing or the OpenRouter call fails.
    """
    if not settings.openrouter_api_key:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY not configured")

    rows = db.execute(_NARRATIVE_SQL, [reep_id]).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Player not found: {reep_id}")

    (
        reep_id_, name, nationality, position_detail,
        position_macro, cluster_id, cluster_label,
        prior_mean, posterior_mean, posterior_std,
        hdi_low, hdi_high, shrinkage_weight, wc_minutes,
        confidence_score, percentile_rank,
    ) = rows[0]

    high_confidence = float(confidence_score) >= settings.narrative_confidence_threshold
    voice = "data_analyst" if high_confidence else "traditional_scout"
    system_prompt = _DATA_ANALYST_SYSTEM if high_confidence else _TRADITIONAL_SCOUT_SYSTEM

    display_name = name or reep_id_
    position_label = position_detail or position_macro or "Unknown position"
    archetype_label = cluster_label or f"Cluster {cluster_id}"
    wc_weight_pct = (1.0 - float(shrinkage_weight)) * 100.0

    if high_confidence:
        user_message = (
            f"Generate a tactical scouting report for {display_name}"
            f" ({nationality or 'nationality unknown'}).\n\n"
            f"Position: {position_label}\n"
            f"Archetype: {archetype_label}\n\n"
            f"Bayesian Posterior Metrics:\n"
            f"- Overall rating: {float(posterior_mean):.3f}"
            f" (p{float(percentile_rank) * 100:.0f} within position group)\n"
            f"- 90% HDI: {float(hdi_low):.3f} – {float(hdi_high):.3f}"
            f"  (uncertainty: ±{float(posterior_std):.3f})\n"
            f"- Club prior rating: {float(prior_mean):.3f}"
            f" — weighted {float(shrinkage_weight) * 100:.0f}% of posterior\n"
            f"- World Cup data contribution: {wc_weight_pct:.0f}% of posterior"
            f" ({float(wc_minutes):.0f} minutes played)\n"
            f"- Confidence score: {float(confidence_score):.2f}/1.00\n"
        )
    else:
        user_message = (
            f"Write a scouting report for {display_name}"
            f" ({nationality or 'nationality unknown'}).\n\n"
            f"Position: {position_label}\n"
            f"Archetype: {archetype_label}\n"
            f"World Cup minutes: {float(wc_minutes):.0f}\n"
            f"Data note: Limited match data (confidence {float(confidence_score):.2f}/1.00).\n"
            f"Describe their typical tactical role and positional characteristics only."
        )

    try:
        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        completion = client.chat.completions.create(
            model=settings.openrouter_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=450,
            temperature=0.7,
        )
        narrative = (completion.choices[0].message.content or "").strip()
        if not narrative:
            narrative = _FALLBACK_NARRATIVE
    except Exception as exc:
        logger.warning("OpenRouter call failed for %s: %s", reep_id, exc)
        narrative = _FALLBACK_NARRATIVE

    return NarrativeResponse(narrative=narrative, voice=voice)
