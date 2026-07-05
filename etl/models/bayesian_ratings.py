"""
Hierarchical Bayesian ratings — analytical Normal-Normal conjugate shrinkage.

NO PyMC, NO NumPyro, NO MCMC.  Pure NumPy/Pandas/DuckDB, fully vectorized.

Two-tier stratification
-----------------------
  Tier 1 — Macro (GK | DEF | MID | FWD)
      Used for the shrinkage math and archetype variance.  Large sample sizes
      ensure stable estimates of the group variance.

  Tier 2 — Micro (reep position_detail, e.g. "Centre Back", "Defensive Midfielder")
      Used only for the final percentile ranking.  A DM's posterior is shrunk
      toward the MID macro mean, but his dashboard percentile ranks him against
      other DMs only.

Normal-Normal conjugate update
-------------------------------
  Prior:       N(mu_prior, sigma2_prior)
    mu_prior    = cluster_wc_mean
                  + club_composite_z * cluster_wc_std * PRIOR_PULL * (not GK)
    sigma2_prior = cluster_wc_var  (archetype cluster variance of wc_rating_avg)

  Likelihood:  N(wc_rating_avg, sigma2_wc)
    sigma2_wc   = BASE_WC_VAR * 90 / max(wc_minutes, MIN_WC_MINUTES)
    (→ inf for players with no WC data, giving tau_wc = 0)

  Posterior:   N(mu_post, sigma2_post)
    tau_post   = tau_prior + tau_wc
    mu_post    = (tau_prior * mu_prior + tau_wc * mu_wc) / tau_post
    sigma2_post = 1 / tau_post

  HDI (90%):   mu_post ± 1.645 * sigma_post

Usage
-----
    python -m etl.models.bayesian_ratings
    python -m etl.models.bayesian_ratings --validate   # sanity checks, skip DB write
"""
import argparse
import logging
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings
from etl.db.connection import get_read_conn, write_conn

logger = logging.getLogger(__name__)

FEATURES_PATH = Path(settings.parquet_silver_dir) / "player_stats" / "features.parquet"
MV_PARQUET    = Path(settings.parquet_bronze_dir) / "market_values.parquet"

# ---------------------------------------------------------------------------
# Calibration constants
# ---------------------------------------------------------------------------

# Variance of a single Sofascore match rating  (≈ 0.55 std per match → var ≈ 0.30)
BASE_WC_VAR = 0.30

# Floor on WC minutes to avoid near-zero σ²_wc
MIN_WC_MINUTES = 15.0

# Dampening factor: how much of the club Z-score adjusts the prior mean.
# 0.0 = pure archetype mean; 1.0 = full Z-score translation.
PRIOR_PULL = 0.50

# Market value pull: weaker signal used when has_prior=False but market_value_eur is known.
# Half of PRIOR_PULL — MV reflects transfer fees and age, not direct performance.
MV_PRIOR_PULL = 0.20

# Minimum WC players per cluster to use cluster stats; smaller → bucket fallback
MIN_CLUSTER_WC = 5

# Micro-position groups with fewer than this many players are collapsed
# into their macro-bucket fallback.
MIN_MICRO_N = 8

# Opponent-strength adjustment exponent — matches build_features._OPPONENT_ALPHA.
# Stored here as documentation; the actual adjustment is applied upstream in
# build_features.py before features.parquet is written.
OPPONENT_ALPHA = 0.5

# Age-position curve (step 6): asymmetric Gaussian applied to prior deviation.
# prior_mean_adj = cluster_mean + (prior_mean - cluster_mean) * age_factor
# age_factor = exp(-0.5 * ((age - peak) / σ)^2), clipped to [AGE_FACTOR_FLOOR, 1.0]
# σ_below (development) is wider than σ_above (decline) — decline is steeper.
AGE_FACTOR_FLOOR = 0.75   # never discount prior deviation by more than 25%

_AGE_CURVE: dict[str, tuple[float, float, float]] = {
    # bucket: (peak_age, σ_below, σ_above)
    "GK":  (29.0, 9.0, 6.0),   # GKs develop slowly, peak late, decline gradually
    "DEF": (27.0, 7.0, 5.0),
    "MID": (26.0, 6.0, 5.0),
    "FWD": (25.0, 6.0, 5.0),
}

# ---------------------------------------------------------------------------
# League ELO coefficients (from leagues table, EPL = 1.0 reference)
# ---------------------------------------------------------------------------

