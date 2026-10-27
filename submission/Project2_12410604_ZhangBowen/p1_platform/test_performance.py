"""Small independent checks of frequency, wealth and information contracts."""

import math

import pandas as pd
import pytest

from .performance import summarize_monthly


def test_initial_loss_counts_and_total_wealth_is_separate_from_excess_sharpe():
    index = pd.period_range("2020-01", periods=3, freq="M")
    total = pd.Series([-0.10, 0.20, -0.05], index=index)
    excess = pd.Series([-0.11, 0.19, -0.06], index=index)
    result = summarize_monthly(total, excess)
    # Independent arithmetic: NAV = 1, 0.9, 1.08, 1.026.
    assert result["total_return"] == pytest.approx(0.026)
    assert result["cagr_total"] == pytest.approx(1.026**4 - 1)
    assert result["max_drawdown_total"] == pytest.approx(0.10)
    mean = (-0.11 + 0.19 - 0.06) / 3
    sample_variance = sum((x - mean) ** 2 for x in [-0.11, 0.19, -0.06]) / 2
    assert result["annualized_mean_excess"] == pytest.approx(mean * 12)
    assert result["annualized_volatility_excess"] == pytest.approx(math.sqrt(sample_variance * 12))
    assert result["sharpe"] == pytest.approx(mean * 12 / math.sqrt(sample_variance * 12))


@pytest.mark.parametrize("case", ["unsorted", "duplicate_month", "missing_month", "nan", "bankruptcy", "misaligned"])
def test_invalid_inputs_fail_closed(case):
    index = pd.to_datetime(["2020-01-31", "2020-02-29", "2020-03-31"])
    total = pd.Series([0.01, -0.02, 0.03], index=index)
    excess = total.copy()
    if case == "unsorted":
        total = total.iloc[::-1]
    elif case == "duplicate_month":
        total.index = pd.to_datetime(["2020-01-30", "2020-01-31", "2020-03-31"])
    elif case == "missing_month":
        total = total.iloc[[0, 2]]
        excess = excess.iloc[[0, 2]]
    elif case == "nan":
        excess.iloc[1] = float("nan")
    elif case == "bankruptcy":
        total.iloc[0] = -1.0
    elif case == "misaligned":
        excess.index = excess.index.to_period("M")
    with pytest.raises(ValueError):
        summarize_monthly(total, excess)


def test_constant_excess_returns_have_undefined_sharpe_and_optional_inputs_reconcile():
    index = pd.period_range("2020-01", periods=2, freq="M")
    result = summarize_monthly(
        pd.Series([0.01, 0.01], index=index),
        pd.Series([0.0, 0.0], index=index),
        pd.Series([1.0, 2.0], index=index),
        pd.Series([1.0, 1.0], index=index),
    )
    assert result["sharpe"] is None
    assert result["annualized_volatility_excess"] == 0.0
    assert result["average_weight"] == 1.5
    assert result["annualized_turnover"] == 12.0
