"""Reference-linked control factors and labels for the approved r3 study.

Only observed raw CSV price text is used.  Neither adjustment factors nor any
return label is an input to formation.  The constructed returns are reference
price returns, not dividends-reinvested or cash-account wealth returns.

Events must come from the runner's normalized frozen r2 event catalogue.  Its
optional ``conflict`` flag explicitly identifies conflicting economic terms;
multiple different actions are not, by themselves, a conflict.  Unverified or
late event records are diagnostics, never an explanation for a visible break.
"""
import json

import numpy as np
import pandas as pd

try:
    from .alphaforge_case_r2_features import _date, _decimal, _text, _verified
except ImportError:
    from alphaforge_case_r2_features import _date, _decimal, _text, _verified


WINDOW = 21
FACTORS = ('momentum20', 'reversal5', 'lowvol20')
COUNT_COLUMNS = [
    'bridge_count', 'valid_bridge_count', 'reference_change_count',
    'unknown_reference_count', 'unexplained_reference_change_count',
    'known_action_count', 'event_timing_unverified_count', 'known_conflict_count']
FEATURE_COLUMNS = [
    'trade_date', 'ts_code', 'window_start', 'window_end', 'reference_valid',
    'reason', *FACTORS, 'valid_quote_count_21', *COUNT_COLUMNS,
    'K_start', 'K_end', 'P_start', 'P_end', 'reference_failure_reasons']
LABEL_COLUMNS = [
    'signal_date', 'ts_code', 'execution_date', 'R_end', 'R_week', 'R_valid',
    'R_reason', *COUNT_COLUMNS, 'K_start', 'K_end', 'stock_reference_return',
    'benchmark_return', 'R_failure_reasons']


def _days(values, name, allow_missing=False):
    result = pd.DatetimeIndex([_date(value) for value in values])
    if not allow_missing and result.hasnans:
        raise ValueError(f'{name} contains missing or invalid dates')
    # Date-level source dates must not be silently rounded down from intraday.
    for raw, day in zip(values, result):
        if pd.notna(day) and pd.Timestamp(str(raw)) != day:
            raise ValueError(f'{name} must contain date-level values')
    return result


def _calendar(values):
    result = _days(list(values), 'Calendar')
    if result.has_duplicates or not result.is_monotonic_increasing:
        raise ValueError('Calendar must be sorted and unique')
    return result


def _float(decimal):
    if decimal is None:
        return np.float64(np.nan)
    with np.errstate(over='ignore', under='ignore'):
        number = np.float64(float(decimal))
    return number if np.isfinite(number) and number > 0 else np.float64(np.nan)


def _events(events, code, calendar):
    """Index literal (previous open, current open] event intervals once."""
    result = [[] for _ in calendar]
    if events is None:
        return result
    frame = pd.DataFrame(events).copy()
    if frame.empty:
        return result
    required = {'code', 'event_date', 'known_date', 'timing_verified', 'event_id'}
    if not required.issubset(frame):
        raise ValueError(f'Missing event columns: {required - set(frame)}')
    frame = frame.loc[frame.code.eq(code)].copy()
    if frame.event_id.isna().any() or frame.event_id.astype(str).str.strip().eq('').any():
        raise ValueError('Every event needs a nonempty event_id')
    if frame.event_id.astype(str).duplicated().any():
        raise ValueError('Duplicate event_id; normalize economic events first')
    for row in frame.to_dict('records'):
        effective = _date(row['event_date'])
        if pd.isna(effective):
            raise ValueError('Missing or invalid event effective date')
        item = dict(event_id=str(row['event_id']), event_date=effective,
                    known_date=_date(row['known_date']),
                    timing_verified=_verified(row['timing_verified']),
                    conflict=_verified(row.get('conflict', False)))
        current = int(calendar.searchsorted(effective, side='left'))
        if 0 < current < len(calendar) and calendar[current - 1] < effective <= calendar[current]:
            result[current].append(item)
    for items in result:
        items.sort(key=lambda row: row['event_id'])
    return result