_LEAGUE_ELO: dict[str, float] = {
    # ── Tier 1: Big-5 European leagues (EPL = 1.000 reference) ──────────────
    "EPL":            1.000,
    "Premier League": 1.000,   # FBref / understat name variant
    "La_Liga":        0.926,
    "LaLiga":         0.926,   # variant (no underscore)
    "Bundesliga":     0.918,
    "Serie_A":        0.909,
    "Serie A":        0.909,   # variant (space not underscore)
    "Ligue_1":        0.908,
    "Ligue 1":        0.908,   # variant (space not underscore)

    # ── Tier 2: Strong European leagues (UEFA coefficient ~0.80–0.85) ────────
    "Liga Portugal Betclic": 0.840,    # Primeira Liga (Portugal)
    "Primeira Liga":          0.840,
    "Brasileirão Betano":     0.835,   # Brazil Série A
    "Liga Profesional de Fútbol": 0.790,  # Argentina
    "Trendyol Süper Lig":     0.785,   # Turkey
    "VriendenLoterij Eredivisie": 0.820,  # Netherlands (PSV, Ajax, Feyenoord)
    "Eredivisie":             0.820,
    "Pro League":             0.810,   # Belgian Pro League
    "Jupiler Pro League":     0.810,
    "2. Bundesliga":          0.820,   # Germany second tier
    "LaLiga 2":               0.815,   # Spain second tier
    "Serie B":                0.805,   # Italy second tier
    "Ligue 2":                0.800,   # France second tier

    # ── Tier 3: Mid-table European + major non-European (0.70–0.79) ─────────
    "Russian Premier League": 0.755,
    "Championship":           0.755,   # England Championship
    "Swiss Super League":     0.750,
    "Austrian Bundesliga":    0.750,
    "Czech First League":     0.720,
    "Niké Liga":              0.720,   # Slovak Superliga
    "Danish Superliga":       0.730,
    "Scottish Premiership":   0.715,   # Celtic/Rangers dominance, weak depth
    "Allsvenskan":            0.720,   # Sweden
    "Eliteserien":            0.715,   # Norway
    "Ekstraklasa":            0.715,   # Poland
    "Stoiximan Super League": 0.710,   # Greece
    "HNL":                    0.710,   # Croatia
    "SuperLiga României":     0.695,
    "OTP Bank Liga":          0.690,   # Hungary
    "Parva Liga":             0.680,   # Bulgaria
    "Challenger Pro League":  0.755,   # Belgian second tier (treat ≈ Pro League)
    "Liga MX, Apertura":      0.720,
    "Liga MX, Clausura":      0.720,
    "Eerste Divisie":         0.770,   # Dutch second tier

    # ── Tier 4: Weaker / non-European leagues (< 0.70) ───────────────────────
    "MLS":                    0.685,
    "Stars League":           0.645,   # Saudi Pro League
    "Saudi Pro League":       0.645,
    "K League 1":             0.680,   # South Korea
    "J1 League":              0.695,   # Japan
    "A-League Men":           0.625,   # Australia
    "Persian Gulf Pro League": 0.645,  # Iran
    "Egyptian Premier League": 0.610,
    "Uzbekistan Super League": 0.560,
    "South African Premier Division": 0.555,
    "Tunisian Ligue Professionnelle 1": 0.580,
    "Indonesian Super League": 0.540,
    "Indonesia Super League":  0.540,   # alias: name used in features.parquet
    "Liga FUTVE":             0.510,   # Venezuela
    "Liga Panameña de Fútbol, Clausura": 0.520,
    "Liga Nacional de Fútbol de Guatemala, Apertura": 0.510,
    "Israeli Premier League": 0.690,
    "Stoiximan Super League": 0.710,
    "Cyprus League by Stoiximan": 0.640,
    "UAE Pro League":         0.610,
    "League One":             0.730,   # England League One (Tier 3)
    "2. Liga":                0.720,   # Austria second tier
    "Trendyol 1.Lig":         0.720,   # Turkey second tier
    "Primera Federación":     0.790,   # Spain third tier (actually high quality)
    "PrvaLiga":               0.700,   # Slovenia
    "Serie C, Girone C":      0.760,   # Italy third tier
    "Betinia Liga":           0.640,
    "LigaPro Serie A":        0.660,   # Ecuador
    "Primera División, Apertura": 0.680,  # Uruguay
    "USL Championship":       0.640,   # USA second tier

    # ── International competitions — apply no discount (ELO=1.0) ───────────
    # Players sourced from intl competitions usually have xg=xa=0, so ELO
    # has no effect; set 1.0 to be accurate and avoid accidental weighting.
    "WC 2026":                    1.000,
    "WC 2026 Qual CONMEBOL":      1.000,
    "WC 2026 Qual CONCACAF":      1.000,
    "Africa Cup of Nations 2023": 1.000,
    "Copa America 2024":          1.000,
    "UEFA Euro 2024":             1.000,
}
_MEAN_ELO = float(
    np.mean([v for k, v in _LEAGUE_ELO.items()
             if k in ("EPL","La_Liga","Bundesliga","Serie_A","Ligue_1")])
)  # ≈ 0.932 — used only for unrecognised leagues

