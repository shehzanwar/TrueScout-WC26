"""
Shared calibration helpers — single source of truth for the advance-probability model.

Design
------
- Davidson (1970) draw extension of Bradley–Terry is the link function.
- Scale ν is frozen at 0.778 (≈ 28% draw rate at equal strengths, matching
  historical WC knockout 90-min draw frequency); only logistic_scale is fitted.
- fit_scale() runs a grid search over brier_log graded matches, minimising
  mean log-loss.  Falls back to DEFAULT_SCALE when fewer than 12 matches are
  available (not enough signal to distinguish scale choices).
- model_params table (run_date, param, value) is an append-only audit trail so
  scale drift is visible across nightly runs.

Import contract
---------------
- monte_carlo_sim imports: advance_prob_vec, load_fitted_scale, FALLBACK_STRENGTH
- brier_tracker imports:   advance_prob, load_fitted_scale, ET_BIAS_STRONGER,
                           ET_BIAS_WEAKER, FALLBACK_STRENGTH
- run_nightly imports:     fit_scale (called in step 6.5)
- export_json imports:     load_fitted_scale (expose logistic_scale in brier.json)

No imports from monte_carlo_sim or brier_tracker — avoids circular deps.
"""
from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ET_BIAS_STRONGER = 0.55   # P(stronger team wins ET/pens) — baked in for draws
ET_BIAS_WEAKER   = 0.45
FALLBACK_STRENGTH = 7.0   # team strength when no valid posterior ratings exist
DEFAULT_SCALE     = 1.0   # logistic scale when < 12 graded matches available
NU                = 0.778 # Davidson draw tendency; ν/(2+ν) ≈ 28% draw rate at equal strengths

CLIP_LO, CLIP_HI = 0.01, 0.99

_SCALE_LO, _SCALE_HI, _SCALE_STEP = 0.8, 2.5, 0.025


# ---------------------------------------------------------------------------
# Davidson-extended Bradley–Terry
# ---------------------------------------------------------------------------

def three_way_probs(
    s_a: float, s_b: float, scale: float, nu: float = NU
) -> tuple[float, float, float]:
    """
    Davidson (1970) extension of Bradley–Terry.

    Returns (p_win_a, p_draw, p_win_b):
        a = 10^(s_a / scale),  b = 10^(s_b / scale),  d = ν√(ab)
        probs = (a, d, b) / (a + b + d)
    """
    a = math.pow(10.0, s_a / scale)
    b = math.pow(10.0, s_b / scale)
    d = nu * math.sqrt(a * b)
    total = a + b + d
    return a / total, d / total, b / total


def advance_prob(s_a: float, s_b: float, scale: float) -> float:
    """
    P(team_a advances to the next round).

    Folds draws into the advance probability via ET/pens bias:
        P(a advances) = P(a wins 90') + P(draw 90') × et_bias_a
        et_bias_a = ET_BIAS_STRONGER if s_a ≥ s_b else ET_BIAS_WEAKER

    Symmetry: advance_prob(s_a, s_b) + advance_prob(s_b, s_a) == 1.0.
    """
    pW, pD, _ = three_way_probs(s_a, s_b, scale)
    et_bias = ET_BIAS_STRONGER if s_a >= s_b else ET_BIAS_WEAKER
    return pW + pD * et_bias


def advance_prob_vec(
    s_left: "np.ndarray",
    s_right: "np.ndarray",
    scale: float,
    nu: float = NU,
) -> "np.ndarray":
    """
    Vectorised advance_prob for the Monte Carlo sim hot path.

    Inputs are NumPy arrays of shape (n_sim, n_matches) — same as the
    sim's s_left / s_right arrays.  Returns the same shape.
    """
    a = np.power(10.0, s_left  / scale)
    b = np.power(10.0, s_right / scale)
    d = nu * np.sqrt(a * b)
    total  = a + b + d
    p_win  = a / total
    p_draw = d / total
    et_bias = np.where(s_left >= s_right, ET_BIAS_STRONGER, ET_BIAS_WEAKER)
    return p_win + p_draw * et_bias


# ---------------------------------------------------------------------------
# model_params table helpers
# ---------------------------------------------------------------------------