class _Asset:
    def __init__(self, group, calendar, events, require_open=False):
        required = {'trade_date', 'ts_code', 'close_text', 'pre_close_text'}
        if require_open and not ({'open', 'open_text'} & set(group)):
            raise ValueError('Labels require raw open or open_text')
        if not required.issubset(group):
            raise ValueError(f'Raw CSV price text is required: {required - set(group)}')
        frame = group.copy()
        if frame.empty or frame.ts_code.isna().any() or frame.ts_code.nunique() != 1:
            raise ValueError('Exactly one nonempty asset per call is required')
        self.code = str(frame.ts_code.iloc[0])
        frame['trade_date'] = _days(list(frame.trade_date), 'Quote dates')
        if frame.trade_date.duplicated().any():
            raise ValueError('Duplicate asset/date')
        if not frame.trade_date.isin(calendar).all():
            raise ValueError('Quote outside calendar')
        self.calendar = calendar
        self.present = calendar.isin(frame.trade_date)
        g = frame.set_index('trade_date').reindex(calendar)
        # Explicit source-text missingness is authoritative, never replaced by
        # the float columns.  Other columns, including adj_factor, are ignored.
        self.close_text = [_text(value) for value in g.close_text]
        self.reference_text = [_text(value) for value in g.pre_close_text]
        self.close_decimal = [_decimal(value) for value in self.close_text]
        self.reference_decimal = [_decimal(value) for value in self.reference_text]
        self.close = np.asarray([_float(value) for value in self.close_decimal], dtype=np.float64)
        self.reference = np.asarray([_float(value) for value in self.reference_decimal], dtype=np.float64)
        self.opened = None
        if require_open:
            column = g.open_text if 'open_text' in g else g.open
            self.opened = np.asarray([_float(_decimal(value)) for value in column], dtype=np.float64)
        self.events = _events(events, self.code, calendar)

    def path(self, start, end, formation=None):
        """Build K and P in a fixed scalar float64 order, without filling.

        ``formation=None`` means each bridge's own rear date is the event
        information cutoff.  A formation cutoff is used only for past factors.
        The first point's pre_close is never read as part of this interval.
        """
        counts = {name: 0 for name in COUNT_COLUMNS}
        counts['bridge_count'] = end - start
        failures = []

        def fail(reason):
            if reason not in failures:
                failures.append(reason)

        present = self.present[start:end + 1]
        closes = self.close[start:end + 1]
        quote_valid = present & np.isfinite(closes) & (closes > 0)
        if not present.all():
            fail('missing_quote')
        if (present & ~np.isfinite(closes)).any():
            fail('invalid_close')
        for current in range(start + 1, end + 1):
            cutoff = self.calendar[current] if formation is None else formation
            matches = self.events[current]
            known = [item for item in matches if item['timing_verified'] and
                     pd.notna(item['known_date']) and item['known_date'] <= cutoff]
            counts['known_action_count'] += len(known)
            counts['event_timing_unverified_count'] += len(matches) - len(known)
            conflict = sum(item['conflict'] for item in known)
            counts['known_conflict_count'] += conflict
            left, right = self.close_decimal[current - 1], self.reference_decimal[current]
            unknown = (not self.present[current - 1] or not self.present[current] or
                       left is None or right is None or
                       not np.isfinite(self.close[current - 1]) or
                       not np.isfinite(self.reference[current]))
            changed = left is not None and right is not None and left != right
            counts['reference_change_count'] += int(changed)
            unexplained = bool(changed and not known)
            if unknown:
                counts['unknown_reference_count'] += 1
                fail('unknown_reference')
            if conflict:
                fail('known_action_conflict')
            if unexplained:
                counts['unexplained_reference_change_count'] += 1
                fail('unexplained_reference_change')
            counts['valid_bridge_count'] += int(not (unknown or conflict or unexplained))
        result = dict(counts, valid_quote_count=int(quote_valid.sum()),
                      valid=False, reason=failures[0] if failures else 'valid',
                      failures=failures, K=None, P=None)
        if failures:
            return result
        scales = np.empty(end - start + 1, dtype=np.float64)
        prices = np.empty_like(scales)
        scales[0] = np.float64(1.)
        prices[0] = np.float64(self.close[start] * scales[0])
        with np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
            for local, current in enumerate(range(start + 1, end + 1), start=1):
                scales[local] = np.float64(np.float64(scales[local - 1] * self.close[current - 1]) /
                                           self.reference[current])
                prices[local] = np.float64(self.close[current] * scales[local])
        if not (np.isfinite(scales).all() and np.isfinite(prices).all() and
                (scales > 0).all() and (prices > 0).all()):
            result.update(reason='nonfinite_reference_index', failures=['nonfinite_reference_index'])
            return result
        result.update(valid=True, K=scales, P=prices)
        return result


def compute_reference_windows(group, calendar, signal_dates, events=None):
    """Return one row for every supplied key, including failed 21-point paths.

    Required group columns: trade_date, ts_code, close_text, pre_close_text.
    Raw text is parsed as positive finite Decimal for exact reference matching;
    float64 conversion is used only for the specified index arithmetic.  Events
    are normalized records, with an optional explicit ``conflict`` Boolean.
    """
    calendar = _calendar(calendar)
    signals = _days(list(signal_dates), 'Signal dates')
    if signals.has_duplicates or not signals.is_monotonic_increasing:
        raise ValueError('Signal dates must be sorted and unique')
    positions = calendar.get_indexer(signals)
    if (positions < 0).any():
        raise ValueError('Signal outside calendar')
    asset = _Asset(group, calendar, events)
    rows = []
    for day, position in zip(signals, positions):
        row = dict(trade_date=day, ts_code=asset.code, window_start=pd.NaT,
                   window_end=day, reference_valid=False, reason='warmup_21',
                   valid_quote_count_21=0, K_start=np.nan, K_end=np.nan,
                   P_start=np.nan, P_end=np.nan, reference_failure_reasons='["warmup_21"]',
                   **{name: np.nan for name in FACTORS},
                   **{name: 0 for name in COUNT_COLUMNS})
        if position >= WINDOW - 1:
            start = int(position - WINDOW + 1)
            result = asset.path(start, int(position), formation=day)
            row.update({name: result[name] for name in COUNT_COLUMNS})
            row.update(window_start=calendar[start], valid_quote_count_21=result['valid_quote_count'],
                       reason=result['reason'], reference_failure_reasons=json.dumps(result['failures']))
            if result['valid']:
                prices = result['P']
                with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
                    values = dict(momentum20=np.float64(prices[-1] / prices[0] - 1.),
                                  reversal5=np.float64(-(prices[-1] / prices[-6] - 1.)),
                                  lowvol20=np.float64(-np.std(prices[1:] / prices[:-1] - 1., ddof=1)))
                row.update(K_start=result['K'][0], K_end=result['K'][-1],
                           P_start=prices[0], P_end=prices[-1])
                if all(np.isfinite(value) for value in values.values()):
                    row.update(values, reference_valid=True)
                else:
                    row.update(reason='nonfinite_factor', reference_failure_reasons='["nonfinite_factor"]')
        rows.append(row)
    return pd.DataFrame(rows, columns=FEATURE_COLUMNS)