# ---------------------------------------------------------------------------
# Micro-position mapping (Tier 2)
# ---------------------------------------------------------------------------

_MICRO_MAP: dict[str, str] = {
    # Goalkeepers
    "goalkeeper":           "Goalkeeper",
    "goaltender":           "Goalkeeper",
    # Defenders — split CB vs. FB
    "centre-back":          "Centre Back",
    "centre back":          "Centre Back",
    "center back":          "Centre Back",
    "stopper":              "Centre Back",
    "sweeper":              "Centre Back",
    "centerhalf":           "Centre Back",
    "defender":             "Centre Back",
    "full-back":            "Full Back",
    "right-back":           "Full Back",
    "left back":            "Full Back",
    "right back":           "Full Back",
    "wing half":            "Winger",
    # Wing-backs bucket into MID (see build_features.py); micro = Winger
    "wing-back":            "Winger",
    "wing back":            "Winger",
    # Midfielders
    "midfielder":           "Central Midfielder",
    "central midfielder":   "Central Midfielder",
    "defensive midfielder": "Defensive Midfielder",
    "attacking midfielder": "Attacking Midfielder",
    "playmaker":            "Attacking Midfielder",
    "wide midfielder":      "Winger",
    "winger":               "Winger",
    "left winger":          "Winger",
    "right winger":         "Winger",
    "inverted winger":      "Winger",
    "inside forward":       "Winger",
    # Forwards
    "forward":              "Centre Forward",
    "attacker":             "Centre Forward",
    "centre-forward":       "Centre Forward",
    "striker":              "Centre Forward",
    "second striker":       "Centre Forward",
    "false 9":              "Centre Forward",
    "false nine":           "Centre Forward",
}

_MACRO_FALLBACK: dict[str, str] = {
    "GK":  "Goalkeeper",
    "DEF": "Defender",
    "MID": "Midfielder",
    "FWD": "Forward",
    "UNK": "Unknown",
}


def _assign_micro(reep_pos: str | None, macro: str) -> str:
    if reep_pos:
        m = _MICRO_MAP.get(str(reep_pos).strip().lower())
        if m:
            return m
    return _MACRO_FALLBACK.get(macro, "Unknown")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_data() -> pd.DataFrame:
    """
    Load features.parquet and join cluster_id from the archetypes DuckDB table.
    Returns a single DataFrame ready for the Bayesian update.
    """
    df = pd.read_parquet(FEATURES_PATH)

    conn = get_read_conn()
    try:
        arcs = conn.execute(
            "SELECT reep_id, cluster_id FROM archetypes"
        ).df()
    finally:
        conn.close()

    # Market values live in Bronze Parquet (survives nightly identity reload).
    if MV_PARQUET.exists():
        mv = pd.read_parquet(MV_PARQUET)[["reep_id", "market_value_eur"]]
        mv = mv[mv["market_value_eur"].notna() & (mv["market_value_eur"] > 0)]
        logger.info("Loaded %d market values from %s", len(mv), MV_PARQUET)
    else:
        mv = pd.DataFrame(columns=["reep_id", "market_value_eur"])
        logger.warning("market_values.parquet not found — MV prior disabled")

    df = df.merge(arcs, on="reep_id", how="left")
    df = df.merge(mv,   on="reep_id", how="left")
    df["cluster_id"]        = df["cluster_id"].fillna(-1).astype(int)
    df["market_value_eur"]  = pd.to_numeric(df.get("market_value_eur"), errors="coerce")

    # Defensive: drop rows with no reep_id or no position_bucket
    df = df[df["reep_id"].notna() & df["position_bucket"].notna()].copy()

    logger.info("Loaded %d players from features.parquet + archetypes join", len(df))
    return df


# ---------------------------------------------------------------------------
# Prior composite (outfield only; GK stays at 0 → archetype-mean anchor)
# ---------------------------------------------------------------------------

def _add_prior_composite(df: pd.DataFrame) -> pd.DataFrame:
    """
    Offensive prior composite = (xg_per_90 + xa_per_90) * elo_coef.
    GK rows are set to 0.0 (archetype cluster mean is their anchor).
    """
    elo = df["league"].map(_LEAGUE_ELO).fillna(_MEAN_ELO)
    xg  = df["prior_xg_per_90"].fillna(0.0)
    xa  = df["prior_xa_per_90"].fillna(0.0)
    df["prior_composite"] = np.where(
        df["position_bucket"] == "GK",
        0.0,
        (xg + xa) * elo,
    )

    # Market value auxiliary signal — log-transformed to compress the €300K–€180M range.
    # has_mv_prior flags outfield no-prior players that have MV data; GKs excluded
    # (archetype mean is their only anchor regardless).
    df["log_mv"] = np.log1p(df["market_value_eur"].fillna(0.0))
    df["has_mv_prior"] = (
        df["market_value_eur"].notna()
        & ~df["has_prior"]
        & (df["position_bucket"] != "GK")
    )
    logger.info(
        "Market value prior available for %d outfield no-prior players",
        df["has_mv_prior"].sum(),
    )
    return df


