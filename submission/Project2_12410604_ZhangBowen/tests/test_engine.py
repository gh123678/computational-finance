"""Economic identities and signal-timing tests for the monthly implementation."""
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data import monthly_panel, read_french_zip
from src.engine import fit_scale, managed_weights, regression, simulate_monthly


def test_french_units_and_first_section_only(tmp_path):
    path = tmp_path / "factors.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("factors.csv", "Header\n,Mkt-RF,SMB,HML,RF\n202001,1.2,0.3,-0.2,0.1\n202002,-2.4,0.4,0.5,0.1\n\nAnnual Factors\n2020,5,5,5,5\n")
    data = read_french_zip(path, "monthly")
    assert list(data.index.astype(str)) == ["2020-01", "2020-02"]
    np.testing.assert_allclose(data["Mkt-RF"], [.012, -.024])


def test_french_missing_value_is_rejected(tmp_path):
    path = tmp_path / "factors.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("factors.csv", "202001,-99.99,0,0,0\n")
    with pytest.raises(ValueError, match="Missing"):
        read_french_zip(path, "monthly")


def _daily_months():
    dates = pd.bdate_range("2020-01-01", "2020-01-31").append(pd.bdate_range("2020-02-01", "2020-02-29"))
    daily = pd.DataFrame({"Mkt-RF": np.arange(len(dates), dtype=float) / 1000}, index=dates)
    monthly = pd.DataFrame({"Mkt-RF": [.02, -.03], "RF": [.001, .001]},
                           index=pd.period_range("2020-01", "2020-02", freq="M", name="date"))
    return daily, monthly


def test_signal_uses_previous_calendar_month_centered_squared_sum():
    daily, monthly = _daily_months()
    panel = monthly_panel(daily, monthly)
    january = daily.loc["2020-01", "Mkt-RF"].to_numpy()
    expected = np.sum((january - np.mean(january)) ** 2)
    assert np.isnan(panel.iloc[0].lag_rv)
    assert panel.iloc[1].lag_rv == pytest.approx(expected)
    # A return shock during February cannot alter February's position signal.
    shocked = daily.copy()
    shocked.loc["2020-02", "Mkt-RF"] *= 10
    changed = monthly_panel(shocked, monthly)
    assert changed.iloc[1].lag_rv == panel.iloc[1].lag_rv
    assert changed.iloc[1].rv != panel.iloc[1].rv


def test_sample_variance_sensitivity_is_explicit():
    daily, monthly = _daily_months()
    pop, sample = monthly_panel(daily, monthly, 0), monthly_panel(daily, monthly, 1)
    n = int(pop.iloc[0].daily_count)
    assert sample.iloc[0].rv == pytest.approx(pop.iloc[0].rv * n / (n - 1))


def test_scale_equalizes_sample_volatility_and_cap_is_not_rescaled():
    index = pd.period_range("2000-01", periods=36, freq="M")
    panel = pd.DataFrame({"market_excess": .03 * np.sin(np.arange(36)) + .005,
                          "lag_rv": np.linspace(.00003, .0008, 36)}, index=index)
    scale = fit_scale(panel)
    raw = managed_weights(panel, scale)
    assert (raw * panel.market_excess).std() == pytest.approx(panel.market_excess.std())
    capped = managed_weights(panel, scale, cap=2)
    np.testing.assert_allclose(capped, np.minimum(raw, 2))
    assert (capped[raw < 2] == raw[raw < 2]).all()


def test_regression_annualizes_intercept_and_hc1_covariance():
    x = np.array([-.04, .01, .02, -.03, .05, .001, .04, -.01])
    y = .002 + .6 * x + np.array([.002, -.001, .004, -.003, .001, .001, -.004, 0])
    idx = pd.period_range("2020-01", periods=len(x), freq="M")
    actual = regression(pd.Series(y, idx), pd.Series(x, idx))
    design = np.column_stack([np.ones(len(x)), x])
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    resid = y - design @ coef
    inv = np.linalg.inv(design.T @ design)
    cov = inv @ (design.T @ ((resid ** 2)[:, None] * design)) @ inv * len(x) / (len(x) - 2)
    assert actual["alpha_annual_pct"] == pytest.approx(coef[0] * 1200)
    assert actual["alpha_se_annual_pct"] == pytest.approx(np.sqrt(cov[0, 0]) * 1200)
    assert actual["beta"] == pytest.approx(coef[1])
    assert actual["beta_se"] == pytest.approx(np.sqrt(cov[1, 1]))


