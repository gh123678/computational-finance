"""Expose adjustment changes not covered by the verified event registry."""
import pandas as pd

MATERIAL_ADJUSTMENT_THRESHOLD = 0.005


def audit_adjustments(bars, actions, rights, threshold=MATERIAL_ADJUSTMENT_THRESHOLD):
    """Expose economically material factor moves without a registered event.

    Tushare's historical adjustment factors occasionally change at the fourth
    decimal for most of the market and later reverse.  A 50 bp return-gap
    threshold keeps those precision revisions out of the corporate-action
    ledger while still failing closed on material unregistered events.
    """
    if not 0 < threshold < 1:
        raise ValueError('Threshold must be within (0, 1)')
    dates = {}
    for event in [*actions, *rights]:
        dates.setdefault(event.code, []).append(event.ex)
    frame = bars[['ts_code', 'trade_date', 'adj_factor']].sort_values(['ts_code', 'trade_date']).copy()
    grouped = frame.groupby('ts_code')
    frame['prior_date'] = grouped.trade_date.shift(1)
    frame['relative_change'] = grouped.adj_factor.pct_change()
    frame = frame.loc[frame.relative_change.abs().gt(threshold)]
    unexplained = [not any(row.prior_date < d <= row.trade_date for d in dates.get(row.ts_code, []))
                   for row in frame.itertuples(index=False)]
    return frame.loc[unexplained].copy()


def return_consistency_check(bars, actions, rights, threshold=MATERIAL_ADJUSTMENT_THRESHOLD):
    """Flag days where adjusted and raw returns diverge without a registered event.

    Adjustment factors must only move because of corporate actions. When a factor
    changes while raw prices stay continuous (vendor factor-history revisions,
    e.g. the 2020-01-02 year-boundary jumps seen in both Tushare and iFinD),
    adjusted returns silently drift from raw returns. Divergences matched by a
    registered event are real corporate actions and not flagged.
    """
    if not 0 < threshold < 1:
        raise ValueError('Threshold must be within (0, 1)')
    dates = {}
    for event in [*actions, *rights]:
        dates.setdefault(event.code, []).append(event.ex)
    frame = bars[['ts_code', 'trade_date', 'close', 'adj_factor']].sort_values(['ts_code', 'trade_date']).copy()
    grouped = frame.groupby('ts_code')
    frame['prior_date'] = grouped.trade_date.shift(1)
    frame['raw_return'] = grouped.close.pct_change()
    frame['adjusted_return'] = (frame.close * frame.adj_factor).groupby(frame.ts_code).pct_change()
    frame['return_gap'] = frame.adjusted_return - frame.raw_return
    frame = frame.loc[frame.return_gap.abs().gt(threshold)]
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