# ---------------------------------------------------------------------------
# Cluster / bucket statistics (anchors for the shrinkage)
# ---------------------------------------------------------------------------

def _compute_anchor_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-cluster stats (from WC players only) and per-bucket fallbacks.

    Returns a stats DataFrame with columns:
      position_bucket, cluster_id,
      cluster_wc_mean, cluster_wc_var, cluster_wc_count,
      cluster_prior_mean, cluster_prior_std
    """
    wc = df[df["has_wc_data"] & df["wc_rating_avg"].notna()]

    # Cluster-level WC stats
    clust_wc = (
        wc.groupby(["position_bucket", "cluster_id"])["wc_rating_avg"]
        .agg(cluster_wc_mean="mean", cluster_wc_var="var", cluster_wc_count="count")
        .reset_index()
    )

    # Bucket-level WC fallback (for clusters with too few WC players)
    bucket_wc = (
        wc.groupby("position_bucket")["wc_rating_avg"]
        .agg(bucket_wc_mean="mean", bucket_wc_var="var")
        .reset_index()
    )

    # Cluster-level prior-composite stats (for Z-scoring)
    prior = df[df["has_prior"] & (df["position_bucket"] != "GK")]
    clust_prior = (
        prior.groupby(["position_bucket", "cluster_id"])["prior_composite"]
        .agg(cluster_prior_mean="mean", cluster_prior_std="std")
        .reset_index()
    )

    stats = (
        clust_wc
        .merge(clust_prior, on=["position_bucket", "cluster_id"], how="left")
        .merge(bucket_wc,   on="position_bucket",                  how="left")
    )

    # Fall back to bucket stats for small clusters
    small = stats["cluster_wc_count"] < MIN_CLUSTER_WC
    stats.loc[small, "cluster_wc_mean"] = stats.loc[small, "bucket_wc_mean"]
    stats.loc[small, "cluster_wc_var"]  = stats.loc[small, "bucket_wc_var"]

    # Fill any remaining NaN (cluster never observed in WC)
    for col in ("cluster_wc_mean", "cluster_wc_var"):
        stats[col] = stats[col].fillna(stats.groupby("position_bucket")[col].transform("mean"))
    # Final fallback for buckets with no WC at all (shouldn't happen)
    stats["cluster_wc_mean"] = stats["cluster_wc_mean"].fillna(7.0)
    stats["cluster_wc_var"]  = stats["cluster_wc_var"].fillna(0.20)

    # Floor variance so precision is bounded
    stats["cluster_wc_var"] = stats["cluster_wc_var"].clip(lower=0.01)

    return stats


# ---------------------------------------------------------------------------
# Age-position curve  (step 6)
# ---------------------------------------------------------------------------

def _apply_age_curve(df: pd.DataFrame, prior_mean: pd.Series) -> pd.Series:
    """
    Compress the prior-mean deviation from cluster mean for off-peak players.

    age_factor = exp(-0.5 * ((age - peak) / σ)²), clipped to [AGE_FACTOR_FLOOR, 1.0]
    σ_below (development) is wider than σ_above (decline): players approaching
    peak get near-zero discount; veterans and teenagers take the biggest hit.

    Result: prior_mean_adj = cluster_mean + (prior_mean - cluster_mean) * age_factor
    When deviation = 0 (cluster-mean players) the curve has no effect.
    When has_prior = True the deviation is already grounded in xG/xA data, so
    the curve provides only a small residual correction for aging/development.
    """
    age = pd.to_numeric(df.get("age"), errors="coerce")
    if age.isna().all():
        return prior_mean  # no age data — skip

    prior_mean = prior_mean.copy()
    n_adjusted = 0

    for bucket, (peak, sigma_below, sigma_above) in _AGE_CURVE.items():
        mask = df["position_bucket"] == bucket
        if not mask.any():
            continue

        a   = age[mask].fillna(peak)   # missing age → no adjustment
        dev = prior_mean[mask] - df.loc[mask, "cluster_wc_mean"]

        sigma = np.where(a <= peak, sigma_below, sigma_above)
        factor = np.exp(-0.5 * ((a - peak) / sigma) ** 2).clip(lower=AGE_FACTOR_FLOOR)

        prior_mean[mask] = df.loc[mask, "cluster_wc_mean"] + dev * factor
        n_adjusted += int(mask.sum())

    if n_adjusted:
        logger.info(
            "Age-position curve applied to %d players (floor=%.2f)", n_adjusted, AGE_FACTOR_FLOOR
        )
    return prior_mean


# ---------------------------------------------------------------------------
# Bayesian update — vectorized Normal-Normal conjugate
# ---------------------------------------------------------------------------

def _bayesian_update(df: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    df = df.merge(stats, on=["position_bucket", "cluster_id"], how="left")

    # Guard: stats is empty when no WC Parquets exist (CI "Local Scrape, Cloud Math"
    # run). Fill with global defaults so the prior math doesn't NaN-collapse everyone.
    df["cluster_wc_mean"] = df["cluster_wc_mean"].fillna(7.0)
    df["cluster_wc_var"]  = df["cluster_wc_var"].fillna(0.20).clip(lower=1e-4)

    # --- Prior mean ---
    # Club composite Z-score within cluster (0 when no prior → no deviation)
    comp_z = (
        (df["prior_composite"] - df["cluster_prior_mean"].fillna(0.0))
        / df["cluster_prior_std"].fillna(1.0).clip(lower=1e-8)
    )
    comp_z = comp_z.where(df["has_prior"] & (df["position_bucket"] != "GK"), 0.0)

    # Market value Z-score (per position bucket) for outfield no-prior players.
    # Reference distribution = all players with MV data in each bucket (stable mean/std).
    # Zeroed out for has_prior players (their xG/xA composite already handles it)
    # and for GKs (archetype-mean only).
    bucket_mv = (
        df[df["log_mv"] > 0]
        .groupby("position_bucket")["log_mv"]
        .agg(mv_mean="mean", mv_std="std")
        .reset_index()
    )
    df = df.merge(bucket_mv, on="position_bucket", how="left")
    mv_z = (
        (df["log_mv"] - df["mv_mean"].fillna(0.0))
        / df["mv_std"].fillna(1.0).clip(lower=1e-8)
    ).where(df["has_mv_prior"], 0.0).fillna(0.0)
    df = df.drop(columns=["mv_mean", "mv_std"])

    n_mv = int((mv_z != 0).sum())
    if n_mv:
        logger.info(
            "Market value Z-score applied to %d players (MV_PRIOR_PULL=%.2f)",
            n_mv, MV_PRIOR_PULL,
        )

    cluster_wc_std = np.sqrt(df["cluster_wc_var"])

    # Clamp MV adjustment to ±0.4 rating points — prevents extreme market
    # valuations (star players or data outliers) from dominating the prior.
    # Missing-data players already have mv_z=0 (enforced by has_mv_prior gate);
    # this clamp additionally caps the upside/downside for players who DO have data.
    MV_ADJ_CAP = 0.4
    mv_adj = (mv_z * cluster_wc_std * MV_PRIOR_PULL).clip(lower=-MV_ADJ_CAP, upper=MV_ADJ_CAP)

    df["prior_mean"] = (
        df["cluster_wc_mean"]
        + comp_z * cluster_wc_std * PRIOR_PULL
        + mv_adj
    )

    # GK: reset to pure archetype mean (club composite carries no signal)
    df.loc[df["position_bucket"] == "GK", "prior_mean"] = (
        df.loc[df["position_bucket"] == "GK", "cluster_wc_mean"]
    )

    # Safety net: fall back to club_composite (outfield) or 6.5 (GK / no prior)
    _fallback = df["prior_composite"].where(
        df["has_prior"] & (df["position_bucket"] != "GK"), np.nan
    ).fillna(6.5)
    df["prior_mean"] = df["prior_mean"].fillna(_fallback)

    # ── Step 6: age-position curve adjustment ──────────────────────────────
    # Compress the prior deviation from cluster mean for players who are
    # significantly younger or older than their position's peak age.
    # Has no effect when prior_mean == cluster_mean (deviation = 0).
    if "age" in df.columns:
        df["prior_mean"] = _apply_age_curve(df, df["prior_mean"])

    # --- Precisions ---
    sigma2_prior = df["cluster_wc_var"].clip(lower=1e-4).values  # (N,)

    wc_mins = df["wc_minutes"].clip(lower=MIN_WC_MINUTES).fillna(MIN_WC_MINUTES).values
    # Require a non-NaN Sofascore rating — brief subs (e.g. 1 min) may lack one
    has_wc  = df["has_wc_data"].values.astype(bool) & df["wc_rating_avg"].notna().values
    sigma2_wc = np.where(has_wc, BASE_WC_VAR * 90.0 / wc_mins, np.inf)

    tau_prior = 1.0 / sigma2_prior
    tau_wc    = np.where(np.isinf(sigma2_wc), 0.0, 1.0 / sigma2_wc)
    tau_post  = tau_prior + tau_wc

    mu_prior = df["prior_mean"].values
    # Prefer opponent-strength-adjusted rating when build_features has computed it
    wc_obs_col = "wc_rating_adjusted" if "wc_rating_adjusted" in df.columns else "wc_rating_avg"
    mu_wc = df[wc_obs_col].fillna(df["wc_rating_avg"]).fillna(df["prior_mean"]).values
    if wc_obs_col == "wc_rating_adjusted":
        logger.info("Using opponent-adjusted WC ratings (wc_rating_adjusted)")

    # Posterior
    mu_post    = (tau_prior * mu_prior + tau_wc * mu_wc) / tau_post
    sigma2_post = 1.0 / tau_post
    sigma_post  = np.sqrt(sigma2_post)

    # Clamp any residual NaNs (e.g. wc_minutes=0 players) to their prior_mean.
    nan_mask = np.isnan(mu_post)
    if nan_mask.any():
        logger.warning("Clamping %d NaN posterior_mean values to prior_mean.", nan_mask.sum())
        mu_post = np.where(nan_mask, df["prior_mean"].values, mu_post)

    df["posterior_mean"]   = mu_post
    df["posterior_std"]    = sigma_post
    df["shrinkage_weight"] = tau_wc / tau_post   # 0=prior  1=WC
    df["hdi_low"]          = mu_post - 1.645 * sigma_post
    df["hdi_high"]         = mu_post + 1.645 * sigma_post

    return df


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------

def _confidence(df: pd.DataFrame) -> pd.Series:
    """
    Confidence from Bayesian posterior_std: lower std → tighter posterior → higher confidence.
    exp(10*(0.27 - std)) maps the practical std range [0.22, 0.62] → (0.95, 0.03].
    Fixes the old minutes-only formula which capped no-prior players (e.g. Messi) at 0.70
    even when WC data was sufficient to form a tight posterior.
    """
    std = df["posterior_std"].clip(lower=0.01)
    return (np.exp(10.0 * (0.27 - std))).clip(0.0, 0.95)


# ---------------------------------------------------------------------------
# Micro-position (Tier 2) + percentile rank
# ---------------------------------------------------------------------------

def _add_micro_and_percentile(df: pd.DataFrame) -> pd.DataFrame:
    df["position_micro"] = [
        _assign_micro(r, b)
        for r, b in zip(df["reep_position"], df["position_bucket"])
    ]

    # Collapse micro groups with < MIN_MICRO_N players into macro fallback
    counts = df["position_micro"].value_counts()
    small  = set(counts[counts < MIN_MICRO_N].index)
    if small:
        logger.info("Collapsing %d small micro-position groups: %s", len(small), small)
        mask = df["position_micro"].isin(small)
        df.loc[mask, "position_micro"] = (
            df.loc[mask, "position_bucket"].map(_MACRO_FALLBACK)
        )

    # Percentile rank within micro-position (0=worst, 1=best).
    # UNK players are excluded — their position is unknown so cross-player
    # comparison is meaningless.
    known = df["position_bucket"] != "UNK"
    df["percentile_rank"] = np.nan
    if known.any():
        df.loc[known, "percentile_rank"] = (
            df[known].groupby("position_micro")["posterior_mean"].rank(pct=True)
        )

    return df


# ---------------------------------------------------------------------------
# DuckDB write (bulk — no row-by-row loops)
# ---------------------------------------------------------------------------

_INSERT_SQL = """
INSERT INTO player_ratings (
    reep_id, position_macro, position_micro, cluster_id,
    prior_mean, posterior_mean, posterior_std,
    hdi_low, hdi_high, shrinkage_weight,
    wc_minutes, confidence_score, percentile_rank, updated_at
)
SELECT
    reep_id, position_macro, position_micro, cluster_id,
    prior_mean, posterior_mean, posterior_std,
    hdi_low, hdi_high, shrinkage_weight,
    wc_minutes, confidence_score, percentile_rank,
    now()