def test_regression_rejects_misaligned_dates():
    x = pd.Series([.01, -.01, .02], pd.period_range("2020-01", periods=3, freq="M"))
    with pytest.raises(ValueError, match="dates"):
        regression(x, x.shift(1).dropna())


def _book_account(panel, weights, cost_bps, spread_bps):
    """Independently hold risky dollars and cash, solving trade size by bisection."""
    wealth, risky = 1.0, 0.0
    rows = []
    rate = cost_bps / 10000
    spread = spread_bps / 10000 / 12
    for (_, period), weight in zip(panel.iterrows(), weights):
        previous = wealth
        drift = risky / previous
        # fee(q) is proportional to absolute dollar trading, and q equals the
        # chosen fraction of the wealth remaining after that fee is paid.
        lo, hi = 0., max(weight * wealth, risky, 1.) * 2
        for _ in range(100):
            q = (lo + hi) / 2
            equation = q - weight * (wealth - rate * abs(q - risky))
            if equation > 0:
                hi = q
            else:
                lo = q
        position = (lo + hi) / 2
        fee = rate * abs(position - risky)
        cash = wealth - fee - position
        risky = position * (1 + period.rf + period.market_excess)
        cash = cash * (1 + period.rf) - max(-cash, 0) * spread
        wealth = risky + cash
        rows.append((wealth / previous - 1, wealth, fee / previous,
                     abs(position - previous * drift) / previous, drift))
    return np.asarray(rows)


@pytest.mark.parametrize("cost_bps,spread_bps", [(0, 0), (10, 0), (30, 200)])
def test_funded_account_matches_explicit_cash_and_risky_dollar_book(cost_bps, spread_bps):
    idx = pd.period_range("2020-01", periods=5, freq="M")
    panel = pd.DataFrame({"market_excess": [.10, -.08, .04, -.03, .015],
                          "rf": [.002, .003, .001, .002, .001]}, index=idx)
    weights = pd.Series([1.4, .2, 1.8, 1.8, 0.], index=idx)
    out = simulate_monthly(panel, weights, cost_bps, spread_bps)
    book = _book_account(panel, weights, cost_bps, spread_bps)
    np.testing.assert_allclose(out[["total_return", "nav", "fee_fraction", "one_way_turnover", "pretrade_weight"]], book,
                               rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(out.net_excess + out.rf, out.total_return, atol=1e-14)


def test_market_account_at_zero_cost_equals_buy_and_hold_total_return():
    idx = pd.period_range("2020-01", periods=3, freq="M")
    panel = pd.DataFrame({"market_excess": [.03, -.05, .01], "rf": [.001, .001, .001]}, index=idx)
    out = simulate_monthly(panel, pd.Series(1., idx))
    np.testing.assert_allclose(out.total_return, panel.market_excess + panel.rf)
    np.testing.assert_allclose(out.nav, np.cumprod(1 + panel.market_excess + panel.rf))
    # All-risky wealth remains all-risky after every return, with no rebalancing.
    assert np.max(np.abs(out.one_way_turnover.iloc[1:])) < 1e-14


def test_leverage_account_rejects_insolvency():
    idx = pd.period_range("2020-01", periods=1, freq="M")
    panel = pd.DataFrame({"market_excess": [-.6], "rf": [0.]}, index=idx)
    with pytest.raises(ValueError, match="insolvency"):
        simulate_monthly(panel, pd.Series(2., idx))


def test_cost_position_combination_must_be_feasible():
    idx = pd.period_range("2020-01", periods=1, freq="M")
    panel = pd.DataFrame({"market_excess": [.01], "rf": [0.]}, index=idx)
    with pytest.raises(ValueError, match="infeasible"):
        simulate_monthly(panel, pd.Series(10., idx), cost_bps=1000)
