"""
DuckDB connection utilities and schema bootstrap.

  from etl.db.connection import write_conn, get_read_conn, query_parquet
  from etl.db.init_db    import init_schema, refresh_parquet_views
"""
from etl.db.connection import write_conn, get_read_conn, close_write_conn, query_parquet

__all__ = ["write_conn", "get_read_conn", "close_write_conn", "query_parquet"]
