"""
TrueScout — Nightly Batch Orchestrator
=======================================
Runs the full pipeline in dependency order:
  1.   ESPN pull          (knockout matches + odds)
  2.   Sofascore pull     (knockout lineups / stats)
  3.   Load group stage   (upsert new matches to Silver)
  4.   Load identity      (Reep people.parquet → identity_players crosswalk)
  4.5. Market values      (botasaurus headless fetch; Windows-only, skipped on CI)
  5.   Build features     (unified Silver feature matrix)
  6.   Bayesian ratings   (update posteriors with new WC likelihood)
  7.   Monte Carlo sim    (re-simulate remaining bracket)
  8.   Brier tracker      (grade model against new market odds)
  9.   Export JSON        (write frontend/public/data/*.json for Vercel)
  9.5. Verify outputs     (hard assertions on exported JSON — hard-fail gate)
  9.6. Chat index         (compact tournament snapshot for AI chat; soft-fail)

Designed for Windows Task Scheduler (single-user V1) and GitHub Actions.

Exit code semantics ("Local Scrape, Cloud Math" pattern):
  - Steps 1–4 are INGESTION (non-critical):  Sofascore is permanently blocked
    by Cloudflare on datacenter IPs.  A Sofascore 403 should NOT fail the CI
    job — committed Parquets provide the baseline WC data.  The identity load
    (step 4) is also non-critical: if people.parquet is missing the model
    falls back to prior-only ratings.
  - Steps 5–9 are CRITICAL: if any math or export step fails the process
    exits 1, failing the GitHub Action so the breakage is visible.

Run manually:
    C:\\Users\\couga\\miniconda3\\envs\\wc26\\python.exe run_nightly.py

Task Scheduler action:
    Program:   C:\\Users\\couga\\miniconda3\\envs\\wc26\\python.exe
    Arguments: S:\\Projects\\TrueScout\\run_nightly.py
    Start in:  S:\\Projects\\TrueScout
"""
import logging
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Load .env from project root before any module reads os.environ
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # python-dotenv not installed; set env vars manually or via Task Scheduler


# ---------------------------------------------------------------------------
# Logging — file + console, configured before any module imports
# ---------------------------------------------------------------------------

LOG_DIR  = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "nightly.log"

_fmt = "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"
_datefmt = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=_fmt,
    datefmt=_datefmt,
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=7, encoding="utf-8"),
    ],
)
# Silence noisy third-party loggers
for _noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("truescout.nightly")


# ---------------------------------------------------------------------------
# Pipeline definition
# ---------------------------------------------------------------------------

def _step(name: str, fn, *, hard_fail: bool = False) -> bool:
    """
    Run one pipeline step. Returns True on success, False on failure.
    If hard_fail=True, re-raises the exception and aborts the pipeline.
    """
    logger.info("── Step: %s ──────────────────────────────────", name)
    t0 = time.monotonic()
    try:
        fn()
        elapsed = time.monotonic() - t0
        logger.info("   ✓ %s completed in %.1fs", name, elapsed)
        return True
    except Exception as exc:
        elapsed = time.monotonic() - t0
        if hard_fail:
            logger.critical("   ✗ %s FATAL ERROR after %.1fs — aborting pipeline", name, elapsed, exc_info=True)
            raise
        logger.error("   ✗ %s failed after %.1fs — continuing with existing data", name, elapsed)
        logger.error("     %s: %s", type(exc).__name__, exc)
        return False


