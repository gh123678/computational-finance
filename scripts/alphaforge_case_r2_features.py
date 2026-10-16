"""Past-only reference/action eligibility for the separately approved r2 study.

The r1 mathematics and units are reused unchanged. No future factor recovery,
return label, tolerance or synthetic adjusted trading volume is consumed.
"""
from decimal import Decimal, InvalidOperation
import json

import numpy as np
import pandas as pd

try:
    from .alphaforge_case_factor import WINDOW, VOLUME_TO_SHARES, FORMULA_FIELDS, _evaluate
except ImportError:
    from alphaforge_case_factor import WINDOW, VOLUME_TO_SHARES, FORMULA_FIELDS, _evaluate


COUNT_FIELDS = ('reference_change_count', 'unknown_reference_count',
                'known_action_count', 'event_timing_unverified_count',
                'adj_factor_change_count')
TRANSITION_COLUMNS = [
    'signal_date', 'ts_code', 'window_start', 'window_end',
    'previous_date', 'current_date', 'previous_close_text', 'current_pre_close_text',
    'reference_status', 'adj_factor_changed', 'matched_event_ids',
    'known_action_ids', 'unverified_event_ids', 'event_known_dates', 'event_effective_dates',
    'known_action_count', 'event_timing_unverified_count',
    'isolated_factor_change_no_observed_reference_break']


def _date(value):
    if value is None or pd.isna(value):
        return pd.NaT
    try:
        result = pd.Timestamp(str(value))
    except (ValueError, TypeError):
        return pd.NaT
    if result.tzinfo is not None:
        raise ValueError('Event dates must be date-level values without a timezone')
    return result.normalize()


def _verified(value):
    """Unknown is false; strings must never acquire Python truthiness."""
    if value is None or pd.isna(value):
        return False
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ('true', '1', '1.0'):
        return True
    if text in ('false', '0', '0.0', ''):
        return False
    raise ValueError('Unrecognized timing_verified flag')


def _decimal(value):
    if value is None or pd.isna(value):
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


def _text(value):
    return None if value is None or pd.isna(value) else str(value)


def _events_by_date(events, code):
    if events is None:
        return {}
    frame = pd.DataFrame(events).copy()
    if frame.empty:
        return {}
    required = {'code', 'event_date', 'known_date', 'timing_verified', 'event_id'}
    if not required.issubset(frame):
        raise ValueError(f'Missing event columns: {required - set(frame)}')
    if not code:
        raise ValueError('ts_code is required when events are supplied')
    frame = frame.loc[frame.code.eq(code)].copy()
    if frame.event_id.isna().any() or frame.event_id.astype(str).str.strip().eq('').any():
        raise ValueError('Every event needs a nonempty event_id')
    if frame.event_id.astype(str).duplicated().any():
        raise ValueError('Duplicate event_id for the asset')
    result = {}
    for record in frame.to_dict('records'):
        day = _date(record['event_date'])
        if pd.isna(day):
            raise ValueError('Event effective date is missing or invalid')
        row = dict(event_id=str(record['event_id']), event_date=day,
                   known_date=_date(record['known_date']),
                   timing_verified=_verified(record['timing_verified']))
        result.setdefault(day, []).append(row)
    for rows in result.values():
        rows.sort(key=lambda row: row['event_id'])
    return result


