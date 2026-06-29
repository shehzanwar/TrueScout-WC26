"""
Health-check endpoints.

GET /health/ping   — minimal liveness probe (no DB required)
GET /health/       — readiness probe: confirms DB is reachable and schema is in place
GET /health/db     — detailed table row-counts for quick sanity checks
"""
import logging

import duckdb
from fastapi import APIRouter, Depends

from api.deps import get_db
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])

# Tables that must exist for the app to be considered ready
_CORE_TABLES = {
    "leagues", "teams", "players", "squads",
    "club_priors", "matches", "player_match_stats",
    "player_ratings", "archetypes", "brier_log", "simulations",
}


@router.get("/ping")
def ping() -> dict:
    """Liveness probe — returns immediately without touching the database."""
    return {"status": "ok", "message": "pong"}


@router.get("/")
def readiness(db: duckdb.DuckDBPyConnection = Depends(get_db)) -> dict:
    """
    Readiness probe.

    Verifies the database is reachable and all core tables exist.
    Returns HTTP 200 either way; the `status` field reflects readiness.
    """
    try:
        rows = db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY 1"
        ).fetchall()
        present = {r[0] for r in rows}
        missing = sorted(_CORE_TABLES - present)
        return {
            "status": "ready" if not missing else "degraded",
            "db": "connected",
            "db_path": settings.duckdb_path,
            "tables_present": sorted(present),
            "tables_missing": missing,
        }
    except Exception as exc:
        logger.exception("Readiness check failed")
        return {"status": "error", "detail": str(exc)}


@router.get("/db")
def db_stats(db: duckdb.DuckDBPyConnection = Depends(get_db)) -> dict:
    """
    Row counts for every table — quick data-population sanity check.

    Returns an empty dict for each table that has no rows yet.
    """
    try:
        rows = db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY 1"
        ).fetchall()
        counts: dict[str, int] = {}
        for (table,) in rows:
            result = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
            counts[table] = result[0] if result else 0
        return {"status": "ok", "row_counts": counts}
    except Exception as exc:
        logger.exception("DB stats failed")
        return {"status": "error", "detail": str(exc)}
