"""
K-Means archetype clustering — one pass per position bucket.

Reads:
  data/silver/player_stats/features.parquet
  data/silver/selected_features.json       (from feature_selection.py)

For each position bucket (GK, DEF, MID, FWD):
  1. Filter to players with at least one valid data source.
  2. Impute NaN with column median (robust; preserves population mean).
  3. RobustScaler — handles extreme outliers (Haaland xG, GK save spikes).
  4. KMeans k=3..8 — pick k with highest mean silhouette score.
  5. Upsert results to DuckDB archetypes table.
  6. Print top-5 players per cluster for tactical sanity check.

Usage:
    python -m etl.models.archetypes
    python -m etl.models.archetypes --validate  # skip DuckDB write
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import RobustScaler

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings
from etl.db.connection import write_conn

logger = logging.getLogger(__name__)

FEATURES_PATH   = Path(settings.parquet_silver_dir) / "player_stats" / "features.parquet"
SELECTIONS_PATH = Path(settings.parquet_silver_dir) / "selected_features.json"
K_RANGE         = range(3, 9)      # try k=3..8
MIN_CLUSTER_N   = 10               # require at least this many players per cluster

# Fallback features if selected_features.json is missing
_FALLBACK_FEATURES = {
    "GK":  ["wc_saves_per_90", "wc_rating_avg", "prior_xg_per_90"],
    "DEF": ["wc_tackles_per_90", "wc_interceptions_per_90", "wc_clearances_per_90",
            "prior_xg_per_90", "prior_xa_per_90", "wc_rating_avg"],
    "MID": ["prior_xg_per_90", "prior_xa_per_90", "prior_key_passes_per_90",
            "wc_xg_per_90", "wc_xa_per_90", "wc_rating_avg"],
    "FWD": ["prior_xg_per_90", "prior_npxg_per_90", "prior_shots_per_90",
            "wc_xg_per_90", "wc_shots_per_90", "wc_rating_avg"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_selections() -> dict[str, list[str]]:
    if SELECTIONS_PATH.exists():
        return json.loads(SELECTIONS_PATH.read_text())
    logger.warning("selected_features.json not found — using fallback features.")
    return _FALLBACK_FEATURES


def _best_k(X: np.ndarray, k_range: range) -> tuple[int, float, KMeans]:
    """Try each k; return (best_k, best_silhouette, fitted_KMeans)."""
    best_k, best_sil, best_km = k_range.start, -1.0, None
    for k in k_range:
        if X.shape[0] < k * MIN_CLUSTER_N:
            break  # not enough players for this k
        km = KMeans(n_clusters=k, n_init=15, random_state=42)
        labels = km.fit_predict(X)
        sil = silhouette_score(X, labels, sample_size=min(1000, len(X)), random_state=42)
        logger.debug("    k=%d  silhouette=%.4f", k, sil)
        if sil > best_sil:
            best_k, best_sil, best_km = k, sil, km
    return best_k, best_sil, best_km


def _cluster_bucket(
    df: pd.DataFrame,
    bucket: str,
    feature_cols: list[str],
) -> pd.DataFrame | None:
    """
    Cluster one position bucket.  Returns a DataFrame with columns:
      reep_id, position_bucket, cluster_id, silhouette_score
    or None if clustering was skipped.
    """
    sub = df[df["position_bucket"] == bucket].copy()
    logger.info("--- %s: %d players ---", bucket, len(sub))

    # Keep only columns that exist and have ≥30% non-NaN
    valid_cols = [
        c for c in feature_cols
        if c in sub.columns and sub[c].notna().mean() >= 0.30
    ]
    if len(valid_cols) < 2:
        logger.warning("  Not enough valid feature columns (%d) — skipping.", len(valid_cols))
        return None

    # Impute NaN with column median
    X_df = sub[valid_cols].copy()
    for col in valid_cols:
        X_df[col] = X_df[col].fillna(X_df[col].median())

    # Drop rows still containing NaN (edge case: all-NaN column after median impute)
    mask = X_df.notna().all(axis=1)
    sub   = sub[mask].reset_index(drop=True)
    X_df  = X_df[mask].reset_index(drop=True)

    if len(sub) < K_RANGE.start * MIN_CLUSTER_N:
        logger.warning(
            "  Too few players (%d) for k≥%d — skipping.", len(sub), K_RANGE.start
        )
        return None

    # Scale
    X = RobustScaler().fit_transform(X_df.values)

    # Find optimal k
    best_k, best_sil, km = _best_k(X, K_RANGE)
    logger.info(
        "  Best k=%d  silhouette=%.4f  (features: %s)",
        best_k, best_sil, ", ".join(valid_cols),
    )

    sub = sub.copy()
    sub["cluster_id"]       = km.labels_
    sub["silhouette_score"] = best_sil

    # Sanity-check: print top-5 per cluster ranked by WC rating (or prior xG)
    rank_col = (
        "wc_rating_avg"     if "wc_rating_avg"  in sub.columns else
        "prior_xg_per_90"   if "prior_xg_per_90" in sub.columns else
        valid_cols[0]
    )
    print(f"\n{'='*60}")
    print(f"  {bucket} archetypes (k={best_k}, silhouette={best_sil:.3f})")
    print(f"  Features: {', '.join(valid_cols)}")
    print('='*60)
    for cid in sorted(sub["cluster_id"].unique()):
        grp = sub[sub["cluster_id"] == cid].nlargest(5, rank_col, keep="all")
        # Compute mean profile for labelling
        means = X_df[sub["cluster_id"] == cid][valid_cols].mean()
        top_feat = means.abs().idxmax()
        print(f"\n  Cluster {cid}  (n={( sub['cluster_id']==cid).sum()})  "
              f"top feature: {top_feat}={means[top_feat]:.2f}")
        for _, row in grp.iterrows():
            name = row.get("player_name", "?")
            nat  = row.get("nationality", "")
            val  = row.get(rank_col, float("nan"))
            print(f"    {name} ({nat})  {rank_col}={val:.3f}")

    return sub[["reep_id", "position_bucket", "cluster_id", "silhouette_score"]].copy()


# ---------------------------------------------------------------------------
# DuckDB upsert
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT OR REPLACE INTO archetypes (reep_id, position_bucket, cluster_id, silhouette_score, updated_at)
VALUES (?, ?, ?, ?, now())
"""


