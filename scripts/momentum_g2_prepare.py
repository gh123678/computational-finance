"""Fresh historical common-pool preparation using raw economic G bridges."""
from decimal import Decimal
import json
import math
import re

import numpy as np
import pandas as pd

from momentum_g2_events import (bridge_terms, day, display_price, number,
                                validate_calendar)


class PreparationError(RuntimeError):
    def __init__(self, reason, partial=None, detail=None):
        super().__init__(reason)
        self.reason, self.partial, self.detail = reason, partial or {}, detail or {}


def _date_column(frame, name):
    if name not in frame:
        return pd.Series(pd.NaT, index=frame.index, dtype='datetime64[ns]')
    return pd.to_datetime(frame[name].map(day), errors='coerce')


def historical_pool(date, universe, names, industries, calendar):
    """Existing interval assumptions with strict date-only ST availability."""
    date = pd.Timestamp(date)
    listed = universe.loc[universe.ts_code.str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ)$')].copy()
    list_date, delist_date = _date_column(listed, 'list_date'), _date_column(listed, 'delist_date')
    age = calendar.searchsorted(date, side='right') - calendar.searchsorted(pd.DatetimeIndex(list_date))
    listed = listed.loc[list_date.notna() & list_date.le(date) & (delist_date.isna() | delist_date.gt(date)) & (age >= 120)]
    start, end, announced = (_date_column(names, k) for k in ('start_date', 'end_date', 'ann_date'))
    # Announcement on the formation day becomes available next open, including
    # when the stamp is a close-level cutoff.
    active = names.loc[start.le(date) & (end.isna() | end.ge(date)) & announced.lt(date)]
    risk = active.loc[active.name.astype(str).str.contains('ST|^PT', case=False, na=False), 'ts_code']
    listed = listed.loc[~listed.ts_code.isin(risk)]
    start, end = (_date_column(industries, k) for k in ('in_date', 'out_date'))
    sector = industries.loc[start.le(date) & (end.isna() | end.gt(date))].copy()
    nonempty = sector.l1_code.notna() & sector.l1_code.astype(str).str.strip().ne('')
    sector = sector.loc[nonempty]
    counts = sector.groupby('ts_code').l1_code.nunique()
    sector = sector.loc[sector.ts_code.isin(counts[counts.eq(1)].index)].drop_duplicates('ts_code')
    return listed[['ts_code']].merge(sector[['ts_code', 'l1_code']].rename(columns={'l1_code': 'industry'}),
                                      on='ts_code', validate='one_to_one')


def _bridge(book, code, calendar, right_pos, previous, current):
    left, right = calendar[right_pos - 1], calendar[right_pos]
    d, s, events, reason = bridge_terms(book, code, right)
    prev, ref = display_price(previous), display_price(current)
    theoretical = None
    if not reason:
        if prev is None or ref is None:
            reason = 'invalid_raw_reference_representation'
        else:
            # Use the lexical original close before the one fixed display
            # quantization; never round C before subtracting D or dividing.
            exact_prev = Decimal(str(previous))
            theoretical = display_price((exact_prev - d) / (1 + s))
            if theoretical is None or theoretical != ref:
                reason = 'pre_close_display_mismatch'
    future = book.unknown_effective(code, right)
    late = bool(future and not events)
    if future and events:
        signature = lambda r: (r['kind'], r['status'], r.get('record'), r.get('ex'),
                               number(r.get('cash_div_tax')), number(r.get('stk_div')))
        known_signatures = {signature(r) for r in events}
        # A later conflicting economic version is audit evidence of an
        # unresolved actually consumed entitlement, even where display cents
        # happen to conceal its numeric difference.  Metadata-only updates do
        # not change the previously available economic object.
        late = any(signature(r) not in known_signatures for r in future)
    # Future facts are diagnostics.  A consumed past bridge cannot silently
    # receive them, even if its pre_close happens to look unchanged.
    late_reason = 'actual_bridge_requires_unavailable_event_terms' if late else ''
    return dict(ts_code=code, bridge_pos=right_pos, bridge_left=left, bridge_right=right,
        previous_close_text=str(previous), current_pre_close_text=str(current),
        D=str(d) if d is not None else None, s=str(s) if s is not None else None,
        theoretical_pre_close_text=str(theoretical) if theoretical is not None else None,
        displayed_pre_close_text=str(ref) if ref is not None else None,
        event_ids=json.dumps([r['event_id'] for r in events]),
        event_versions=json.dumps([r['version_id'] for r in events]),
        source_known_dates=json.dumps([r['known_date'] for r in events]),
        valid=not reason, reason=reason, late_source_hard_error=late,
        late_reason=late_reason,
        late_event_ids=json.dumps([r['event_id'] for r in future]),
        factor_D=float(d) if d is not None else np.nan,
        factor_s=float(s) if s is not None else np.nan)


