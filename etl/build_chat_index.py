"""
build_chat_index.py — Build chat_index.json for the TrueScout AI assistant.

Reads the already-exported static JSON files and distils them into a compact
knowledge context that the /api/chat route injects into every Gemini prompt.
Keeps the context under ~4,000 tokens to leave headroom for conversation.

Run: python -m etl.build_chat_index
     (also called as step 9.7 by run_nightly.py after export_json.py)
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR   = Path(__file__).parent.parent / "frontend" / "public" / "data"
OUTPUT_FILE = DATA_DIR / "chat_index.json"

ROUND_LABELS = {
    "GS": "Group Stage", "R32": "Round of 32", "R16": "Round of 16",
    "QF": "Quarterfinals", "SF": "Semifinals", "F": "Final", "W": "Winner",
}

def _read(name: str) -> dict | list | None:
    path = DATA_DIR / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build() -> dict:
    sims     = _read("simulations.json") or {}
    matchups = _read("matchups.json") or {}
    top_stats = _read("top_stats.json") or {}
    insights = _read("insights.json") or {}
    awards   = _read("awards.json") or {}

    now = datetime.now(timezone.utc).isoformat()
    run_date = sims.get("run_date", "unknown")

    # ── Tournament stage ────────────────────────────────────────────────────
    # Find the earliest round with ungraded (future) matches
    ROUND_ORDER = ["R32", "R16", "QF", "SF", "F"]
    current_stage = "Unknown"
    for rnd in ROUND_ORDER:
        rnd_data = matchups.get(rnd, {})
        matches = rnd_data.get("matches", [])
        if any(not m.get("is_completed") for m in matches):
            current_stage = ROUND_LABELS.get(rnd, rnd)
            break
    else:
        current_stage = "Final concluded"

    # ── Champion probabilities (top 12) ─────────────────────────────────────
    all_teams: dict[str, float] = {}
    for rnd in sims.get("rounds", []):
        for t in rnd.get("teams", []):
            tid = t.get("team_id", "")
            tp  = float(t.get("title_prob") or 0)
            if tid and tp > 0:
                all_teams[tid] = max(all_teams.get(tid, 0), tp)
    champion_probs = sorted(all_teams.items(), key=lambda x: -x[1])[:12]

    # ── Upcoming matches ─────────────────────────────────────────────────────
    upcoming = []
    for rnd_code in ROUND_ORDER:
        rnd_data = matchups.get(rnd_code, {})
        for m in rnd_data.get("matches", []):
            if m.get("is_completed"):
                continue
            home = m.get("home", {})
            away = m.get("away", {})
            entry = {
                "round":     ROUND_LABELS.get(rnd_code, rnd_code),
                "date":      m.get("match_date", ""),
                "home":      home.get("name", "?"),
                "away":      away.get("name", "?"),
            }
            mp = home.get("model_advance_prob")
            if mp is not None:
                entry["home_win_prob"] = round(float(mp) * 100, 1)
                entry["away_win_prob"] = round((1 - float(mp)) * 100, 1)
            upcoming.append(entry)
    upcoming = upcoming[:8]

    # ── Recent results ───────────────────────────────────────────────────────
    recent: list[dict] = []
    for rnd_code in ROUND_ORDER:
        rnd_data = matchups.get(rnd_code, {})
        for m in rnd_data.get("matches", []):
            if not m.get("is_completed"):
                continue
            home = m.get("home", {})
            away = m.get("away", {})
            hs   = home.get("score")
            as_  = away.get("score")
            recent.append({
                "round":  ROUND_LABELS.get(rnd_code, rnd_code),
                "date":   m.get("match_date", ""),
                "home":   home.get("name", "?"),
                "away":   away.get("name", "?"),
                "score":  f"{hs}–{as_}" if hs is not None and as_ is not None else "?",
                "winner": m.get("winner") or (
                    home.get("name") if (hs or 0) > (as_ or 0) else away.get("name")
                ),
            })
    # Most recent 8 completed matches
    recent = recent[-8:]

    # ── Top performers ───────────────────────────────────────────────────────
    scorers   = [
        {"name": p["name"], "team": p.get("national_team", ""), "goals": int(p["value"])}
        for p in (top_stats.get("top_scorers") or [])[:5]
    ]
    assisters = [
        {"name": p["name"], "team": p.get("national_team", ""), "assists": int(p["value"])}
        for p in (top_stats.get("top_assists") or [])[:3]
    ]
    defensive = [
        {"name": p["name"], "team": p.get("national_team", ""), "actions": int(p["value"])}
        for p in (top_stats.get("top_defensive") or [])[:3]
    ]

    # ── Awards ───────────────────────────────────────────────────────────────
    award_summary = {}
    for key in ("golden_boot", "silver_boot", "bronze_boot"):
        e = awards.get(key)
        if e:
            award_summary[key] = {"name": e["name"], "team": e.get("national_team", ""), "goals": int(e["value"])}
    if awards.get("golden_glove"):
        g = awards["golden_glove"]
        award_summary["golden_glove"] = {"name": g["name"], "team": g.get("national_team", ""), "saves": int(g["value"])}
    if awards.get("golden_ball_candidates"):
        award_summary["golden_ball_leader"] = {
            "name":   awards["golden_ball_candidates"][0]["name"],
            "team":   awards["golden_ball_candidates"][0].get("national_team", ""),
            "rating": awards["golden_ball_candidates"][0]["value"],
        }

    return {
        "generated_at":    now,
        "run_date":        run_date,
        "current_stage":   current_stage,
        "champion_probs":  [{"team": t, "prob_pct": round(p * 100, 1)} for t, p in champion_probs],
        "upcoming_matches": upcoming,
        "recent_results":  recent,
        "top_scorers":     scorers,
        "top_assisters":   assisters,
        "top_defensive":   defensive,
        "awards":          award_summary,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    index = build()
    OUTPUT_FILE.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"chat_index.json — stage={index['current_stage']}, "
        f"{len(index['upcoming_matches'])} upcoming, "
        f"{len(index['recent_results'])} recent results, "
        f"{len(index['champion_probs'])} teams"
    )


if __name__ == "__main__":
    main()
