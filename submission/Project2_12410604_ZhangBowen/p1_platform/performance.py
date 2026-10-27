"""Monthly performance adapter based on Project 1 ``backtest.summarize``.

The source function assumes 252 trading days. This adapter uses 12 months,
preserves the initial NAV for drawdown, and distinguishes total-return wealth
from the arithmetic mean and Sharpe ratio of excess returns. Neither the
Project 1 stock-execution ledger nor its 252-day annualization is applied to
the zero-investment, potentially levered factor portfolios.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .attribution import monthly_returns

PERIODS_PER_YEAR = 12


def _monthly_series(values: pd.Series, name: str) -> tuple[pd.Series, pd.PeriodIndex]:
    if not isinstance(values, pd.Series) or values.empty:
        raise ValueError(f"{name} must be a nonempty pandas Series")
    if not isinstance(values.index, (pd.DatetimeIndex, pd.PeriodIndex)):
        raise ValueError(f"{name} requires a DatetimeIndex or monthly PeriodIndex")
    if values.index.hasnans or values.index.has_duplicates or not values.index.is_monotonic_increasing:
        raise ValueError(f"{name} index must be unique and chronological without missing dates")
    if isinstance(values.index, pd.PeriodIndex):
        if values.index.freqstr != "M":
            raise ValueError(f"{name} PeriodIndex must have monthly frequency")
        months = values.index
    else:
        if values.index.tz is not None:
            raise ValueError(f"{name} dates must be timezone-naive monthly observations")
        months = values.index.to_period("M")
    if months.has_duplicates or not months.equals(pd.period_range(months[0], months[-1], freq="M")):
        raise ValueError(f"{name} must contain exactly one observation in each consecutive month")
    try:
        numeric = values.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain numeric observations") from exc
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError(f"{name} contains missing or nonfinite observations")
    return numeric, months


def summarize_monthly(
    total_returns: pd.Series,
    excess_returns: pd.Series,
    weights: pd.Series | None = None,
    turnover: pd.Series | None = None,
) -> dict:
    """Summarize aligned monthly returns in decimal units.

    ``total_returns`` includes the risk-free cash return and governs wealth,
    CAGR and drawdown. ``excess_returns`` excludes that return and governs
    arithmetic mean, sample standard deviation (ddof=1) and Sharpe. Optional
    weights and turnover are monthly exposure and one-way exposure changes.
    All supplied Series must have the exact same monthly index. A one-month
    sample has undefined volatility and Sharpe (returned as ``None``).
    """
    total, months = _monthly_series(total_returns, "total_returns")
    excess, _ = _monthly_series(excess_returns, "excess_returns")
    if not total.index.equals(excess.index):
        raise ValueError("total_returns and excess_returns must have exactly aligned indices")
    if (total <= -1).any() or (excess <= -1).any():
        raise ValueError("Returns must be strictly greater than -1")

    aligned = {}
    for name, values in (("weights", weights), ("turnover", turnover)):
        if values is not None:
            checked, _ = _monthly_series(values, name)
            if not total.index.equals(checked.index):
                raise ValueError(f"{name} must have the exact return index")
            if name == "turnover" and (checked < 0).any():
                raise ValueError("turnover must be nonnegative")
            aligned[name] = checked

    # P1 measured NAV relative to an observation before the evaluation starts.
    # Preserve that baseline even if the first monthly return is negative.
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        wealth = np.r_[1.0, np.cumprod(1.0 + total.to_numpy())]
    if not np.isfinite(wealth).all() or (wealth <= 0).any():
        raise ValueError("Total-return NAV must remain finite and strictly positive")
    nav_months = pd.PeriodIndex([months[0] - 1, *months], freq="M")
    nav = pd.Series(wealth, index=nav_months.to_timestamp("M"), name="equity")

    # This unchanged P1 function is part of the actual result path, not only
    # shipped as reference code. Reconcile every monthly return before metrics.
    recovered = monthly_returns(nav)
    if not recovered.index.equals(months):
        raise AssertionError("P1 monthly return reconstruction changed evaluation months")
    np.testing.assert_allclose(recovered.to_numpy(), total.to_numpy(), rtol=1e-10, atol=1e-12)

    drawdown = 1.0 - nav / nav.cummax()
    n = len(total)
    annualized_mean = float(excess.mean() * PERIODS_PER_YEAR)
    volatility = float(excess.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR)) if n >= 2 else None
    sharpe = annualized_mean / volatility if volatility is not None and volatility > 0 else None
    result = {
        "months": n,
        "start": str(months[0]),
        "end": str(months[-1]),
        "periods_per_year": PERIODS_PER_YEAR,
        "total_return": float(nav.iloc[-1] - 1.0),
        "cagr_total": float(nav.iloc[-1] ** (PERIODS_PER_YEAR / n) - 1.0),
        "max_drawdown_total": float(drawdown.max()),
        "final_nav": float(nav.iloc[-1]),
        "annualized_mean_excess": annualized_mean,
        "annualized_volatility_excess": volatility,
        "sharpe": sharpe,
        "monthly_return_reconciliation_max_abs_error": float(np.max(np.abs(recovered.to_numpy() - total.to_numpy()))),
    }
    if "weights" in aligned:
        exposure = aligned["weights"]
        result.update(
            average_weight=float(exposure.mean()),
            minimum_weight=float(exposure.min()),
            maximum_weight=float(exposure.max()),
            average_gross_exposure=float(exposure.abs().mean()),
        )
    if "turnover" in aligned:
        changes = aligned["turnover"]
        result.update(
            total_turnover=float(changes.sum()),
            average_monthly_turnover=float(changes.mean()),
            annualized_turnover=float(changes.mean() * PERIODS_PER_YEAR),
        )
    return result