def compute_asset(group, calendar, signal_dates, events=None):
    """Return (formation features, nine internal transition rows per full window).

    Events affect eligibility only when effective in (window_start, formation],
    explicitly timing-verified and known no later than formation. Other matched
    events are reported, never used as an assumption that no action occurred.
    Counts of actions are event-ID counts, not numbers of reference transitions.
    """
    calendar, signals = pd.DatetimeIndex(calendar), pd.DatetimeIndex(signal_dates)
    if calendar.hasnans or calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Calendar must be sorted, finite and unique')
    if signals.hasnans or signals.has_duplicates or not signals.is_monotonic_increasing:
        raise ValueError('Signal dates must be sorted, finite and unique')
    positions = calendar.get_indexer(signals)
    if (positions < 0).any():
        raise ValueError('Signal outside calendar')
    required = {'trade_date', 'close', 'pre_close', 'vol', 'adj_factor'}
    if not required.issubset(group):
        raise ValueError(f'Missing columns: {required - set(group)}')
    frame = group.copy()
    dates = frame.trade_date
    frame['trade_date'] = (pd.to_datetime(dates.astype(str), format='%Y%m%d')
                           if pd.api.types.is_integer_dtype(dates) else pd.to_datetime(dates))
    if frame.trade_date.isna().any() or frame.trade_date.duplicated().any():
        raise ValueError('Missing or duplicate asset/date')
    if not frame.trade_date.isin(calendar).all():
        raise ValueError('Quote outside calendar')
    if 'ts_code' in frame and (frame.ts_code.isna().any() or frame.ts_code.nunique() > 1):
        raise ValueError('Exactly one asset per call is required')
    code = str(frame.ts_code.iloc[0]) if 'ts_code' in frame and len(frame) else ''
    event_days = _events_by_date(events, code)
    # Preserve strings before parsing floats; explicitly supplied source text is
    # authoritative, including its missingness, and must not be silently replaced.
    frame['_close_text'] = frame['close_text'] if 'close_text' in frame else frame.close.map(_text)
    frame['_pre_close_text'] = frame['pre_close_text'] if 'pre_close_text' in frame else frame.pre_close.map(_text)
    fields = ['close', 'vol', 'adj_factor']
    frame[fields] = frame[fields].apply(pd.to_numeric, errors='raise')
    g = frame.set_index('trade_date').reindex(calendar)
    data = g[fields].to_numpy(dtype=np.float64)
    valid = np.isfinite(data).all(axis=1) & (data > 0).all(axis=1)
    close_text = [_text(v) for v in g._close_text]
    pre_close_text = [_text(v) for v in g._pre_close_text]
    close_decimal = [_decimal(v) for v in close_text]
    pre_close_decimal = [_decimal(v) for v in pre_close_text]
    transitions, rows = [], []
    ready_windows, eligible_rows = [], []
    for date, position in zip(signals, positions):
        row = dict(trade_date=date, window_start=pd.NaT, window_end=date,
                   case_valid=False, reason='warmup_10', valid_quote_count_10=0,
                   volume_scale=VOLUME_TO_SHARES, guard=pd.NA,
                   isolated_factor_change_no_observed_reference_break=False,
                   **{name: 0 for name in COUNT_FIELDS},
                   **{name: np.nan for name in FORMULA_FIELDS})
        if position < WINDOW - 1:
            rows.append(row)
            continue
        start = position - WINDOW + 1
        row['window_start'] = calendar[start]
        row['valid_quote_count_10'] = int(valid[start:position + 1].sum())
        for current in range(start + 1, position + 1):
            left, right = close_decimal[current - 1], pre_close_decimal[current]
            status = ('unknown_reference' if left is None or right is None else
                      'continuous' if left == right else 'raw_reference_change')
            if status == 'unknown_reference':
                row['unknown_reference_count'] += 1
            elif status == 'raw_reference_change':
                row['reference_change_count'] += 1
            previous_adj, current_adj = data[current - 1, 2], data[current, 2]
            changed = bool(np.isfinite([previous_adj, current_adj]).all() and previous_adj != current_adj)
            row['adj_factor_change_count'] += int(changed)
            # Each pair spans its intervening closed calendar days as well.
            # Retain original effective dates rather than silently moving events.
            matches = [e for event_date, day_events in event_days.items()
                       if calendar[current - 1] < event_date <= calendar[current]
                       for e in day_events]
            matches.sort(key=lambda e: e['event_id'])
            known = [e for e in matches if e['timing_verified'] and pd.notna(e['known_date'])
                     and e['known_date'] <= date]
            known_ids = [e['event_id'] for e in known]
            unverified_ids = [e['event_id'] for e in matches if e['event_id'] not in known_ids]
            row['known_action_count'] += len(known_ids)
            row['event_timing_unverified_count'] += len(unverified_ids)
            transitions.append(dict(
                signal_date=date, ts_code=code, window_start=calendar[start], window_end=date,
                previous_date=calendar[current - 1], current_date=calendar[current],
                previous_close_text=close_text[current - 1], current_pre_close_text=pre_close_text[current],
                reference_status=status, adj_factor_changed=changed,
                matched_event_ids=json.dumps([e['event_id'] for e in matches], ensure_ascii=False),
                known_action_ids=json.dumps(known_ids, ensure_ascii=False),
                unverified_event_ids=json.dumps(unverified_ids, ensure_ascii=False),
                event_known_dates=json.dumps({e['event_id']: None if pd.isna(e['known_date']) else
                                             e['known_date'].strftime('%Y-%m-%d') for e in matches},
                                            ensure_ascii=False, sort_keys=True),
                event_effective_dates=json.dumps({e['event_id']: e['event_date'].strftime('%Y-%m-%d')
                                                 for e in matches}, ensure_ascii=False, sort_keys=True),
                known_action_count=len(known_ids), event_timing_unverified_count=len(unverified_ids),
                isolated_factor_change_no_observed_reference_break=bool(changed and status == 'continuous' and not known_ids)))
        row['isolated_factor_change_no_observed_reference_break'] = bool(
            row['adj_factor_change_count'] and not row['reference_change_count']
            and not row['unknown_reference_count'] and not row['known_action_count'])
        # A missing quote necessarily leaves at least one internal reference
        # unknown; a bad non-reference numeric input still invalidates the factor.
        if row['unknown_reference_count']:
            row['reason'] = 'unknown_reference'
        elif row['reference_change_count']:
            row['reason'] = 'raw_reference_change'
        elif row['known_action_count']:
            row['reason'] = 'known_action'
        elif row['valid_quote_count_10'] != WINDOW:
            row['reason'] = 'invalid_quote'
        else:
            row['reason'] = 'valid'
            ready_windows.append(data[start:position + 1])
            eligible_rows.append(len(rows))
        rows.append(row)
    if eligible_rows:
        windows = np.asarray(ready_windows)
        values = _evaluate(windows[:, :, 0], windows[:, :, 1] * VOLUME_TO_SHARES)
        for index, target in enumerate(eligible_rows):
            finite = all(np.isfinite(values[name][index]) for name in FORMULA_FIELDS)
            rows[target]['guard'] = bool(values['guard'][index])
            if finite:
                rows[target]['case_valid'] = True
                for name in FORMULA_FIELDS:
                    rows[target][name] = float(values[name][index])
            else:
                rows[target]['reason'] = 'nonfinite_factor'
    columns = ['trade_date', 'window_start', 'window_end', 'case_valid', 'reason',
               'valid_quote_count_10', 'volume_scale', *FORMULA_FIELDS, 'guard',
               *COUNT_FIELDS, 'isolated_factor_change_no_observed_reference_break']
    features = pd.DataFrame(rows, columns=columns)
    features['guard'] = features.guard.astype('boolean')
    return features, pd.DataFrame(transitions, columns=TRANSITION_COLUMNS)
