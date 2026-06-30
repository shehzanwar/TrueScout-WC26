"""
etl/models/generate_narratives.py — Pre-generate AI scouting reports nightly.

Anti-hallucination approach (PR7):
  Python builds structured "fact bullets" for each player; the LLM only rephrases
  them into prose. The system prompt bans inventing any number not in the bullets.
  This yields reliable output even with free-tier models that can't see the player
  data independently.

Reads frontend/public/data/players.json and calls OpenRouter for players that
don't already have a cached report, writing results to
frontend/public/data/narratives/{reep_id}.json.

Designed to run as optional step 9.6 of run_nightly.py (soft-fail — skips
gracefully when OPENROUTER_API_KEY is absent or rate-limit is hit).

Usage
-----
    python -m etl.models.generate_narratives              # top 100 uncached
    python -m etl.models.generate_narratives --limit 50
    python -m etl.models.generate_narratives --force      # overwrite existing
    python -m etl.models.generate_narratives --min-confidence 0.5
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)

OUTPUT_DIR   = ROOT / "frontend" / "public" / "data" / "narratives"
PLAYERS_JSON = ROOT / "frontend" / "public" / "data" / "players.json"

CONFIDENCE_THRESHOLD = 0.7
DEFAULT_LIMIT        = 100
DEFAULT_MIN_CONF     = 0.3

CALL_DELAY_S   = 3.0
MAX_RETRIES    = 4
BACKOFF_BASE_S = 5.0
CIRCUIT_BREAKER = 3

# Primary model from env; three hardcoded fallbacks tried in order on failure.
# Must mirror the chain in frontend/app/api/narratives/[reep_id]/route.ts.
_FALLBACK_MODELS = [
    os.environ.get("OPENROUTER_MODEL", "poolside/laguna-m.1:free"),
    "google/gemma-3-27b-it:free",
    "nvidia/llama-3.1-nemotron-70b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# ---------------------------------------------------------------------------
# System prompts — anti-hallucination templated approach (PR7)
# ---------------------------------------------------------------------------

_ANTI_HALLUCINATION = (
    "\n\nCRITICAL FACTUAL CONSTRAINT: You may ONLY use the numbers and facts "
    "explicitly listed in the 'Facts' section of the user message. "
    "Do NOT invent, extrapolate, or add any statistics, percentages, goals, "
    "assists, ratings, or biographical details not stated there. "
    "If a fact is not in the bullets, do not mention it."
)

_ANTI_YAPPING = (
    "\n\nFORMATTING: Output ONLY the final report in 2-3 short paragraphs. "
    "No chain of thought, no introductory filler ('Here is…', 'Based on…'). "
    "Start directly with the player's name or tactical role."
)

_JARGON_BAN = (
    "\n\nLANGUAGE: Never use: 'posterior', 'HDI', 'Bayesian', 'shrinkage', "
    "'percentile rank', 'confidence score', 'prior', 'credible interval'. "
    "Write as a TV football analyst — clear, direct, accessible."
)

DATA_ANALYST_SYSTEM = (
    "You are an elite football scout covering FIFA World Cup 2026. "
    "Write a concise tactical scouting report in 3-4 short paragraphs. "
    "Explain the player's strengths, weaknesses, and role using the "
    "specific numbers provided. Be direct and professional."
    + _ANTI_HALLUCINATION + _ANTI_YAPPING + _JARGON_BAN
)

TRADITIONAL_SCOUT_SYSTEM = (
    "You are a traditional football scout covering FIFA World Cup 2026. "
    "Match data for this player is limited — write an impressionistic scouting "
    "report in 2-3 short paragraphs based only on what you are told. "
    "YOU ARE STRICTLY FORBIDDEN from inventing statistical numbers, xG values, "
    "ratings, or specific records. Focus on tactical role and playing style."
    + _ANTI_HALLUCINATION + _ANTI_YAPPING + _JARGON_BAN
)


# ---------------------------------------------------------------------------
# Fact-bullet builder — the anti-hallucination payload
# ---------------------------------------------------------------------------

def _build_fact_bullets(p: dict, high_confidence: bool) -> str:
    """
    Build a structured "fact bullets" user message.

    For high-confidence players: includes rating, HDI-range, club/WC split,
    minutes, and any raw WC stats present in the export.
    For low-confidence players: position + playing style only — no invented numbers.
    """
    name      = p.get("name") or p["reep_id"]
    nat       = p.get("nationality") or "nationality unknown"
    position  = p.get("position_detail") or p.get("position_macro") or "Unknown position"
    archetype = p.get("cluster_label") or position

    if not high_confidence:
        wc_mins = round(p.get("wc_minutes", 0))
        return (
            f"Write a scouting report for {name} ({nat}).\n\n"
            f"Position: {position}\n"
            f"Playing style: {archetype}\n"
            f"World Cup minutes: {wc_mins}\n\n"
            f"Facts (use only what is listed here):\n"
            f"• Limited World Cup data — focus on typical tactical role for a {position.lower()}\n"
            f"• Playing style cluster: {archetype}"
        )

    shrinkage = p.get("shrinkage_weight", 0.5)
    wc_pct    = round((1.0 - shrinkage) * 100)
    club_pct  = 100 - wc_pct
    pct_rank  = p.get("percentile_rank", 0.5)
    pct_top   = max(1, round((1 - pct_rank) * 100))
    hdi_low   = round(p.get("hdi_low", 0.0), 2)
    hdi_high  = round(p.get("hdi_high", 10.0), 2)
    post_mean = round(p.get("posterior_mean", 5.0), 2)
    wc_mins   = round(p.get("wc_minutes", 0))

    bullets = [
        f"• Overall rating: {post_mean} out of 10 — top {pct_top}% of {position.lower()}s at this tournament",
        f"• Rating range: {hdi_low}–{hdi_high} (reflecting match sample size)",
        f"• {club_pct}% of rating from club form (last 2 seasons); {wc_pct}% from this World Cup",
        f"• World Cup minutes played: {wc_mins}",
    ]

    # Append any available raw WC stats
    stat_labels: list[tuple[str, str]] = [
        ("wc_goals_per_90",        "Goals per 90 min (WC)"),
        ("wc_assists_per_90",      "Assists per 90 min (WC)"),
        ("wc_xg_per_90",           "xG per 90 min (WC)"),
        ("wc_xa_per_90",           "xA per 90 min (WC)"),
        ("wc_shots_per_90",        "Shots per 90 min (WC)"),
        ("wc_key_passes_per_90",   "Key passes per 90 min (WC)"),
        ("wc_tackles_per_90",      "Tackles per 90 min (WC)"),
        ("wc_interceptions_per_90","Interceptions per 90 min (WC)"),
        ("wc_saves_per_90",        "Saves per 90 min (WC)"),
        ("prior_goals_per_90",     "Goals per 90 min (club, last 2 seasons)"),
        ("prior_assists_per_90",   "Assists per 90 min (club, last 2 seasons)"),
        ("prior_xg_per_90",        "xG per 90 min (club, last 2 seasons)"),
    ]
    for col, label in stat_labels:
        val = p.get(col)
        if val is not None and isinstance(val, (int, float)) and val > 0:
            bullets.append(f"• {label}: {round(float(val), 3)}")

    bullets_text = "\n".join(bullets)
    return (
        f"Generate a tactical scouting report for {name} ({nat}).\n\n"
        f"Position: {position}\n"
        f"Playing style: {archetype}\n\n"
        f"Facts (you may ONLY reference these numbers — do not invent any others):\n"
        f"{bullets_text}"
    )


# ---------------------------------------------------------------------------
# OpenRouter caller with fallback chain
# ---------------------------------------------------------------------------

def _strip_reasoning_tags(text: str) -> str:
    """Remove <think>…</think> and <reasoning>…</reasoning> preambles."""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<reasoning>[\s\S]*?</reasoning>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _call_model(api_key: str, model: str, system: str, user: str) -> str | None:
    """
    Single model call with exponential backoff on 429. Returns text or None.
    """
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model":       model,
        "messages":    [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens":  800,
        "temperature": 0.7,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  "https://truescout.vercel.app",
            "X-Title":       "TrueScout WC 2026",
        },
        method="POST",
    )

    backoff = BACKOFF_BASE_S
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            raw = body["choices"][0]["message"]["content"]
            if not raw:
                return None
            return _strip_reasoning_tags(raw) or None
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < MAX_RETRIES:
                retry_after = None
                try:
                    retry_after = float(exc.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    pass
                wait = retry_after if retry_after else backoff
                logger.warning("429 from %s — retry %d/%d in %.1fs", model, attempt, MAX_RETRIES, wait)
                time.sleep(wait)
                backoff *= 2
                continue
            logger.warning("Model %s HTTP error: %d %s", model, exc.code, exc.reason)
            return None
        except Exception as exc:
            logger.warning("Model %s failed: %s", model, exc)
            return None
    return None


def _call_openrouter(api_key: str, system: str, user: str) -> tuple[str, str] | None:
    """
    Try each model in FALLBACK_MODELS in order. Returns (narrative, model_used) or None.
    """
    for model in _FALLBACK_MODELS:
        narrative = _call_model(api_key, model, system, user)
        if narrative:
            return narrative, model
        logger.warning("Model %s returned no content — trying next fallback", model)
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(
    limit: int = DEFAULT_LIMIT,
    min_confidence: float = DEFAULT_MIN_CONF,
    force: bool = False,
) -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.info("OPENROUTER_API_KEY not set — skipping narrative pre-generation.")
        return

    if not PLAYERS_JSON.exists():
        logger.warning("players.json not found at %s — run export_json.py first.", PLAYERS_JSON)
        return

    players = json.loads(PLAYERS_JSON.read_text(encoding="utf-8"))
    logger.info("Loaded %d players from players.json.", len(players))

    candidates = [
        p for p in players
        if (p.get("confidence_score") or 0) >= min_confidence
    ]
    candidates.sort(key=lambda p: (-(p.get("confidence_score") or 0), -(p.get("posterior_mean") or 0)))
    logger.info(
        "%d candidates (confidence >= %.2f); limit=%d; force=%s",
        len(candidates), min_confidence, limit, force,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    generated = 0
    skipped   = 0
    consecutive_failures = 0

    for p in candidates:
        if generated >= limit:
            break

        reep_id  = p["reep_id"]
        out_path = OUTPUT_DIR / f"{reep_id}.json"

        if out_path.exists() and not force:
            skipped += 1
            continue

        high_confidence = (p.get("confidence_score") or 0) >= CONFIDENCE_THRESHOLD
        voice  = "data_analyst" if high_confidence else "traditional_scout"
        system = DATA_ANALYST_SYSTEM if high_confidence else TRADITIONAL_SCOUT_SYSTEM
        user   = _build_fact_bullets(p, high_confidence)

        result = _call_openrouter(api_key, system, user)
        if not result:
            consecutive_failures += 1
            logger.warning("No narrative for %s (%s)", reep_id, p.get("name"))
            if consecutive_failures >= CIRCUIT_BREAKER:
                if generated == 0:
                    logger.warning(
                        "%d consecutive all-model failures — all models may require credits "
                        "or be unavailable. Check https://openrouter.ai/models",
                        consecutive_failures,
                    )
                else:
                    logger.warning(
                        "%d consecutive failures — likely daily cap hit. "
                        "Stopping; remaining players picked up on next run.",
                        consecutive_failures,
                    )
                break
            time.sleep(CALL_DELAY_S)
            continue

        narrative, model_used = result
        consecutive_failures  = 0

        payload = {
            "narrative":    narrative,
            "voice":        voice,
            "model":        model_used,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "[%d/%d] %s — %s — %s — %d chars",
            generated + 1, limit,
            p.get("name") or reep_id,
            voice,
            model_used.split("/")[-1],
            len(narrative),
        )
        generated += 1
        time.sleep(CALL_DELAY_S)

    logger.info(
        "Narrative generation complete: %d generated, %d already cached, %d skipped.",
        generated, skipped, len(candidates) - generated - skipped,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description="Pre-generate player scouting narratives.")
    parser.add_argument("--limit",          type=int,   default=DEFAULT_LIMIT)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONF)
    parser.add_argument("--force",          action="store_true")
    args = parser.parse_args()
    main(limit=args.limit, min_confidence=args.min_confidence, force=args.force)
