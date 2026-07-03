"""
etl/models/generate_narratives.py — Pre-generate AI scouting reports nightly.

Anti-hallucination approach:
  Python builds structured "fact bullets" for each player; the model only rephrases
  them into prose. The system prompt bans inventing any number not in the bullets,
  and specifies the exact paragraph structure so the output is always complete.

Reads frontend/public/data/players.json and calls the Gemini native REST API for
players that don't already have a cached report, writing results to
frontend/public/data/narratives/{reep_id}.json.

Designed to run as optional step 9.6 of run_nightly.py (soft-fail — skips
gracefully when GOOGLE_AI_API_KEY is absent or rate-limit quota is exhausted).

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

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(ROOT / ".env")
except ImportError:
    pass

logger = logging.getLogger(__name__)

OUTPUT_DIR   = ROOT / "frontend" / "public" / "data" / "narratives"
PLAYERS_JSON = ROOT / "frontend" / "public" / "data" / "players.json"

CONFIDENCE_THRESHOLD = 0.7
DEFAULT_LIMIT        = 100
DEFAULT_MIN_CONF     = 0.3

CALL_DELAY_S    = 4.0   # 4 s between calls — stays under 15 RPM free-tier quota
MAX_RETRIES     = 3
BACKOFF_BASE_S  = 10.0
CIRCUIT_BREAKER = 3

# Model chain mirrors frontend/app/api/narratives/[reep_id]/route.ts
_PRIMARY_MODEL  = os.environ.get("GOOGLE_AI_MODEL", "gemini-2.5-flash")
_GEMINI_MODELS  = [_PRIMARY_MODEL]

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# ---------------------------------------------------------------------------
# System prompts — explicit paragraph structure prevents truncation
# ---------------------------------------------------------------------------

_ANTI_HALLUCINATION = (
    "\n\nCRITICAL FACTUAL CONSTRAINT: You may ONLY reference numbers and facts "
    "explicitly listed in the 'Facts' section below. "
    "Do NOT invent, estimate, or extrapolate any statistics, goals, assists, "
    "ratings, minutes, percentages, or biographical details not stated there. "
    "If a fact is not in the bullets, do not mention it."
)

_ANTI_YAPPING = (
    "\n\nFORMATTING: Output ONLY the final scouting report — no chain of thought, "
    "no introductory filler ('Here is…', 'Based on…', 'Certainly…'). "
    "Start the first paragraph directly with the player's name."
)

_JARGON_BAN = (
    "\n\nLANGUAGE: Never use these words: 'posterior', 'HDI', 'Bayesian', "
    "'shrinkage', 'percentile rank', 'confidence score', 'prior', "
    "'credible interval', 'weighted blend'. "
    "Write as a football analyst speaks on television — clear, direct, accessible."
)

# High-confidence: structured 3-paragraph report built around numbers
DATA_ANALYST_SYSTEM = (
    "You are an elite football scout covering FIFA World Cup 2026. "
    "Write a tactical scouting report in EXACTLY 3 short paragraphs. "
    "Each paragraph must be 2–4 complete sentences and end with a full stop.\n\n"
    "Paragraph 1 — Player overview: Who is this player, what position do they play, "
    "and where does their rating place them in the tournament?\n"
    "Paragraph 2 — Performance evidence: Cite 2–3 specific statistics from the Facts "
    "section to illustrate their strengths and any notable weaknesses.\n"
    "Paragraph 3 — Tournament verdict: What role do they play in their national team, "
    "and what should scouts and fans watch for in their remaining matches?"
    + _ANTI_HALLUCINATION
    + _ANTI_YAPPING
    + _JARGON_BAN
)

# Low-confidence: impressionistic 2-paragraph report — no invented numbers
TRADITIONAL_SCOUT_SYSTEM = (
    "You are a traditional football scout covering FIFA World Cup 2026. "
    "Write a brief scouting report in EXACTLY 2 short paragraphs. "
    "Each paragraph must be 2–3 complete sentences and end with a full stop.\n\n"
    "Paragraph 1 — Player profile: Describe the player's position, playing style, "
    "and what they typically bring to a team — based only on the position and style "
    "information provided, not invented statistics.\n"
    "Paragraph 2 — World Cup role: Describe their contribution so far and what "
    "observers should watch for — without citing any specific numbers beyond "
    "the minutes played figure if provided.\n\n"
    "YOU ARE STRICTLY FORBIDDEN from mentioning specific goals, assists, ratings, "
    "xG values, tackle counts, or any other statistic not listed in the Facts section."
    + _ANTI_HALLUCINATION
    + _ANTI_YAPPING
    + _JARGON_BAN
)


# ---------------------------------------------------------------------------
# Fact-bullet builder — the anti-hallucination payload
# ---------------------------------------------------------------------------

def _build_fact_bullets(p: dict, high_confidence: bool) -> str:
    name      = p.get("name") or p["reep_id"]
    nat       = p.get("nationality") or "nationality unknown"
    position  = p.get("position_detail") or p.get("position_macro") or "Unknown position"
    archetype = p.get("cluster_label") or position

    if not high_confidence:
        wc_mins = round(p.get("wc_minutes", 0))
        return (
            f"Write a scouting report for {name} ({nat}).\n\n"
            f"Position: {position}\n"
            f"Playing style: {archetype}\n\n"
            f"Facts (use ONLY what is listed here — do not add anything else):\n"
            f"• World Cup minutes played: {wc_mins}\n"
            f"• Playing style cluster: {archetype}\n"
            f"• Limited World Cup data available"
        )

    shrinkage = p.get("shrinkage_weight", 0.5)
    wc_pct    = round((1.0 - shrinkage) * 100)
    club_pct  = 100 - wc_pct
    pct_rank  = p.get("percentile_rank", 0.5)
    pct_top   = max(1, round((1 - pct_rank) * 100))
    hdi_low   = round(p.get("hdi_low",  0.0), 2)
    hdi_high  = round(p.get("hdi_high", 10.0), 2)
    post_mean = round(p.get("posterior_mean", 5.0), 2)
    wc_mins   = round(p.get("wc_minutes", 0))

    bullets = [
        f"• Overall rating: {post_mean}/10 — top {pct_top}% of {position.lower()}s at this tournament",
        f"• Rating range: {hdi_low}–{hdi_high} (reflects match sample size)",
        f"• {club_pct}% of rating from club form (last 2 seasons); {wc_pct}% from this World Cup",
        f"• World Cup minutes played: {wc_mins}",
    ]

    # Append any available per-90 stats
    stat_labels: list[tuple[str, str]] = [
        ("wc_goals_per_90",         "Goals per 90 min at this World Cup"),
        ("wc_assists_per_90",       "Assists per 90 min at this World Cup"),
        ("wc_xg_per_90",            "Expected goals (xG) per 90 min at this World Cup"),
        ("wc_xa_per_90",            "Expected assists (xA) per 90 min at this World Cup"),
        ("wc_shots_per_90",         "Shots per 90 min at this World Cup"),
        ("wc_key_passes_per_90",    "Key passes per 90 min at this World Cup"),
        ("wc_tackles_per_90",       "Tackles per 90 min at this World Cup"),
        ("wc_interceptions_per_90", "Interceptions per 90 min at this World Cup"),
        ("wc_clearances_per_90",    "Clearances per 90 min at this World Cup"),
        ("wc_saves_per_90",         "Saves per 90 min at this World Cup"),
        ("prior_goals_per_90",      "Goals per 90 min at club level (last 2 seasons)"),
        ("prior_assists_per_90",    "Assists per 90 min at club level (last 2 seasons)"),
        ("prior_xg_per_90",         "xG per 90 min at club level (last 2 seasons)"),
        ("prior_xa_per_90",         "xA per 90 min at club level (last 2 seasons)"),
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
        f"Facts (you may ONLY reference these — do not invent anything else):\n"
        f"{bullets_text}"
    )


# ---------------------------------------------------------------------------
# Gemini native REST caller — mirrors route.ts logic
# ---------------------------------------------------------------------------

def _strip_reasoning_tags(text: str) -> str:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<reasoning>[\s\S]*?</reasoning>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _call_gemini(api_key: str, model: str, system: str, user: str) -> str | None:
    """Single Gemini native REST call with exponential back-off on 429."""
    import urllib.request
    import urllib.error

    url     = f"{_GEMINI_BASE}/{model}:generateContent?key={api_key}"
    payload = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents":           [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig":   {"maxOutputTokens": 1200, "temperature": 0.7},
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    backoff = BACKOFF_BASE_S
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            raw = (
                body.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                    .strip()
            )
            if not raw:
                logger.warning("Gemini %s returned empty content", model)
                return None
            return _strip_reasoning_tags(raw) or None
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < MAX_RETRIES:
                try:
                    retry_after = float(exc.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    retry_after = None
                wait = retry_after if retry_after else backoff
                logger.warning("HTTP %d from %s — retry %d/%d in %.1fs", exc.code, model, attempt, MAX_RETRIES, wait)
                time.sleep(wait)
                backoff *= 2
                continue
            logger.warning("Gemini %s HTTP %d", model, exc.code)
            return None
        except Exception as exc:
            logger.warning("Gemini %s failed: %s", model, exc)
            return None
    return None


def _call_gemini_chain(api_key: str, system: str, user: str) -> tuple[str, str] | None:
    """Try primary then fallback model. Returns (narrative, model_used) or None."""
    for model in _GEMINI_MODELS:
        narrative = _call_gemini(api_key, model, system, user)
        if narrative:
            return narrative, model
        logger.warning("Gemini %s returned no content — trying next model", model)
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(
    limit: int = DEFAULT_LIMIT,
    min_confidence: float = DEFAULT_MIN_CONF,
    force: bool = False,
) -> None:
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "")
    if not api_key:
        logger.info("GOOGLE_AI_API_KEY not set — skipping narrative pre-generation.")
        return

    if not PLAYERS_JSON.exists():
        logger.warning("players.json not found at %s — run export_json.py first.", PLAYERS_JSON)
        return

    players = json.loads(PLAYERS_JSON.read_text(encoding="utf-8"))
    logger.info("Loaded %d players from players.json.", len(players))

    # Sort highest confidence + highest rating first — best narratives cached earliest
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

        result = _call_gemini_chain(api_key, system, user)
        if not result:
            consecutive_failures += 1
            logger.warning("No narrative for %s (%s)", reep_id, p.get("name"))
            if consecutive_failures >= CIRCUIT_BREAKER:
                if generated == 0:
                    logger.warning(
                        "%d consecutive failures — API key may be invalid or quota "
                        "exhausted. Check https://aistudio.google.com",
                        consecutive_failures,
                    )
                else:
                    logger.warning(
                        "%d consecutive failures — likely daily quota hit. "
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
            model_used,
            len(narrative),
        )
        generated += 1
        time.sleep(CALL_DELAY_S)

    logger.info(
        "Narrative generation complete: %d generated, %d already cached, %d not reached.",
        generated, skipped, max(0, len(candidates) - generated - skipped),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description="Pre-generate player scouting narratives.")
    parser.add_argument("--limit",          type=int,   default=DEFAULT_LIMIT)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONF)
    parser.add_argument("--force",          action="store_true")
    args = parser.parse_args()
    main(limit=args.limit, min_confidence=args.min_confidence, force=args.force)
