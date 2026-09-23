"""Expose adjustment changes not covered by the verified event registry."""
import pandas as pd


def audit_adjustments(bars, actions, rights):
    dates = {}
    for event in [*actions, *rights]:
        dates.setdefault(event.code, []).append(event.ex)
    frame = bars[['ts_code', 'trade_date', 'adj_factor']].sort_values(['ts_code', 'trade_date']).copy()
    grouped = frame.groupby('ts_code')
    frame['prior_date'] = grouped.trade_date.shift(1)
    frame['relative_change'] = grouped.adj_factor.pct_change()
    frame = frame.loc[frame.relative_change.abs().gt(1e-5)]
    unexplained = [not any(row.prior_date < d <= row.trade_date for d in dates.get(row.ts_code, []))
                   for row in frame.itertuples(index=False)]
    return frame.loc[unexplained].copy()


def quarantine_factors(factors, issues, calendar, window=20):
    """Blank price factors while an unexplained adjustment remains in lookback."""
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ValueError('Quarantine window must be a positive integer')
    result = factors.copy()
    quarantined = set()
    positions = {date: i for i, date in enumerate(calendar)}
    for row in issues.itertuples(index=False):
        start = positions.get(pd.Timestamp(row.trade_date))
        if start is None:
            continue
        for date in calendar[start:start + window]:
            quarantined.add((date, row.ts_code))
    mask = pd.MultiIndex.from_frame(result[['trade_date', 'ts_code']]).isin(quarantined)
    columns = ['momentum20', 'reversal5', 'lowvol20']
    result.loc[mask, columns] = float('nan')
    return result, int(mask.sum())
