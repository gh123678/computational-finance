"""Approved r3 reference-price guard; no labels, returns or portfolio selection.

The exhaustive audit is deliberately stricter than a holding-only guard.  Every
fixed security is scanned on every account session.  A supplied adjustment
factor is diagnostic only and never changes an economic decision.
"""
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re

import numpy as np
import pandas as pd

from quant_research.accounting import Action
from quant_research.rights import RightsIssue


DAILY_COLUMNS = ['date', 'ts_code', 'lifecycle', 'has_quote', 'prior_quote_date',
                 'prior_close_text', 'pre_close_text', 'reference_equal',
                 'event_ids', 'decision', 'reason', 'suspend_type', 'suspend_timing']
FAILURE_COLUMNS = ['date', 'ts_code', 'reason', 'detail']
EVENT_COLUMNS = ['event_id', 'code', 'kind', 'record', 'ex', 'cash_pay',
                 'stock_pay', 'list_date', 'cash_per_share', 'stock_per_share',
                 'taxable_bonus_per_share', 'price', 'ratio', 'source', 'source_sha256']
ALERT_COLUMNS = ['date', 'ts_code', 'prior_quote_date', 'prior_adj_factor',
                 'adj_factor', 'relative_change', 'material_old_guard',
                 'registered_ex_in_interval', 'economic_decision_affected']


def day(value):
    """Strict day parser: no integer nanoseconds, timezone or intraday times."""
    if value is None or pd.isna(value) or value == '':
        return pd.NaT
    if isinstance(value, str):
        if re.fullmatch(r'\d{8}', value):
            return pd.to_datetime(value, format='%Y%m%d', errors='coerce')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return pd.NaT
    elif not isinstance(value, (pd.Timestamp, np.datetime64)):
        # datetime/date are accepted by Timestamp without accepting raw ints.
        from datetime import date, datetime
        if not isinstance(value, (date, datetime)):
            return pd.NaT
    result = pd.Timestamp(value)
    return result if result.tzinfo is None and result == result.normalize() else pd.NaT


def decimal_price(value):
    """Only original CSV text or Decimal may supply the reference comparison."""
    if not isinstance(value, (str, Decimal)):
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def lifecycle_state(date, list_date, delist_date=pd.NaT):
    if pd.isna(list_date) or (pd.notna(delist_date) and delist_date < list_date):
        return 'invalid_lifecycle'
    if date < list_date:
        return 'pre_listing'
    if pd.isna(delist_date) or date < delist_date:
        return 'listed'
    return 'scheduled_delisting' if date == delist_date else 'post_delisting'


def _stamp(value):
    return None if value is None or pd.isna(value) else pd.Timestamp(value).strftime('%Y-%m-%d')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