_CREATE_MODEL_PARAMS = """
CREATE TABLE IF NOT EXISTS model_params (
    run_date  DATE    NOT NULL,
    param     VARCHAR NOT NULL,
    value     DOUBLE  NOT NULL,
    PRIMARY KEY (run_date, param)
)
"""


def _ensure_model_params(conn: "duckdb.DuckDBPyConnection") -> None:
    conn.execute(_CREATE_MODEL_PARAMS)


def _persist_param(
    conn: "duckdb.DuckDBPyConnection",
    param: str,
    value: float,
) -> None:
    """Upsert (run_date=today, param, value) into model_params."""
    from datetime import date
    _ensure_model_params(conn)
    today = str(date.today())
    conn.execute(
        """
        INSERT INTO model_params (run_date, param, value)
        VALUES (?, ?, ?)
        ON CONFLICT (run_date, param) DO UPDATE SET value = excluded.value
        """,
        [today, param, value],
    )


def load_fitted_scale(conn: "duckdb.DuckDBPyConnection") -> float:
    """
    Read the most recently fitted logistic_scale from model_params.
    Falls back to DEFAULT_SCALE if the table is missing or empty.
    """
    try:
        _ensure_model_params(conn)
        row = conn.execute("""
            SELECT value FROM model_params
            WHERE param = 'logistic_scale'
            ORDER BY run_date DESC
            LIMIT 1
        """).fetchone()
        if row is not None:
            scale = float(row[0])
            logger.info("Loaded fitted logistic_scale=%.4f from model_params.", scale)
            return scale
    except Exception as exc:
        logger.warning("load_fitted_scale: could not read model_params (%s) — using %.2f", exc, DEFAULT_SCALE)
    return DEFAULT_SCALE


# ---------------------------------------------------------------------------
# Team strength query (shared across fit_scale and brier_tracker)
# ---------------------------------------------------------------------------

_STRENGTH_SQL = """
WITH wc_players AS (
    SELECT DISTINCT
        CAST(l.player_id AS VARCHAR) AS sofascore_id,
        CASE l.team_side
            WHEN 'home' THEN e.home_team_name
            WHEN 'away' THEN e.away_team_name
        END AS national_team
    FROM read_parquet('{lineup_glob}', union_by_name=true) l
    JOIN read_parquet('{events_glob}', union_by_name=true) e
      ON CAST(l.event_id AS BIGINT) = CAST(e.event_id AS BIGINT)
),
player_national AS (
    SELECT wc.national_team, ip.reep_id, pr.posterior_mean
    FROM wc_players wc
    JOIN identity_players ip ON wc.sofascore_id = ip.key_sofascore
    JOIN player_ratings   pr ON ip.reep_id       = pr.reep_id
),
ranked AS (
    SELECT national_team, posterior_mean,
           ROW_NUMBER() OVER (
               PARTITION BY national_team ORDER BY posterior_mean DESC
           ) AS rn
    FROM player_national
)
SELECT national_team AS team, AVG(posterior_mean) AS strength
FROM ranked
WHERE rn <= 15
GROUP BY national_team
"""


def _build_team_strengths(conn: "duckdb.DuckDBPyConnection") -> dict[str, float]:
    """Top-15 player average strength per WC national team."""
    from etl.utils.team_aliases import normalize as _alias_normalize

    bronze      = Path(settings.parquet_bronze_dir)
    lineup_glob = (bronze / "sofascore" / "lineups" / "*.parquet").as_posix()
    events_glob = (bronze / "sofascore" / "events"  / "*.parquet").as_posix()

    df = conn.execute(_STRENGTH_SQL.format(lineup_glob=lineup_glob, events_glob=events_glob)).df()
    df["team"] = df["team"].map(lambda t: _alias_normalize(t) or t)
    return dict(zip(df["team"], df["strength"].astype(float)))


# ---------------------------------------------------------------------------
# Fallback team strength
# ---------------------------------------------------------------------------