def prepare(bars, calendar, schedule, universe, names, industries, event_book, progress=None,
            *, minimum_pool=200):
    """Return common features, coverage, exclusions, unique consumed bridges.

    ``schedule`` has signal_date and execution_date; bars contain original
    numeric OHLC/vol/amount and lexical close_text/pre_close_text.  The keyword
    minimum_pool exists for small synthetic contract tests; production runner
    freezes and uses the approved default 200.
    """
    calendar = validate_calendar(calendar)
    if not event_book.calendar.equals(calendar):
        raise PreparationError('event_and_quote_calendar_conflict')
    fields = ('open', 'high', 'low', 'close', 'vol', 'amount')
    required = {'ts_code', 'trade_date', 'close_text', 'pre_close_text', *fields}
    if not required.issubset(bars):
        raise PreparationError('missing_original_raw_bar_fields')
    bars = bars.copy(deep=False)
    dates = pd.to_datetime(bars.trade_date)
    if (dates.isna().any() or not dates.eq(dates.dt.normalize()).all()
            or bars.duplicated(['ts_code', 'trade_date']).any()):
        raise PreparationError('invalid_or_duplicate_raw_quote_identity')
    if not dates.isin(calendar).all():
        raise PreparationError('raw_bar_outside_frozen_calendar')
    if universe.ts_code.duplicated().any():
        raise PreparationError('duplicate_historical_universe_identity')
    if not {'signal_date', 'execution_date'}.issubset(schedule):
        raise PreparationError('invalid_weekly_schedule_fields')
    sched = schedule[['signal_date', 'execution_date']].copy()
    sched['signal_date'] = pd.to_datetime(sched.signal_date)
    sched['execution_date'] = pd.to_datetime(sched.execution_date)
    if (sched.isna().any().any() or sched.signal_date.duplicated().any()
            or sched.execution_date.duplicated().any() or not sched.signal_date.is_monotonic_increasing
            or not sched.signal_date.isin(calendar).all() or not sched.execution_date.isin(calendar).all()
            or not sched.execution_date.gt(sched.signal_date).all()):
        raise PreparationError('invalid_or_duplicate_weekly_schedule_identity')
    features, coverage, exclusions, consumed_audit = [], [], [], []
    # Each stock/session bridge is evaluated once, then referenced by every
    # overlapping weekly window.  Quote validity and ADV are rolling arrays.
    groups = {}
    for code, frame in bars.groupby('ts_code', sort=False):
        if not re.fullmatch(r'(?:60\d{4}\.SH|00\d{4}\.SZ)', str(code)):
            continue
        frame = frame.set_index('trade_date').reindex(calendar)
        values = frame[list(fields)].apply(pd.to_numeric, errors='coerce').to_numpy(float)
        valid = np.isfinite(values).all(axis=1) & (values > 0).all(axis=1)
        bad = np.r_[0, np.cumsum(~valid)]
        amount = values[:, fields.index('amount')]
        adv = pd.Series(np.where(np.isfinite(amount) & (amount > 0), amount, np.nan)).rolling(20, min_periods=20).mean().to_numpy() * 1000.
        groups[code] = dict(frame=frame, values=values, bad=bad, adv=adv, bridges={}, consumed=set())

    def result():
        return dict(feature_rows=pd.DataFrame(features, columns=['trade_date', 'ts_code', 'industry',
            'momentum', 'adv20_cny', 'formation_close', 'window_start', 'signal_end', 'bridge_count']),
            coverage=pd.DataFrame(coverage, columns=['trade_date', 'execution_date', 'historical_pool',
                'common_pool', 'excluded', 'minimum_pool', 'passed', 'reason_counts']),
            exclusions=pd.DataFrame(exclusions, columns=['trade_date', 'ts_code', 'reason', 'detail',
                'window_start', 'signal_end']),
            daily_bridge_audit=pd.DataFrame(consumed_audit, columns=['ts_code', 'bridge_pos',
                'bridge_left', 'bridge_right', 'previous_close_text', 'current_pre_close_text',
                'D', 's', 'theoretical_pre_close_text', 'displayed_pre_close_text', 'event_ids',
                'event_versions', 'source_known_dates', 'valid', 'reason', 'late_source_hard_error',
                'late_reason', 'late_event_ids', 'factor_D', 'factor_s', 'economic_factor']),
            event_inventory=event_book.inventory())

    try:
        for period, formation in enumerate(sched.itertuples(index=False)):
            date = formation.signal_date
            pos = calendar.get_indexer([date])[0]
            if pos < 273:
                raise PreparationError('insufficient_full_calendar_274_points', result(), {'trade_date': str(date)})
            start, end_signal = pos - 273, pos - 21
            pool = historical_pool(date, universe, names, industries, calendar)
            accepted = 0
            reason_counts = {}
            for candidate in pool.itertuples(index=False):
                code = candidate.ts_code
                g, reason, detail = groups.get(code), '', ''
                if g is None:
                    reason = 'missing_complete_274_point_window'
                elif g['bad'][pos + 1] - g['bad'][start] != 0:
                    reason = 'missing_or_invalid_six_field_274_point_window'
                elif not math.isfinite(g['adv'][pos]) or g['adv'][pos] < 20_000_000:
                    reason = 'incomplete_or_insufficient_adv20'
                elif 100 * g['values'][pos, fields.index('close')] > 49_000:
                    reason = 'formation_one_lot_exceeds_49000'
                else:
                    issues = event_book.exposure_issues(code, date, calendar[start])
                    if issues:
                        reason = 'known_unsupported_or_conflicting_action'
                        detail = json.dumps([r['event_id'] for r in issues])
                bridge_rows = []
                if not reason:
                    frame, bcache = g['frame'], g['bridges']
                    for p in range(start + 1, pos + 1):
                        if p not in bcache:
                            bcache[p] = _bridge(event_book, code, calendar, p,
                                frame.iloc[p - 1]['close_text'], frame.iloc[p]['pre_close_text'])
                        bridge_rows.append(bcache[p])
                    invalid = next((r for r in bridge_rows if not r['valid']), None)
                    if invalid is not None:
                        reason, detail = invalid['reason'], str(invalid['bridge_right'])
                    # First apply only visible quote/economic guards.  An invalid
                    # past-visible bridge excludes this name without consuming G.
                    # Audit-only late facts can stop only an otherwise consumable
                    # window; they never choose its historical membership.
                    late = next((r for r in bridge_rows if r['late_source_hard_error']), None) if not reason else None
                    if late is not None:
                        for r in bridge_rows:
                            p = r['bridge_pos']
                            if p not in g['consumed']:
                                consumed_audit.append(r); g['consumed'].add(p)
                        raise PreparationError('consumed_bridge_requires_later_or_unavailable_terms', result(),
                            {'trade_date': date.isoformat(), 'ts_code': code, 'bridge': late})
                if reason:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                    exclusions.append(dict(trade_date=date, ts_code=code, reason=reason, detail=detail,
                        window_start=calendar[start], signal_end=calendar[end_signal]))
                    continue
                # The denominator is exactly the 274-point window's first point,
                # with 252 factors up through i-21.  The last 21 remain checked.
                value = 1.
                for r in bridge_rows:
                    p = r['bridge_pos']
                    close = g['values'][p, fields.index('close')]
                    previous = g['values'][p - 1, fields.index('close')]
                    factor = (close * (1 + r['factor_s']) + r['factor_D']) / previous
                    if not math.isfinite(factor) or factor <= 0:
                        raise PreparationError('invalid_consumed_economic_factor', result(), r)
                    if p <= end_signal:
                        value *= factor
                    if p not in g['consumed']:
                        consumed_audit.append(dict(r, economic_factor=factor)); g['consumed'].add(p)
                if not math.isfinite(value):
                    raise PreparationError('invalid_consumed_economic_chain', result(), {'ts_code': code, 'trade_date': str(date)})
                accepted += 1
                features.append(dict(trade_date=date, ts_code=code, industry=candidate.industry,
                    momentum=value - 1., adv20_cny=g['adv'][pos], formation_close=g['values'][pos, fields.index('close')],
                    window_start=calendar[start], signal_end=calendar[end_signal], bridge_count=273))
            coverage.append(dict(trade_date=date, execution_date=formation.execution_date,
                historical_pool=len(pool), common_pool=accepted, excluded=len(pool) - accepted,
                minimum_pool=minimum_pool, passed=accepted >= minimum_pool,
                reason_counts=json.dumps(reason_counts, sort_keys=True)))
            if progress:
                try:
                    progress(dict(stage='prepare', period=period + 1, periods=len(sched), trade_date=str(date.date()), common_pool=accepted))
                except Exception as exc:
                    raise PreparationError('preparation_progress_guard_stop', result(),
                        dict(trade_date=date.isoformat(), error_type=type(exc).__name__, reason=str(exc))) from exc
            if accepted < minimum_pool:
                raise PreparationError('common_pool_below_200' if minimum_pool == 200 else 'common_pool_below_test_minimum',
                                       result(), coverage[-1])
    except PreparationError:
        raise
    except Exception as exc:
        raise PreparationError('preparation_engineering_exception', result(),
            dict(error_type=type(exc).__name__, reason=str(exc))) from exc
    return result()


prepare_from_frames = prepare