def freeze_event_registry(actions=(), rights=(), source_hashes=None):
    """Bind already-normalized frozen terms, without selecting raw versions.

    The caller uses the old correct_actions/normalize_actions and verified_rights.
    Exact duplicates in this *normalized list* are errors, not new raw-version
    preferences. Pure-zero distributions cannot explain a reference discontinuity.
    Registry errors are returned so the audit can continue inventorying all dates.
    """
    hashes = {} if source_hashes is None else dict(source_hashes)
    rows, failures, seen = [], [], {}
    for kind, items in [('distribution', actions), ('rights', rights)]:
        for item in items:
            code = getattr(item, 'code', '')
            ex = day(getattr(item, 'ex', None))
            expected = Action if kind == 'distribution' else RightsIssue
            if not isinstance(item, expected):
                failures.append(dict(date=ex, ts_code=code, reason='unapproved_event_type', detail=kind))
                continue
            if kind == 'distribution' and not (item.cash_per_share or item.stock_per_share):
                continue
            source_key = 'dividend' if kind == 'distribution' else 'rights'
            source = ('frozen_correct_actions_then_normalize_actions' if kind == 'distribution' else item.source)
            source_sha = hashes.get(source_key, '')
            row = dict(event_id='', code=code, kind=kind, record=day(item.record), ex=ex,
                       cash_pay=pd.NaT, stock_pay=pd.NaT, list_date=pd.NaT,
                       cash_per_share=0., stock_per_share=0., taxable_bonus_per_share=0.,
                       price=None, ratio=None, source=source, source_sha256=source_sha)
            if kind == 'distribution':
                for field in ['cash_pay', 'stock_pay']:
                    row[field] = day(getattr(item, field))
                for field in ['cash_per_share', 'stock_per_share', 'taxable_bonus_per_share']:
                    row[field] = getattr(item, field)
            else:
                row.update(price=item.price, ratio=item.ratio, list_date=day(item.list_date))
            identity = {k: (_stamp(v) if k in ('record', 'ex', 'cash_pay', 'stock_pay', 'list_date') else v)
                        for k, v in row.items() if k != 'event_id'}
            row['event_id'] = kind + ':' + _digest(identity)
            key = (code, ex)
            if key in seen:
                reason = 'duplicate_normalized_event' if seen[key] == row['event_id'] else 'conflicting_same_day_events'
                failures.append(dict(date=ex, ts_code=code, reason=reason, detail=row['event_id']))
            seen[key] = row['event_id']
            if not re.fullmatch(r'[0-9a-fA-F]{64}', str(source_sha)):
                failures.append(dict(date=ex, ts_code=code, reason='missing_event_source_hash', detail=source_key))
            if pd.isna(row['record']) or pd.isna(ex) or row['record'] >= ex or not source:
                failures.append(dict(date=ex, ts_code=code, reason='invalid_event_terms', detail=row['event_id']))
            rows.append(row)
    return pd.DataFrame(rows, columns=EVENT_COLUMNS), pd.DataFrame(failures, columns=FAILURE_COLUMNS)


def suspension_evidence(suspensions):
    """Use the old adapter's same-day S membership; never infer resumed periods."""
    evidence = defaultdict(list)
    if suspensions is None:
        return evidence
    if isinstance(suspensions, pd.DataFrame):
        required = {'trade_date', 'ts_code', 'suspend_type', 'suspend_timing'}
        if not required.issubset(suspensions):
            raise ValueError('Suspension evidence requires original daily type and timing fields')
        for row in suspensions[list(required)].to_dict('records'):
            date = day(row['trade_date'])
            if pd.isna(date):
                raise ValueError('Invalid suspension evidence date')
            evidence[(date, row['ts_code'])].append((str(row['suspend_type']),
                                                    '' if pd.isna(row['suspend_timing']) else str(row['suspend_timing'])))
    else:
        # Compatibility with the original simulate positional API. The explicit
        # frozen S set is retained as set evidence, not invented raw timing.
        for date, code in suspensions:
            parsed = day(date)
            if pd.isna(parsed):
                raise ValueError('Invalid suspension-set date')
            evidence[(parsed, code)].append(('S', 'frozen_S_set_no_raw_timing'))
    return evidence


def _calendar(values, name):
    result = pd.DatetimeIndex(values)
    if result.empty or result.hasnans or result.has_duplicates or not result.is_monotonic_increasing:
        raise ValueError(name + ' must be nonempty, sorted and unique')
    if result.tz is not None or not result.equals(result.normalize()):
        raise ValueError(name + ' must contain day-level naive timestamps')
    return result


def _quotes(frame, name):
    if frame is None:
        return pd.DataFrame(columns=['trade_date', 'ts_code', 'close_text', 'pre_close_text'])
    required = {'trade_date', 'ts_code', 'close_text', 'pre_close_text'}
    if not required.issubset(frame):
        raise ValueError(name + ' must preserve raw CSV close_text/pre_close_text')
    result = frame.copy(deep=False).copy()
    result['trade_date'] = result.trade_date.map(day)
    if result.trade_date.isna().any() or result.duplicated(['trade_date', 'ts_code']).any():
        raise ValueError(name + ' has invalid dates or duplicate quotes')
    return result


