"""Approved eight past-only features; old feature modules remain unchanged."""
import numpy as np
import pandas as pd

WINDOWS = (20, 50, 100, 200)
FEATURES = [f'{kind}_{n}' for n in WINDOWS for kind in ('price', 'amount')]
QUOTE_FIELDS = ['open', 'high', 'low', 'close', 'adj_factor', 'vol', 'amount']


def compute_asset(group, calendar, signal_dates, issue_dates=()):
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Calendar must be sorted and unique')
    if group.trade_date.duplicated().any():
        raise ValueError('Duplicate asset/date')
    if not set(pd.DatetimeIndex(signal_dates)).issubset(set(calendar)):
        raise ValueError('Signal outside calendar')
    g = group.set_index('trade_date').reindex(calendar)
    finite = np.isfinite(g[QUOTE_FIELDS].to_numpy(dtype=float)).all(axis=1)
    valid = pd.Series(finite, index=calendar) & g[QUOTE_FIELDS].gt(0).all(axis=1)
    present = pd.Series(calendar.isin(group.trade_date), index=calendar)
    close = (g.close * g.adj_factor).where(valid)
    amount = (g.amount * 1000).where(valid)
    complete = valid.astype(int).rolling(200, min_periods=200).sum().eq(200)
    quarantine = pd.Series(False, index=calendar)
    for day in issue_dates:
        position = calendar.get_indexer([pd.Timestamp(day)])[0]
        if position >= 0:
            quarantine.iloc[position:position + 200] = True
    result = pd.DataFrame(index=calendar)
    for n in WINDOWS:
        result[f'price_{n}'] = close.rolling(n, min_periods=n).mean() / close - 1
        result[f'amount_{n}'] = amount.rolling(n, min_periods=n).mean() / amount - 1
    available = complete & ~quarantine & np.isfinite(result[FEATURES]).all(axis=1)
    result.loc[~available, FEATURES] = np.nan
    result['feature_valid'] = available
    result['long_quarantined'] = quarantine
    result['valid_quote_count_200'] = valid.astype(int).rolling(200, min_periods=1).sum()
    missing = (~present).astype(int).rolling(200, min_periods=1).sum().gt(0)
    invalid = (present & ~valid).astype(int).rolling(200, min_periods=1).sum().gt(0)
    result['feature_reason'] = np.select(
        [np.arange(len(calendar)) < 199, quarantine, missing, invalid, available],
        ['warmup_200', 'unknown_adjustment', 'missing_quote', 'invalid_quote', 'valid'],
        default='nonfinite_feature')
    result['current_amount_cny'] = amount
    result['trade_date'] = calendar
    returns = close.pct_change(fill_method=None)
    return result.loc[result.index.isin(signal_dates)].reset_index(drop=True), returns
