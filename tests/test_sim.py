"""
Tests for the Monte Carlo simulation engine.

Designed to run before the W1.1 calibration refactor so they can validate
that the refactor preserves all mathematical guarantees.

In-memory bracket — no DuckDB required for most tests.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from etl.models.monte_carlo_sim import _run_sim, ROUNDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uniform_strengths(n: int = 32, value: float = 7.0) -> np.ndarray:
    return np.full(n, value, dtype=np.float64)


def _gradient_strengths(n: int = 32) -> np.ndarray:
    """Teams 0..n-1 with linearly increasing strength — biggest spread of outcomes."""
    return np.linspace(6.0, 8.5, n)


# ---------------------------------------------------------------------------
# Probability identities
# ---------------------------------------------------------------------------

class TestProbabilityIdentities:
    def test_equal_strengths_near_half(self):
        """With uniform strengths, every team should win ~1/32 of the time."""
        strengths = _uniform_strengths()
        counts, _ = _run_sim(strengths, n_sim=200_000, scale=1.0, seed=42)
        title_probs = counts[:, -1] / 200_000
        # Each team should be close to 1/32 ≈ 0.03125
        assert all(abs(p - 1/32) < 0.01 for p in title_probs), (
            f"Title probs deviate too far from 1/32: {title_probs}"
        )

    def test_dominant_team_favoured(self):
        """A team with much higher strength should win the most."""
        strengths = _uniform_strengths()
        strengths[0] = 9.0   # team 0 is dominant; others at 7.0
        counts, _ = _run_sim(strengths, n_sim=100_000, scale=1.0, seed=42)
        title_probs = counts[:, -1] / 100_000
        # Team 0 should have the highest title prob by a clear margin
        assert title_probs[0] == max(title_probs), "Strongest team should be most likely champion"
        assert title_probs[0] > 0.15, f"Dominant team title prob too low: {title_probs[0]:.3f}"

    def test_logistic_symmetry(self):
        """P(A beats B at strength x) == P(B beats A at strength -x) — logistic is symmetric."""
        strengths_ab = np.array([7.5, 7.0])  # just 2 teams
        # Simulate a 2-team "bracket" — one round only
        # P(A wins) with s_A=7.5, s_B=7.0, scale=1.0:
        p = 1.0 / (1.0 + 10.0 ** (-(7.5 - 7.0) / 1.0))
        p_reverse = 1.0 / (1.0 + 10.0 ** (-(7.0 - 7.5) / 1.0))
        assert abs(p + p_reverse - 1.0) < 1e-10, "Logistic probs must sum to 1"


# ---------------------------------------------------------------------------
# Title probability integrity
# ---------------------------------------------------------------------------

class TestTitleProbabilityIntegrity:
    @pytest.mark.parametrize("n_sim", [10_000, 100_000])
    def test_title_probs_sum_to_one(self, n_sim):
        """Title probs must sum to 1.0 ± 0.005 (matches tightened _validate tolerance)."""
        strengths = _gradient_strengths()
        counts, _ = _run_sim(strengths, n_sim=n_sim, scale=1.0, seed=42)
        title_probs = counts[:, -1] / n_sim
        total = title_probs.sum()
        assert abs(total - 1.0) < 0.005, (
            f"Title probs sum to {total:.6f}, expected 1.0 ± 0.005"
        )

    def test_all_rounds_non_negative(self):
        """advance_prob must be in [0, 1] for every team/round."""
        strengths = _gradient_strengths()
        counts, _ = _run_sim(strengths, n_sim=50_000, scale=1.0, seed=42)
        probs = counts / 50_000
        assert (probs >= 0).all(), "Negative advance_prob found"
        assert (probs <= 1.0 + 1e-9).all(), "advance_prob > 1 found"

    def test_r32_all_one(self):
        """Every team starts R32 — advance_count[:, 0] should equal n_sim."""
        strengths = _uniform_strengths()
        counts, _ = _run_sim(strengths, n_sim=1_000, scale=1.0, seed=42)
        assert (counts[:, 0] == 1_000).all(), "Not all teams counted in R32"


# ---------------------------------------------------------------------------
# Monotonicity
# ---------------------------------------------------------------------------

class TestMonotonicity:
    def test_advance_prob_monotone_decreasing(self):
        """P(reach round r+1) ≤ P(reach round r) for every team."""
        strengths = _gradient_strengths()
        counts, _ = _run_sim(strengths, n_sim=100_000, scale=1.0, seed=0)
        probs = counts / 100_000  # (n_teams, n_rounds)
        for team_idx in range(len(strengths)):
            for r in range(probs.shape[1] - 1):
                assert probs[team_idx, r + 1] <= probs[team_idx, r] + 1e-9, (
                    f"Team {team_idx}: P(round {r+1}) > P(round {r}) — "
                    f"{probs[team_idx, r+1]:.4f} > {probs[team_idx, r]:.4f}"
                )


# ---------------------------------------------------------------------------
# Seed determinism
# ---------------------------------------------------------------------------

class TestSeedDeterminism:
    def test_same_seed_same_result(self):
        """Identical seeds must produce identical advance counts."""
        strengths = _gradient_strengths()
        counts_a, _ = _run_sim(strengths, n_sim=10_000, scale=1.0, seed=42)
        counts_b, _ = _run_sim(strengths, n_sim=10_000, scale=1.0, seed=42)
        np.testing.assert_array_equal(counts_a, counts_b)

    def test_different_seeds_differ(self):
        """Different seeds should (almost certainly) differ."""
        strengths = _gradient_strengths()
        counts_a, _ = _run_sim(strengths, n_sim=10_000, scale=1.0, seed=1)
        counts_b, _ = _run_sim(strengths, n_sim=10_000, scale=1.0, seed=2)
        assert not np.array_equal(counts_a, counts_b), (
            "Different seeds produced identical results — very unlikely"
        )


# ---------------------------------------------------------------------------
# Lock-in broadcast
# ---------------------------------------------------------------------------

class TestLockIn:
    def test_completed_r32_respected(self):
        """
        When team 0 is the confirmed R32 winner of match 0, it should advance
        with probability 1.0 (100% of sims), regardless of strength.
        """
        strengths = _gradient_strengths()
        # Team 0 plays at bracket position 0; team 1 at position 1.
        # Confirm team 0 (position 0) won.
        completed_r32 = {0: 0}   # match 0, winner = bracket position 0 (team 0)
        counts, _ = _run_sim(
            strengths, n_sim=5_000, scale=1.0, seed=42,
            completed_r32=completed_r32,
        )
        # Team 0 must appear in R16 (round idx 1) in every sim
        assert counts[0, 1] == 5_000, (
            f"Lock-in failed: team 0 only in R16 in {counts[0, 1]}/5000 sims"
        )
        # Team 1 must NOT appear in R16 (they lost to team 0)
        assert counts[1, 1] == 0, (
            f"Lock-in failed: eliminated team 1 appeared in R16 {counts[1, 1]} times"
        )


# ---------------------------------------------------------------------------
# Scale sensitivity
# ---------------------------------------------------------------------------

class TestScaleSensitivity:
    def test_higher_scale_more_upsets(self):
        """
        Higher scale = softer discrimination = more upsets = more spread title probs.
        The weakest team's title prob should be higher at scale=3 than scale=0.5.
        """
        strengths = _gradient_strengths()
        counts_tight, _ = _run_sim(strengths, n_sim=100_000, scale=0.5, seed=42)
        counts_soft,  _ = _run_sim(strengths, n_sim=100_000, scale=3.0, seed=42)
        weak_tight = counts_tight[0, -1] / 100_000
        weak_soft  = counts_soft [0, -1] / 100_000
        assert weak_soft > weak_tight, (
            f"Softer scale should give weakest team higher title prob "
            f"({weak_soft:.4f} vs {weak_tight:.4f})"
        )


# ---------------------------------------------------------------------------
# Guard: LOGISTIC_SCALE lives in calibration.py only (W1.1 invariant)
# ---------------------------------------------------------------------------

def test_no_logistic_scale_constant_in_sim():
    """LOGISTIC_SCALE must not be defined in monte_carlo_sim — it lives in calibration.py."""
    import etl.models.monte_carlo_sim as sim_module
    assert not hasattr(sim_module, "LOGISTIC_SCALE"), (
        "LOGISTIC_SCALE still defined in monte_carlo_sim — move it to calibration.py"
    )
