"""Strict 61-quote, 60-return risk inputs from fixed r5 targets."""
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

NUMERIC = ('open', 'high', 'low', 'close', 'vol', 'amount')
EMPTY_LABELS = pd.DataFrame(columns=['ts_code', 'signal_date', 'execution_date', 'R_end', 'R_valid'])


def positive_text(value):
    if not isinstance(value, str):
        return None
    try:
        number = Decimal(value)
        return number if number.is_finite() and number > 0 else None
    except InvalidOperation:
        return None


def target_keys(targets):
    parts = []
    for frame in targets.values():
        if frame.duplicated(['signal_date', 'ts_code']).any():
            raise ValueError('Duplicate target key')
        weight = frame.target_weight.to_numpy(dtype=np.float64)
        if not np.isfinite(weight).all() or (weight < 0).any():
            raise ValueError('Invalid base weights')
        if not (frame.trade_date == frame.signal_date).all():
            raise ValueError('Base target signal mismatch')
        parts.append(frame.loc[frame.target_weight > 0, ['ts_code', 'signal_date']])
    return (pd.concat(parts).drop_duplicates().rename(columns={'signal_date': 'trade_date'})
            .sort_values(['trade_date', 'ts_code']).reset_index(drop=True))


def risk_inputs(bars, calendar, keys):
    """Retain all requested keys, raw rows and every invalid numeric input."""
    cal = pd.DatetimeIndex(calendar)
    if cal.has_duplicates or not cal.is_monotonic_increasing:
        raise ValueError('Invalid calendar')
    if bars.duplicated(['ts_code', 'trade_date']).any():
        raise ValueError('Duplicate quote')
    lookup = {code: group.set_index('trade_date') for code, group in bars.groupby('ts_code')}
    windows, returns, failures = {}, {}, []
    for code, signal in keys[['ts_code', 'trade_date']].itertuples(index=False, name=None):
        end = cal.get_indexer([signal])[0]
        if end < 60:
            failures.append(dict(ts_code=code, signal_date=signal, date=signal,
                                 field='calendar', reason='insufficient_calendar'))
            windows[code, signal] = pd.DataFrame()
            returns[code, signal] = None
            continue
        days = cal[end-60:end+1]
        data = lookup.get(code, pd.DataFrame(columns=[*NUMERIC, 'close_text', 'pre_close_text'])).reindex(days).copy()
        data.index.name = 'date'
        data['ts_code'] = code
        data['signal_date'] = signal
        valid = True
        for index, day in enumerate(days):
            row = data.loc[day]
            for field in NUMERIC:
                try:
                    ok = math.isfinite(float(row[field])) and float(row[field]) > 0
                except (TypeError, ValueError):
                    ok = False
                if not ok:
                    valid = False
                    failures.append(dict(ts_code=code, signal_date=signal, date=day,
                                         field=field, reason='missing_or_nonpositive_quote'))
            for field in ('close_text', 'pre_close_text') if index else ('close_text',):
                value = positive_text(row[field])
                if value is None:
                    valid = False
                    failures.append(dict(ts_code=code, signal_date=signal, date=day,
                                         field=field, reason='invalid_decimal_reference'))
                elif field == 'close_text' and float(value) != float(row['close']):
                    valid = False
                    failures.append(dict(ts_code=code, signal_date=signal, date=day,
                                         field=field, reason='numeric_and_text_close_differ'))
        series = None
        if valid:
            values = np.array([float(positive_text(a) / positive_text(b) - Decimal(1))
                               for a, b in zip(data.close_text.iloc[1:], data.pre_close_text.iloc[1:])], dtype=np.float64)
            if not np.isfinite(values).all():
                failures.append(dict(ts_code=code, signal_date=signal, date=signal,
                                     field='returns', reason='nonfinite_returns'))
            else:
                series = pd.Series(values, index=days[1:], name=code)
        windows[code, signal] = data.reset_index()
        returns[code, signal] = series
    columns = ['ts_code', 'signal_date', 'date', 'field', 'reason']
    return windows, returns, pd.DataFrame(failures, columns=columns)