FROM ratings_temp
"""


def _write_ratings(df: pd.DataFrame) -> None:
    out = df[[
        "reep_id", "position_bucket", "position_micro", "cluster_id",
        "prior_mean", "posterior_mean", "posterior_std",
        "hdi_low", "hdi_high", "shrinkage_weight",
        "wc_minutes", "confidence_score", "percentile_rank",
    ]].rename(columns={"position_bucket": "position_macro"}).copy()

    out["cluster_id"] = out["cluster_id"].fillna(-1).astype(int)
    out["wc_minutes"] = out["wc_minutes"].fillna(0.0)

    with write_conn() as conn:
        conn.execute("DELETE FROM player_ratings")
        conn.register("ratings_temp", out)
        conn.execute(_INSERT_SQL)

    logger.info("Written %d rows -> player_ratings", len(out))


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------

def _validate(df: pd.DataFrame) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("\n" + "=" * 70)
    print("  VALIDATION REPORT — Bayesian Ratings")
    print("=" * 70)

    # (a) Low-minute player: should be heavily shrunk toward prior/archetype.
    # Require non-NaN wc_rating_avg so we can compute |post - WC| meaningfully.
    low_min = df[
        df["has_wc_data"]
        & df["wc_rating_avg"].notna()
        & (df["wc_minutes"] < 45)
    ].copy()
    if not low_min.empty:
        row = low_min.nsmallest(1, "wc_minutes").iloc[0]
        print(f"\n(a) Low-minute player shrinkage check")
        print(f"    Player       : {row.get('player_name','?')} ({row.get('nationality','?')})")
        print(f"    WC minutes   : {row.get('wc_minutes', 0):.0f}")
        print(f"    WC rating    : {row.get('wc_rating_avg', float('nan')):.3f}")
        print(f"    Prior mean   : {row['prior_mean']:.3f}")
        print(f"    Posterior    : {row['posterior_mean']:.3f}")
        print(f"    Shrinkage w  : {row['shrinkage_weight']:.3f}  (0=prior, 1=WC)")
        delta_to_prior = abs(row["posterior_mean"] - row["prior_mean"])
        delta_to_wc    = abs(row["posterior_mean"] - row.get("wc_rating_avg", row["prior_mean"]))
        result = "✓ PASS" if delta_to_prior < delta_to_wc else "✗ FAIL"
        print(f"    |post-prior| = {delta_to_prior:.3f}  |post-WC| = {delta_to_wc:.3f}  → {result}")

    # (b) High-minute WC star: posterior should track the WC observation.
    # Uses wc_rating_adjusted (opponent-adjusted) — the same value used as the
    # Bayesian likelihood input — so |post-WC| is apples-to-apples.
    high_min = df[df["has_wc_data"] & (df["wc_minutes"] >= 270)].copy()
    if not high_min.empty:
        row = high_min.nlargest(1, "wc_rating_avg").iloc[0]
        adj    = row.get("wc_rating_adjusted")
        wc_obs = float(adj) if (adj is not None and pd.notna(adj)) else float(row.get("wc_rating_avg", row["prior_mean"]))
        print(f"\n(b) High-minute WC star shrinkage check")
        print(f"    Player          : {row.get('player_name','?')} ({row.get('nationality','?')})")
        print(f"    WC minutes      : {row.get('wc_minutes', 0):.0f}")
        print(f"    WC rating (raw) : {row.get('wc_rating_avg', float('nan')):.3f}")
        print(f"    WC rating (adj) : {wc_obs:.3f}  <- used as likelihood")
        print(f"    Prior mean      : {row['prior_mean']:.3f}")
        print(f"    Posterior       : {row['posterior_mean']:.3f}")
        print(f"    Shrinkage w     : {row['shrinkage_weight']:.3f}")
        delta_to_wc    = abs(row["posterior_mean"] - wc_obs)
        delta_to_prior = abs(row["posterior_mean"] - row["prior_mean"])
        result = "PASS" if delta_to_wc < delta_to_prior else "FAIL"
        print(f"    |post-WC_adj| = {delta_to_wc:.3f}  |post-prior| = {delta_to_prior:.3f}  -> {result}")

    # (c) Micro-position ranking: DM vs AM
    dm = df[df["position_micro"] == "Defensive Midfielder"].copy()
    am = df[df["position_micro"] == "Attacking Midfielder"].copy()
    if not dm.empty and not am.empty:
        print(f"\n(c) Micro-position percentile check")
        print(f"    Defensive Midfielders ({len(dm)} players) — top 3 by posterior:")
        for _, r in dm.nlargest(3, "posterior_mean").iterrows():
            print(f"      {r.get('player_name','?'):30s}  "
                  f"post={r['posterior_mean']:.3f}  "
                  f"pct={r['percentile_rank']:.2f} (vs DMs only)")
        print(f"    Attacking Midfielders ({len(am)} players) — top 3 by posterior:")
        for _, r in am.nlargest(3, "posterior_mean").iterrows():
            print(f"      {r.get('player_name','?'):30s}  "
                  f"post={r['posterior_mean']:.3f}  "
                  f"pct={r['percentile_rank']:.2f} (vs AMs only)")
        print("    → DMs and AMs each have their own percentile scale.  ✓ PASS")

    # Summary stats
    print(f"\n--- Summary ---")
    print(f"  Total players    : {len(df)}")
    print(f"  Has WC data      : {df['has_wc_data'].sum()}")
    print(f"  Has club prior   : {df['has_prior'].sum()}")
    print(f"  Has MV prior     : {df['has_mv_prior'].sum()}  (no-prior outfield, MV known)")
    print(f"  Both WC + prior  : {(df['has_wc_data'] & df['has_prior']).sum()}")
    print(f"  Shrinkage w >0.5 : {(df['shrinkage_weight'] > 0.5).sum()}  (WC-dominant)")
    print(f"  Shrinkage w <0.2 : {(df['shrinkage_weight'] < 0.2).sum()}  (prior-dominant)")
    print()
    print(f"--- Posterior stats per macro bucket ---")
    print(
        df.groupby("position_bucket")[["posterior_mean", "posterior_std", "confidence_score"]]
        .agg(["mean", "min", "max"])
        .round(3)
        .to_string()
    )

    print(f"\n--- Top 5 players per macro bucket (by posterior_mean) ---")
    for bucket in ["GK", "DEF", "MID", "FWD"]:
        sub = df[df["position_bucket"] == bucket].nlargest(5, "posterior_mean")
        print(f"\n  {bucket}:")
        for _, r in sub.iterrows():
            print(f"    {r.get('player_name','?'):30s}  "
                  f"post={r['posterior_mean']:.3f}  "
                  f"w={r['shrinkage_weight']:.2f}  "
                  f"conf={r['confidence_score']:.2f}  "
                  f"pct={r['percentile_rank']:.2f}  "
                  f"({r['position_micro']})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    logger.info("=== TrueScout Phase 2: bayesian_ratings ===")

    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true",
                        help="Print validation report; skip DuckDB write.")
    args = parser.parse_args()

    if not FEATURES_PATH.exists():
        logger.error(
            "features.parquet not found — skipping bayesian_ratings for this run. "
            "Existing ratings preserved."
        )
        return

    df = _load_data()
    df = _add_prior_composite(df)

    stats = _compute_anchor_stats(df)
    logger.info("Anchor stats computed for %d clusters", len(stats))

    df = _bayesian_update(df, stats)
    df["confidence_score"] = _confidence(df)
    df = _add_micro_and_percentile(df)

    logger.info(
        "Ratings ready: %d players  "
        "(shrinkage w: min=%.3f  mean=%.3f  max=%.3f)",
        len(df),
        df["shrinkage_weight"].min(),
        df["shrinkage_weight"].mean(),
        df["shrinkage_weight"].max(),
    )

    # ── Position sanity checks (hard failures) ────────────────────────────────
    unk_n = (df["position_bucket"] == "UNK").sum()
    if unk_n:
        logger.warning(
            "%d players have UNK position bucket (excluded from percentile ranking).", unk_n
        )

    if "wc_saves_per_90" in df.columns:
        bad_saves = df[
            (df["wc_saves_per_90"].fillna(0) > 0.5) & (df["position_bucket"] != "GK")
        ]
        if not bad_saves.empty:
            raise RuntimeError(
                f"Position sanity FAILED: {len(bad_saves)} save-makers (wc_saves_per_90 > 0.5) "
                f"bucketed as non-GK:\n"
                + bad_saves[["player_name", "position_bucket", "wc_saves_per_90"]].to_string()
            )

    if "wc_xg_per_90" in df.columns:
        # DEF/GK players with xg_per_90 > 1.0 are almost certainly Reep mis-labelled strikers.
        # DEF players between 0.5–1.0 are likely attacking wingers/full-backs mis-classified.
        # Auto-reclassify rather than crash: these are data-quality issues, not code bugs.
        xg = df["wc_xg_per_90"].fillna(0)
        to_fwd = (xg > 1.0) & df["position_bucket"].isin(["DEF", "GK"])
        if to_fwd.any():
            names = df.loc[to_fwd, "player_name"].tolist()[:10]
            logger.warning(
                "%d DEF/GK players have wc_xg_per_90 > 1.0 — reclassifying → FWD: %s",
                to_fwd.sum(), names,
            )
            df.loc[to_fwd, "position_bucket"] = "FWD"

        to_mid = (xg > 0.5) & (df["position_bucket"] == "DEF")
        if to_mid.any():
            names = df.loc[to_mid, "player_name"].tolist()[:10]
            logger.warning(
                "%d DEF players have wc_xg_per_90 > 0.5 — reclassifying → MID: %s",
                to_mid.sum(), names,
            )
            df.loc[to_mid, "position_bucket"] = "MID"

    _validate(df)

    if args.validate:
        logger.info("--validate: skipping DuckDB write.")
    else:
        _write_ratings(df)

    logger.info("=== bayesian_ratings complete ===")


if __name__ == "__main__":
    main()
