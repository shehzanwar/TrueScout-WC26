"""
Statistical models — Phase 2.

Modules to implement:
  archetypes.py   — K-Means clustering (scikit-learn); silhouette validation
  ratings.py      — Hierarchical Bayesian player ratings (PyMC / NumPyro);
                    partial pooling shrinks low-minute players to archetype mean
  simulation.py   — Monte Carlo knockout-bracket simulation (NumPy, 10k+ iters)
  brier.py        — Brier-score tracker: TrueScout vs market odds
  confidence.py   — Per-player confidence score (league tier + WC minutes)
"""
