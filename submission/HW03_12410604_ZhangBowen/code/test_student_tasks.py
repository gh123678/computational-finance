"""All twelve supplied checklist topics, replaced with substantive assertions."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

import gbm
import student_tasks as tasks


@pytest.mark.parametrize("prices", [[1, 0], [1, -1], [1, np.nan], [1, np.inf], [1], [[1, 2], [3, 4]]])
def test_01_reject_nonpositive_or_nonfinite_prices(prices):
    with pytest.raises(ValueError):
        tasks.log_returns(np.asarray(prices))


def _write_csv(tmp_path, dates, prices=None, field="Price"):
    path = tmp_path / "prices.csv"
    if prices is None:
        prices = np.arange(len(dates)) + 10
    pd.DataFrame({"Date": dates, field: prices}).to_csv(path, index=False)
    return path


@pytest.mark.parametrize("dates", [
    ["2026-10-01", "2026-10-01"], ["2026-10-01", None],
    ["2026-10-01", "NaT"], ["2026-10-01", ""],
    ["2026-10-01", "2026/10/02"], ["2026-10-01", "2026-10-2"],
    ["2026-10-01", "2026-02-30"], ["2026-10-01", "2026-10-02T00:00:00"],
])
def test_02_audit_rejects_duplicate_invalid_and_missing_dates(tmp_path, dates):
    with pytest.raises(ValueError):
        tasks.load_prices(_write_csv(tmp_path, dates))


def test_02_sorting_gaps_and_adjusted_price_alias_are_reported(tmp_path):
    path = _write_csv(tmp_path, ["2026-10-05", "2026-10-01", "2026-10-02"], [12, 10, 11], "AdjClose")
    frame, audit = tasks.load_prices(path)
    assert frame.Date.is_monotonic_increasing
    assert frame.Price.tolist() == [10, 11, 12]
    assert audit["selected_price_column"] == "AdjClose"
    assert audit["price_alias_added"] is True
    assert audit["sorting_performed"] is True
    assert audit["max_calendar_gap_days"] == 3
    assert audit["rows_deleted"] == 0
    assert audit["nontrading_dates_filled"] is False
    assert audit["missing_us_equity_sessions"] == []
    assert len(audit["source_sha256"]) == 64
    with pytest.raises(ValueError, match="Missing price column"):
        tasks.load_prices(path, price_column="Unknown")


@pytest.mark.parametrize("prices", [[10, 0], [10, -2], [10, np.nan], [10, np.inf], [10, "invalid"]])
def test_02_csv_rejects_invalid_prices(tmp_path, prices):
    path = _write_csv(tmp_path, ["2026-10-01", "2026-10-02"], prices)
    with pytest.raises(ValueError):
        tasks.load_prices(path)


def test_03_return_aggregation_identity():
    prices = np.array([100., 110., 99., 123.])
    r = tasks.log_returns(prices)
    simple = prices[1:] / prices[:-1] - 1
    assert r.sum() == pytest.approx(np.log(123 / 100))
    assert np.expm1(r.sum()) == pytest.approx(np.prod(1 + simple) - 1)
    assert simple.sum() != pytest.approx(123 / 100 - 1)


def test_04_histogram_normalization_and_qq_ordering():
    x = np.array([-3., -1., 0., 1., 5.])
    heights, edges = np.histogram(x, bins=4, density=True)
    assert np.dot(heights, np.diff(edges)) == pytest.approx(1)
    q, z = tasks.qq_coordinates(x)
    np.testing.assert_allclose(q, norm.ppf((np.arange(1, 6) - 0.5) / 5))
    assert np.all(np.diff(q) > 0)
    assert np.all(np.diff(z) > 0)
    assert z.mean() == pytest.approx(0, abs=1e-14)
    assert z.var(ddof=1) == pytest.approx(1)
    with pytest.raises(ValueError, match="constant"):
        tasks.standardize([1, 1])


def test_05_permutation_preserves_marginal_but_changes_temporal_statistics():
    x = np.array([1., 2., 4., 7., 11.])
    permuted = x[[2, 0, 4, 1, 3]]
    for key in ["mean", "variance", "skewness", "excess_kurtosis"]:
        assert tasks.descriptive_stats(x)[key] == pytest.approx(tasks.descriptive_stats(permuted)[key])
    assert not np.allclose(tasks.acf(x, 2), tasks.acf(permuted, 2))
    np.testing.assert_allclose(tasks.acf([1., 2., 4., 3.], 2), [1., 0.15, -0.5])
    for lag in [-1, 2.5, True, 5]:
        with pytest.raises(ValueError):
            tasks.acf(x, lag)
    with pytest.raises(ValueError):
        tasks.acf([1, 1], 1)
    with pytest.raises(ValueError, match="Nonconstant"):
        tasks.descriptive_stats([1, 1])


def test_06_physical_model_annualization_and_units():
    returns = np.array([-0.01, 0.01, 0.03])
    fitted = tasks.fit_gbm(returns)
    mean, variance = 0.01, 0.0004
    assert fitted["m_hat"] == pytest.approx(252 * mean)
    assert fitted["sigma_squared_hat"] == pytest.approx(252 * variance)
    assert fitted["sigma_hat"] == pytest.approx(np.sqrt(252 * variance))
    assert fitted["mu_hat"] == pytest.approx(252 * (mean + variance / 2))
    assert fitted["log_drift_se"] == pytest.approx(252 * np.sqrt(variance / 3))
    assert fitted["observed_horizon_years"] == pytest.approx(3 / 252)
    # More frequent sampling at fixed H does not improve model drift SE.
    assert fitted["sigma_hat"] / np.sqrt(fitted["observed_horizon_years"]) == pytest.approx(fitted["log_drift_se"])
    assert tasks.fit_gbm([0.01, 0.01])["sigma_hat"] == 0


def test_07_gbm_moments_and_quantiles_from_independent_reasoning():
    moments = tasks.gbm_moments(100, 0.08, 0.30, 2)
    assert moments["mean"] == pytest.approx(100 * np.exp(0.16))
    assert moments["variance"] == pytest.approx(10000 * np.exp(0.32) * np.expm1(0.18))
    quantiles = tasks.gbm_quantiles(np.array([0.025, 0.5, 0.975]), 100, 0.08, 0.30, 2)
    assert quantiles[1] == pytest.approx(100 * np.exp(0.07))
    np.testing.assert_allclose(np.log(quantiles / 100), 0.07 + 0.30 * np.sqrt(2) * norm.ppf([.025, .5, .975]))
    assert tasks.gbm_density(np.array([-1, 0, 100]), 100, .08, .3, 2)[0] == 0
    # Exact terminal draws use the supplied RNG and correct log-mean/variance.
    expected_z = np.random.default_rng(92).standard_normal(10)
    actual = tasks.exact_terminal(100, .08, .3, 2, 10, np.random.default_rng(92))
    np.testing.assert_allclose(np.log(actual / 100), .07 + .3 * np.sqrt(2) * expected_z)


def test_08_deterministic_limits_and_invalid_inputs():
    np.testing.assert_allclose(tasks.exact_terminal(100, .08, 0, 2, 8, np.random.default_rng(1)), 100 * np.exp(.16))
    np.testing.assert_allclose(tasks.gbm_quantiles(np.array([.1, .9]), 100, .08, .3, 0), 100)
    assert tasks.gbm_moments(100, .08, 0, 2)["variance"] == 0
    for s0, mu, sigma, T in [(0, .08, .3, 1), (100, np.nan, .3, 1), (100, .08, -.3, 1), (100, .08, .3, -1)]:
        with pytest.raises(ValueError):
            tasks.gbm_moments(s0, mu, sigma, T)
    for probabilities in [[0], [1], [-.1], [np.nan]]:
        with pytest.raises(ValueError):
            tasks.gbm_quantiles(np.array(probabilities), 100, .08, .3, 1)
    with pytest.raises(ValueError):
        tasks.gbm_density(np.array([100]), 100, .08, 0, 1)
    for step in [0, -1, np.nan]:
        with pytest.raises(ValueError):
            tasks.fit_gbm([.01, .02], step)


def test_09_mean_interval_scaling_is_distinct_from_prediction():
    sample = np.array([1., 2., 3., 4.])
    result = tasks.mean_ci(sample)
    assert result["mean"] == pytest.approx(2.5)
    assert result["standard_error"] == pytest.approx(np.sqrt(5 / 3) / 2)
    assert result["ci95"][1] - result["ci95"][0] == pytest.approx(2 * 1.96 * result["standard_error"])
    # Equal empirical variance in the two explicit samples isolates n^-1/2.
    larger = np.tile(sample - sample.mean(), 4)
    larger *= np.std(sample, ddof=1) / np.std(larger, ddof=1)
    assert tasks.mean_ci(larger)["standard_error"] == pytest.approx(result["standard_error"] / 2)
    p = tasks.gbm_quantiles(np.array([.025, .975]), 100, .08, .3, 2)
    assert p[1] - p[0] > 100
    with pytest.raises(ValueError):
        tasks.mean_ci(np.array([1.]))


def test_10_common_brownian_terminal_increment_and_known_updates():
    fine = np.array([[.1, -.2, .3, -.1], [-.2, .4, -.1, .2]])
    coarse = tasks.coarsen_increments(fine, 2)
    np.testing.assert_allclose(coarse, [[-.1, .2], [.2, .1]])
    np.testing.assert_allclose(fine.sum(axis=1), coarse.sum(axis=1))
    f = tasks.coupled_terminals(fine, 100, .08, .3, .25)
    c = tasks.coupled_terminals(coarse, 100, .08, .3, .5)
    np.testing.assert_allclose(f["exact"], c["exact"])
    np.testing.assert_allclose(f["euler"], 100 * np.prod(1.02 + .3 * fine, axis=1))
    np.testing.assert_allclose(f["wrong"], 100 * np.prod(1.02 + .15 * fine, axis=1))
    with pytest.raises(ValueError):
        tasks.coarsen_increments(fine, 3)
    with pytest.raises(ValueError):
        tasks.coupled_terminals(np.array([.1, .2]), 100, .08, .3, .5)


def test_11_nonpositive_multipliers_and_paths_are_retained():
    # Two negative multipliers give a positive terminal: path flags must still
    # record the failure, rather than relying on the final sign alone.
    out = tasks.coupled_terminals(np.array([[-2., -2.], [-2., 0.], [0., 0.]]), 100, 0, 1, 1)
    np.testing.assert_array_equal(out["euler"], [100, -100, 100])
    np.testing.assert_array_equal(out["euler_nonpositive_path"], [True, True, False])
    np.testing.assert_array_equal(out["euler_nonpositive_terminal"], [False, True, False])
    assert out["euler_nonpositive_multipliers"].sum() == 3
    assert len(out["exact"]) == 3
    assert np.all(out["exact"] > 0)


def test_12_discrete_moments_convergence_and_batch_reproducibility():
    for alpha, method in [(0.5, "euler"), (1., "wrong")]:
        interface = tasks.discrete_moments(100, .08, .3, 1, 16, alpha)
        separate = gbm.product_moments(100, .08, .3, 1, 16, method)
        for key in ["mean", "variance", "second_moment"]:
            assert interface[key] == pytest.approx(separate[key])
    assert tasks.discrete_moments(100, .08, .3, 1, 4096, 1)["variance"] < tasks.discrete_moments(100, .08, .3, 1, 16, 1)["variance"] / 100
    assert tasks.discrete_moments(100, .08, .3, 0, 16, -.5)["variance"] == 0
    fine = np.random.default_rng(219).standard_normal((53, 16)) / 4
    full = tasks.coupled_terminals(fine, 100, .08, .3, 1 / 16)
    chunks = [tasks.coupled_terminals(fine[i:i+7], 100, .08, .3, 1 / 16) for i in range(0, len(fine), 7)]
    for key, values in full.items():
        np.testing.assert_array_equal(np.concatenate([chunk[key] for chunk in chunks]), values)
    streamed = gbm.coupled_terminals(100, .08, .3, 1, 53, [16], np.random.default_rng(219), 7)
    for key in ["exact", "euler", "wrong"]:
        expected = streamed["exact"] if key == "exact" else streamed[key][16]
        np.testing.assert_allclose(full[key], expected, rtol=1e-14)


def test_driver_honors_nondefault_seed_and_restores_module_state(tmp_path, monkeypatch):
    import experiments_gbm as experiments
    original = experiments.RESULTS, experiments.FIGURES, experiments.MASTER_SEED
    seen = []
    def small_probe():
        seen.append((experiments.MASTER_SEED, experiments.RESULTS, float(experiments.stream(3).normal())))
        return {"probe": seen[-1][2]}
    monkeypatch.setattr(experiments, "run_a3", small_probe)
    tasks.run_coupled_experiment(tmp_path / "one", seed=17)
    tasks.run_coupled_experiment(tmp_path / "two", seed=17)
    tasks.run_coupled_experiment(tmp_path / "three", seed=18)
    assert seen[0][0] == seen[1][0] == 17
    assert seen[0][2] == seen[1][2]
    assert seen[0][2] != seen[2][2]
    assert seen[0][1] == (tmp_path / "one" / "results").resolve()
    assert (experiments.RESULTS, experiments.FIGURES, experiments.MASTER_SEED) == original


def test_driver_restores_state_after_failure(tmp_path, monkeypatch):
    import experiments_gbm as experiments
    original = experiments.RESULTS, experiments.FIGURES, experiments.MASTER_SEED
    def failing_probe():
        raise RuntimeError("deliberate exception verifies restoration")
    monkeypatch.setattr(experiments, "run_a3", failing_probe)
    with pytest.raises(RuntimeError, match="deliberate exception"):
        tasks.run_coupled_experiment(tmp_path / "failure", seed=53)
    assert (experiments.RESULTS, experiments.FIGURES, experiments.MASTER_SEED) == original