def run_pipeline() -> dict[str, bool]:
    """
    Execute all 9 steps in order.  Returns a dict of step_name → success.
    """
    # Import here so logging is configured first and module-level basicConfig
    # calls in each module are no-ops (logging already initialised).
    from etl.sources.espn_pull           import main as espn_main
    from etl.sources.sofascore_pull      import main as sofascore_main
    from etl.load.load_group_stage       import main as load_main
    from etl.load.load_identity          import main as identity_main
    from etl.silver.build_features       import main as features_main
    from etl.models.archetypes           import main as archetypes_main
    from etl.models.bayesian_ratings     import main as ratings_main
    from etl.models.calibration          import fit_scale as _fit_scale
    from etl.models.monte_carlo_sim      import main as sim_main
    from etl.models.brier_tracker        import main as brier_main
    from etl.export_json                 import main as export_main
    from etl.verify_outputs              import main as verify_main
    from etl.build_chat_index            import main as chat_index_main

    # botasaurus requires a real browser (Edge/Chrome); not available on GitHub Actions.
    # Import here so a missing dep silently degrades to skip rather than hard-crashing.
    _market_value_main = None
    try:
        from etl.sources.market_value_pull import main as _market_value_main
    except ImportError:
        logger.warning("   ⚠  botasaurus not installed — market_value_pull step will be skipped")

    results: dict[str, bool] = {}

    # Step 1 — ESPN pull (knockout mode: fetches R32→F matches + pre-match odds)
    results["1_espn_pull"] = _step(
        "ESPN pull (knockout)",
        lambda: espn_main(date_str=None, group_stage=False, knockout=True),
    )

    # Step 2 — Sofascore pull (group stage — rounds 1/2/3 via /events/round/{N})
    # Soft-fail: Cloudflare blocks are expected; downstream steps use cached data.
    results["2_sofascore_pull"] = _step(
        "Sofascore pull (group stage rounds)",
        lambda: sofascore_main(round_numbers=[], all_rounds=True),
    )

    # Step 2.5 — Sofascore knockout pull via cuptrees bracket
    # /events/round/{N} returns 404 for R32/R16/QF/SF/F; cuptrees endpoint works.
    # Soft-fail: if cuptrees is unavailable we fall back to previously cached parquets.
    results["2_sofascore_knockout"] = _step(
        "Sofascore pull (knockout bracket)",
        lambda: sofascore_main(round_numbers=[], all_rounds=False, knockout=True),
    )
    if not results["2_sofascore_pull"] and not results["2_sofascore_knockout"]:
        logger.warning(
            "   ⚠  Both Sofascore steps failed — Steps 5–7 will use previously cached "
            "lineups/stats. Model quality is unaffected until new matches are played."
        )

    # Step 3 — Load group stage / knockout results to Silver
    results["3_load_matches"] = _step(
        "Load matches (group stage + knockout)",
        load_main,
    )

    # Step 4 — Load identity crosswalk (Reep people.parquet → identity_players)
    # Non-critical: if people.parquet is absent the model falls back to prior-only.
    results["4_load_identity"] = _step(
        "Load identity crosswalk",
        identity_main,
    )

    # Step 4.5 — Fetch market values for WC players (Windows-only; skipped on CI)
    # Requires botasaurus (headless browser). Soft-fail — missing dep or Cloudflare
    # block should not abort the pipeline; market_value_eur column defaults to NULL.
    if _market_value_main is not None:
        results["4_market_values"] = _step(
            "Market value fetch (Sofascore/Transfermarkt)",
            _market_value_main,
        )
    else:
        results["4_market_values"] = False
        logger.info("   — Skipping market value fetch (botasaurus unavailable)")

    # Step 5 — Rebuild Silver feature matrix
    results["5_build_features"] = _step(
        "Build Silver feature matrix",
        features_main,
    )

    # Step 5.5 — K-Means archetype clustering (position-aware, 3-8 clusters)
    # Reads features.parquet written by step 5; must run before bayesian_ratings
    # so the archetypes table is fresh when ratings joins cluster_id.
    results["5_archetypes"] = _step(
        "K-Means archetype clustering",
        archetypes_main,
    )

    # Step 6 — Update Bayesian posteriors
    results["6_bayesian_ratings"] = _step(
        "Bayesian ratings update",
        ratings_main,
    )

    # Step 6.5 — Fit calibration scale (Davidson BT, grid search over brier_log)
    # Runs after ratings so strengths are current; result persisted to model_params.
    # Soft-fail: < 12 graded matches → falls back to DEFAULT_SCALE=1.0.
    def _run_fit_scale() -> None:
        import duckdb as _duckdb
        _conn = _duckdb.connect(str(__import__("config").settings.duckdb_path))
        try:
            _fit_scale(_conn)
        finally:
            _conn.close()

    results["6_fit_calibration"] = _step(
        "Fit calibration scale",
        _run_fit_scale,
    )

    # Step 7 — Re-simulate remaining bracket
    results["7_monte_carlo_sim"] = _step(
        "Monte Carlo bracket simulation",
        sim_main,
    )

    # Step 8 — Grade completed matches against model + market odds
    results["8_brier_tracker"] = _step(
        "Brier score tracker",
        brier_main,
    )

    # Step 9 — Export static JSON for Vercel (critical: Vercel deploy depends on this)
    results["9_export_json"] = _step(
        "Export static JSON",
        export_main,
    )

    # Step 9.5 — Verify exported JSON (hard-fail: bad data must not reach Vercel)
    results["9_verify_outputs"] = _step(
        "Verify exported JSON",
        verify_main,
        hard_fail=True,
    )

    # Step 9.6 — Build chat knowledge index (soft-fail: non-critical convenience layer)
    # Note: narrative pre-gen removed — Gemini quota is reserved for on-demand chat + scouting reports.
    results["9_chat_index"] = _step(
        "Build chat knowledge index",
        chat_index_main,
    )

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    wall_start = datetime.now(timezone.utc)
    t0 = time.monotonic()

    logger.info("=" * 72)
    logger.info("  TrueScout Nightly Batch — %s UTC", wall_start.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 72)

    try:
        results = run_pipeline()
    except Exception:
        # Only raised by a hard_fail step (none currently configured)
        logger.critical("Pipeline aborted by a fatal step failure.")
        sys.exit(1)

    elapsed = time.monotonic() - t0
    passed  = sum(v for v in results.values())
    total   = len(results)

    logger.info("=" * 72)
    logger.info("  Batch complete — %d/%d steps succeeded — %.1fs total", passed, total, elapsed)
    for step, ok in results.items():
        icon = "✓" if ok else "✗"
        logger.info("    %s  %s", icon, step)
    logger.info("=" * 72)

    # ── Exit logic: distinguish ingestion failures from pipeline failures ────
    # Ingestion steps (1–3) are non-critical: Sofascore is permanently blocked
    # on GitHub Actions datacenter IPs.  Only math/export failures are fatal.
    _INGESTION = {"1_espn_pull", "2_sofascore_pull", "2_sofascore_knockout",
                  "3_load_matches", "4_load_identity",
                  "4_market_values",    # botasaurus unavailable on CI; skipped by design
                  "5_archetypes",       # soft-fail: sklearn optional dep, falls back to stale clusters
                  "6_fit_calibration",  # soft-fail: < 12 graded matches → DEFAULT_SCALE used
                  "9_chat_index"}   # chat index: soft-fail (convenience layer, not blocking)
    _CRITICAL  = {"5_build_features", "6_bayesian_ratings", "7_monte_carlo_sim",
                  "8_brier_tracker", "9_export_json", "9_verify_outputs"}

    failed            = {k for k, ok in results.items() if not ok}
    critical_failures = failed & _CRITICAL
    ingestion_failures= failed & _INGESTION

    if critical_failures:
        logger.error(
            "Critical step(s) failed — exiting 1: %s",
            ", ".join(sorted(critical_failures)),
        )
        sys.exit(1)

    if ingestion_failures:
        logger.warning(
            "Non-critical ingestion step(s) failed (%s) — "
            "using baseline Git data; downstream math succeeded. "
            "Vercel deployment will proceed.",
            ", ".join(sorted(ingestion_failures)),
        )
    # else: all steps passed — exit 0 implicitly


if __name__ == "__main__":
    main()
