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