def weekly_reference_labels(group, calendar, schedule, benchmark_open, events=None):
    """Open-u to open-v reference excess returns; never cash-account returns.

    Schedule columns are signal_date, execution_date, next_execution.  The u
    anchor has K=1 and ignores its own pre_close and all earlier events.  Each
    later bridge uses known_date <= that bridge's rear date, not signal_date.
    Missing labels remain rows and are never used to filter formation keys.
    """
    calendar = _calendar(calendar)
    required = {'signal_date', 'execution_date', 'next_execution'}
    if not required.issubset(schedule):
        raise ValueError(f'Missing schedule columns: {required - set(schedule)}')
    plans = schedule.copy()
    for column in required:
        plans[column] = _days(list(plans[column]), column, allow_missing=column == 'next_execution')
    if plans.signal_date.duplicated().any() or not plans.signal_date.is_monotonic_increasing:
        raise ValueError('Schedule signal dates must be sorted and unique')
    if not (plans.signal_date < plans.execution_date).all() or (
            plans.next_execution.notna() & plans.next_execution.le(plans.execution_date)).any():
        raise ValueError('Schedule must have signal < execution < next execution')
    if (calendar.get_indexer(plans.signal_date) < 0).any():
        raise ValueError('Signal outside calendar')
    asset = _Asset(group, calendar, events, require_open=True)
    benchmark = pd.Series(benchmark_open).copy()
    benchmark.index = _days(list(benchmark.index), 'Benchmark dates')
    if benchmark.index.has_duplicates:
        raise ValueError('Duplicate benchmark date')
    benchmark = pd.to_numeric(benchmark, errors='coerce').reindex(calendar).to_numpy(dtype=np.float64)
    rows = []
    for item in plans.itertuples(index=False):
        row = dict(signal_date=item.signal_date, ts_code=asset.code,
                   execution_date=item.execution_date, R_end=item.next_execution,
                   R_week=np.nan, R_valid=False, R_reason='missing_next_execution',
                   K_start=np.nan, K_end=np.nan, stock_reference_return=np.nan,
                   benchmark_return=np.nan, R_failure_reasons='["missing_next_execution"]',
                   **{name: 0 for name in COUNT_COLUMNS})
        start, end = calendar.get_indexer([item.execution_date, item.next_execution])
        if pd.notna(item.next_execution):
            if start < 0 or end < 0:
                row.update(R_reason='outside_period', R_failure_reasons='["outside_period"]')
            else:
                result = asset.path(int(start), int(end))
                row.update({name: result[name] for name in COUNT_COLUMNS})
                failures = list(result['failures'])
                if not (np.isfinite(asset.opened[[start, end]]).all() and
                        (asset.opened[[start, end]] > 0).all()):
                    failures.insert(0, 'stock_endpoint')
                if not (np.isfinite(benchmark[[start, end]]).all() and
                        (benchmark[[start, end]] > 0).all()):
                    failures.insert(0, 'benchmark_endpoint')
                row.update(R_reason=failures[0] if failures else 'valid',
                           R_failure_reasons=json.dumps(failures))
                if not failures:
                    with np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
                        opened_start = np.float64(asset.opened[start] * result['K'][0])
                        opened_end = np.float64(asset.opened[end] * result['K'][-1])
                        stock = np.float64(opened_end / opened_start - 1.)
                        index = np.float64(benchmark[end] / benchmark[start] - 1.)
                        value = np.float64(stock - index)
                    if np.isfinite([stock, index, value]).all():
                        row.update(R_week=value, R_valid=True, K_start=result['K'][0],
                                   K_end=result['K'][-1], stock_reference_return=stock,
                                   benchmark_return=index)
                    else:
                        row.update(R_reason='nonfinite_label', R_failure_reasons='["nonfinite_label"]')
        rows.append(row)
    return pd.DataFrame(rows, columns=LABEL_COLUMNS)
