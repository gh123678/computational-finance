"""Independent AlphaForge case-5 mathematics with a frozen local data mapping.

This is a single expression, not AlphaForge's mining or dynamic combination.
Local inputs are corrected *raw* close in CNY and Tushare vol * 100 shares.
Windows containing an adjustment-factor change are excluded, without filling
missing exchange sessions. The local trading hypothesis uses -factor; that is
not a claim about a permanent direction in the paper's combined strategy.
"""
import numpy as np
import pandas as pd


WINDOW = 10
EPSILON = 1e-6
VOLUME_TO_SHARES = 100.0
FORMULA_FIELDS = ('rho', 'factor', 'signal', 'nlvar', 'nrvar')


def _evaluate(close, volume_shares):
    """Evaluate along the final axis, retaining the source epsilon branch."""
    left = close - close.mean(axis=-1, keepdims=True)
    right = volume_shares - volume_shares.mean(axis=-1, keepdims=True)
    covariance_sum = (left * right).sum(axis=-1)
    nlvar = (left * left).sum(axis=-1)
    nrvar = (right * right).sum(axis=-1)
    guard = (nlvar < EPSILON) | (nrvar < EPSILON)
    denominator = np.sqrt(nlvar * nrvar)
    denominator = np.where(guard, 1, denominator)
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        rho = covariance_sum / denominator
        factor = np.sign(rho) * np.log1p(np.abs(rho))
    # A guarded rho need not lie in [-1, 1]; clipping changes the source rule.
    return dict(rho=rho, factor=factor, signal=-factor, nlvar=nlvar,
                nrvar=nrvar, guard=guard)


def formula_10(close, volume_shares, *, dtype=np.float64):
    """Return scalar values for exactly ten finite observations of each input.

    Inputs here are already in the desired units. No unit conversion or price
    adjustment occurs in this mathematical reference entry point. float32 can
    be requested for comparison with the author's torch.float data loading;
    the local research path deliberately computes with float64.
    """
    if np.dtype(dtype) not in (np.dtype('float32'), np.dtype('float64')):
        raise ValueError('Only float32 or float64 arithmetic is supported')
    left, right = np.asarray(close, dtype=dtype), np.asarray(volume_shares, dtype=dtype)
    if left.shape != (WINDOW,) or right.shape != (WINDOW,):
        raise ValueError('Exactly 10 observations per input are required')
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError('Formula inputs must be finite')
    values = _evaluate(left, right)
    return {name: bool(value) if name == 'guard' else float(value)
            for name, value in values.items()}


def compute_asset(group, calendar, signal_dates):
    """Compute past-only formation rows for one security on an exchange calendar.

    At formation position t the window is [t-9, t], including that day's close.
    Missing or nonpositive close/vol/adj_factor invalidates the entire window.
    Every adjustment-factor value in the window must be identical. Formation
    validity never uses future prices, labels, availability, or returns.
    """
    calendar = pd.DatetimeIndex(calendar)
    signals = pd.DatetimeIndex(signal_dates)
    if calendar.hasnans or calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Calendar must be sorted, finite and unique')
    if signals.hasnans or signals.has_duplicates or not signals.is_monotonic_increasing:
        raise ValueError('Signal dates must be sorted, finite and unique')
    positions = calendar.get_indexer(signals)
    if (positions < 0).any():
        raise ValueError('Signal outside calendar')
    required = {'trade_date', 'close', 'vol', 'adj_factor'}
    if not required.issubset(group):
        raise ValueError(f'Missing columns: {required - set(group)}')
    frame = group.copy()
    dates = frame.trade_date
    frame['trade_date'] = (pd.to_datetime(dates.astype(str), format='%Y%m%d')
                           if pd.api.types.is_integer_dtype(dates)
                           else pd.to_datetime(dates))
    if frame.trade_date.isna().any() or frame.trade_date.duplicated().any():
        raise ValueError('Missing or duplicate asset/date')
    if not frame.trade_date.isin(calendar).all():
        raise ValueError('Quote outside calendar')
    if 'ts_code' in frame and (frame.ts_code.isna().any() or frame.ts_code.nunique() > 1):
        raise ValueError('Exactly one asset per call is required')
    fields = ['close', 'vol', 'adj_factor']
    frame[fields] = frame[fields].apply(pd.to_numeric, errors='raise')
    g = frame.set_index('trade_date').reindex(calendar)
    data = g[fields].to_numpy(dtype=np.float64)
    present = calendar.isin(frame.trade_date)
    valid = np.isfinite(data).all(axis=1) & (data > 0).all(axis=1)

    result = pd.DataFrame({'trade_date': signals,
                           'window_start': pd.NaT, 'window_end': signals,
                           'case_valid': False, 'reason': 'warmup_10',
                           'valid_quote_count_10': 0,
                           'volume_scale': VOLUME_TO_SHARES})
    for name in FORMULA_FIELDS:
        result[name] = np.nan
    result['guard'] = pd.Series(pd.NA, index=result.index, dtype='boolean')
    ready = positions >= WINDOW - 1
    rows = np.flatnonzero(ready)
    if not len(rows):
        return result
    indexes = positions[ready, None] + np.arange(-WINDOW + 1, 1)
    windows = data[indexes]
    count = valid[indexes].sum(axis=1)
    missing = (~present[indexes]).any(axis=1)
    invalid = (present[indexes] & ~valid[indexes]).any(axis=1)
    adjustment_change = (windows[:, :, 2] != windows[:, :1, 2]).any(axis=1)
    eligible = ~missing & ~invalid & ~adjustment_change
    result.loc[rows, 'window_start'] = calendar[indexes[:, 0]].to_numpy()
    result.loc[rows, 'valid_quote_count_10'] = count
    result.loc[rows, 'reason'] = np.select(
        [missing, invalid, adjustment_change],
        ['missing_quote', 'invalid_quote', 'adjustment_factor_change'], default='valid')
    chosen = rows[eligible]
    if len(chosen):
        values = _evaluate(windows[eligible, :, 0],
                           windows[eligible, :, 1] * VOLUME_TO_SHARES)
        finite = np.isfinite(np.column_stack([values[n] for n in FORMULA_FIELDS])).all(axis=1)
        for name in FORMULA_FIELDS:
            result.loc[chosen, name] = values[name]
        result.loc[chosen, 'guard'] = values['guard']
        result.loc[chosen, 'case_valid'] = finite
        result.loc[chosen[~finite], 'reason'] = 'nonfinite_factor'
        result.loc[chosen[~finite], list(FORMULA_FIELDS)] = np.nan
    return result
