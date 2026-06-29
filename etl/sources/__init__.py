"""
Ingestion sources — Phase 1.

Modules to implement:
  sofascore.py      — curl_cffi TLS-spoof scraper; integer-ID resolution chain
                      (scheduled-events → eventId → lineups/statistics → teamId/playerId)
  espn.py           — ESPN public API fallback; JSON schema validation
  soccerdata_pull.py — soccerdata wrappers for FBref (club priors) and Club Elo
                       (league-strength coefficients)
"""
