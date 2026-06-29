"""
Elastic Net feature selection for each position bucket.

Two-pass approach:
  Pass 1 — Correlation filter: for each pair with |r| > CORR_THRESHOLD, drop the
            member with lower variance (preserves the more discriminating stat).
  Pass 2 — ElasticNetCV: fit on the correlation-filtered features with
            wc_rating_avg as target; keep features with non-zero coefficients.
            Falls back to pass-1 features alone if too few players have WC data.

Output: data/silver/selected_features.json
        {
          "GK":  ["wc_saves_per_90", "prior_xg_per_90", ...],
          "DEF": [...],
          "MID": [...],
          "FWD": [...],
        }

Usage:
    python -m etl.models.feature_selection
    python -m etl.models.feature_selection --validate  # print selections only
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNetCV
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings

logger = logging.getLogger(__name__)

FEATURES_PATH    = Path(settings.parquet_silver_dir) / "player_stats" / "features.parquet"
SELECTIONS_PATH  = Path(settings.parquet_silver_dir) / "selected_features.json"

CORR_THRESHOLD   = 0.85   # drop one from each highly correlated pair
MIN_NONNAN_FRAC  = 0.40   # drop features with >60% NaN in a position bucket
ELASTICNET_CV    = 5
ELASTICNET_ITERS = 5000

# Features available per position bucket (union used; some will be dropped by NaN filter)
_WC_FEATURES = [
    "wc_goals_per_90", "wc_assists_per_90", "wc_xg_per_90", "wc_xa_per_90",
    "wc_shots_per_90", "wc_sot_per_90", "wc_key_passes_per_90",
    "wc_tackles_per_90", "wc_interceptions_per_90", "wc_clearances_per_90",
    "wc_saves_per_90",
    # wc_rating_avg is the ElasticNet target — excluded from candidate features
]

_PRIOR_FEATURES = [
    "prior_xg_per_90", "prior_xa_per_90", "prior_npxg_per_90",
    "prior_goals_per_90", "prior_assists_per_90",
    "prior_shots_per_90", "prior_key_passes_per_90",
]

_ALL_CANDIDATE = _WC_FEATURES + _PRIOR_FEATURES


def _corr_filter(df: pd.DataFrame, candidates: list[str], threshold: float) -> list[str]:
    """
    Greedy correlation filter.

    For each pair of features with |r| > threshold, drop the feature with
    lower variance.  Returns the surviving feature names.
    """
    available = [c for c in candidates if c in df.columns]
    sub = df[available].dropna(how="all")
    if sub.empty or len(available) < 2:
        return available

    corr = sub.corr(method="pearson", numeric_only=True).abs()
    variances = sub.var()
    keep = set(available)

    for i, fi in enumerate(available):
        if fi not in keep:
            continue
        for fj in available[i + 1:]:
            if fj not in keep:
                continue
            if corr.loc[fi, fj] > threshold:
                # Drop lower-variance member
                drop = fi if variances[fi] < variances[fj] else fj
                keep.discard(drop)
                logger.debug("  corr %.2f: %s vs %s → drop %s", corr.loc[fi, fj], fi, fj, drop)

    return [f for f in available if f in keep]


def _elasticnet_select(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str = "wc_rating_avg",
) -> list[str]:
    """
    Fit ElasticNetCV on `feature_cols` with `target_col` as target.

    Returns features whose absolute coefficient exceeds zero (L1 sparsity).
    Falls back to `feature_cols` unchanged if fewer than 30 rows have both
    target and feature data (too few to fit reliably).
    """
    available = [c for c in feature_cols if c in df.columns]
    if target_col not in df.columns:
        logger.warning("Target '%s' not in DataFrame — skipping ElasticNet.", target_col)
        return available

    sub = df[available + [target_col]].dropna(subset=[target_col])
    # Impute feature NaN with column median for fitting
    sub = sub.copy()
    for col in available:
        sub[col] = sub[col].fillna(sub[col].median())
    sub = sub.dropna()

    if len(sub) < 30:
        logger.warning(
            "  Only %d rows with target data — skipping ElasticNet, using corr-filter result.",
            len(sub),
        )
        return available

    X = StandardScaler().fit_transform(sub[available])
    y = sub[target_col].values

    en = ElasticNetCV(cv=ELASTICNET_CV, max_iter=ELASTICNET_ITERS, n_jobs=-1, random_state=42)
    en.fit(X, y)

    nonzero = [f for f, c in zip(available, en.coef_) if abs(c) > 1e-8]
    logger.info(
        "  ElasticNet: %d/%d features non-zero  (alpha=%.4f)",
        len(nonzero), len(available), en.alpha_,
    )
    # Always keep at least the corr-filtered set in case EN over-sparsifies
    return nonzero if len(nonzero) >= 3 else available


def select_features(df: pd.DataFrame) -> dict[str, list[str]]:
    selected: dict[str, list[str]] = {}

    for bucket in ["GK", "DEF", "MID", "FWD"]:
        sub = df[df["position_bucket"] == bucket].copy()
        logger.info("--- %s: %d players ---", bucket, len(sub))

        if len(sub) < 10:
            logger.warning("  Too few players (%d) — skipping selection for %s.", len(sub), bucket)
            selected[bucket] = []
            continue

        # Drop features with too many NaN in this bucket
        candidates = [
            c for c in _ALL_CANDIDATE
            if c in sub.columns
            and sub[c].notna().mean() >= MIN_NONNAN_FRAC
        ]
        logger.info("  After NaN filter: %d candidates", len(candidates))

        # Pass 1: correlation filter
        corr_passed = _corr_filter(sub, candidates, CORR_THRESHOLD)
        logger.info("  After corr filter (>%.0f%%): %d features", CORR_THRESHOLD * 100, len(corr_passed))

        # Pass 2: ElasticNet with wc_rating_avg as target
        final = _elasticnet_select(sub, corr_passed, target_col="wc_rating_avg")
        logger.info("  Final selected: %s", final)
        selected[bucket] = final

    return selected


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    logger.info("=== TrueScout Phase 2: feature_selection ===")

    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true", help="Print selections only; do not write.")
    args = parser.parse_args()

    if not FEATURES_PATH.exists():
        logger.error("features.parquet not found — run build_features.py first.")
        sys.exit(1)

    df = pd.read_parquet(FEATURES_PATH)
    logger.info("Loaded features: %d rows x %d cols", len(df), len(df.columns))

    selected = select_features(df)

    print("\n=== Selected features per position bucket ===")
    for bucket, feats in selected.items():
        print(f"  {bucket:3s}: {feats}")

    if not args.validate:
        SELECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SELECTIONS_PATH.write_text(json.dumps(selected, indent=2))
        logger.info("Written: %s", SELECTIONS_PATH)


if __name__ == "__main__":
    main()