def input_fingerprint(bars, calendar, universe, actions, suspensions, rights,
                      codes, seed_bars, source_hashes, full_calendar):
    """Bind a reusable precheck to its actual inputs; no performance fields."""
    digest = hashlib.sha256()
    def frame_hash(frame, columns, sort):
        if frame is None:
            digest.update(b'none'); return
        columns = [c for c in columns if c in frame]
        value = frame[columns].copy()
        if 'ts_code' in value:
            value = value.loc[value.ts_code.isin(codes)]
        if sort:
            value = value.sort_values([c for c in sort if c in value], kind='stable')
        for col in ('close_text', 'pre_close_text'):
            if col in value:
                # A cache that inferred a float cannot masquerade as an
                # unchanged raw lexeme merely because str(float) happens to
                # equal this particular CSV spelling.
                lexical = value[col].map(lambda x: isinstance(x, (str, Decimal)))
                digest.update(lexical.to_numpy(dtype=bool).tobytes())
        # Canonical scalar text avoids category/storage dtype differences.
        value = value.astype('string').fillna('<NA>')
        digest.update('|'.join(columns).encode())
        digest.update(pd.util.hash_pandas_object(value, index=False).to_numpy().tobytes())
    frame_hash(bars, ['trade_date', 'ts_code', 'close_text', 'pre_close_text', 'open', 'close', 'vol', 'amount'], ['trade_date', 'ts_code'])
    frame_hash(seed_bars, ['trade_date', 'ts_code', 'close_text', 'pre_close_text'], ['trade_date', 'ts_code'])
    frame_hash(universe, ['ts_code', 'list_date', 'delist_date'], ['ts_code'])
    if isinstance(suspensions, pd.DataFrame):
        frame_hash(suspensions, ['trade_date', 'ts_code', 'suspend_type', 'suspend_timing'], ['trade_date', 'ts_code'])
    else:
        digest.update(str(sorted((str(d), c) for d, c in (suspensions or ()))).encode())
    digest.update(_digest(dict(calendar=list(map(str, calendar)), full_calendar=list(map(str, full_calendar)) if full_calendar is not None else None,
                               codes=sorted(codes), actions=[asdict(a) for a in actions],
                               rights=[asdict(a) for a in rights], source_hashes=source_hashes)).encode())
    return digest.hexdigest()


