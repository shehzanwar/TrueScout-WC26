"""
ETL pipeline package.

Sub-packages:
  etl.db        — DuckDB connection management and schema bootstrap
  etl.sources   — Data scrapers (Sofascore, ESPN, FBref/Club Elo via soccerdata)
  etl.matching  — Cross-source player/team ID reconciliation
  etl.models    — Bayesian ratings, K-Means archetypes, Monte Carlo sim (Phase 2)
"""
