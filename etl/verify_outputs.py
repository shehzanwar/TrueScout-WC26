"""
Output verification gate — step 9.5 in the nightly pipeline.

Reads the four JSON files written by export_json.py and runs hard assertions.
If any assertion fails the function raises AssertionError, which run_nightly.py
treats as a critical failure (hard_fail=True) so CI turns red immediately.

Run standalone:
    python -m etl.verify_outputs
"""
import json
import logging
import math
import sys
from pathlib import Path

ROOT_DIR   = Path(__file__).parent.parent.resolve()
OUTPUT_DIR = ROOT_DIR / "frontend" / "public" / "data"

logger = logging.getLogger(__name__)

# Minimum player count below which we assume catastrophic data loss
_MIN_PLAYERS = 50

# Title probabilities must sum to this ± tolerance
_TITLE_PROB_SUM_TOLERANCE = 0.005

# All valid position_macro values — UNK is intentional for players
# whose position cannot be resolved from any of the three sources
# (Reep, Understat, Sofascore modal); they are excluded from
# percentile ranking but remain in the export.
_VALID_POSITIONS = {"GK", "DEF", "MID", "FWD", "UNK"}


class VerificationError(Exception):
    pass


def _load(filename: str) -> object:
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise VerificationError(f"Missing export file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VerificationError(f"Invalid JSON in {filename}: {exc}") from exc


def verify_simulations(data: dict) -> None:
    """Title probability sum across all remaining teams must be ~1.0."""
    rounds = data.get("rounds", [])
    if not rounds:
        logger.warning("verify_outputs: simulations.json has no rounds — skipping title_prob check")
        return

    # Use the last round's title_probs (they represent tournament title probability)
    all_title_probs = []
    for rnd in rounds:
        for team in rnd.get("teams", []):
            tp = team.get("title_prob")
            if tp is not None:
                all_title_probs.append(float(tp))

    if not all_title_probs:
        logger.warning("verify_outputs: no title_prob values found — skipping sum check")
        return

    # Title probs should sum to ≈ 1.0 (each team appears once per run)
    # De-dupe by taking max per team across rounds — the sim stores cumulative probs
    # per round so we take the earliest round where all teams still alive are listed.
    first_round_teams = rounds[0].get("teams", [])
    title_sum = sum(
        float(t["title_prob"]) for t in first_round_teams
        if t.get("title_prob") is not None
    )

    if not first_round_teams:
        return

    if abs(title_sum - 1.0) > _TITLE_PROB_SUM_TOLERANCE:
        raise VerificationError(
            f"title_prob sum = {title_sum:.4f} (expected 1.0 ± {_TITLE_PROB_SUM_TOLERANCE})"
        )
    logger.info("verify_outputs: title_prob sum = %.4f ✓", title_sum)


def verify_players(players: list) -> None:
    """Player list must be non-empty, all have reep_id, valid positions, numeric ratings."""
    n = len(players)
    if n < _MIN_PLAYERS:
        raise VerificationError(
            f"players.json has only {n} players (minimum {_MIN_PLAYERS}) — "
            "suspected data loss"
        )
    logger.info("verify_outputs: %d players ✓", n)

    bad_reep_ids = [
        p.get("reep_id") for p in players
        if not str(p.get("reep_id", "")).startswith("reep_")
    ]
    if bad_reep_ids:
        raise VerificationError(
            f"{len(bad_reep_ids)} players with malformed reep_id (sample: {bad_reep_ids[:5]})"
        )

    bad_positions = [
        (p.get("reep_id"), p.get("position_macro")) for p in players
        if p.get("position_macro") not in _VALID_POSITIONS
    ]
    if bad_positions:
        raise VerificationError(
            f"{len(bad_positions)} players with invalid position_macro "
            f"(sample: {bad_positions[:5]})"
        )

    nan_posterior = []
    out_of_range_confidence = []
    for p in players:
        pm = p.get("posterior_mean")
        cs = p.get("confidence_score")
        hl = p.get("hdi_low")
        hh = p.get("hdi_high")

        if pm is None or math.isnan(pm):
            nan_posterior.append(p.get("reep_id"))

        if cs is not None and not (0.0 <= cs <= 1.0):
            out_of_range_confidence.append((p.get("reep_id"), cs))

        # hdi_low <= posterior_mean <= hdi_high (unless all None)
        if pm is not None and hl is not None and hh is not None:
            if not (hl <= pm <= hh):
                logger.warning(
                    "verify_outputs: %s HDI anomaly: low=%.3f mean=%.3f high=%.3f",
                    p.get("reep_id"), hl, pm, hh,
                )

    if nan_posterior:
        raise VerificationError(
            f"{len(nan_posterior)} players with null/NaN posterior_mean "
            f"(sample: {nan_posterior[:5]})"
        )

    out_of_range_rating = [
        (p.get("reep_id"), p.get("posterior_mean")) for p in players
        if p.get("posterior_mean") is not None and not (4.0 <= p["posterior_mean"] <= 9.5)
    ]
    if out_of_range_rating:
        raise VerificationError(
            f"{len(out_of_range_rating)} players with posterior_mean outside [4.0, 9.5] "
            f"(sample: {out_of_range_rating[:3]}) — clamp missing in export_json.py"
        )

    if out_of_range_confidence:
        raise VerificationError(
            f"{len(out_of_range_confidence)} players with confidence_score out of [0,1] "
            f"(sample: {out_of_range_confidence[:3]})"
        )

    logger.info("verify_outputs: player fields validated ✓")


def verify_matchups(matchups: dict) -> None:
    """At least one round present; every match has home/away names and a date."""
    if not matchups:
        raise VerificationError("matchups.json is empty")

    missing_fields = []
    for round_code, rnd in matchups.items():
        for m in rnd.get("matches", []):
            h = m.get("home", {})
            a = m.get("away", {})
            if not h.get("name") or not a.get("name"):
                missing_fields.append(m.get("event_id"))
            if not m.get("match_date"):
                missing_fields.append(m.get("event_id"))

    if missing_fields:
        raise VerificationError(
            f"{len(missing_fields)} matchups missing home/away name or match_date "
            f"(event_ids: {missing_fields[:5]})"
        )

    total = sum(r.get("n_matches", 0) for r in matchups.values())
    logger.info("verify_outputs: %d matchups across %d rounds ✓", total, len(matchups))


def verify_brier(brier: dict) -> None:
    """Brier log may be empty early in the tournament — just check structure."""
    summary = brier.get("summary")
    if summary is None:
        raise VerificationError("brier.json missing 'summary' key")

    avg_brier = summary.get("avg_brier_model")
    if avg_brier is not None and not (0.0 <= avg_brier <= 0.5):
        raise VerificationError(
            f"avg_brier_model={avg_brier:.4f} outside expected range [0, 0.5] "
            "(a coin flip scores 0.25; values above 0.5 indicate a labelling error)"
        )

    logger.info(
        "verify_outputs: brier summary ok — %d matches graded ✓",
        summary.get("n_matches", 0),
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    errors: list[str] = []
    checks = [
        ("simulations.json", verify_simulations),
        ("players.json",     verify_players),
        ("matchups.json",    verify_matchups),
        ("brier.json",       verify_brier),
    ]

    for filename, fn in checks:
        try:
            data = _load(filename)
            fn(data)
        except VerificationError as exc:
            errors.append(f"{filename}: {exc}")
            logger.error("FAIL  %s — %s", filename, exc)
        except Exception as exc:
            errors.append(f"{filename}: unexpected error — {exc}")
            logger.exception("FAIL  %s — unexpected error", filename)

    if errors:
        logger.critical(
            "verify_outputs: %d assertion(s) failed:\n  %s",
            len(errors), "\n  ".join(errors),
        )
        raise AssertionError(f"Output verification failed ({len(errors)} errors)")

    logger.info("verify_outputs: all checks passed ✓")


if __name__ == "__main__":
    main()
