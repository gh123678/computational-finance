"""Meaningful validation of GBM laws, coupling, limits, and finite-step moments."""

import math

import numpy as np
import pytest
from scipy.integrate import quad

from gbm import (
    coupled_terminals,
    density,
    exact_sampler,
    model_moments,
    prediction_interval,
    product_moments,
)


def rng(seed=58130):
    return np.random.default_rng(seed)


@pytest.mark.parametrize("mu", [0.05, 0.20])
def test_density_integrates_to_one_and_recovers_mean(mu):
    area = quad(lambda x: density(x, 1, mu, 0.4, 1), 0, np.inf)[0]
    first = quad(lambda x: x * density(x, 1, mu, 0.4, 1), 0, np.inf)[0]
    assert area == pytest.approx(1, abs=1e-9)
    assert first == pytest.approx(math.exp(mu), rel=1e-9)
    np.testing.assert_array_equal(density([-np.inf, -1, 0, np.inf], 1, mu, 0.4, 1), 0)


def test_t6_analytical_values_and_fixed_prediction_interval():
    m = model_moments(100, 0.08, 0.30, 2)
    assert m["mean"] == pytest.approx(117.35108709918103)
    assert m["variance"] == pytest.approx(2715.935063641711)
    assert m["median"] == pytest.approx(107.25081812542166)
    low, high = prediction_interval(100, 0.08, 0.30, 2)
    assert low == pytest.approx(46.693856862072145)
    assert high == pytest.approx(246.34371117703844)


def test_exact_sampler_log_drift_time_and_variance_scaling():
    M = 50000
    prices = exact_sampler(100, 0.08, 0.30, 2, M, rng())
    logs = np.log(prices / 100)
    expected_mean = (0.08 - 0.5 * 0.30**2) * 2
    expected_variance = 0.30**2 * 2
    assert abs(logs.mean() - expected_mean) < 6 * math.sqrt(expected_variance / M)
    assert abs(logs.var(ddof=1) - expected_variance) < 6 * expected_variance * math.sqrt(2 / (M - 1))
    assert np.all(prices > 0)
    # Same normal draws at T=1 and T=4 isolate time scaling exactly.
    log1 = np.log(exact_sampler(1, 0.08, 0.30, 1, 20, rng(192)) )
    log4 = np.log(exact_sampler(1, 0.08, 0.30, 4, 20, rng(192)) )
    m = 0.08 - 0.5 * 0.30**2
    np.testing.assert_allclose(log4 - 4 * m, 2 * (log1 - m), rtol=1e-13, atol=1e-14)


def test_deterministic_limits_have_no_ordinary_density():
    np.testing.assert_array_equal(exact_sampler(100, 0.08, 0.3, 0, 10, rng()), 100)
    np.testing.assert_allclose(exact_sampler(100, 0.08, 0, 2, 10, rng()), 100 * math.exp(0.16))
    assert model_moments(100, 0.08, 0, 2)["variance"] == 0
    assert prediction_interval(100, 0.08, 0, 2)[0] == prediction_interval(100, 0.08, 0, 2)[1]
    for sigma, T in [(0, 1), (0.3, 0)]:
        with pytest.raises(ValueError, match="point mass"):
            density(100, 100, 0.08, sigma, T)


@pytest.mark.parametrize("params", [
    (0, 0.08, 0.3, 1), (-1, 0.08, 0.3, 1),
    (100, float("nan"), 0.3, 1), (100, 0.08, -0.3, 1),
    (100, 0.08, 0.3, -1), (100, 0.08, float("inf"), 1),
])
def test_invalid_model_parameters_are_rejected(params):
    with pytest.raises(ValueError):
        model_moments(*params)
    with pytest.raises(ValueError):
        exact_sampler(*params, 2, rng())
    with pytest.raises(ValueError):
        density(100, *params)


@pytest.mark.parametrize("size", [-1, 1.5, True])
def test_invalid_sample_sizes(size):
    with pytest.raises(ValueError):
        exact_sampler(100, 0.08, 0.3, 1, size, rng())


def test_explicit_random_stream_and_resolution_checks():
    with pytest.raises(TypeError):
        exact_sampler(100, 0.08, 0.3, 1, 10, None)
    for steps, batch in [([], 1000), ([3, 4], 1000), ([4], 1001), ([0], 10)]:
        with pytest.raises(ValueError):
            coupled_terminals(100, 0.08, 0.3, 1, 10, steps, rng(), batch)
    with pytest.raises(ValueError):
        product_moments(100, 0.08, 0.3, 1, 16, "unknown")


