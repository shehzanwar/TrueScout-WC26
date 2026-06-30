"""
etl/models/generate_narratives.py — Pre-generate AI scouting reports nightly.

Reads frontend/public/data/players.json and calls OpenRouter for players that
don't already have a cached report, writing each result to
frontend/public/data/narratives/{reep_id}.json.

Designed to run as optional step 10 of run_nightly.py (soft-fail — skips
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
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)

OUTPUT_DIR = ROOT / "frontend" / "public" / "data" / "narratives"
PLAYERS_JSON = ROOT / "frontend" / "public" / "data" / "players.json"

CONFIDENCE_THRESHOLD = 0.7   # high-confidence voice gate (mirrors route.ts)
DEFAULT_LIMIT        = 100
DEFAULT_MIN_CONF     = 0.3   # skip players with almost no data

# OpenRouter free-tier (':free' suffix) models enforce a strict per-minute
# rate limit (commonly ~20 req/min without purchased credits). 3s spacing
# keeps sustained throughput under that; MAX_RETRIES + backoff absorbs bursts.
CALL_DELAY_S  = 3.0
MAX_RETRIES   = 4
BACKOFF_BASE_S = 5.0

_ANTI_YAPPING = (
    "\n\nCRITICAL FORMATTING RULE: Do NOT output your chain of thought, reasoning "
    "process, or internal monologue. Output ONLY the final scouting report in 2-3 "
    "concise paragraphs. Do not use introductory filler like 'Here is the scouting "
    "report' or 'Based on the data'. Just start the analysis directly with the "
    "player's name or tactical role."
)

_JARGON_BAN = (
    "\n\nSTRICT LANGUAGE RULE: Never use these words: 'posterior', 'HDI', "
    "'Bayesian', 'shrinkage', 'percentile rank', 'confidence score', 'prior', "
    "'credible interval'. Write as a football analyst speaks on TV — for someone "
    "who watches games but does not read academic papers."
)

DATA_ANALYST_SYSTEM = (
    "You are an elite football scout covering FIFA World Cup 2026. "
    "Write a concise tactical scouting report in 3-4 short paragraphs. "
    "Cite the specific numbers provided to explain the player's strengths, "
    "weaknesses, and role in plain football language. Be direct and professional. "
    "Do not invent any statistics not given to you."
    + _ANTI_YAPPING + _JARGON_BAN
)

TRADITIONAL_SCOUT_SYSTEM = (
    "You are a traditional football scout covering FIFA World Cup 2026. "
    "Match data for this player is limited — write an impressionistic scouting "
    "report in 2-3 short paragraphs based on their position and playing style. "
    "YOU ARE STRICTLY FORBIDDEN from inventing, hallucinating, or mentioning "
    "specific statistical numbers, xG values, or ratings not explicitly provided. "
    "Focus on their tactical role and positional characteristics."
    + _ANTI_YAPPING + _JARGON_BAN
)


def _build_user_message(p: dict, high_confidence: bool) -> str:
    name      = p.get("name") or p["reep_id"]
    nat       = p.get("nationality") or "nationality unknown"
    position  = p.get("position_detail") or p.get("position_macro") or "Unknown position"
    archetype = p.get("cluster_label") or position
    shrinkage = p.get("shrinkage_weight", 0.5)
    wc_pct    = round((1.0 - shrinkage) * 100)
    club_pct  = 100 - wc_pct
    pct_rank  = p.get("percentile_rank", 0.5)
    pct_top   = max(1, round((1 - pct_rank) * 100))
    hdi_low   = round(p.get("hdi_low", 0.0), 2)
    hdi_high  = round(p.get("hdi_high", 10.0), 2)
    post_mean = round(p.get("posterior_mean", 5.0), 2)
    wc_mins   = round(p.get("wc_minutes", 0))

    if high_confidence:
        return (
            f"Generate a tactical scouting report for {name} ({nat}).\n\n"
            f"Position: {position}\n"
            f"Playing style: {archetype}\n\n"
            f"Performance data:\n"
            f"- Overall rating: {post_mean} out of 10"
            f" — ranks in the top {pct_top}% of {position.lower()}s at this tournament\n"
            f"- Rating likely between {hdi_low} and {hdi_high} (accounting for match sample size)\n"
            f"- {club_pct}% of rating comes from club form (last 2 seasons);"
            f" {wc_pct}% from this World Cup\n"
            f"- Played {wc_mins} minutes at this World Cup\n"
        )
    return (
        f"Write a scouting report for {name} ({nat}).\n\n"
        f"Position: {position}\n"
        f"Playing style: {archetype}\n"
        f"World Cup minutes: {wc_mins}\n"
        f"Note: Limited match data — describe their typical tactical role and"
        f" positional characteristics only."
    )


def _call_openrouter(api_key: str, model: str, system: str, user: str) -> str | None:
    """
    Call OpenRouter chat completions. Returns narrative text or None on failure.

    Retries on HTTP 429 with exponential backoff (honouring a Retry-After
    header when the API sends one) — free-tier models rate-limit aggressively
    and a single retry-less attempt fails most calls in a tight loop.
    """
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model":       model,
        "messages":    [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens":  450,
        "temperature": 0.7,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization":  f"Bearer {api_key}",
            "Content-Type":   "application/json",
            "HTTP-Referer":   "https://truescout.vercel.app",
            "X-Title":        "TrueScout WC 2026",
        },
        method="POST",
    )

    backoff = BACKOFF_BASE_S
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            text = body["choices"][0]["message"]["content"]
            return text.strip() if text else None
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < MAX_RETRIES:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                wait = float(retry_after) if retry_after else backoff
                logger.warning(
                    "OpenRouter rate-limited (429) — retry %d/%d in %.1fs",
                    attempt, MAX_RETRIES - 1, wait,
                )
                time.sleep(wait)
                backoff *= 2
                continue
            logger.warning("OpenRouter call failed: HTTP %d %s", exc.code, exc.reason)
            return None
        except Exception as exc:
            logger.warning("OpenRouter call failed: %s", exc)
            return None
    return None


def main(
    limit: int = DEFAULT_LIMIT,
    min_confidence: float = DEFAULT_MIN_CONF,
    force: bool = False,
) -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.info("OPENROUTER_API_KEY not set — skipping narrative pre-generation.")
        return

    model = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")

    if not PLAYERS_JSON.exists():
        logger.warning("players.json not found at %s — run export_json.py first.", PLAYERS_JSON)
        return

    players = json.loads(PLAYERS_JSON.read_text(encoding="utf-8"))
    logger.info("Loaded %d players from players.json.", len(players))

    # Filter and sort: most-confident first (they'll benefit most from a cached report)
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
    CIRCUIT_BREAKER = 8   # consecutive failures after retry exhaustion → likely daily cap hit

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
        user   = _build_user_message(p, high_confidence)

        narrative = _call_openrouter(api_key, model, system, user)
        if not narrative:
            consecutive_failures += 1
            logger.warning("No narrative returned for %s (%s) — skipping.", reep_id, p.get("name"))
            if consecutive_failures >= CIRCUIT_BREAKER:
                logger.warning(
                    "%d consecutive failures after retry exhaustion — likely the OpenRouter "
                    "daily free-tier cap (50 req/day without purchased credits). Stopping early; "
                    "remaining players will be picked up on a future run.",
                    consecutive_failures,
                )
                break
            time.sleep(CALL_DELAY_S)
            continue
        consecutive_failures = 0

        payload = {
            "narrative":    narrative,
            "voice":        voice,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "[%d/%d] %s — %s — %d chars",
            generated + 1, limit,
            p.get("name") or reep_id,
            voice,
            len(narrative),
        )
        generated += 1
        time.sleep(CALL_DELAY_S)

    logger.info(
        "Narrative generation complete: %d generated, %d already cached, %d skipped (no narrative).",
        generated,
        skipped,
        len(candidates) - generated - skipped,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description="Pre-generate player scouting narratives.")
    parser.add_argument("--limit",          type=int,   default=DEFAULT_LIMIT,
                        help=f"Max new reports to generate (default {DEFAULT_LIMIT})")
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONF,
                        help=f"Minimum confidence_score to include (default {DEFAULT_MIN_CONF})")
    parser.add_argument("--force",          action="store_true",
                        help="Overwrite existing cached reports")
    args = parser.parse_args()
    main(limit=args.limit, min_confidence=args.min_confidence, force=args.force)
