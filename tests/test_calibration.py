"""
Tests for etl/models/calibration.py — Davidson model, advance_prob, scale helpers.

Covers W1.1+W1.2 (Davidson formula) and W1.3 (fallback_strength, MV cap).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from etl.models.calibration import (
    three_way_probs,
    advance_prob,
    advance_prob_vec,
    fallback_strength,
    load_fitted_scale,
    DEFAULT_SCALE,
    FALLBACK_STRENGTH,
    NU,
    ET_BIAS_STRONGER,
    ET_BIAS_WEAKER,
)


# ---------------------------------------------------------------------------
# Davidson three_way_probs
# ---------------------------------------------------------------------------

class TestThreeWayProbs:
    def test_probs_sum_to_one(self):
        """(pW, pD, pA) must sum to exactly 1.0."""
        pW, pD, pA = three_way_probs(7.5, 7.0, scale=1.0)
        assert abs(pW + pD + pA - 1.0) < 1e-12

    def test_draw_rate_at_equal_strengths(self):
        """At equal strengths, draw prob = ν / (2 + ν) ≈ 0.28 for ν=0.778."""
        _, pD, _ = three_way_probs(7.0, 7.0, scale=1.0)
        expected = NU / (2.0 + NU)
        assert abs(pD - expected) < 1e-10

    def test_favourite_has_higher_win_prob(self):
        """Stronger team should have higher 90-min win probability."""
        pW, _, pA = three_way_probs(8.0, 6.0, scale=1.0)
        assert pW > pA

    def test_equal_strengths_symmetric(self):
        """At equal strengths pW == pA."""
        pW, pD, pA = three_way_probs(7.0, 7.0, scale=1.0)
        assert abs(pW - pA) < 1e-12

    def test_draw_decreases_for_mismatch(self):
        """Draw rate should drop when team quality gap widens."""
        _, pD_close, _ = three_way_probs(7.1, 7.0, scale=1.0)
        _, pD_far,   _ = three_way_probs(9.0, 5.0, scale=1.0)
        assert pD_far < pD_close


# ---------------------------------------------------------------------------
# advance_prob — scalar
# ---------------------------------------------------------------------------

class TestAdvanceProb:
    def test_sums_to_one(self):
        """P(A advances) + P(B advances) == 1.0."""
        p_ab = advance_prob(7.5, 7.0, scale=1.0)
        p_ba = advance_prob(7.0, 7.5, scale=1.0)
        assert abs(p_ab + p_ba - 1.0) < 1e-12

    def test_stronger_team_favoured(self):
        """Higher-rated team should have advance_prob > 0.5."""
        p = advance_prob(8.0, 6.0, scale=1.0)
        assert p > 0.5

    def test_output_in_zero_one(self):
        """Result always in (0, 1)."""
        for s_a, s_b, sc in [(7.0, 7.0, 1.0), (9.0, 5.0, 0.5), (5.0, 9.0, 2.0)]:
            p = advance_prob(s_a, s_b, sc)
            assert 0.0 < p < 1.0

    def test_et_bias_applied(self):
        """Equal strengths: home uses ET_BIAS_STRONGER, away 1-that."""
        p = advance_prob(7.0, 7.0, scale=1.0)
        pW, pD, _ = three_way_probs(7.0, 7.0, scale=1.0)
        expected = pW + pD * ET_BIAS_STRONGER
        assert abs(p - expected) < 1e-12

    def test_scale_sensitivity(self):
        """Higher scale = softer discrimination = advance_prob closer to 0.5."""
        p_tight = advance_prob(8.0, 6.0, scale=0.5)
        p_soft  = advance_prob(8.0, 6.0, scale=2.5)
        assert p_tight > p_soft


# ---------------------------------------------------------------------------
# advance_prob_vec — vectorised hot path
# ---------------------------------------------------------------------------

class TestAdvanceProbVec:
    def test_matches_scalar(self):
        """Vectorised result must match calling advance_prob element-wise."""
        rng = np.random.default_rng(0)
        s_l = rng.uniform(6.0, 8.5, size=(10, 4))
        s_r = rng.uniform(6.0, 8.5, size=(10, 4))
        vec = advance_prob_vec(s_l, s_r, scale=1.0)
        for i in range(s_l.shape[0]):
            for j in range(s_l.shape[1]):
                scalar = advance_prob(float(s_l[i, j]), float(s_r[i, j]), scale=1.0)
                assert abs(vec[i, j] - scalar) < 1e-10, (
                    f"vec[{i},{j}]={vec[i,j]:.8f} != scalar={scalar:.8f}"
                )

    def test_sums_to_one_elementwise(self):
        """
        p(a advances) + p(b advances) == 1.0 when strengths differ.

        Note: equal strengths are excluded — both calls use ET_BIAS_STRONGER (>=)
        so the two values don't sum to 1.0 when called symmetrically.  In
        practice the sim never calls both directions; it uses 1-p_left instead.
        """
        # Only non-equal-strength pairs
        s_l = np.array([[8.0, 6.5], [7.5, 5.0]])
        s_r = np.array([[6.0, 7.5], [6.5, 8.0]])
        p_l = advance_prob_vec(s_l, s_r, scale=1.0)
        p_r = advance_prob_vec(s_r, s_l, scale=1.0)
        np.testing.assert_allclose(p_l + p_r, 1.0, atol=1e-12)


# ---------------------------------------------------------------------------
# fallback_strength (no live DB — must degrade to FALLBACK_STRENGTH)
# ---------------------------------------------------------------------------

class TestFallbackStrength:
    def test_no_db_returns_constant(self):
        """Without a DB connection that has lineup/rating data, returns FALLBACK_STRENGTH."""
        import duckdb
        conn = duckdb.connect(":memory:")
        # No tables — should return FALLBACK_STRENGTH gracefully
        fb = fallback_strength(conn)
        conn.close()
        assert fb == FALLBACK_STRENGTH

    def test_constant_is_sensible(self):
        """FALLBACK_STRENGTH must be in the plausible rating range [6, 8]."""
        assert 6.0 <= FALLBACK_STRENGTH <= 8.0


# ---------------------------------------------------------------------------
# load_fitted_scale fallback
# ---------------------------------------------------------------------------

class TestLoadFittedScale:
    def test_no_db_returns_default(self):
        """Without model_params table, load_fitted_scale returns DEFAULT_SCALE."""
        import duckdb
        conn = duckdb.connect(":memory:")
        scale = load_fitted_scale(conn)
        conn.close()
        assert scale == DEFAULT_SCALE

    def test_reads_persisted_value(self):
        """After persisting a scale, load_fitted_scale returns it."""
        import duckdb
        from datetime import date
        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE model_params (
                run_date DATE NOT NULL,
                param    VARCHAR NOT NULL,
                value    DOUBLE NOT NULL,
                PRIMARY KEY (run_date, param)
            )
        """)
        conn.execute(
            "INSERT INTO model_params VALUES (?, ?, ?)",
            [str(date.today()), "logistic_scale", 1.35],
        )
        scale = load_fitted_scale(conn)
        conn.close()
        assert abs(scale - 1.35) < 1e-10