def audit_reference_guard(bars, calendar, universe, actions=(), suspensions=None, rights=(), *,
                          codes=None, seed_bars=None, source_hashes=None, full_calendar=None,
                          adjustment_bars=None):
    """Inventory every failure, including failures in never-held fixed securities.

    ``calendar`` is the original account calendar. ``full_calendar`` must also
    include its true preceding exchange session. ``seed_bars`` supplies exactly
    that session, never each security's last surviving quote. Universe lifecycle
    dates come exclusively from the frozen r2 universe metadata.
    """
    calendar = _calendar(calendar, 'Account calendar')
    raw = _quotes(bars, 'bars')
    seed = _quotes(seed_bars, 'seed_bars')
    codes = set(raw.ts_code) if codes is None else set(codes)
    if not codes:
        raise ValueError('Empty fixed security scope')
    if not {'ts_code', 'list_date', 'delist_date'}.issubset(universe):
        raise ValueError('Frozen universe lifecycle fields required')
    if universe.loc[universe.ts_code.isin(codes)].ts_code.duplicated().any():
        raise ValueError('Duplicate frozen universe security')
    if not raw.trade_date.isin(calendar).all():
        raise ValueError('Guard bars outside explicit account calendar')
    actions, rights = tuple(actions), tuple(rights)
    registry, initial_errors = freeze_event_registry(actions, rights, source_hashes)
    errors = initial_errors.loc[initial_errors.ts_code.isin(codes)].to_dict('records')
    evidence = suspension_evidence(suspensions)
    previous_session = pd.NaT
    full = None if full_calendar is None else _calendar(full_calendar, 'Full exchange calendar')
    if full is None or not calendar.isin(full).all() or not (full < calendar[0]).any():
        errors.append(dict(date=calendar[0], ts_code='*', reason='missing_preceding_exchange_calendar', detail='No certified seed session'))
    else:
        previous_session = full[full < calendar[0]][-1]
        if not calendar.equals(full[(full >= calendar[0]) & (full <= calendar[-1])]):
            errors.append(dict(date=calendar[0], ts_code='*', reason='account_calendar_omits_exchange_sessions', detail='Full interval must be scanned'))
        if not seed.empty and not seed.trade_date.eq(previous_session).all():
            errors.append(dict(date=calendar[0], ts_code='*', reason='invalid_seed_session', detail=str(previous_session.date())))
    metadata = universe.set_index('ts_code')
    raw = raw.loc[raw.ts_code.isin(codes)]
    groups = raw.groupby('ts_code', sort=False)
    seed_groups = seed.loc[seed.trade_date.eq(previous_session)].groupby('ts_code', sort=False)
    invalid_keys = {(item['ts_code'], item['date']) for item in initial_errors.to_dict('records')}
    registry['allowed'] = [(row.code, row.ex) not in invalid_keys for row in registry.itertuples()]
    registry['account_date_domain'] = [
        ('overlaps_account_calendar' if any(pd.notna(row[field]) and calendar[0] <= row[field] <= calendar[-1]
                                           for field in ('record', 'ex', 'cash_pay', 'stock_pay', 'list_date'))
         else 'outside_account_calendar') for row in registry.to_dict('records')]
    event_groups = {code: g.to_dict('records') for code, g in registry.groupby('code')}
    daily_parts, alerts = [], []
    adjustment = adjustment_bars if adjustment_bars is not None else bars
    adj_groups = {}
    if adjustment is not None and ('adj_factor' in adjustment or 'orig_adj_factor' in adjustment):
        adj = adjustment.copy(deep=False)
        adj_groups = {code: g for code, g in adj.groupby('ts_code', sort=False) if code in codes}
    calendar_set = set(calendar)
    full_set = calendar_set if full is None else set(full)
    for code_index, code in enumerate(sorted(codes), start=1):
        if code not in metadata.index:
            listing = delisting = pd.NaT
            errors.append(dict(date=calendar[0], ts_code=code, reason='missing_universe_security', detail=''))
        else:
            listing, delisting = day(metadata.loc[code, 'list_date']), day(metadata.loc[code, 'delist_date'])
            raw_delist = metadata.loc[code, 'delist_date']
            if pd.isna(listing) or (pd.notna(raw_delist) and raw_delist != '' and pd.isna(delisting)) or (pd.notna(delisting) and delisting < listing):
                errors.append(dict(date=calendar[0], ts_code=code, reason='invalid_lifecycle_dates', detail=str(metadata.loc[code].to_dict())))
                listing = pd.NaT
        records = {} if code not in groups.groups else groups.get_group(code).set_index('trade_date').to_dict('index')
        prior_date, prior_close, prior_text = pd.NaT, None, ''
        if code in seed_groups.groups and pd.notna(listing):
            if lifecycle_state(previous_session, listing, delisting) != 'listed':
                errors.append(dict(date=previous_session, ts_code=code, reason='seed_quote_outside_lifecycle', detail=''))
        if pd.notna(listing) and listing < calendar[0]:
            if code in seed_groups.groups:
                q = seed_groups.get_group(code).iloc[0]
                prior_close = decimal_price(q.close_text)
                if lifecycle_state(previous_session, listing, delisting) != 'listed' or prior_close is None:
                    errors.append(dict(date=previous_session, ts_code=code, reason='invalid_initial_seed', detail=str(q.close_text)))
                    prior_close = None
                else:
                    prior_date, prior_text = previous_session, str(q.close_text)
            elif pd.isna(delisting) or delisting >= calendar[0]:
                errors.append(dict(date=calendar[0], ts_code=code, reason='missing_initial_seed', detail=_stamp(previous_session)))
        items = event_groups.get(code, [])
        ex_events, equity_dates = defaultdict(list), []
        for event in items:
            valid = bool(event['allowed'])
            for field in ['record', 'ex']:
                event_day = event[field]
                if pd.isna(event_day):
                    continue
                if calendar[0] <= event_day <= calendar[-1] and event_day not in full_set:
                    errors.append(dict(date=event_day, ts_code=code, reason='event_date_off_calendar', detail=event['event_id'] + ':' + field))
                    valid = False
                if pd.notna(listing) and lifecycle_state(event_day, listing, delisting) != 'listed' and calendar[0] <= event_day <= calendar[-1]:
                    errors.append(dict(date=event_day, ts_code=code, reason='event_outside_listed_lifecycle', detail=event['event_id'] + ':' + field))
                    valid = False
            for field in ['record', 'ex', 'cash_pay', 'stock_pay', 'list_date']:
                if pd.notna(event[field]):
                    equity_dates.append((event[field], event['event_id'], field))
            if valid:
                ex_events[event['ex']].append(event['event_id'])
            else:
                registry.loc[registry.event_id.eq(event['event_id']), 'allowed'] = False
        rows, gap_started = [], False
        for date in calendar:
            state = lifecycle_state(date, listing, delisting)
            quote = records.get(date)
            has_quote = quote is not None
            daily_reasons = []
            equal, ids = None, []
            values = evidence.get((date, code), [])
            is_suspended = any(value[0] == 'S' for value in values)
            suspend_type = '|'.join(value[0] for value in values)
            suspend_timing = '|'.join(value[1] for value in values)
            reference_text = '' if not has_quote else quote['pre_close_text']
            old_date, old_text = prior_date, prior_text
            def fail(reason, detail=''):
                daily_reasons.append(reason)
                errors.append(dict(date=date, ts_code=code, reason=reason, detail=detail))
            if state == 'invalid_lifecycle':
                fail('invalid_lifecycle')
                decision = 'stop'
            elif state in ('pre_listing', 'post_delisting'):
                if has_quote:
                    fail('quote_outside_lifecycle', state)
                decision = 'outside_lifecycle' if not daily_reasons else 'stop'
            elif state == 'scheduled_delisting':
                if any(event_day == date for event_day, _, _ in equity_dates):
                    fail('delisting_equity_date_conflict')
                decision = 'zero_recovery_write_off' if not daily_reasons else 'stop'
            elif not has_quote:
                if not is_suspended:
                    fail('missing_quote_without_daily_suspension')
                if prior_close is None:
                    fail('missing_prior_close_for_stale_mark')
                crossed = [(d, identity, field) for d, identity, field in equity_dates
                           if (pd.isna(prior_date) or prior_date < d) and d <= date]
                if crossed:
                    fail('equity_date_in_missing_quote_interval', '|'.join(identity + ':' + field for _, identity, field in crossed))
                gap_started = True
                decision = 'stale_mark_registered_suspension' if not daily_reasons else 'stop'
            else:
                close = decimal_price(quote['close_text'])
                reference = decimal_price(reference_text)
                if close is None:
                    fail('invalid_close_text')
                if reference is None:
                    fail('invalid_pre_close_text')
                for field in ('open', 'close', 'vol', 'amount'):
                    if field not in quote:
                        continue
                    try:
                        numeric = float(quote[field])
                        okay = math.isfinite(numeric) and (numeric > 0 if field in ('open', 'close') else numeric >= 0)
                        if field == 'close' and close is not None:
                            okay = okay and numeric == float(close)
                    except (TypeError, ValueError, OverflowError):
                        okay = False
                    if not okay:
                        fail('invalid_quote_' + field)
                if gap_started:
                    crossed = [(d, identity, field) for d, identity, field in equity_dates
                               if (pd.isna(prior_date) or prior_date < d) and d <= date]
                    if crossed:
                        fail('equity_date_in_missing_quote_interval', '|'.join(identity + ':' + field for _, identity, field in crossed))
                if prior_close is None:
                    if date == listing and close is not None:
                        decision = 'listing_initial_anchor'
                    else:
                        fail('missing_prior_close_for_reference')
                        decision = 'stop'
                else:
                    equal = reference == prior_close if reference is not None else None
                    ids = ex_events.get(date, [])
                    if reference is not None and not equal and not ids:
                        fail('unexplained_reference_change')
                    decision = 'registered_action_reference' if ids else 'continuous_reference'
                if daily_reasons:
                    decision = 'stop'
                # Continue the inventory from each actual close even after a
                # failure. This never authorizes trading or repairs past data.
                if close is not None:
                    prior_date, prior_close, prior_text = date, close, str(quote['close_text'])
                gap_started = False
            rows.append((date, code, state, has_quote, old_date, old_text, reference_text,
                         equal, '|'.join(ids), decision, '|'.join(daily_reasons), suspend_type, suspend_timing))
        daily_parts.append(pd.DataFrame(rows, columns=DAILY_COLUMNS))
        if code in adj_groups:
            a = adj_groups[code].copy()
            a['trade_date'] = a.trade_date.map(day)
            field = 'orig_adj_factor' if 'orig_adj_factor' in a else 'adj_factor'
            a = a.loc[a.trade_date.isin(calendar)].sort_values('trade_date')
            previous = None
            for item in a[['trade_date', field]].itertuples(index=False, name=None):
                d, factor = item
                try:
                    factor = float(factor)
                except (TypeError, ValueError):
                    factor = np.nan
                if previous is not None and (not math.isfinite(factor) or factor != previous[1]):
                    valid = math.isfinite(factor) and math.isfinite(previous[1]) and previous[1] > 0
                    change = factor / previous[1] - 1 if valid else np.nan
                    explained = any(previous[0] < event['ex'] <= d for event in items)
                    alerts.append((d, code, previous[0], previous[1], factor, change,
                                   bool(abs(change) > .005) if valid else False, explained, False))
                previous = (d, factor)
        if code_index % 250 == 0 or code_index == len(codes):
            print(f'Reference guard securities {code_index}/{len(codes)}; failures inventoried {len(errors)}', flush=True)
    daily = pd.concat(daily_parts, ignore_index=True)
    for col in ['ts_code', 'lifecycle', 'decision', 'reason', 'suspend_type', 'suspend_timing']:
        daily[col] = daily[col].astype('category')
    failures = pd.DataFrame(errors, columns=FAILURE_COLUMNS)
    if not failures.empty:
        failures = failures.sort_values(['date', 'ts_code', 'reason'], kind='stable', na_position='last').reset_index(drop=True)
    summary = dict(passed=failures.empty, failure_count=len(failures), fixed_security_count=len(codes),
                   account_sessions=len(calendar), security_session_rows=len(daily),
                   calendar_start=_stamp(calendar[0]), calendar_end=_stamp(calendar[-1]),
                   seed_session=_stamp(previous_session), lifecycle_counts=daily.lifecycle.value_counts().to_dict(),
                   decision_counts=daily.decision.value_counts().to_dict(),
                   failure_reason_counts=dict(Counter(failures.reason)), event_count=len(registry),
                   accounts_started=0, performance_computed=False,
                   economic_terms_certified=False,
                   enable_status='blocked_by_unverified_data_and_forward_validation',
                   input_fingerprint=input_fingerprint(bars, calendar, universe, actions, suspensions, rights,
                                                       codes, seed_bars, source_hashes, full_calendar))
    return dict(summary=summary, daily=daily, failures=failures,
                adjustment_alerts=pd.DataFrame(alerts, columns=ALERT_COLUMNS), event_registry=registry)
