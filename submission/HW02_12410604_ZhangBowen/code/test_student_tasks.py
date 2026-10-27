"""Starter tests, not a complete grading suite.

Run: python -m pytest code/test_student_tasks.py -v
Unimplemented TODOs are explicitly SKIPPED, never silently counted as passed.
Add numerical, boundary, statistical, and reproducibility tests of your own.
"""
from __future__ import annotations
import importlib
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Alternate module enables instructor validation without changing student code.
tasks = importlib.import_module(os.environ.get("HW02_TASK_MODULE", "student_tasks"))


def implemented(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except NotImplementedError:
        pytest.skip("TODO is not implemented; this is NOT a correctness pass")


def test_basic_payoffs():
    s = np.array([0.0, 50.0, 100.0])
    c = implemented(tasks.call_payoff, s, 50)
    p = implemented(tasks.put_payoff, s, 50)
    np.testing.assert_allclose(c, [0, 0, 50])
    np.testing.assert_allclose(p, [50, 0, 0])
    np.testing.assert_allclose(c - p, s - 50)


def test_butterfly_replication():
    s = np.array([0.0, 40.0, 50.0, 60.0, 100.0])
    c = implemented(tasks.butterfly_payoff, s, (40, 50, 60), "call")
    p = implemented(tasks.butterfly_payoff, s, (40, 50, 60), "put")
    np.testing.assert_allclose(c, p, atol=1e-12)
    assert np.all(c >= -1e-12)
    np.testing.assert_allclose(c[[0, 1, 3, 4]], 0)


def test_profit_financing():
    out = implemented(tasks.financed_profit, np.array([0.0, 10.0]), 4.0, 0.0, 1.0)
    np.testing.assert_allclose(out, [-4, 6])


def test_compounding_roundtrip():
    for m in [1, 12, 365]:
        rc = implemented(tasks.nominal_from_continuous, 0.05, m)
        r = implemented(tasks.continuous_from_nominal, rc, m)
        total_rc = implemented(tasks.rate_for_total_periods, 0.05, 2, 2 * m)
        assert r == pytest.approx(0.05, abs=1e-12)
        assert total_rc == pytest.approx(rc, abs=1e-12)
        assert (1 + rc / m) ** (2 * m) == pytest.approx(np.exp(0.1), rel=1e-12)


def test_exponential_quantile():
    p = np.array([0.0, 0.1, 0.5, 0.9])
    q = implemented(tasks.exponential_quantile, p, 2.0)
    assert q[0] == 0
    assert np.all(np.diff(q) > 0)
    np.testing.assert_allclose(-np.expm1(-2 * q), p, atol=1e-14)
    with pytest.raises(ValueError):
        tasks.exponential_quantile([1.0], 1.0)
    with pytest.raises(ValueError):
        tasks.exponential_quantile([0.5], 0.0)


def test_sampler_reproducibility():
    first = implemented(tasks.exponential_samples, 1.0, 30, np.random.default_rng(123))
    second = implemented(tasks.exponential_samples, 1.0, 30, np.random.default_rng(123))
    np.testing.assert_array_equal(first, second)
    assert np.all(np.isfinite(first)) and np.all(first >= 0)


def test_clt_shape_and_random_state():
    rng = np.random.default_rng(2026)
    z = implemented(tasks.standardized_exponential_sums, 30, 100, 1.0, rng, 17)
    z2 = implemented(tasks.standardized_exponential_sums, 30, 100, 1.0, rng, 17)
    assert z.shape == (100,)
    assert np.all(np.isfinite(z))
    assert not np.array_equal(z, z2)


def test_normal_qq_positions():
    x, y = implemented(tasks.normal_qq, np.array([3, -1, 0, 1]))
    assert np.all(np.isfinite(x)) and np.all(np.diff(x) > 0)
    np.testing.assert_allclose(x, -x[::-1])
    np.testing.assert_array_equal(y, [-1, 0, 1, 3])


def test_binomial_replication_and_parity():
    args = (100.0, 100.0, 1.2, 0.8, 0.05, 1.0)
    c = implemented(tasks.exact_binomial, *args, "call")
    p = implemented(tasks.exact_binomial, *args, "put")
    assert c["delta"] * 120 + c["bank"] * np.exp(0.05) == pytest.approx(c["payoff_up"])
    assert c["delta"] * 80 + c["bank"] * np.exp(0.05) == pytest.approx(c["payoff_down"], abs=1e-12)
    assert c["price"] - p["price"] == pytest.approx(100 - 100 * np.exp(-0.05))


def test_invalid_tree():
    implemented(tasks.risk_neutral_probability, 1.2, 0.8, 0.05, 1.0)
    with pytest.raises(ValueError):
        tasks.risk_neutral_probability(1.01, 0.8, 0.05, 1.0)
    with pytest.raises(ValueError):
        tasks.risk_neutral_probability(1.2, 1.2, 0.05, 1.0)


def test_mc_uncertainty_and_pairing():
    result = implemented(tasks.monte_carlo_binomial, 100, 100, 1.2, 0.8, 0.05, 1.0,
                         10000, np.random.default_rng(12345))
    assert result["call"] >= 0 and result["put"] >= 0
    assert result["call_se"] > 0 and result["put_se"] > 0
    assert result["call_ci_high"] - result["call"] == pytest.approx(1.96 * result["call_se"])
    residual = result["call"] - result["put"] - (100 - 100 * np.exp(-0.05))
    assert result["parity_residual"] == pytest.approx(residual, abs=1e-12)
