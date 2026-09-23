"""Descriptive cost and monthly-return summaries; never optimize the strategy."""
import numpy as np
import pandas as pd


def cost_breakdown(orders):
    filled = orders.loc[orders.shares.gt(0)].copy()
    result = filled.groupby('role').agg(orders=('shares', 'size'), notional=('notional', 'sum'),
                                         fees=('fee', 'sum'), slippage=('slippage_cost', 'sum'))
    result['total_cost'] = result.fees + result.slippage
    total = result.total_cost.sum()
    result['cost_share'] = result.total_cost / total if total > 0 else 0.
    return result


def monthly_returns(equity):
    if equity.index.has_duplicates or not equity.index.is_monotonic_increasing or not np.isfinite(equity).all() or (equity <= 0).any():
        raise ValueError('Provide unique chronological positive equity observations')
    daily = equity.pct_change().iloc[1:]
    return daily.groupby(daily.index.to_period('M')).apply(lambda values: (1 + values).prod() - 1).rename('return')