def _upsert_archetypes(results: list[pd.DataFrame]) -> None:
    combined = pd.concat(results, ignore_index=True)
    with write_conn() as conn:
        for _, row in combined.iterrows():
            conn.execute(
                _UPSERT_SQL,
                [row["reep_id"], row["position_bucket"],
                 int(row["cluster_id"]), float(row["silhouette_score"])],
            )
    logger.info("Upserted %d rows -> archetypes", len(combined))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    logger.info("=== TrueScout Phase 2: archetypes ===")

    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true",
                        help="Run clustering and print results; skip DuckDB write.")
    args = parser.parse_args()

    if not FEATURES_PATH.exists():
        logger.error("features.parquet not found — run build_features.py first.")
        sys.exit(1)

    df          = pd.read_parquet(FEATURES_PATH)
    selections  = _load_selections()

    results: list[pd.DataFrame] = []
    for bucket in ["GK", "DEF", "MID", "FWD"]:
        feat_cols = selections.get(bucket, _FALLBACK_FEATURES.get(bucket, []))
        if not feat_cols:
            logger.warning("No features for %s — skipping.", bucket)
            continue
        result = _cluster_bucket(df, bucket, feat_cols)
        if result is not None:
            results.append(result)

    if not results:
        logger.error("No clustering results produced.")
        sys.exit(1)

    if args.validate:
        logger.info("--validate: skipping DuckDB write.")
    else:
        _upsert_archetypes(results)

    total_clustered = sum(len(r) for r in results)
    logger.info("=== Archetypes complete: %d players clustered ===", total_clustered)


if __name__ == "__main__":
    main()
