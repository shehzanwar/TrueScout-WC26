"""
Tests for Brier tracker math and structural invariants.

These tests cover:
- The 2-way logistic probability function
- Market collapse from 3-way to 2-way odds
- Brier score range checks
- Guard that LOGISTIC_SCALE is removed in W1.1 refactor
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from etl.models.brier_tracker import _logistic_advance, _market_2way, CLIP_LO, CLIP_HI


# ---------------------------------------------------------------------------
# Logistic probability
# ---------------------------------------------------------------------------

class TestLogisticAdvance:
    def test_equal_strengths(self):
        """Equal strengths → 50% advance probability."""
        p = _logistic_advance(7.0, 7.0, scale=1.5)
        assert abs(p - 0.5) < 1e-10

    def test_symmetry(self):
        """P(A beats B) + P(B beats A) == 1."""
        p_ab = _logistic_advance(7.5, 7.0, scale=1.5)
        p_ba = _logistic_advance(7.0, 7.5, scale=1.5)
        assert abs(p_ab + p_ba - 1.0) < 1e-10

    def test_stronger_home_favoured(self):
        """Higher strength home team should have P > 0.5."""
        p = _logistic_advance(8.0, 6.0, scale=1.5)
        assert p > 0.5

    def test_scale_sensitivity(self):
        """Smaller scale → stronger discrimination (larger P for the better team)."""
        delta = 7.5 - 7.0
        p_tight = _logistic_advance(7.5, 7.0, scale=0.5)
        p_soft  = _logistic_advance(7.5, 7.0, scale=2.0)
        assert p_tight > p_soft, (
            f"Smaller scale should give higher P for favourite: {p_tight:.4f} vs {p_soft:.4f}"
        )

    def test_output_in_zero_one(self):
        """Result must always be in (0, 1)."""
        for s_h, s_a, sc in [(7.0, 7.0, 1.5), (9.0, 5.0, 0.5), (5.0, 9.0, 3.0)]:
            p = _logistic_advance(s_h, s_a, sc)
            assert 0.0 < p < 1.0, f"P={p} out of (0,1) for ({s_h}, {s_a}, {sc})"


# ---------------------------------------------------------------------------
# Market 2-way collapse
# ---------------------------------------------------------------------------

class TestMarket2Way:
    def test_pure_home_win(self):
        """If draw=0 and away=0, home advance prob should equal home_win prob."""
        p = _market_2way(1.0, 0.0, 0.0, et_bias=0.55)
        assert abs(p - 1.0) < 1e-10

    def test_equal_3way_collapse(self):
        """
        For 1/3 each, the 2-way collapse depends on et_bias.
        market_2way = pW + pD × et_bias = 1/3 + 1/3 × 0.55 ≈ 0.5167
        """
        p = _market_2way(1/3, 1/3, 1/3, et_bias=0.55)
        expected = 1/3 + 1/3 * 0.55
        assert abs(p - expected) < 1e-9

    def test_none_inputs_return_none(self):
        """Missing home or away returns None; missing draw only = already 2-way market."""
        assert _market_2way(None, None, None, et_bias=0.55) is None
        assert _market_2way(None, 0.3,  0.6,  et_bias=0.55) is None
        # draw=None means 2-way market already — return home_win directly
        assert abs(_market_2way(0.4, None, 0.6, et_bias=0.55) - 0.4) < 1e-10

    def test_result_in_clip_range(self):
        """Output should be within [CLIP_LO, CLIP_HI]."""
        p = _market_2way(0.95, 0.03, 0.02, et_bias=0.55)
        assert CLIP_LO <= p <= CLIP_HI

    def test_symmetry_with_neutral_bias(self):
        """
        With equal teams and et_bias=0.5 (neutral ET), collapse should be ~0.5.
        pW=pD=pA=1/3 → 1/3 + 1/3×0.5 = 0.5
        """
        p = _market_2way(1/3, 1/3, 1/3, et_bias=0.5)
        assert abs(p - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# Brier score bounds
# ---------------------------------------------------------------------------

class TestBrierBounds:
    def test_perfect_prediction_brier_zero(self):
        """Brier score of a perfect prediction (prob=1, outcome=1) should be 0."""
        p, outcome = 0.99, 1  # clipped to CLIP_HI
        brier = (p - outcome) ** 2
        assert brier < 0.01

    def test_worst_prediction_brier_near_one(self):
        """Brier score of p=0.01, outcome=1 should be near 1."""
        p, outcome = 0.01, 1
        brier = (p - outcome) ** 2
        assert brier > 0.95

    def test_coin_flip_brier(self):
        """Coin flip (p=0.5) scores 0.25 regardless of outcome."""
        assert abs((0.5 - 0) ** 2 - 0.25) < 1e-10
        assert abs((0.5 - 1) ** 2 - 0.25) < 1e-10


# ---------------------------------------------------------------------------
# Guard: LOGISTIC_SCALE lives in calibration.py only (W1.1 invariant)
# ---------------------------------------------------------------------------

def test_no_logistic_scale_constant_in_brier():
    """LOGISTIC_SCALE must not be defined in brier_tracker — it lives in calibration.py."""
    import etl.models.brier_tracker as bt_module
    assert not hasattr(bt_module, "LOGISTIC_SCALE"), (
        "LOGISTIC_SCALE still defined in brier_tracker — move it to calibration.py"
    )
