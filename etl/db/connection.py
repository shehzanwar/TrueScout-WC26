"""
DuckDB connection management for TrueScout.

Connection pattern
──────────────────
• One singleton *write* connection per process, guarded by a threading.Lock.
  The nightly batch ETL uses this exclusively.
• Per-request *read-only* connections for FastAPI endpoints — each caller
  opens one and is responsible for closing it (use the `get_db` dependency
  in api/deps.py, not this module directly).

DuckDB v1.0+ supports multiple concurrent in-process connections to the same
database file, so reads and the write connection coexist without locking issues.
"""
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import duckdb

from config import settings

logger = logging.getLogger(__name__)

_write_conn: duckdb.DuckDBPyConnection | None = None
_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_db_dir() -> None:
    Path(settings.duckdb_path).parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Write connection (singleton, serialised)
# ---------------------------------------------------------------------------

def get_write_conn() -> duckdb.DuckDBPyConnection:
    """Return (or lazily create) the singleton read-write connection."""
    global _write_conn
    if _write_conn is None:
        _ensure_db_dir()
        _write_conn = duckdb.connect(settings.duckdb_path)
        logger.info("DuckDB write connection opened -> %s", settings.duckdb_path)
    return _write_conn


@contextmanager
def write_conn() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """
    Context manager for any operation that writes to DuckDB.

    Serialises concurrent writes with a module-level lock so the nightly
    batch and any manual admin scripts cannot race each other.

    Usage:
        with write_conn() as db:
            db.execute("INSERT INTO leagues VALUES (...)")
    """
    with _write_lock:
        yield get_write_conn()


def close_write_conn() -> None:
    """Close the write connection — called from the FastAPI shutdown hook."""
    global _write_conn
    if _write_conn is not None:
        _write_conn.close()
        _write_conn = None
        logger.info("DuckDB write connection closed.")


# ---------------------------------------------------------------------------
# Read connections (one per request / query)
# ---------------------------------------------------------------------------

def get_read_conn() -> duckdb.DuckDBPyConnection:
    """
    Return a cursor on the singleton write connection for read queries.

    DuckDB disallows mixing read_only and read-write connections to the same
    file. Using a cursor shares the underlying connection safely — each cursor
    has its own result state and is closed independently by the caller.
    """
    return get_write_conn().cursor()


# ---------------------------------------------------------------------------
# Parquet query helper
# ---------------------------------------------------------------------------

def query_parquet(
    glob_path: str,
    where: str = "",
    conn: duckdb.DuckDBPyConnection | None = None,
) -> "pandas.DataFrame":
    """
    Query Parquet files directly via DuckDB's read_parquet() without loading
    them into DuckDB tables first.

    Args:
        glob_path: Path glob, e.g. "data/bronze/sofascore/*.parquet"
        where:     Optional WHERE clause, e.g. "WHERE round = 'round_of_16'"
        conn:      Existing connection to reuse; creates a throwaway one if None.

    Returns:
        pandas DataFrame.

    Example:
        df = query_parquet("data/bronze/fbref/*.parquet", "WHERE season = '2024-25'")
    """
    import pandas as pd  # noqa: F401 — imported here to keep startup light

    # DuckDB needs forward slashes even on Windows
    safe_path = glob_path.replace("\\", "/")
    sql = f"SELECT * FROM read_parquet('{safe_path}', union_by_name=true) {where}"

    if conn is not None:
        return conn.execute(sql).df()

    _conn = get_read_conn()
    try:
        return _conn.execute(sql).df()
    finally:
        _conn.close()
