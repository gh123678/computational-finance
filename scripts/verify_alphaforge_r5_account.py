"""Independent r5 account audit, rebuilt from raw quotes and frozen terms.

This module neither imports the account/guard nor reuses Ledger or execution.
It returns audit records; the exclusive runner owns persistence and manifests.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import json
import math
from pathlib import Path
import re

import pandas as pd


_CASH_ADDITIONS = frozenset({
    ('002661.SZ', '2018-03-30'), ('603033.SH', '2018-05-21'),
    ('002729.SZ', '2018-05-24'), ('002637.SZ', '2018-05-30'),
    ('002431.SZ', '2018-06-11'), ('603939.SH', '2018-06-14'),
    ('002778.SZ', '2018-06-15'), ('002408.SZ', '2018-06-20'),
    ('002738.SZ', '2018-06-22'), ('600122.SH', '2018-06-25'),
    ('000967.SZ', '2018-06-29'), ('002573.SZ', '2018-07-11'),
    ('603315.SH', '2018-07-16'), ('002437.SZ', '2018-07-18'),
    ('601390.SH', '2018-07-18'), ('000426.SZ', '2018-08-16'),
    ('600282.SH', '2019-04-26'), ('603315.SH', '2019-06-27'),
    ('600483.SH', '2019-07-29'), ('600267.SH', '2020-07-15'),
})
_ORIGINAL_ALLOW = frozenset({('000756.SZ', '2018-01-26'),
    ('600309.SH', '2018-01-26'), ('600226.SH', '2018-03-26')})


def _known_state(code, date, evidence):
    """Reconstruct date-only status availability without the overlay selector."""
    day = _day(date)
    candidates = [row for row in evidence.get('status_events', ())
                  if row['code'] == code and row['known_date'] <= day
                  and row['effective_date'] <= day]
    if not candidates:
        return None
    row = deepcopy(max(candidates, key=lambda r: (r['known_date'], r['effective_date'])))
    known = row['known_date'] < day or row.get('publication_time_intraday_certified', False)
    row.update(pre_open_known=known, usable_for_missing_quote=known and row['state'] in
               {'suspended_listing', 'suspended_trading', 'delisted'})
    return row


def _distribution(action, date, evidence):
    """Select raw versions independently; a future cancellation cannot erase a record."""
    rows = [r for r in evidence.get('event_versions', ())
            if r['code'] == action.code and _day(r['ex']) == _day(action.ex)
            and pd.Timestamp(r['known_date']) <= date]
    base = dict(asdict(action), role='original_distribution', version='original',
                known_date=None, ordinary=True, apply_distribution=True,
                reference_explained=bool(action.cash_per_share or action.stock_per_share),
                unsupported_special=False, pre_open_known=True, sources=[])
    if not rows:
        return base
    row = deepcopy(max(rows, key=lambda r: (r['known_date'], str(r['version']))))
    original = row.get('original_action')
    assert original is not None, ('Version lacks original Action binding', action.code)
    _equal(_normal(original), _normal(asdict(action)), ('Version original Action binding', action.code))
    base.update(row)
    for key in ('record', 'ex', 'cash_pay', 'stock_pay'):
        base[key] = pd.to_datetime(base[key], errors='coerce')
    for key in ('cash_per_share', 'stock_per_share', 'taxable_bonus_per_share'):
        base[key] = float(base[key])
    base['pre_open_known'] = (pd.Timestamp(row['known_date']) < date or
        bool(row.get('publication_time_intraday_certified', False)))
    return base


def _rights_stage(issue, date, evidence, stage):
    """Read personal quota and listing evidence as of the relevant stage only."""
    rows = [r for r in evidence.get('rights_stages', ()) if r['code'] == issue.code
            and _day(r['record']) == _day(issue.record) and _day(r['ex']) == _day(issue.ex)]
    assert len(rows) <= 1, ('Duplicate staged rights evidence', issue.code)
    reserved = (issue.code, _day(issue.record)) in {
        ('000977.SZ', '2020-03-10'), ('600999.SH', '2020-07-09')}
    source_required = bool(issue.price is not None and re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)', issue.code))
    if not rows and not source_required:
        return dict(code=issue.code, record=issue.record, ex=issue.ex, price=issue.price,
            quota_ratio=issue.ratio, market_ex_ratio=None, list_date=issue.list_date,
            terms_known_date=None, result_known_date=None, listing_known_date=None,
            stage_usable=True, reason='', sources=[], personal_actual_allocation_certified=False)
    if not rows:
        raise AssertionError(('Missing staged rights evidence', issue.code, date, stage))
    row = rows[0]
    original = row.get('original_subscription_terms')
    if issue.price is not None:
        assert original is not None, ('Original rights terms lack binding', issue.code)
    if original is not None:
        for field in ('price', 'ratio', 'list_date'):
            actual, expected = getattr(issue, field), original[field]
            same = (_day(actual) == _day(expected) if field == 'list_date' else
                    Decimal(str(actual)) == Decimal(str(expected)))
            assert same, ('Original rights terms were modified', issue.code, field)
    assert bool(row.get('original_subscription_authorized')) == (issue.price is not None), (
        'New subscription authorization', issue.code)
    # A later publication never supplies an earlier phase's field or date.
    def sources(role):
        return [s for s in row.get('sources', ()) if s.get('role') == role]
    def usable(field, role):
        known = row.get(field)
        if known is None or pd.isna(known):
            return False
        assert sources(role), ('Stage date lacks matching source', issue.code, field)
        assert all(_day(s.get('known_date')) == _day(known) for s in sources(role)), (
            'Stage source publication conflict', issue.code, field)
        return pd.Timestamp(known) < date or (pd.Timestamp(known) == date and
            all(s.get('publication_time_intraday_certified', False) for s in sources(role)))
    terms = usable('terms_known_date', 'issuance')
    result = usable('result_known_date', 'actual_result')
    listing = usable('listing_known_date', 'listing')
    subscribed = issue.price is not None or issue.ratio is not None
    if reserved and subscribed and issue.code == '000977.SZ':
        assert Decimal(str(row['quota_ratio'])) == Decimal('.12'), '000977 personal quota is not market ratio'
        assert Decimal(str(row['market_ex_ratio'])) == Decimal('.1177945'), '000977 market reference ratio changed'
        assert Decimal(str(row['price'])) == Decimal('12.92'), '000977 issue price changed'
    if reserved and subscribed and issue.code == '600999.SH':
        assert Decimal(str(row['quota_ratio'])) == Decimal('.3') and Decimal(str(row['price'])) == Decimal('7.46'), '600999 fixed subscription terms changed'
    allowed = True if not subscribed else terms if stage in ('record', 'subscription') else listing
    return dict(code=issue.code, record=issue.record, ex=issue.ex,
        price=float(row['price']) if subscribed and terms else None,
        quota_ratio=float(row['quota_ratio']) if subscribed and terms else None,
        market_ex_ratio=row.get('market_ex_ratio') if result else None,
        list_date=pd.Timestamp(row['list_date']) if subscribed and listing and row.get('list_date') else None,
        terms_known_date=row.get('terms_known_date') if terms else None,
        result_known_date=row.get('result_known_date') if result else None,
        listing_known_date=row.get('listing_known_date') if listing else None,
        stage_usable=allowed, reason='' if allowed else 'rights_stage_source_not_known_before_open',
        sources=[deepcopy(s) for s in row.get('sources', ()) if pd.Timestamp(s['known_date']) < date
                 or (pd.Timestamp(s['known_date']) == date and s.get('publication_time_intraday_certified', False))],
        personal_actual_allocation_certified=False)


def _read(folder, name):
    path = Path(folder) / (name + '.csv')
    if not path.exists():
        raise AssertionError('Missing account artifact: ' + str(path))
    try:
        frame = pd.read_csv(path, float_precision='round_trip')
    except pd.errors.EmptyDataError:
        frame = pd.DataFrame()
    if 'date' in frame:
        frame['date'] = pd.to_datetime(frame.date)
    return frame


def _day(value):
    parsed = pd.to_datetime(value, errors='coerce')
    return None if pd.isna(parsed) else pd.Timestamp(parsed).strftime('%Y-%m-%d')


def _normal(value, key=''):
    if key in ('source', 'stage_sources', 'cancellation_source') and isinstance(value, str) and value.startswith('['):
        try:
            return _normal(json.loads(value))
        except json.JSONDecodeError:
            pass
    if isinstance(value, dict):
        return {k: _normal(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normal(v) for v in value]
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if key in ('record', 'ex', 'cash_pay', 'stock_pay', 'list_date', 'date'):
        return _day(value)
    if isinstance(value, (pd.Timestamp,)):
        return _day(value)
    return value


def _equal(actual, expected, context):
    if expected is None or (not isinstance(expected, (dict, list)) and pd.isna(expected)):
        assert actual is None or pd.isna(actual) or actual == '', (context, actual)
    elif isinstance(expected, str) and expected == '':
        assert actual == '' or pd.isna(actual), (context, actual)
    elif isinstance(expected, bool):
        assert bool(actual) == expected, context
    elif isinstance(expected, (int, float)):
        assert pd.notna(actual) and math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=1e-6), (context, actual, expected)
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), (context, actual, expected)
        for key, value in expected.items():
            _equal(actual[key], value, (context, key))
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), context
        for index, (left, right) in enumerate(zip(actual, expected)):
            _equal(left, right, (context, index))
    else:
        assert str(actual) == str(expected), (context, actual, expected)


def _group(frame):
    return {d: g.to_dict('records') for d, g in frame.groupby('date', sort=False)} if len(frame) else {}


def _terms(item, entitled):
    return _normal(dict(asdict(item), entitled_shares=entitled))


def _sorted_payloads(values):
    return sorted((_normal(v) for v in values), key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))


def _independent_stop(error):
    """Translate our own failed invariant to a producer reason, never vice versa."""
    payload = error.args[0] if error.args else ''
    detail = payload[0] if isinstance(payload, tuple) and payload else str(payload)
    reasons = {
        'Unsupported special reorganization': 'unsupported_special_reorganization_exposure_or_plan',
        'Rights record source unavailable as of date': 'rights_record_source_not_usable_asof',
        'Rights subscription source unavailable as of date': 'rights_subscription_source_not_usable_asof',
        'Distribution source unavailable before open': 'distribution_source_not_usable_preopen',
        'Listing source unavailable before release': 'rights_listing_source_not_usable_before_execution',
        'Unreviewed ordinary action across gap': 'unreviewed_distribution_across_quote_gap',
        'Special or unsourced ordinary action': 'special_or_unsourced_distribution_across_quote_gap',
        'Ordinary action not known by gap day': 'distribution_source_not_known_by_gap_day',
        'Nonadjacent distribution record/ex': 'nonadjacent_distribution_record_ex',
        'Unapplied cash entitlement without prior record': 'unapplied_cash_entitlement_without_prior_record',
        'Unquoted rights equity obligation': 'rights_obligation_across_unquoted_equity_date',
        'Post-delisting price exposure': 'price_exposure_or_plan_outside_lifecycle',
        'Same-day official state time uncertified': 'official_state_publication_or_boundary_uncertain',
        'Quote conflicts with official nontrade state': 'quote_conflicts_with_official_nontrade_state',
        'Exposed quote lacks prior raw close': 'missing_actual_prior_quote_for_exposure_or_entry',
        'Unexplained held quote gap': 'missing_quote_without_asof_nontrade_evidence',
        'Unknown reference break': 'unexplained_reference_change',
        'Missing formation anchor': 'entry_formation_anchor_missing',
        'Unexpected quote in gap': 'unexpected_quote_in_gap_index',
        'Invalid raw close or pre_close': 'invalid_raw_close_or_pre_close',
        'Raw close text and numeric conflict': 'raw_text_numeric_close_conflict',
        'Inconsistent OHLC': 'inconsistent_OHLC',
        'Delisting equity date conflict': 'delisting_equity_date_conflict',
        'Price exposure outside lifecycle': 'price_exposure_or_plan_outside_lifecycle',
    }
    if detail == 'Missing staged rights evidence' and isinstance(payload, tuple):
        return 'rights_' + payload[3] + '_source_not_usable_asof', payload[1]
    if detail == 'Cross-gap frozen terms' and isinstance(payload, tuple):
        field = payload[2]
        category = 'terms' if field in ('cash_per_share', 'stock_per_share', 'taxable_bonus_per_share') else 'date'
        return 'distribution_source_' + category + '_conflict', payload[1]
    if detail == 'Invalid quote field' and isinstance(payload, tuple):
        return 'invalid_quote_' + payload[3], payload[1]
    return reasons.get(detail), payload[1] if isinstance(payload, tuple) and len(payload) > 1 else None


def _fee(notional, side, date, config):
    if not notional or config.zero_trading_costs:
        return 0.
    transfer = .00002 if date < pd.Timestamp('2022-04-29') else .00001
    sell_tax = .001 if date < pd.Timestamp('2023-08-28') else .0005
    return round(max(config.minimum_commission, config.commission * notional)
                 + transfer * notional + (sell_tax * notional if side == 'sell' else 0.), 2)


def _fill(side, requested, cash, held, sellable, quote, adv, date, config, suspended):
    """Independent order arithmetic, including lot, cash and T+1 rejection."""
    rejected = dict(status='rejected', reason='', shares=0, price=0., fee=0., cash_after=cash,
                    shares_after=held, sellable_after=sellable)
    def reject(reason):
        return dict(rejected, reason=reason)
    if quote is None:
        return reject('suspended')
    if suspended or quote.get('vol', 0) <= 0:
        return reject('suspended')
    raw, up, down = [float(quote.get(k, float('nan'))) for k in ('open', 'up_limit', 'down_limit')]
    if any(not math.isfinite(x) or x <= 0 for x in (raw, up, down, adv)):
        return reject('missing_or_invalid_market_data')
    if down > up or raw < down - 1e-8 or raw > up + 1e-8:
        return reject('inconsistent_price_limits')
    if (side == 'buy' and raw >= up - 1e-8) or (side == 'sell' and raw <= down + 1e-8):
        return reject('price_limit')
    bps = 0. if config.zero_trading_costs else config.slippage_bps
    price = raw * (1 + bps / 10000 * (1 if side == 'buy' else -1))
    price = float(Decimal(str(price)).quantize(Decimal('.01'), rounding=ROUND_CEILING if side == 'buy' else ROUND_FLOOR))
    if price > up + 1e-8 or price < down - 1e-8 or price <= 0:
        return reject('slippage_outside_limits')
    quantity = min(requested, int(adv * config.participation / price))
    if side == 'buy':
        quantity = min(quantity, int(cash / price)) // 100 * 100
        while quantity and round(quantity * price, 2) + _fee(quantity * price, side, date, config) > cash + 1e-8:
            quantity -= 100
    else:
        quantity = min(quantity, sellable)
        if quantity != held:
            quantity = quantity // 100 * 100
    if quantity <= 0:
        return reject('cash_capacity_lot_or_t1')
    notional = round(quantity * price, 2)
    fee = _fee(notional, side, date, config)
    new_cash = round(cash + (notional if side == 'sell' else -notional) - fee, 2)
    if new_cash < 0:
        return reject('insufficient_cash_for_fee')
    return dict(status='filled', reason='', shares=quantity, price=price, fee=fee,
                cash_after=new_cash, shares_after=held + quantity * (1 if side == 'buy' else -1),
                sellable_after=sellable - (quantity if side == 'sell' else 0))


def verify_account(folder, bars, calendar, targets, actions, rights, universe, suspensions,
                   evidence, config, *, completed=False):
    """Audit the complete prefix, not an uncompleted six-account experiment.

    A failed account must retain failure.json and an account_state.json for its
    last completed close; any intraday failure_state is deliberately excluded.
    """
    folder = Path(folder)
    tables = {name: _read(folder, name) for name in
              ('nav', 'orders', 'holdings', 'corporate_events', 'reference_guard', 'obligations')}
    nav, orders, holdings, events, trace, obligations = [tables[k] for k in tables]
    calendar = pd.DatetimeIndex(calendar)
    assert not calendar.has_duplicates and calendar.is_monotonic_increasing
    assert 'date' in nav and not nav.date.duplicated().any()
    actual_dates = pd.DatetimeIndex(nav.date)
    assert actual_dates.equals(calendar[:len(nav)]), 'Account is not a complete calendar prefix'
    if completed:
        assert actual_dates.equals(calendar) and not (folder / 'failure.json').exists()
    else:
        assert (folder / 'failure.json').exists(), 'Incomplete account needs real failure evidence'
    for name in ('orders', 'holdings', 'corporate_events', 'obligations'):
        frame = tables[name]
        assert not len(frame) or frame.date.isin(actual_dates).all(), 'Uncompleted-day artifact: ' + name
    assert not len(holdings) or not holdings.duplicated(['date', 'ts_code']).any()
    bars = bars.copy()
    bars['trade_date'] = pd.to_datetime(bars.trade_date)
    assert not bars.duplicated(['trade_date', 'ts_code']).any()
    market = {d: g.set_index('ts_code').to_dict('index') for d, g in bars.loc[bars.trade_date.isin(calendar)].groupby('trade_date')}
    histories = {c: g.set_index('trade_date')[['close','close_text']].sort_index() for c, g in bars.groupby('ts_code')}
    amount = bars.loc[bars.trade_date.isin(calendar)].pivot(index='trade_date', columns='ts_code', values='amount').reindex(calendar)
    adv = (amount.rolling(20, min_periods=1).mean().shift(1) * 1000).to_dict('index')
    plans = {pd.Timestamp(d): g.set_index('ts_code').target_weight.to_dict() for d, g in targets.groupby('execution_date')}
    target_dates = {pd.Timestamp(d) for d in targets.execution_date}
    assert not len(orders) or orders.date.isin(target_dates).all()
    suspension_set = set()
    if suspensions is not None:
        if isinstance(suspensions, pd.DataFrame):
            suspension_set = {(pd.Timestamp(r.trade_date), r.ts_code) for r in suspensions.itertuples() if r.suspend_type == 'S'}
        else:
            suspension_set = {(pd.Timestamp(d), c) for d, c in suspensions}
    metadata = universe.set_index('ts_code').to_dict('index')
    delistings = {c: pd.to_datetime(m.get('delist_date'), errors='coerce') for c,m in metadata.items()}
    delistings = {c:d for c,d in delistings.items() if pd.notna(d)}
    ordinary_allow = {(r['code'],pd.Timestamp(r['ex'])):r for r in evidence['ordinary_actions']}
    event_days, order_days, holding_days, obligation_days = map(_group, (events, orders, holdings, obligations))
    actions, rights = tuple(actions), tuple(rights)
    if evidence.get('schema_version') == 5:
        keys = [(r['code'], _day(r['ex'])) for r in evidence['ordinary_actions']]
        assert len(keys) == 23 and set(keys) == _CASH_ADDITIONS | _ORIGINAL_ALLOW, 'Independent 23-source-key scope changed'
        for row in evidence['ordinary_actions']:
            bound = [a for a in actions if a.code == row['code'] and _day(a.ex) == _day(row['ex'])]
            assert len(bound) == 1, ('Approved source Action missing or duplicated', row['code'], row['ex'])
            for field, expected in asdict(bound[0]).items():
                if field in ('cash_per_share', 'stock_per_share', 'taxable_bonus_per_share'):
                    assert Decimal(str(row[field])) == Decimal(str(expected)), ('Approved source frozen amount', row['code'], field)
                else:
                    _equal(_normal(row.get(field), field), _normal(expected, field), ('Approved source frozen field', row['code'], field))
            assert row['known_date'] < row['record'] and row.get('sources'), ('Approved source phase unavailable', row['code'])
            if (row['code'], _day(row['ex'])) in _CASH_ADDITIONS:
                assert Decimal(str(row['stock_per_share'])) == 0 and Decimal(str(row['taxable_bonus_per_share'])) == 0, 'Cash-only approval cannot waive a stock or tax component'
    actions_by_code,rights_by_code=defaultdict(list),defaultdict(list)
    for action in actions:
        actions_by_code[action.code].append(action)
    for issue in rights:
        rights_by_code[issue.code].append(issue)
    positions, locked = defaultdict(int), defaultdict(int)
    prices, entitlements, right_entitlements, applied = {}, {}, {}, set()
    cancelled, scenario_entitlements = set(), []
    pending = []
    cash = float(config.initial_cash)
    boundaries, daily_records = [], []
    previous_nav = None

    def share_scope():
        return ({c for c, n in positions.items() if n} | {p['code'] for p in pending if p['shares']}
                | {a.code for a, n in entitlements.items() if n and a not in applied and a not in cancelled and a.stock_per_share}
                | {r.code for r, n in right_entitlements.items() if n and r.price is not None})

    def state_at(code, date):
        return _known_state(code, date, evidence)

    def effective_actions(code, left, date):
        return [(a, _distribution(a, date, evidence)) for a in actions_by_code[code]
                if any(pd.notna(d) and left < d <= date for d in
                       (a.record, a.ex, a.cash_pay, a.stock_pay))
                and _distribution(a, date, evidence)['apply_distribution']]

    def check_special(code, date, *, planned_signal=None):
        exposed = positions[code] or any(p['code'] == code and (p['cash'] or p['shares']) for p in pending)
        exposed = exposed or any(a.code == code and n and a not in applied and a not in cancelled
                                 for a, n in entitlements.items())
        exposed = exposed or any(r.code == code and n for r, n in right_entitlements.items())
        for action in actions_by_code[code]:
            view = _distribution(action, date, evidence)
            phases = [pd.Timestamp(view[k]) for k in ('record', 'ex', 'stock_pay') if pd.notna(view[k])]
            history = histories.get(code)
            pos = -1 if history is None else history.index.searchsorted(date) - 1
            left = None if pos < 0 else history.index[pos]
            touched = exposed and any(phase == date or (left is not None and left < phase <= date)
                                      for phase in phases)
            if planned_signal is not None:
                touched = touched or any(planned_signal < phase <= date for phase in phases)
            assert not (touched and not view['pre_open_known']), ('Distribution source unavailable before open', code, date)
            assert not (touched and view['unsupported_special']), ('Unsupported special reorganization', code, date)

    def check_rights_stage(issue, date, stage):
        view = _rights_stage(issue, date, evidence, stage)
        assert view['stage_usable'], ('Rights ' + stage + ' source unavailable as of date', issue.code, date)
        return view

    def rights_terms(issue, entitled, date):
        payload = dict(asdict(issue), entitled_shares=entitled)
        view = _rights_stage(issue, date, evidence, 'record')
        payload.update(price=view['price'], ratio=view['quota_ratio'], list_date=view['list_date'],
            market_ex_ratio=view['market_ex_ratio'], terms_known_date=view['terms_known_date'],
            result_known_date=view['result_known_date'], listing_known_date=view['listing_known_date'],
            original_source=issue.source, stage_sources=source_json(view))
        return _normal(payload)

    def approved_ordinary(action,date):
        approved=ordinary_allow.get((action.code,action.ex))
        assert approved is not None, ('Unreviewed ordinary action across gap',action.code,date)
        assert (approved.get('ordinary',False) and not approved.get('special_distribution',False)
                and approved.get('sources')),('Special or unsourced ordinary action',action.code,date)
        assert pd.Timestamp(approved['known_date'])<=date,('Ordinary action not known by gap day',action.code,date)
        for key,value in asdict(action).items():
            if key in ('cash_per_share','stock_per_share','taxable_bonus_per_share'):
                assert Decimal(str(approved.get(key)))==Decimal(str(value)),('Cross-gap frozen terms',action.code,key)
            else:
                _equal(_normal(approved.get(key),key),_normal(value,key),('Cross-gap frozen terms',action.code,key))
        locations=calendar.get_indexer([action.record,action.ex])
        assert locations[0]>=0 and locations[1]==locations[0]+1,('Nonadjacent distribution record/ex',action.code,date)

    def check_cash_obligations(date, only_code=None):
        """Unexecuted cash rights need source checks, never a stock valuation.

        An already created pending cash item is fully determined by its original
        record/ex event and settlement date. It does not create a quote duty.
        """
        price_codes=share_scope()
        for action,entitled in entitlements.items():
            if only_code is not None and action.code != only_code:
                continue
            if not entitled or action in applied or action in cancelled or action.code in price_codes:
                continue
            if action.code in market.get(date,{}):
                continue
            history=histories.get(action.code)
            pos=-1 if history is None else history.index.searchsorted(date)-1
            assert pos>=0,('Unapplied cash entitlement without prior record',action.code,date)
            left=history.index[pos]
            if any(pd.notna(d) and left<d<=date for d in (action.record,action.ex,action.cash_pay)):
                approved_ordinary(action,date)

    def check_exposure(code, date):
        check_special(code, date)
        quote = market.get(date, {}).get(code)
        meta = metadata[code]
        assert pd.Timestamp(meta['list_date']) <= date, ('Price exposure outside lifecycle', code, date)
        delisting = delistings.get(code,pd.NaT)
        if pd.notna(delisting) and date == delisting:
            assert not any(a.record == date or a.ex == date for a in actions_by_code[code]), (
                'Delisting equity date conflict', code, date)
            return
        assert pd.isna(delisting) or date < delisting, ('Post-delisting price exposure', code, date)
        official = state_at(code, date)
        assert official is None or official.get('pre_open_known',True), ('Same-day official state time uncertified',code,date)
        if quote is not None:
            assert official is None or official.get('state') in ('listed','delisting_board'), ('Quote conflicts with official nontrade state', code, date)
            for field in ('open', 'high', 'low', 'close', 'vol', 'amount'):
                try:
                    value = float(quote[field])
                    valid = math.isfinite(value) and (value > 0 if field in ('open', 'high', 'low', 'close') else value >= 0)
                except (KeyError, ValueError, TypeError):
                    valid = False
                assert valid, ('Invalid quote field', code, date, field)
            for field in ('close_text', 'pre_close_text'):
                try:
                    valid = isinstance(quote[field], str)
                    value = Decimal(quote[field]) if valid else None
                    valid = valid and value.is_finite() and value > 0
                except (InvalidOperation, ValueError, TypeError, KeyError):
                    valid = False
                assert valid, ('Invalid raw close or pre_close', code, date)
            assert float(Decimal(quote['close_text'])) == quote['close'], ('Raw close text and numeric conflict', code, date)
            assert quote['low']<=min(quote['open'],quote['close'])<=max(quote['open'],quote['close'])<=quote['high'], ('Inconsistent OHLC', code, date)
        history = histories[code]
        pos = history.index.searchsorted(date) - 1
        assert pos >= 0, ('Exposed quote lacks prior raw close', code, date)
        prior = history.iloc[pos]
        left = history.index[pos]
        gap_dates = list(calendar[(calendar>left)&(calendar<date)]) + ([] if quote is not None else [date])
        for missing in gap_dates:
            assert code not in market.get(missing,{}), ('Unexpected quote in gap',code,missing)
            state = state_at(code,missing)
            assert state is None or state.get('pre_open_known',True), ('Same-day official state time uncertified',code,missing)
            assert (missing,code) in suspension_set or (state is not None and state.get('usable_for_missing_quote',False)), ('Unexplained held quote gap',code,missing)
        interval_actions = [a for a, _ in effective_actions(code, left, date)]
        interval_rights = [r for r in rights_by_code[code] if any(pd.notna(d) and left<d<=date
            for d in (r.record, r.ex, _rights_stage(r, date, evidence, 'listing')['list_date']))]
        if gap_dates:
            for action in interval_actions:
                approved_ordinary(action,date)
            for issue in interval_rights:
                stage = _rights_stage(issue, date, evidence, 'listing')
                observed_ex = issue.ex in histories[code].index
                listing_only = (issue.price is not None and stage['quota_ratio'] is not None and stage['list_date'] is not None
                    and stage['stage_usable']
                    and issue.ex<=left and observed_ex
                    and not any(left<d<=date for d in (issue.record,issue.ex)))
                assert listing_only or (quote is not None and issue.ex==date and issue.record<=left), ('Unquoted rights equity obligation',code,date)
        if quote is not None:
            crossed_actions = [a for a in interval_actions if left < a.ex <= date]
            crossed_rights = [r for r in interval_rights if left < r.ex <= date]
            assert Decimal(quote['pre_close_text']) == Decimal(prior.close_text) or crossed_actions or crossed_rights, ('Unknown reference break', code, date)

    def check_planned(date, only_code=None):
        planned_rows=targets.loc[pd.to_datetime(targets.execution_date).eq(date)]
        for target in planned_rows.itertuples():
            if only_code is not None and target.ts_code != only_code:
                continue
            if target.target_weight<=0:
                continue
            check_special(target.ts_code, date, planned_signal=pd.Timestamp(target.signal_date))
            meta=metadata[target.ts_code]
            assert pd.Timestamp(meta['list_date'])<date
            delisting=delistings.get(target.ts_code,pd.NaT)
            assert pd.isna(delisting) or date<delisting
            state=state_at(target.ts_code,date)
            if target.ts_code not in market.get(date,{}):
                # An empty-position missing execution quote is rejected before
                # it can transact; date-only publication cannot authorize it.
                continue
            assert state is None or state.get('pre_open_known',True), ('Same-day official state time uncertified',target.ts_code,date)
            assert state is None or state.get('state') in ('listed','delisting_board')
            signal=pd.Timestamp(target.signal_date)
            assert signal<date and target.ts_code in market.get(signal,{}), ('Missing formation anchor',date,target.ts_code)
            for bridge_day in calendar[(calendar>signal)&(calendar<=date)]:
                check_exposure(target.ts_code,bridge_day)

    def source_json(view):
        return json.dumps(view.get('sources', []), ensure_ascii=False, default=str)

    def prepare_day(date):
        expected = []
        for action in actions:
            if action.code != '600781.SH' or _day(action.ex) != '2019-07-22':
                continue
            view = _distribution(action, date, evidence)
            if (view['apply_distribution'] or view['unsupported_special']
                    or not view['pre_open_known'] or action in cancelled):
                continue
            entitled = entitlements.pop(action, 0)
            cancelled.add(action)
            for item in scenario_entitlements:
                if item['code'] == action.code and item['ex_date'] == _day(action.ex):
                    item.update(status='cancelled', cancelled_date=_day(date),
                        cancellation_known_date=view['known_date'], cancellation_source=source_json(view))
            expected.append(dict(date=date, code=action.code, event='distribution_cancelled',
                entitled_shares=entitled, record_date=_day(action.record), ex_date=_day(action.ex),
                version=view['version'], known_date=view['known_date'], source=source_json(view),
                reason='known_plan_cancelled_before_execution'))
        for item in pending:
            if not item.get('rights_record') or item.get('stock_pay') is not None:
                continue
            issue = next((r for r in rights if r.code == item['code'] and _day(r.record) == item['rights_record']), None)
            assert issue is not None, 'Pending rights have no original source event'
            view = _rights_stage(issue, date, evidence, 'listing')
            if view['list_date'] is None:
                continue
            assert view['stage_usable'] and pd.Timestamp(view['listing_known_date']) < view['list_date'], (
                'Listing source unavailable before release', issue.code, date)
            item.update(stock_pay=view['list_date'], listing_known_date=view['listing_known_date'])
            expected.append(dict(date=date, code=issue.code, event='rights_listing_date_known',
                list_date=_day(view['list_date']), listing_known_date=view['listing_known_date'],
                source=source_json(view), stage_sources=source_json(view), original_source=issue.source,
                record_date=_day(issue.record), ex_date=_day(issue.ex)))
        return expected

    def reconstruct_day(dayrow, *, compare=True):
        nonlocal cash, pending, prices, previous_nav
        date = dayrow['date']
        daily = market.get(date, {})
        expected_events = prepare_day(date)
        economic = ({p['code'] for p in pending if p['cash'] or p['shares']} |
            {a.code for a,n in entitlements.items() if n and a not in applied and a not in cancelled} |
            {r.code for r,n in right_entitlements.items() if n})
        planned = {c for c,w in plans.get(date, {}).items() if w > 0}
        for code in sorted(share_scope() | economic | planned):
            signal_rows = targets.loc[pd.to_datetime(targets.execution_date).eq(date) & targets.ts_code.eq(code)]
            signal = pd.Timestamp(signal_rows.signal_date.iloc[0]) if code in planned else None
            check_special(code, date, planned_signal=signal)
            if code in share_scope():
                check_exposure(code, date)
            elif code in economic:
                check_cash_obligations(date, code)
            if code in planned:
                check_planned(date, code)
        locked.clear()
        for issue in rights:
            if issue.ex == date and right_entitlements.get(issue, 0):
                check_rights_stage(issue, date, 'subscription')
        for action in actions:
            if action.ex != date:
                continue
            view = _distribution(action, date, evidence)
            if not view['apply_distribution']:
                continue
            assert action not in applied
            applied.add(action)
            entitled = entitlements.get(action, 0)
            if action.code in prices:
                prices[action.code] = (prices[action.code] - action.cash_per_share) / (1 + action.stock_per_share)
                assert prices[action.code] > 0
            if entitled:
                gross = round(entitled * action.cash_per_share, 2)
                tax = round((gross + entitled * action.taxable_bonus_per_share) * config.dividend_tax, 2)
                bonus = math.floor(entitled * action.stock_per_share + 1e-8)
                pending.append(dict(code=action.code, cash=gross-tax, shares=bonus,
                                    cash_pay=action.cash_pay if gross else action.stock_pay,
                                    stock_pay=action.stock_pay))
                expected_events.append(dict(date=date, code=action.code, event='ex', entitled_shares=entitled,
                    gross_cash=gross, assumed_tax=tax, bonus_shares=bonus,
                    fractional_shares_discarded=entitled*action.stock_per_share-bonus))
        for item in pending:
            if item['cash'] and item['cash_pay'] <= date:
                cash = round(cash + item['cash'], 2)
                expected_events.append(dict(date=date, code=item['code'], event='cash_settlement', cash=item['cash']))
                item['cash'] = 0.
            if item['shares'] and item['stock_pay'] is not None and item['stock_pay'] <= date:
                positions[item['code']] += item['shares']
                if item.get('lock_on_settlement', False):
                    locked[item['code']] += item['shares']
                expected_events.append(dict(date=date, code=item['code'], event='stock_settlement', shares=item['shares']))
                item['shares'] = 0
        pending = [p for p in pending if p['cash'] or p['shares']]
        for issue in rights:
            if issue.ex != date:
                continue
            entitled = right_entitlements.pop(issue, 0)
            if not entitled:
                continue
            view = check_rights_stage(issue, date, 'subscription')
            assert issue.code in daily, 'A held rights issue requires observed ex-date valuation'
            event = dict(date=date, code=issue.code, entitled_shares=entitled, source=issue.source,
                original_source=issue.source, stage_sources=source_json(view))
            if issue.price is not None:
                allotted = math.floor(entitled * view['quota_ratio'] + 1e-8)
                cost = round(allotted * view['price'], 2)
                if allotted and cash >= cost - 1e-8:
                    cash = round(cash - cost, 2)
                    pending.append(dict(code=issue.code, cash=0., shares=allotted, cash_pay=pd.NaT,
                                        stock_pay=view['list_date'], lock_on_settlement=True))
                    if issue.code in ('000977.SZ', '600999.SH'):
                        pending[-1].update(rights_record=_day(issue.record), rights_ex=_day(issue.ex),
                            quota_ratio=view['quota_ratio'], market_ex_ratio=view['market_ex_ratio'],
                            listing_known_date=view['listing_known_date'])
                    event.update(event='rights_subscribed', allotted_shares=allotted, price=view['price'],
                        ratio=view['quota_ratio'], cost=cost, list_date=_day(view['list_date']),
                        market_ex_ratio=view['market_ex_ratio'], terms_known_date=view['terms_known_date'],
                        result_known_date=view['result_known_date'], listing_known_date=view['listing_known_date'],
                        research_scenario='ex_date_subscription_floor_not_custody',
                        personal_actual_allocation_certified=False)
                else:
                    event.update(event='rights_not_subscribed', reason='insufficient_cash')
            else:
                event.update(event='rights_not_subscribed')
            expected_events.append(event)
        for code, delisting in delistings.items():
            if date >= delisting:
                lost = positions[code] + sum(p['shares'] for p in pending if p['code'] == code)
                if lost:
                    expected_events.append(dict(date=date, code=code, event='delisting_zero_recovery', shares=lost))
                positions[code] = 0
                for item in pending:
                    if item['code'] == code:
                        item['shares'] = 0
        for code in share_scope():
            if code in daily:
                prices[code] = float(daily[code]['open'])
        receivable = sum(p['cash'] for p in pending)
        opening = cash + receivable + sum((positions[c] + sum(p['shares'] for p in pending if p['code']==c))*prices[c]
                        for c in set(positions) | {p['code'] for p in pending} if positions[c] or any(p['code']==c and p['shares'] for p in pending))
        weights = plans.get(date)
        expected_orders = []
        day_fees = day_slip = day_notional = 0.
        if weights is not None:
            desired = {}
            preliminary_rejections=[]
            for code in set(weights) | {c for c, n in positions.items() if n}:
                price = float(daily[code]['open']) if code in daily else prices.get(code)
                if price is None:
                    history = histories.get(code)
                    previous = None if history is None else history.loc[history.index < date]
                    price = None if previous is None or previous.empty else float(previous.iloc[-1].close)
                if code not in daily and weights.get(code,0.)>0 and not positions[code]:
                    history=histories.get(code)
                    previous=None if history is None else history.loc[history.index<date]
                    sizing_price=None if previous is None or previous.empty else float(previous.iloc[-1].close)
                    requested=0 if sizing_price is None else math.floor(opening*weights[code]/sizing_price/100)*100
                    preliminary_rejections.append(dict(date=date,ts_code=code,side='buy',requested=requested,shares=0,
                        raw_open=float('nan'),price=0.,fee=0.,slippage_cost=0.,status='rejected',reason='missing_execution_quote',
                        cash_after=cash,role='entry',notional=0.,quantity_unknown=sizing_price is None))
                    continue
                total = 0 if price is None else math.floor(opening * weights.get(code, 0.) / price / 100) * 100
                desired[code] = max(0, total - sum(p['shares'] for p in pending if p['code']==code))
            expected_orders.extend(sorted(preliminary_rejections,key=lambda r:r['ts_code']))
            sellable = {c: max(0, n-locked[c]) for c, n in positions.items()}
            for side in ('sell', 'buy'):
                for code in sorted(desired):
                    held = positions[code]
                    difference = desired[code] - held
                    if side=='sell' and difference>=0 or side=='buy' and difference<=0:
                        continue
                    quote = daily.get(code)
                    if quote is not None:
                        check_exposure(code, date)
                    free = cash if side=='sell' else round(max(0., cash-config.cash_buffer*opening), 2)
                    fill = _fill(side, int(abs(difference)), free, held, int(sellable.get(code, 0)), quote,
                                 adv[date].get(code, float('nan')), date, config, (date,code) in suspension_set)
                    cash = round(cash + fill['cash_after']-free, 2)
                    positions[code] = fill['shares_after']
                    sellable[code] = fill['sellable_after']
                    raw = float('nan') if quote is None else quote['open']
                    slip = 0. if not fill['shares'] else fill['shares']*(fill['price']-raw)*(1 if side=='buy' else -1)
                    expected_orders.append(dict(date=date, ts_code=code, side=side, requested=int(abs(difference)),
                        shares=fill['shares'], raw_open=raw, price=fill['price'], fee=fill['fee'], slippage_cost=slip,
                        status=fill['status'], reason=fill['reason'], cash_after=cash,
                        role='entry' if side=='buy' and held==0 else 'exit' if side=='sell' and weights.get(code,0.)==0 else 'resize',
                        notional=fill['shares']*fill['price']))
                    day_fees += fill['fee']; day_slip += slip; day_notional += fill['shares']*fill['price']
        if compare:
            observed_orders = order_days.get(date, [])
            preliminary=[r for r in observed_orders if r.get('reason')=='missing_execution_quote']
            observed_orders=sorted(preliminary,key=lambda r:r['ts_code'])+[r for r in observed_orders if r.get('reason')!='missing_execution_quote']
            assert len(expected_orders)==len(observed_orders), ('Order count / plan replacement', date, len(expected_orders), len(observed_orders))
            for expected, observed in zip(expected_orders, observed_orders):
                for key, value in expected.items():
                    _equal(observed.get(key), value, ('Order', date, key))
        for code in share_scope():
            if code in daily:
                prices[code] = float(daily[code]['close'])
        for action in actions:
            if action.record != date:
                continue
            view = _distribution(action, date, evidence)
            if view['apply_distribution']:
                assert not any(p['code']==action.code and p['shares'] for p in pending), 'Overlapping pending bonus entitlement'
                entitlements[action] = positions[action.code]
                if action.code == '600781.SH' and _day(action.ex) == '2019-07-22':
                    item = dict(code=action.code, recorded_date=_day(date), record_date=_day(action.record),
                        ex_date=_day(action.ex), entitled_shares=entitlements[action], status='planned',
                        version=view['version'], known_date=view['known_date'], source=source_json(view))
                    scenario_entitlements.append(item)
                    expected_events.append(dict(date=date, code=action.code, event='distribution_research_record',
                        **{k:v for k,v in item.items() if k not in ('code', 'recorded_date', 'status')},
                        reason='research_scenario_not_custody'))
        for issue in rights:
            if issue.record == date:
                if positions[issue.code]:
                    check_rights_stage(issue, date, 'record')
                right_entitlements[issue] = positions[issue.code]
        if compare:
            observed_events = event_days.get(date, [])
            assert len(expected_events) == len(observed_events), ('Event count', date, expected_events, observed_events)
            for expected, observed in zip(expected_events, observed_events):
                for key, value in expected.items():
                    _equal(_normal(observed.get(key), key), _normal(value, key), ('Corporate event', date, key))
        prices = {c: p for c, p in prices.items() if c in share_scope()}
        expected_holdings = {c: (positions[c],sum(p['shares'] for p in pending if p['code']==c))
                             for c in set(positions)|{p['code'] for p in pending}
                             if positions[c] or any(p['code']==c and p['shares'] for p in pending)}
        if compare:
            observed_holdings = {r['ts_code']: r for r in holding_days.get(date, [])}
            assert set(expected_holdings)==set(observed_holdings), ('Holding set', date)
        stock = bonus = stale = 0.
        equity = cash + sum(p['cash'] for p in pending)
        for code, (held, unlisted) in expected_holdings.items():
            equity += (held+unlisted)*prices[code]
        for code, (held, unlisted) in expected_holdings.items():
            value = (held+unlisted)*prices[code]
            if compare:
                row = observed_holdings[code]
                for key, expected in dict(shares=held,pending_shares=unlisted,mark=prices[code],value=value,weight=value/equity).items():
                    _equal(row.get(key),expected,('Holdings',date,code,key))
            stock += held*prices[code]; bonus += unlisted*prices[code]
            if code not in daily:
                stale += value
        if compare:
            for key, expected in dict(cash=cash,stock_value=stock,bonus_value=bonus,receivable=sum(p['cash'] for p in pending),
                equity=equity,fees=day_fees,slippage_cost=day_slip,turnover=day_notional/opening,
                stale_value=stale,position_count=sum(n>0 for n in positions.values())).items():
                _equal(dayrow.get(key),expected,('NAV',date,key))
        assert cash >= -1e-7 and all(n>=0 for n in positions.values())
        expected_obligations = [('unapplied_distribution',a.code,_terms(a,n)) for a,n in entitlements.items() if n and a not in applied]
        expected_obligations += [('unapplied_rights',r.code,rights_terms(r,n,date)) for r,n in right_entitlements.items() if n]
        expected_obligations += [('pending',p['code'],_normal(p)) for p in pending if p['cash'] or p['shares']]
        def ordered(rows):
            return sorted(rows,key=lambda r:(r[0],r[1],json.dumps(r[2],sort_keys=True)))
        if compare:
            observed_obligations = [(r['kind'],r['code'],_normal(json.loads(r['payload']))) for r in obligation_days.get(date,[])]
            _equal([list(r) for r in ordered(observed_obligations)],[list(r) for r in ordered(expected_obligations)],('Obligations',date))
        if compare and previous_nav is not None and previous_nav['date'].year!=date.year and previous_nav['date'].year>=2018:
            boundaries.append(dict(prior_date=_day(previous_nav['date']),next_date=_day(date),
                prior_cash=previous_nav['cash'],next_cash=cash,prior_equity=previous_nav['equity'],next_equity=equity,
                cash_reconstruction_error=0.,share_reconstruction_exact=True))
        if compare:
            daily_records.append(dict(date=_day(date),cash=cash,shares=sum(positions.values()),pending_shares=sum(p['shares'] for p in pending),
                                      receivable=sum(p['cash'] for p in pending),equity=equity,stale_value=stale,orders_checked=len(expected_orders),events_checked=len(expected_events)))
            previous_nav=dayrow

    for dayrow in nav.to_dict('records'):
        reconstruct_day(dayrow)
    final=json.loads((folder/'account_state.json').read_text(encoding='utf-8'))
    _equal(final['cash'],cash,'Final cash')
    _equal(final['positions'],{c:n for c,n in positions.items() if n},'Final positions')
    _equal(final['prices'],prices,'Final actual price scope')
    _equal(_sorted_payloads(final['pending']),_sorted_payloads(pending),'Final pending')
    _equal(_sorted_payloads(final['unapplied_distributions']),_sorted_payloads([_terms(a,n) for a,n in entitlements.items() if n and a not in applied]),'Final distributions')
    _equal(_sorted_payloads(final['unapplied_rights']),_sorted_payloads([rights_terms(r,n,actual_dates[-1]) for r,n in right_entitlements.items() if n]),'Final rights')
    _equal(final.get('scenario_entitlements', []), scenario_entitlements, 'Research scenario entitlement archive')
    _equal(_sorted_payloads(final.get('cancelled_distributions', [])),
           _sorted_payloads([asdict(a) for a in cancelled]), 'Cancelled distribution identities')
    failure_reproduced=None
    independent_failure=None
    independent_reason=independent_code=None
    if not completed:
        failure=json.loads((folder/'failure.json').read_text(encoding='utf-8'))
        failure_date=pd.Timestamp(failure['date'])
        assert len(nav)<len(calendar) and failure_date==calendar[len(nav)]
        assert failure.get('reason') and failure.get('type')
        failure_reproduced=False
        try:
            reconstruct_day(dict(date=failure_date), compare=False)
        except (AssertionError,ValueError) as independent_error:
            failure_reproduced=True
            independent_failure=str(independent_error)
            independent_reason, independent_code = _independent_stop(independent_error)
        needs_guard_reproduction=failure.get('guard_row') is not None or failure['type']=='AccountDataFailure'
        if needs_guard_reproduction:
            assert failure_reproduced,'Account data failure not independently reproduced'
            assert len(trace) and trace.decision.eq('stop').any(),'Stopped account lacks failure-day guard evidence'
            stops = trace.loc[trace.decision.eq('stop')]
            assert len(stops) == 1 and stops.date.iloc[0] == failure_date, 'Failure stop is not the first uncompleted day'
            stop = stops.iloc[0]
            assert independent_reason == stop.reason and independent_code == stop.ts_code, (
                'Independent stop differs from recorded failure', independent_reason, independent_code,
                stop.reason, stop.ts_code)
            guard_row = failure.get('guard_row')
            if guard_row is not None:
                assert guard_row.get('reason') == stop.reason and guard_row.get('ts_code') == stop.ts_code
                assert _day(guard_row.get('date')) == _day(failure_date)
        else:
            # A Ledger economic exception has not been independently replayed
            # merely because a separate guard check could find a data problem.
            failure_reproduced=None
        # A runtime/engineering error can still have a correctly reconstructed
        # prefix, but it is never converted to a certified economic data stop.
    return dict(status='passed' if completed else 'passed_partial',days=len(nav),completed_account=completed,
        year_boundaries=boundaries,daily_reconstruction=daily_records,orders_checked=len(orders),corporate_events_checked=len(events),
        data_stop_independently_reproduced=failure_reproduced,independent_failure=independent_failure,
        independent_stop_reason=independent_reason,independent_stop_code=independent_code,
        independent_cash_share_entitlement_cost_mark_reconstruction=True,
        account_simulation_imported=False,guard_module_imported=False,full_six_account_verification_passed=False,
        market_inventory_complete=False,enable_status='blocked_by_unverified_data_and_forward_validation')
