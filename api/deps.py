"""
FastAPI dependency factories.

Usage in a route:
    from api.deps import get_db
    import duckdb

    @router.get("/example")
    def example(db: duckdb.DuckDBPyConnection = Depends(get_db)):
        return db.execute("SELECT 1").fetchone()
"""
from typing import Generator

import duckdb

from etl.db.connection import get_read_conn


def get_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """
    Open a read-only DuckDB connection, yield it to the route handler,
    then close it on teardown.  One connection per HTTP request.
    """
    conn = get_read_conn()
    try:
        yield conn
    finally:
        conn.close()