def fallback_strength(conn: "duckdb.DuckDBPyConnection") -> float:
    """
    Median team strength from current player_ratings → WC lineup join.

    Used when a bracket team has no player_ratings entries.  Returns
    FALLBACK_STRENGTH (7.0) if team strengths cannot be computed.

    Mirrors the ad-hoc `np.median(valid) if valid else FALLBACK_STRENGTH`
    logic in monte_carlo_sim and the `np.median(list(strengths.values()))`
    in brier_tracker — a single authoritative source replaces both.
    """
    try:
        teams = _build_team_strengths(conn)
        if teams:
            valid = [v for v in teams.values() if np.isfinite(v)]
            if valid:
                return float(np.median(valid))
    except Exception as exc:
        logger.warning("fallback_strength: cannot compute (%s) — using %.1f", exc, FALLBACK_STRENGTH)
    return FALLBACK_STRENGTH


# ---------------------------------------------------------------------------
# Scale fitting
# ---------------------------------------------------------------------------

def fit_scale(
    conn: "duckdb.DuckDBPyConnection",
    scale_range: tuple[float, float, float] = (_SCALE_LO, _SCALE_HI, _SCALE_STEP),
) -> float:
    """
    Grid search logistic_scale ∈ [lo, hi] step s, minimising mean log-loss
    over all graded brier_log matches.

    Falls back to DEFAULT_SCALE when:
    - brier_log table doesn't exist
    - fewer than 12 distinct matches are available (not enough signal)
    - team strengths cannot be computed

    Fitted value is persisted to model_params for audit.
    Returns the fitted scale (clamped to [lo, hi]).
    """
    lo, hi, step = scale_range

    # 1. Read graded match outcomes from brier_log
    try:
        df = conn.execute("""
            SELECT home_team, away_team, advanced_team,
                   CAST(event_id AS VARCHAR) AS event_id
            FROM brier_log
            WHERE model_prob IS NOT NULL
        """).df()
    except Exception as exc:
        logger.warning("fit_scale: brier_log unavailable (%s) — using DEFAULT_SCALE=%.2f", exc, DEFAULT_SCALE)
        return DEFAULT_SCALE

    # Keep one entry per match (latest run_date wins if event graded multiple times)
    df = df.drop_duplicates(subset=["event_id"])
    df["outcome"] = (df["advanced_team"] == df["home_team"]).astype(int)

    n_matches = len(df)
    if n_matches < 12:
        logger.info(
            "fit_scale: only %d graded matches (need ≥ 12) — using DEFAULT_SCALE=%.2f",
            n_matches, DEFAULT_SCALE,
        )
        return DEFAULT_SCALE

    # 2. Current team strengths
    try:
        strengths = _build_team_strengths(conn)
    except Exception as exc:
        logger.warning("fit_scale: cannot compute team strengths (%s) — using DEFAULT_SCALE=%.2f", exc, DEFAULT_SCALE)
        return DEFAULT_SCALE

    if not strengths:
        logger.warning("fit_scale: empty strengths map — using DEFAULT_SCALE=%.2f", DEFAULT_SCALE)
        return DEFAULT_SCALE

    fallback = float(np.median(list(strengths.values())))

    # 3. Grid search
    scales = np.arange(lo, hi + step * 0.5, step)
    best_scale = DEFAULT_SCALE
    best_loss  = float("inf")

    for scale in scales:
        total_loss = 0.0
        n_valid    = 0
        for _, row in df.iterrows():
            s_h = strengths.get(row["home_team"], fallback)
            s_a = strengths.get(row["away_team"], fallback)
            p = advance_prob(float(s_h), float(s_a), float(scale))
            p_clipped = max(CLIP_LO, min(CLIP_HI, p))
            outcome = int(row["outcome"])
            p_outcome = p_clipped if outcome == 1 else (1.0 - p_clipped)
            total_loss += -math.log(p_outcome)
            n_valid += 1

        if n_valid > 0:
            mean_loss = total_loss / n_valid
            if mean_loss < best_loss:
                best_loss  = mean_loss
                best_scale = float(scale)

    best_scale = float(np.clip(best_scale, lo, hi))

    # 4. Persist
    try:
        _persist_param(conn, "logistic_scale", best_scale)
    except Exception as exc:
        logger.warning("fit_scale: could not persist to model_params (%s)", exc)

    logger.info(
        "fit_scale: scale=%.4f (log-loss=%.6f over %d matches)",
        best_scale, best_loss, n_matches,
    )
    return best_scale