def estimate(matrix, weights):
    values = np.asarray(matrix, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    if values.shape != (60, len(w)) or not len(w) or not np.isfinite(values).all():
        raise ValueError('Risk requires 60 complete common returns')
    if not np.isfinite(w).all() or (w <= 0).any():
        raise ValueError('Risk requires positive finite original weights')
    covariance = LedoitWolf(store_precision=False, assume_centered=False).fit(values).covariance_
    variance = float(252 * w.T @ covariance @ w)
    if not math.isfinite(variance) or variance <= 0:
        raise ValueError('Invalid or zero predicted portfolio variance')
    sigma = float(np.sqrt(variance))
    return min(1., .15 / sigma), sigma, covariance


def prepare_targets(targets, schedule, windows, returns, bridge_failures, out):
    """Every period has an explicit outcome; partial targets grant no permission."""
    out = Path(out)
    matrices = out/'risk_matrices'
    matrices.mkdir()
    bad_bridges = {(str(row.ts_code), pd.Timestamp(row.formation_date))
                   for row in bridge_failures.itertuples(index=False)}
    records, outputs = [], {}
    for path, base in targets.items():
        scaled = []
        for signal in schedule.signal_date:
            group = base.loc[base.signal_date.eq(signal) & base.target_weight.gt(0)].sort_values('ts_code')
            stamp = signal.strftime('%Y%m%d')
            prefix = matrices/f'{path}_{stamp}'
            codes = group.ts_code.tolist()
            row = dict(path=path, signal_date=signal, target_count=len(codes), status='failed', reason='',
                       sigma=None, scale=None, window_start=pd.NaT, window_end=pd.NaT,
                       original_exposure=None, new_exposure=None)
            if not codes:
                row.update(status='no_positive_targets', reason='no_positive_targets', scale=0.)
                records.append(row)
                continue
            w = group.target_weight.to_numpy(dtype=np.float64)
            weights = pd.DataFrame(dict(ts_code=codes, original_weight=w))
            weights.to_csv(str(prefix)+'_weights.csv', index=False)
            raw = pd.concat([windows[code, signal] for code in codes], ignore_index=True)
            raw.to_csv(str(prefix)+'_quotes.csv', index=False)
            invalid = [code for code in codes if returns[code, signal] is None]
            bad = [code for code in codes if (code, signal) in bad_bridges]
            if invalid or bad:
                row['reason'] = 'invalid_quote_window' if invalid else 'source_bridge_failed'
                records.append(row)
                continue
            matrix = pd.concat([returns[code, signal] for code in codes], axis=1)
            if matrix.shape != (60, len(codes)) or list(matrix.columns) != codes:
                raise ValueError('Matrix alignment changed')
            matrix.index.name = 'date'
            matrix.to_csv(str(prefix)+'_returns.csv')
            try:
                scale, sigma, covariance = estimate(matrix, w)
            except ValueError as error:
                row['reason'] = str(error)
                records.append(row)
                continue
            pd.DataFrame(covariance, index=codes, columns=codes).to_csv(str(prefix)+'_covariance.csv', index_label='ts_code')
            weights['new_weight'] = w * scale
            weights.to_csv(str(prefix)+'_scaled_weights.csv', index=False)
            new = group.copy()
            new['target_weight'] = w * scale
            scaled.append(new)
            row.update(status='passed', sigma=sigma, scale=scale,
                       window_start=matrix.index[0], window_end=matrix.index[-1],
                       original_exposure=float(w.sum()), new_exposure=float((w * scale).sum()))
            records.append(row)
        outputs[path] = pd.concat(scaled, ignore_index=True) if scaled else base.iloc[:0].copy()
        outputs[path].to_csv(out/f'targets_{path}.csv', index=False)
    result = pd.DataFrame(records)
    result.to_csv(out/'risk_periods.csv', index=False)
    return result, outputs
