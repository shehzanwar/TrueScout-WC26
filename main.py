"""
TrueScout — FastAPI application entry point.

Development:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Production (single worker — DuckDB is single-write-connection):
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from etl.db.connection import get_write_conn, close_write_conn
from etl.db.init_db import init_schema, _create_parquet_dirs
from api.routes import health, players, matchups, simulations, brier

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("truescout")


# ---------------------------------------------------------------------------
# Lifespan  (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== TrueScout starting ===")

    # Ensure Parquet cache directories exist (idempotent)
    _create_parquet_dirs()

    # Open the write connection and run schema bootstrap (idempotent)
    conn = get_write_conn()
    init_schema(conn)

    logger.info("TrueScout ready — DB: %s", settings.duckdb_path)
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("=== TrueScout shutting down ===")
    close_write_conn()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="TrueScout",
    description=(
        "Knockout Stage Intelligence Dashboard — 2026 FIFA World Cup.\n\n"
        "Hierarchical Bayesian player ratings · Monte Carlo bracket simulation · "
        "Brier-score calibration tracker · RAG tactical narratives."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET"],   # V1 is read-only from the frontend
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health.router)
app.include_router(players.router)
app.include_router(matchups.router)
app.include_router(simulations.router)
app.include_router(brier.router)

# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/", tags=["root"])
def root() -> dict:
    """API root — links to docs and key endpoints."""
    return {
        "project":    "TrueScout",
        "version":    "1.0.0",
        "tournament": "FIFA World Cup 2026",
        "docs":        "/docs",
        "endpoints": {
            "health":      "/health",
            "db_stats":    "/health/db",
            "player":      "/api/v1/players/{reep_id}",
            "matchups":    "/api/v1/matchups?round=R32",
            "simulations": "/api/v1/simulations",
            "brier":       "/api/v1/brier",
        },
    }