def test_coarse_and_fine_solutions_share_identical_brownian_terminal():
    # For one-step Euler, S_E = S0*(1+mu*T+sigma*W_T). Recover W_T
    # independently from exact terminal logarithms. This catches incorrect
    # aggregation or independent reference paths at every retained path.
    out = coupled_terminals(100, 0.08, 0.3, 1, 137, [1, 4, 16], rng(), 37)
    recovered_w = (np.log(out["exact"] / 100) - (0.08 - 0.5 * 0.3**2)) / 0.3
    expected_one_step = 100 * (1 + 0.08 + 0.3 * recovered_w)
    np.testing.assert_allclose(out["euler"][1], expected_one_step, atol=1e-12)
    np.testing.assert_array_equal(out["wrong"][1], out["euler"][1])
    out2 = coupled_terminals(100, 0.08, 0.3, 1, 137, [1, 4, 16], rng(), 100)
    np.testing.assert_array_equal(out["exact"], out2["exact"])
    for method in ("euler", "wrong"):
        for n in [1, 4, 16]:
            np.testing.assert_array_equal(out[method][n], out2[method][n])


def test_no_clipping_or_discarding_nonpositive_euler_paths():
    out = coupled_terminals(100, 0.08, 1, 1, 10000, [1], rng(221))
    count = np.count_nonzero(out["euler"][1] <= 0)
    assert 0 < count < 10000
    assert out["nonpositive_multipliers"]["euler"][1] == count
    assert len(out["euler"][1]) == 10000
    assert out["euler"][1].min() < 0


def test_product_moments_and_coupled_cross_moments():
    # Finite-n population formulas are checked against a separate seeded run,
    # including E[exact*approx], which tests pathwise coupling itself.
    M = 50000
    out = coupled_terminals(100, 0.08, 0.3, 1, M, [4, 16], rng(9103), 1000)
    for method in ("euler", "wrong"):
        for n in [4, 16]:
            sample = out[method][n]
            p = product_moments(100, 0.08, 0.3, 1, n, method)
            mean_se = sample.std(ddof=1) / math.sqrt(M)
            assert abs(sample.mean() - p["mean"]) < 6 * mean_se
            cross = sample * out["exact"]
            cross_se = cross.std(ddof=1) / math.sqrt(M)
            assert abs(cross.mean() - p["cross_moment_with_exact"]) < 6 * cross_se
            error_squared = (sample - out["exact"])**2
            mse_se = error_squared.std(ddof=1) / math.sqrt(M)
            assert abs(error_squared.mean() - p["mse_against_exact"]) < 6 * mse_se
            # Population variance itself also has an independent MC diagnostic.
            fourth = np.mean((sample - sample.mean())**4)
            var_se = math.sqrt(max(0, (fourth - (M - 3) / (M - 1) * sample.var(ddof=1)**2) / M))
            assert abs(sample.var(ddof=1) - p["variance"]) < 6 * var_se


def test_zero_time_and_zero_volatility_coupled_limits():
    out = coupled_terminals(100, 0.08, 0.3, 0, 12, [4, 16], rng(), 5)
    np.testing.assert_array_equal(out["exact"], 100)
    for method in ("euler", "wrong"):
        for n in [4, 16]:
            np.testing.assert_array_equal(out[method][n], 100)
    for method in ("euler", "wrong"):
        p = product_moments(100, 0.08, 0, 1, 16, method)
        expected = 100 * (1 + 0.08 / 16)**16
        assert p["mean"] == pytest.approx(expected)
        assert p["variance"] == pytest.approx(0, abs=1e-8)
        assert p["rmse_against_deterministic"] == pytest.approx(abs(expected - 100 * math.exp(0.08)), abs=1e-8)


def test_wrong_model_variance_vanishes_but_exact_path_error_does_not():
    coarse = product_moments(100, 0.08, 0.3, 1, 16, "wrong")
    fine = product_moments(100, 0.08, 0.3, 1, 65536, "wrong")
    assert fine["variance"] < coarse["variance"] / 1000
    assert fine["rmse_against_deterministic"] < 0.2
    assert fine["rmse_against_exact"] > 30


def test_mean_standard_error_shrinks_prediction_interval_does_not():
    moments = model_moments(100, 0.08, 0.3, 2)
    se100 = math.sqrt(moments["variance"] / 100)
    se400 = math.sqrt(moments["variance"] / 400)
    assert se400 == se100 / 2
    interval = prediction_interval(100, 0.08, 0.3, 2)
    mean_ci_width100 = 2 * 1.96 * se100
    mean_ci_width400 = 2 * 1.96 * se400
    assert mean_ci_width400 == mean_ci_width100 / 2
    # The physical prediction width uses sigma*sqrt(T), not a /sqrt(M) factor.
    center = 100 * math.exp((0.08 - 0.3**2 / 2) * 2)
    physical_width = center * (math.exp(1.96 * 0.3 * math.sqrt(2))
                               - math.exp(-1.96 * 0.3 * math.sqrt(2)))
    assert interval[1] - interval[0] == pytest.approx(physical_width)
    assert physical_width > mean_ci_width100
