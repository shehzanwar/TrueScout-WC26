"""
Cross-source ID matching — Phase 1.

Resolves the same player or team across Sofascore, FBref, and ESPN by
name-normalisation + fuzzy matching, producing a canonical ID used in
the DuckDB `players` and `teams` tables.
"""
