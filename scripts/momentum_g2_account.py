"""Approved G2 fixed-formation, single-session real-share account.

This adapter deliberately does not call a prior strategy simulator.  Monetary
rounding and the order primitive retain the frozen float-round research scenario.
Only explicitly sourced, point-in-time ordinary distributions are supported.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import json
import math
import re

import numpy as np
import pandas as pd

from quant_research.execution import FeeSchedule, execute_order


BASELINE = pd.Timestamp('2017-12-29')
END = pd.Timestamp('2020-12-31')
INITIAL_CASH = 1_000_000.


class AccountFailure(RuntimeError):
    def __init__(self, error, date=None, partial_result=None):
        self.original = error
        self.date = date
        self.partial_result = partial_result or {}
        self.partial = self.partial_result
        super().__init__(str(error))


def _date(value):
    if value is None or pd.isna(value) or value == '':
        return pd.NaT
    if isinstance(value, (int, float, np.integer, np.floating)):
        value = str(int(value))
    result = pd.to_datetime(value, format='%Y%m%d') if isinstance(value, str) and len(value) == 8 and value.isdigit() else pd.Timestamp(value)
    if result.tzinfo is not None or result != result.normalize():
        raise ValueError('Dates must be timezone-free exchange dates')
    return result


def _finite(value, positive=False):
    try:
        number = float(value)
        return math.isfinite(number) and (number > 0 if positive else number >= 0)
    except (ValueError, TypeError):
        return False


def _show(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def fees_for(cost_bps):
    if cost_bps not in (0, 10, 30):
        raise ValueError('Only frozen 0/10/30bp transaction scenarios are allowed')
    return (FeeSchedule(0., 0., 0., 0., 0.) if cost_bps == 0 else
            FeeSchedule(.0003, 5., .001, .00002, float(cost_bps)))


def _event(row):
    """Normalize names, never invent an absent economic amount or public date."""
    row = dict(row)
    aliases = dict(code='ts_code', cash_per_share='cash_div_tax', stock_per_share='stk_div',
                   taxable_bonus_per_share='stk_bo_rate', record='record_date', ex='ex_date',
                   cash_pay='pay_date', stock_pay='div_listdate', D='cash_div_tax', s='stk_div')
    for old, new in aliases.items():
        if new not in row and old in row:
            row[new] = row[old]
    for name in ('known_date', 'record_date', 'ex_date', 'pay_date', 'div_listdate'):
        row[name] = _date(row.get(name))
    row['code'] = row.get('ts_code')
    row['kind'] = row.get('kind', row.get('status'))
    row['status'] = row.get('status', row.get('kind'))
    return row


def _view(book, date, codes=None):
    values = book.view(date) if codes is None else [row for code in sorted(codes)
        for row in book.known_for_code(code, date)]
    if isinstance(values, pd.DataFrame):
        values = values.to_dict('records')
    result = {}
    for value in values:
        row = _event(value)
        identity = row.get('event_id')
        if not identity or not row.get('code') or pd.isna(row['known_date']) or row['known_date'] > date:
            raise ValueError('Event view has an invalid identity or future/unavailable source')
        if identity in result:
            raise ValueError('Event view contains duplicate active identities')
        result[identity] = row
    return result


def _ordinary(row, date, *, require_dates=False):
    if row['kind'] != 'ordinary' or row['status'] not in ('active', 'ordinary', 'implemented'):
        raise ValueError('Undefined or conflicting ordinary economic event: ' + str(row.get('event_id')))
    if not row.get('source') and not row.get('sources') and not row.get('raw_source'):
        raise ValueError('Ordinary action lacks its frozen source')
    if pd.isna(row['known_date']) or row['known_date'] > date:
        raise ValueError('Ordinary action source is not yet available')
    if any(not _finite(row.get(k)) for k in ('cash_div_tax', 'stk_div', 'stk_bo_rate')):
        raise ValueError('Ordinary action has unknown or illegal economic amounts')
    if float(row['stk_bo_rate']) > float(row['stk_div']) + 1e-10:
        raise ValueError('Taxable bonus exceeds total ordinary distribution')
    if pd.isna(row['record_date']) or pd.isna(row['ex_date']) or row['record_date'] >= row['ex_date']:
        raise ValueError('Ordinary action lacks chronological registration/ex dates')
    if require_dates:
        if float(row['cash_div_tax']) and (pd.isna(row['pay_date']) or row['pay_date'] < row['ex_date']):
            raise ValueError('Ordinary cash settlement source is unavailable')
        if float(row['stk_div']) and pd.notna(row['div_listdate']) and row['div_listdate'] < row['ex_date']:
            raise ValueError('Ordinary share settlement precedes ex-date')
    return row


def _terms(row):
    return tuple(row.get(k) for k in ('code', 'record_date', 'ex_date', 'cash_div_tax', 'stk_div', 'stk_bo_rate'))


def _suspensions(values):
    result = dict(opening=set(), full_day=set(), unknown=set(), evidence=set())
    if values is None:
        return result
    if isinstance(values, pd.DataFrame):
        if not {'trade_date', 'ts_code', 'suspend_type', 'suspend_timing'}.issubset(values):
            raise ValueError('Reliable suspension source needs original date/code/type/timing')
        for row in values.itertuples():
            if str(row.suspend_type) != 'S':
                continue
            key = (_date(row.trade_date), row.ts_code)
            result['evidence'].add(key)
            timing = '' if pd.isna(row.suspend_timing) else str(row.suspend_timing).strip()
            if not timing:
                result['opening'].add(key)
                result['full_day'].add(key)
                continue
            valid = True
            covers_open = False
            intervals = []
            segments = re.split(r'[,;，；]+', timing)
            for segment in segments:
                found = re.fullmatch(r'\s*(\d{2}):(\d{2})(?::(\d{2}))?\s*[-~至]\s*(\d{2}):(\d{2})(?::(\d{2}))?\s*', segment)
                if found is None:
                    valid = False
                    break
                h1, m1, s1, h2, m2, s2 = (int(x or 0) for x in found.groups())
                if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59 or s1 > 59 or s2 > 59:
                    valid = False
                    break
                first, last = h1 * 3600 + m1 * 60 + s1, h2 * 3600 + m2 * 60 + s2
                if first >= last:
                    valid = False
                    break
                covers_open |= first <= 9 * 3600 + 30 * 60 < last
                intervals.append((first, last))
            if not valid:
                result['unknown'].add(key)
            elif covers_open:
                result['opening'].add(key)
                merged = []
                for first, last in sorted(intervals):
                    if merged and first <= merged[-1][1]:
                        merged[-1] = (merged[-1][0], max(last, merged[-1][1]))
                    else:
                        merged.append((first, last))
                if all(any(first <= a and last >= z for first, last in merged)
                       for a, z in [(34200, 41400), (46800, 54000)]):
                    result['full_day'].add(key)
        return result
    for d, code in values:
        key = (_date(d), code)
        result['evidence'].add(key)
        result['opening'].add(key)
        result['full_day'].add(key)
    return result


class OrdinaryLedger:
    """Separate registered rights, cash receivable, and unlisted integer stock."""
    def __init__(self):
        self.cash = INITIAL_CASH
        self.positions = defaultdict(int)
        self.prices = {}
        self.reference_prices = {}
        self.price_dates = {}
        self.registered = {}
        self.pending = {}
        self.applied = set()
        self.cancelled = set()
        self.events = []

    def unlisted(self, code):
        return sum(p['shares'] for p in self.pending.values() if p['code'] == code)

    def receivable(self):
        return sum(p['cash'] for p in self.pending.values())

    def codes(self):
        return {c for c, n in self.positions.items() if n} | {p['code'] for p in self.pending.values() if p['shares']}

    def obligations(self):
        return self.codes() | {p['code'] for p in self.pending.values() if p['cash']} | {
            p['code'] for identity, p in self.registered.items()
            if p['entitled_shares'] and identity not in self.applied and identity not in self.cancelled}

    def trace(self, date, row, event, **values):
        item = dict(date=date, code=row['code'], ts_code=row['code'], event_id=row['event_id'],
            event=event, known_date=row['known_date'], record_date=row.get('record_date'), ex_date=row.get('ex_date'),
            cash_pay=row.get('pay_date'), stock_pay=row.get('div_listdate'), D=row.get('cash_div_tax'),
            s=row.get('stk_div'), taxable_bonus=row.get('stk_bo_rate'), source=row.get('source') or row.get('sources') or row.get('raw_source'),
            version_id=row.get('version_id'), account_guard=row.get('account_guard'),
            research_scenario='fixed_20pct_tax_face_value_1_float_round',
            actual_investor_tax_certified=False, cash_delta=0., positions_delta=0,
            pending_delta=0, receivable_delta=0.)
        item.update(values)
        self.events.append(item)

    def morning(self, date, view):
        for identity, saved in list(self.registered.items()):
            if identity in self.applied or identity in self.cancelled:
                continue
            row = view.get(identity)
            if row is None:
                raise ValueError('Previously registered event disappeared from source view')
            if row['kind'] == 'cancelled' or row['status'] == 'cancelled':
                if identity in self.applied:
                    raise ValueError('Cancellation after an applied action is undefined')
                if identity not in self.cancelled:
                    self.cancelled.add(identity)
                    self.trace(date, row, 'cancelled', entitled_shares=saved['entitled_shares'])
                continue
            _ordinary(row, date)
            if _terms(saved['terms']) != _terms(row):
                raise ValueError('Registered event economic terms changed after registration')
        for identity, row in sorted(view.items()):
            if row['kind'] != 'ordinary' or row['ex_date'] != date:
                continue
            _ordinary(row, date, require_dates=True)
            if identity in self.cancelled:
                continue
            if identity in self.applied:
                raise ValueError('Duplicate economic application')
            self.applied.add(identity)
            if row['code'] in self.prices:
                self.prices[row['code']] = (self.prices[row['code']] - float(row['cash_div_tax'])) / (1. + float(row['stk_div']))
                if self.prices[row['code']] <= 0:
                    raise ValueError('Nonpositive theoretical ex-action mark')
            if row['code'] in self.reference_prices:
                self.reference_prices[row['code']] = (self.reference_prices[row['code']] - Decimal(str(row['cash_div_tax']))) / (1 + Decimal(str(row['stk_div'])))
            saved = self.registered.get(identity)
            n = 0 if saved is None else saved['entitled_shares']
            if n == 0:
                continue
            if _terms(saved['terms']) != _terms(row):
                raise ValueError('Ex-date action differs from registered frozen terms')
            gross = round(n * float(row['cash_div_tax']), 2)
            tax = round((gross + n * float(row['stk_bo_rate'])) * .20, 2)
            shares = math.floor(n * float(row['stk_div']) + 1e-8)
            pay = row['pay_date'] if gross else row['div_listdate']
            due = gross - tax
            if due and pd.isna(pay):
                raise ValueError('Cash or bonus-tax obligation has no known settlement date')
            self.pending[identity] = dict(code=row['code'], event_id=identity, cash=due, shares=shares,
                cash_pay=pay, stock_pay=row['div_listdate'], terms=deepcopy(row), entitled_shares=n)
            self.trace(date, row, 'ex', entitled_shares=n, gross_cash=gross, assumed_tax=tax,
                bonus_shares=shares, fractional_shares_discarded=n * float(row['stk_div']) - shares,
                **dict(pending_delta=shares, receivable_delta=due))
        for identity, item in list(self.pending.items()):
            row = view.get(identity)
            if row is None:
                raise ValueError('Outstanding economic right has no current source view')
            _ordinary(row, date)
            if _terms(item['terms']) != _terms(row):
                raise ValueError('Outstanding ordinary right economic terms changed')
            # Listing may be announced after the ex-date.  Only update from the
            # current view; no future listing field enters an earlier state.
            for key, field in [('stock_pay', 'div_listdate'), ('cash_pay', 'pay_date')]:
                if key == 'cash_pay' and not float(row['cash_div_tax']):
                    continue
                old, new = item[key], row[field]
                if pd.isna(old) and pd.notna(new):
                    if new < date:
                        raise ValueError('Settlement was only learned after its effective date')
                    item[key] = new
                    self.trace(date, row, key + '_known', settlement_date=new)
                elif pd.notna(old) and pd.notna(new) and old != new:
                    raise ValueError('Outstanding settlement date changed without supported revision')
            if item['cash'] and pd.notna(item['cash_pay']) and item['cash_pay'] <= date:
                delta = item['cash']
                self.cash = round(self.cash + delta, 2)
                self.trace(date, row, 'cash_settlement', cash=delta,
                    **dict(cash_delta=delta, receivable_delta=-delta))
                item['cash'] = 0.
                if self.cash < -1e-8:
                    raise ValueError('Cash insufficient for fixed corporate-action tax scenario')
            if item['shares'] and pd.notna(item['stock_pay']) and item['stock_pay'] <= date:
                n = item['shares']
                self.positions[item['code']] += n
                self.trace(date, row, 'stock_settlement', shares=n,
                    **dict(positions_delta=n, pending_delta=-n))
                item['shares'] = 0
            if not item['cash'] and not item['shares']:
                del self.pending[identity]

    def record(self, date, view):
        for identity, row in sorted(view.items()):
            if row['kind'] != 'ordinary' or row['record_date'] != date:
                continue
            n = self.positions[row['code']]
            if not n:
                continue
            _ordinary(row, date)
            if self.unlisted(row['code']):
                raise ValueError('Overlapping unlisted rights lack a unique registration model')
            if identity in self.registered:
                raise ValueError('Corporate registration applied twice')
            self.registered[identity] = dict(code=row['code'], entitled_shares=n, terms=deepcopy(row))
            self.trace(date, row, 'record', entitled_shares=n)

    def components(self):
        stock = bonus = 0.
        for code in self.codes():
            if code not in self.prices:
                raise ValueError('Exposed security has no legal mark: ' + code)
            stock += self.positions[code] * self.prices[code]
            bonus += self.unlisted(code) * self.prices[code]
        receivable = self.receivable()
        return dict(cash=self.cash, stock_value=stock, bonus_value=bonus, receivable=receivable,
                    equity=self.cash + stock + bonus + receivable)


def _plain(value):
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is pd.NaT:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return value


def _state(ledger):
    return _plain(dict(cash=ledger.cash, positions={c: n for c, n in ledger.positions.items() if n},
        prices=dict(ledger.prices), reference_prices=dict(ledger.reference_prices),
        price_dates=dict(ledger.price_dates), pending=deepcopy(ledger.pending),
        registered=deepcopy(ledger.registered), applied=sorted(ledger.applied), cancelled=sorted(ledger.cancelled)))


def simulate_account(bars, full_calendar, schedule, targets, event_book, universe,
                     suspensions=None, cost_bps=10, progress=None):
    """Simulate the frozen evaluation interval; never run a real-data preparation.

    Amount is the unchanged vendor thousand-CNY field. ``schedule`` and targets
    use signal_date/execution_date (formation_date is accepted as an alias).
    Returned economic traces are sufficient for independent daily reconstruction.
    On any failure completed tables and failure-day mutations are attached.
    """
    fees = fees_for(cost_bps)
    full = pd.DatetimeIndex([_date(d) for d in full_calendar])
    if full.empty or full.hasnans or full.has_duplicates or not full.is_monotonic_increasing:
        raise ValueError('Full exchange calendar must be sorted and unique')
    calendar = full[(full >= BASELINE) & (full <= END)]
    if calendar.empty:
        raise ValueError('No evaluation sessions')
    consumed_codes = set(targets.ts_code) if 'ts_code' in targets else set()
    b = bars.loc[bars.ts_code.isin(consumed_codes)].copy() if 'ts_code' in bars else bars.copy()
    required = {'trade_date', 'ts_code', 'open', 'close', 'vol', 'amount', 'pre_close', 'up_limit', 'down_limit'}
    if not required.issubset(b):
        raise ValueError('Missing account raw market fields: ' + str(required - set(b)))
    b['trade_date'] = b.trade_date.map(_date)
    # Every owned name must previously have appeared as a positive target.
    # Keep only those actual-consumption identities and the complete ADV seed;
    # future years and unowned whole-market numeric rows never enter the loop.
    first_index = full.get_indexer([calendar[0]])[0]
    seed_start = full[max(0, first_index - 19)]
    b = b.loc[b.ts_code.isin(consumed_codes) & b.trade_date.between(seed_start, END)].copy()
    if b.duplicated(['trade_date', 'ts_code']).any() or not b.trade_date.isin(full).all():
        raise ValueError('Duplicate or off-calendar market identity')
    market = {d: g.set_index('ts_code').to_dict('index') for d, g in b.groupby('trade_date', sort=False)}
    index = {d: i for i, d in enumerate(full)}
    by_code = {c: g.set_index('trade_date') for c, g in b.groupby('ts_code', sort=False)}
    s = schedule.copy()
    t = targets.copy()
    for frame in (s, t):
        if 'signal_date' not in frame and 'formation_date' in frame:
            frame['signal_date'] = frame['formation_date']
        for col in ('signal_date', 'execution_date'):
            if col not in frame:
                raise ValueError('Schedule and targets need formation/execution dates')
            frame[col] = frame[col].map(_date)
    if s.duplicated(['signal_date']).any() or s.execution_date.duplicated().any():
        raise ValueError('Schedule contains duplicate formation or execution')
    if (s.signal_date >= s.execution_date).any() or not s.signal_date.isin(full).all() or not s.execution_date.isin(calendar).all():
        raise ValueError('Schedule has invalid formation/execution chronology')
    for row in s.itertuples():
        if index[row.execution_date] != index[row.signal_date] + 1:
            raise ValueError('A plan must execute on the immediately following exchange session')
    if t.duplicated(['signal_date', 'ts_code']).any() or not {'ts_code', 'target_weight'}.issubset(t):
        raise ValueError('Targets have missing or duplicate identity')
    pairs = set(zip(s.signal_date, s.execution_date))
    if any((r.signal_date, r.execution_date) not in pairs for r in t.itertuples()):
        raise ValueError('Target is outside the fixed schedule')
    if any(not _finite(w) or (float(w) != 0. and not math.isclose(float(w), .049, abs_tol=1e-14)) for w in t.target_weight):
        raise ValueError('G2 target weights must be zero or 0.049')
    if any((g.target_weight.gt(0).sum() > 20 or g.target_weight.sum() > .98 + 1e-10) for _, g in t.groupby('signal_date')):
        raise ValueError('G2 target slot or cash-buffer limit violated')
    if not {'ts_code', 'list_date', 'delist_date'}.issubset(universe) or universe.ts_code.duplicated().any():
        raise ValueError('Unique frozen lifecycle metadata is required')
    lifecycle = universe.set_index('ts_code').to_dict('index')
    suspension_info = _suspensions(suspensions)
    suspension_set = suspension_info['opening']
    full_day_suspensions = suspension_info['full_day']
    formation_to_exec = dict(zip(s.signal_date, s.execution_date))
    target_groups = {d: g.set_index('ts_code').to_dict('index') for d, g in t.groupby('signal_date')}
    ledger = OrdinaryLedger()
    nav, orders, holdings, obligations, intents, daily_trace, episodes = [], [], [], [], [], [], []
    plans = {}
    active_episodes = {}
    initial_plan = None
    initial_execution = None
    ownership_start = {}
    position_history = {}
    last_completed_state = _state(ledger)
    date = None

    def adv_at(code, formation):
        i = index[formation]
        dates = full[max(0, i - 19):i + 1]
        raw = by_code.get(code)
        values = None if raw is None else raw.reindex(dates)
        valid = len(dates) == 20 and values is not None and all(_finite(x, True) for x in values.amount)
        if valid:
            return float(values.amount.astype(float).mean()) * 1000., ''
        bad = dates if values is None else dates[[not _finite(x, True) for x in values.amount]]
        if len(dates) != 20 or any((d, code) not in full_day_suspensions for d in bad):
            raise ValueError('Unexplained incomplete formation ADV: ' + code)
        return np.nan, 'incomplete_adv_registered_suspension'

    def exposure_guard(code, day, view, *, planned=False):
        if planned and (day, code) in suspension_info['unknown']:
            raise ValueError('Unknown intraday suspension timing on a planned opening: ' + code)
        if code not in lifecycle:
            raise ValueError('Missing frozen lifecycle metadata: ' + code)
        listed = _date(lifecycle[code].get('list_date'))
        delisted = _date(lifecycle[code].get('delist_date'))
        if pd.isna(listed) or day <= listed:
            raise ValueError('Unknown/pre-listing/initial-listing exposure: ' + code)
        if pd.notna(delisted) and day >= delisted:
            raise ValueError('Unknown delisting economic recovery; no last-price cash-out: ' + code)
        start = ownership_start.get(code, full[max(0, index[day] - 1)])
        for row in view.values():
            if row['code'] != code or row['kind'] in ('ordinary', 'cancelled') or row['status'] == 'cancelled':
                continue
            if pd.notna(row['ex_date']) and row['ex_date'] < start:
                continue
            # A newly known unsupported fact touching actual obligations is a
            # hard stop even where its eventual effective date is still absent.
            raise ValueError('Undefined/conflicting economic exposure or planned bridge: ' + code + ':' + str(row['event_id']))
        issues = event_book.exposure_issues(code, day, window_start=start)
        if isinstance(issues, pd.DataFrame):
            issues = issues.to_dict('records')
        if issues:
            raise ValueError('EventBook reports unresolved economic exposure: ' + code)

    def quote_guard(code, day, view):
        quote = market.get(day, {}).get(code)
        reliable_s = (day, code) in full_day_suspensions
        if quote is None:
            if not reliable_s or code not in ledger.prices:
                raise ValueError('Missing exposed/planned quote without legal suspended valuation: ' + code)
            for row in view.values():
                if row['code'] == code and row.get('account_guard') == 'capitalization_tax_origin_unknown' and row['ex_date'] == day:
                    raise ValueError('Unknown capitalization source crosses a missing-price exposure')
            return None
        if any(not _finite(quote.get(k), True) for k in ('open', 'close', 'pre_close')):
            raise ValueError('Invalid exposed raw price: ' + code)
        if any(not _finite(quote.get(k)) for k in ('vol', 'amount')):
            raise ValueError('Illegal exposed volume/amount: ' + code)
        vol_zero, amount_zero = float(quote['vol']) == 0, float(quote['amount']) == 0
        if vol_zero != amount_zero:
            raise ValueError('Conflicting zero volume and amount: ' + code)
        if vol_zero and not reliable_s:
            # A full-day zero print may veto an order but cannot invent legal
            # stale valuation or explain a missing economic bridge.
            if code in ledger.codes():
                raise ValueError('Held zero-volume quote has no reliable suspension evidence: ' + code)
        if vol_zero and reliable_s:
            for row in view.values():
                if row['code'] == code and row.get('account_guard') == 'capitalization_tax_origin_unknown' and row['ex_date'] == day:
                    raise ValueError('Unknown capitalization source crosses a stale-price exposure')
        previous = ledger.reference_prices.get(code)
        if previous is None:
            i = index[day]
            prior = None if i == 0 else market.get(full[i - 1], {}).get(code)
            if prior is None or not _finite(prior.get('close'), True):
                raise ValueError('Planned bridge lacks previous exchange-session raw close: ' + code)
            previous = Decimal(str(prior.get('close_text', prior['close'])))
            for row in view.values():
                if row['code'] == code and row['kind'] == 'ordinary' and row['ex_date'] == day:
                    _ordinary(row, day)
                    previous = (previous - Decimal(str(row['cash_div_tax']))) / (1 + Decimal(str(row['stk_div'])))
        if _show(previous) != _show(quote.get('pre_close_text', quote['pre_close'])):
            raise ValueError('Unexplained exposed raw pre-close bridge: ' + code)
        return quote

    def tables(failure=None):
        end_date = nav[-1]['date'] if failure is not None and nav else calendar[-1] if failure is None else BASELINE
        episode_rows = []
        for item in episodes:
            row = {k: v for k, v in item.items() if k != 'unit_factor'}
            start = index[row['first_execution_date']]
            window = full[start:start + 5]
            row['complete_five_session_window'] = len(window) == 5 and window[-1] <= end_date
            row['five_session_end'] = window[-1] if len(window) == 5 else pd.NaT
            row['first_intent_completion'] = min(1., row['first_intent_filled_equivalent'] / row['frozen_total_shares'])
            row['securities_risk_closed'] = pd.notna(row.get('risk_closed_date'))
            row['status'] = 'closed' if row['securities_risk_closed'] else 'right_censored'
            row['residual_shares'] = ledger.positions[row['ts_code']] + ledger.unlisted(row['ts_code']) if not row['securities_risk_closed'] else 0
            episode_rows.append(row)
        deployment = []
        if initial_plan is not None:
            values = [p for p in intents if p['plan_id'] == initial_plan]
            first_execution = initial_execution
            plan_value = sum(p['requested_formation_shares'] * p['formation_close'] for p in values if p['side'] == 'buy')
            filled_value = sum(min(p['requested_formation_shares'], p['filled_formation_equivalent']) * p['formation_close'] for p in values if p['side'] == 'buy')
            start = index[first_execution]
            window = full[start:start + 5]
            deployment.append(dict(plan_id=initial_plan, first_execution_date=first_execution, denominator_cny=980000.,
                planned_cny=plan_value, filled_formation_reference_cny=filled_value,
                unconditional_completion=filled_value / 980000., whole_lot_plan_coverage=plan_value / 980000.,
                filled_over_whole_lot_plan=filled_value / plan_value if plan_value else np.nan,
                complete_five_session_window=len(window) == 5 and window[-1] <= end_date,
                five_session_end=window[-1] if len(window) == 5 else pd.NaT))
        result = dict(nav=pd.DataFrame(nav), orders=pd.DataFrame(orders), holdings=pd.DataFrame(holdings),
            corporate_events=pd.DataFrame(ledger.events), obligations=pd.DataFrame(obligations), intents=pd.DataFrame(intents),
            daily_trace=pd.DataFrame(daily_trace), exit_episodes=pd.DataFrame(episode_rows),
            deployment=pd.DataFrame(deployment), account_state=_state(ledger), cost_bps=cost_bps)
        if not result['intents'].empty:
            result['intents'] = result['intents'].drop(columns=['_conversions'])
        if failure is not None:
            result['failure_state'] = result['account_state']
            result['account_state'] = last_completed_state
            result['failure'] = dict(date=_plain(date), exception_type=type(failure).__name__,
                reason=str(failure), last_completed_date=_plain(nav[-1]['date']) if nav else None,
                last_completed_state=deepcopy(last_completed_state),
                account_completed=False, product_and_strategy_gates_evaluable=False)
            complete = set(result['nav'].get('date', []))
            for name in ('orders', 'holdings', 'corporate_events', 'obligations', 'daily_trace'):
                frame = result[name]
                if not frame.empty and 'date' in frame:
                    mask = frame.date.isin(complete)
                    result['failure_day_' + name] = frame.loc[~mask].copy()
                    result[name] = frame.loc[mask].copy()
        return result

    try:
        for date in calendar:
            day_plans = plans.get(date, [])
            view_codes = ledger.obligations() | {p['ts_code'] for p in day_plans} | set(target_groups.get(date, {}))
            view = _view(event_book, date, view_codes)
            scope = ledger.obligations() | {p['ts_code'] for p in day_plans if p['requested_formation_shares']}
            price_scope = ledger.codes() | {v['code'] for k, v in ledger.registered.items()
                if k not in ledger.applied and k not in ledger.cancelled and v['entitled_shares']} | {p['ts_code'] for p in day_plans if p['requested_formation_shares']}
            for code in sorted(scope):
                exposure_guard(code, date, view, planned=any(p['ts_code'] == code and p['requested_formation_shares'] for p in day_plans))
                unavailable = event_book.unknown_effective(code, date)
                if any(row.get('event_id') not in view for row in unavailable):
                    raise ValueError('Actual economic bridge requires unavailable/future provenance: ' + code)
            before_ex = set(ledger.applied)
            cash_before_corporate = ledger.cash
            for identity, row in view.items():
                if row['code'] not in scope or row['kind'] != 'ordinary' or row['ex_date'] != date:
                    continue
                _ordinary(row, date)
                ex_index = index.get(row['ex_date'], -1)
                if ex_index <= 0 or full[ex_index - 1] != row['record_date']:
                    raise ValueError('Ordinary record date is not the previous exchange session')
                if row['known_date'] > row['record_date']:
                    raise ValueError('Ordinary terms were unavailable by registration')
                if identity not in ledger.registered and position_history.get(row['record_date'], {}).get(row['code'], 0):
                    raise ValueError('Past held registration requires information unavailable at that time')
            current_ex_codes = [r['code'] for r in view.values() if r['code'] in scope
                and r['kind'] == 'ordinary' and r['status'] != 'cancelled' and r['ex_date'] == date]
            if len(current_ex_codes) != len(set(current_ex_codes)):
                raise ValueError('Multiple ordinary events cannot be summed on one economic bridge')
            ledger.morning(date, {k: v for k, v in view.items() if v['code'] in scope})
            for identity in ledger.applied - before_ex:
                row = view[identity]
                if float(row['stk_div']):
                    if row['code'] in active_episodes:
                        active_episodes[row['code']]['unit_factor'] *= 1 + float(row['stk_div'])
                    for plan in day_plans:
                        if plan['ts_code'] != row['code'] or not plan['requested_formation_shares']:
                            continue
                        frozen = {e['event_id']: e for e in plan['_conversions']}
                        if identity not in frozen or _terms(frozen[identity]) != _terms(row):
                            raise ValueError('Formation request needs share-conversion terms not known at formation')
            for code in sorted(price_scope):
                quote_guard(code, date, view)
            sellable = {c: n for c, n in ledger.positions.items()}
            day_fees = day_slippage = day_turnover = 0.
            for side in ('sell', 'buy'):
                for plan in sorted(day_plans, key=lambda p: p['ts_code']):
                    if plan['side'] != side or not plan['requested_formation_shares']:
                        continue
                    code = plan['ts_code']
                    for frozen in plan['_conversions']:
                        current = view.get(frozen['event_id'])
                        if current is None or current['kind'] == 'cancelled':
                            raise ValueError('Frozen requested share conversion was cancelled or disappeared')
                        if _terms(current) != _terms(frozen):
                            raise ValueError('Frozen requested share conversion changed at execution')
                    multiplier = plan['unit_multiplier']
                    quantity = math.floor(plan['requested_formation_shares'] * multiplier + 1e-8)
                    if side == 'buy' or not plan['full_exit']:
                        quantity = quantity // 100 * 100
                    quote = market.get(date, {}).get(code, {})
                    held = ledger.positions[code]
                    available = sellable.get(code, 0)
                    cash_before = ledger.cash
                    free_cash = cash_before if side == 'sell' else round(max(0., cash_before - plan['cash_reserve']), 2)
                    raw_open = quote.get('open', np.nan)
                    zero_day = bool(quote) and float(quote['vol']) == 0 and float(quote['amount']) == 0
                    fill = execute_order(side=side, requested=int(quantity), cash=free_cash,
                        held=int(held), sellable=int(available), raw_open=raw_open,
                        up_limit=quote.get('up_limit', np.nan), down_limit=quote.get('down_limit', np.nan),
                        suspended=(date, code) in suspension_set or zero_day,
                        prior_adv_cny=plan['adv20_cny'], fees=fees, participation=.005)
                    delta = fill.cash_after - free_cash
                    ledger.cash = round(ledger.cash + delta, 2)
                    ledger.positions[code] = fill.shares_after
                    if side == 'buy' and fill.shares and code not in ownership_start:
                        ownership_start[code] = date
                    sellable[code] = fill.sellable_after
                    notional = round(fill.shares * fill.price, 2)
                    equivalent = fill.shares / multiplier
                    plan['filled_formation_equivalent'] = equivalent
                    plan['requested_execution_shares'] = quantity
                    plan['status'] = 'expired'
                    plan['execution_status'] = ('partial' if 0 < fill.shares < quantity else fill.status)
                    plan['expiry_date'] = date
                    reason = 'final_zero_volume_veto' if zero_day else plan['adv_reason'] if not _finite(plan['adv20_cny'], True) else fill.reason
                    slip = 0. if not fill.shares else fill.shares * (fill.price - raw_open) * (1 if side == 'buy' else -1)
                    episode = active_episodes.get(code)
                    if episode and side == 'sell':
                        episode_equivalent = fill.shares / episode['unit_factor']
                        if plan['plan_id'] == episode['first_plan_id']:
                            episode['first_intent_filled_equivalent'] += episode_equivalent
                    orders.append(dict(date=date, plan_id=plan['plan_id'], formation_date=plan['formation_date'],
                        execution_date=date, ts_code=code, side=side, requested=quantity, shares=fill.shares,
                        requested_formation_shares=plan['requested_formation_shares'], formation_equivalent_shares=equivalent,
                        unit_multiplier=multiplier, raw_open=raw_open, price=fill.price, fee=fill.fee, notional=notional,
                        cash_before=cash_before, cash_after=ledger.cash, cash_delta=delta, held_before=held,
                        held_after=fill.shares_after, sellable_before=available, sellable_after=fill.sellable_after,
                        adv20_cny=plan['adv20_cny'], capacity_cny=plan['adv20_cny'] * .005,
                        cash_reserve=plan['cash_reserve'], slippage_cost=slip,
                        status=plan['execution_status'], reason=reason, role=plan['role'], episode_id=plan['episode_id']))
                    day_fees += fill.fee
                    day_slippage += slip
                    day_turnover += notional
            for plan in day_plans:
                if plan['status'] == 'formed':
                    plan.update(status='expired', expiry_date=date, execution_status='no_request')
            for code in sorted(ledger.codes()):
                quote = market.get(date, {}).get(code)
                if quote is not None and float(quote['vol']) > 0:
                    ledger.prices[code] = float(quote['close'])
                    ledger.reference_prices[code] = Decimal(str(quote.get('close_text', quote['close'])))
                    ledger.price_dates[code] = date
                elif quote is not None and (date, code) in suspension_set and code not in ledger.prices:
                    raise ValueError('Cannot initialize a suspended asset from an untraded quote')
                if code not in ledger.prices:
                    raise ValueError('Position created without legal closing valuation')
            for row in view.values():
                if row['code'] in ledger.codes() and row['kind'] == 'ordinary' and row['record_date'] == date:
                    _ordinary(row, date)
                    ex_index = index.get(row['ex_date'], -1)
                    if ex_index <= 0 or full[ex_index - 1] != date:
                        raise ValueError('Ordinary record date is not the previous exchange session')
            ledger.record(date, {k: v for k, v in view.items() if v['code'] in ledger.codes()})
            position_history[date] = {c: n for c, n in ledger.positions.items() if n}
            for code, episode in list(active_episodes.items()):
                if ledger.positions[code] + ledger.unlisted(code) == 0:
                    episode['risk_closed_date'] = date
                    episode['settlement_receivable_at_risk_close'] = sum(p['cash'] for p in ledger.pending.values() if p['code'] == code)
                    del active_episodes[code]
            parts = ledger.components()
            if parts['equity'] <= 0 or ledger.cash < -1e-8 or any(n < 0 for n in ledger.positions.values()):
                raise ValueError('Nonpositive equity or negative cash/share constraint')
            stale_value = 0.
            for code in sorted(ledger.codes()):
                held, pending = ledger.positions[code], ledger.unlisted(code)
                stale = ledger.price_dates.get(code) != date
                value = (held + pending) * ledger.prices[code]
                stale_value += value if stale else 0.
                holdings.append(dict(date=date, ts_code=code, shares=held, pending_shares=pending,
                    sellable=sellable.get(code, 0), mark=ledger.prices[code], mark_date=ledger.price_dates.get(code),
                    stale=stale, value=value, weight=value / parts['equity']))
            for identity, item in sorted(ledger.pending.items()):
                obligations.append(dict(date=date, code=item['code'], event_id=identity, kind='pending',
                    cash=item['cash'], shares=item['shares'], cash_pay=item['cash_pay'], stock_pay=item['stock_pay'],
                    entitled_shares=item['entitled_shares'], known_date=item['terms']['known_date']))
            for identity, item in sorted(ledger.registered.items()):
                if identity not in ledger.applied and identity not in ledger.cancelled:
                    obligations.append(dict(date=date, code=item['code'], event_id=identity, kind='registered',
                        cash=0., shares=0, entitled_shares=item['entitled_shares'],
                        known_date=item['terms']['known_date']))
            previous_equity = nav[-1]['equity'] if nav else INITIAL_CASH
            nav.append(dict(date=date, **parts, fees=day_fees, slippage_cost=day_slippage,
                turnover_value=day_turnover, one_way_turnover=day_turnover / (2 * previous_equity),
                position_count=sum(n > 0 for n in ledger.positions.values()), stale_value=stale_value,
                cost_bps=cost_bps))
            daily_trace.append(dict(date=date, cash_before_corporate=cash_before_corporate,
                corporate_cash_delta=ledger.cash - cash_before_corporate - sum(o['cash_delta'] for o in orders if o['date'] == date),
                cash_after=ledger.cash, registered_count=len(ledger.registered), pending_count=len(ledger.pending)))
            last_completed_state = _state(ledger)
            # Form only after all day's corporate, trading, close and registration
            # accounting. No opening repricing of these quantities is permitted.
            if date in formation_to_exec:
                execution = formation_to_exec[date]
                plan_id = date.strftime('%Y%m%d') + '_' + execution.strftime('%Y%m%d')
                if initial_plan is None:
                    initial_plan = plan_id
                    initial_execution = execution
                selected = target_groups.get(date, {})
                plan_rows = []
                for code in sorted(set(selected) | ledger.codes()):
                    weight = float(selected.get(code, {}).get('target_weight', 0.))
                    exposed = ledger.positions[code] + ledger.unlisted(code)
                    if not weight and not exposed:
                        continue
                    exposure_guard(code, date, view, planned=bool(weight))
                    quote = market.get(date, {}).get(code)
                    if weight:
                        if quote is None or not _finite(quote.get('close'), True) or float(quote['vol']) <= 0 or float(quote['amount']) <= 0:
                            raise ValueError('Positive target lacks a legal formation raw close')
                        close = float(quote['close'])
                    else:
                        close = ledger.prices.get(code)
                        if close is None:
                            raise ValueError('Exposed exit cannot be valued at formation')
                    total = 100 * math.floor(weight * parts['equity'] / (100 * close))
                    held, unlisted = ledger.positions[code], ledger.unlisted(code)
                    difference = total - held - unlisted
                    side = 'buy' if difference > 0 else 'sell' if difference < 0 else 'none'
                    requested = (held if weight == 0 else abs(difference) // 100 * 100)
                    if side == 'sell' and weight > 0:
                        requested = min(requested, held // 100 * 100)
                    if side == 'none':
                        requested = 0
                    adv, adv_reason = adv_at(code, date)
                    conversions = []
                    multiplier = 1.
                    for row in view.values():
                        if row['code'] == code and row['kind'] == 'ordinary' and date < row['ex_date'] <= execution and _finite(row.get('stk_div')) and float(row['stk_div']):
                            _ordinary(row, date)
                            conversions.append(deepcopy(row))
                            multiplier *= 1 + float(row['stk_div'])
                    episode = active_episodes.get(code)
                    if weight == 0 and exposed and episode is None:
                        episode = dict(episode_id=code + '_' + plan_id, ts_code=code, formation_date=date,
                            first_execution_date=execution, first_plan_id=plan_id, frozen_total_shares=exposed,
                            frozen_listed_shares=held, frozen_unlisted_shares=unlisted, reference_price=close,
                            reference_amount=exposed * close, reason='target_zero', first_intent_filled_equivalent=0.,
                            risk_closed_date=pd.NaT, reversal_date=pd.NaT, unit_factor=1.)
                        active_episodes[code] = episode
                        episodes.append(episode)
                    elif weight > 0 and episode is not None and pd.isna(episode['reversal_date']):
                        episode['reversal_date'] = date
                    row = dict(plan_id=plan_id, formation_date=date, signal_date=date, execution_date=execution,
                        ts_code=code, target_weight=weight, equity_at_formation=parts['equity'], cash_at_formation=ledger.cash,
                        formation_close=close, formation_listed_shares=held, formation_unlisted_shares=unlisted,
                        target_total_shares=total, side=side, requested_formation_shares=int(requested),
                        cash_reserve=.02 * parts['equity'], adv20_cny=adv, adv_reason=adv_reason,
                        unit_multiplier=multiplier, conversions_json=json.dumps(_plain(conversions), ensure_ascii=False, default=str),
                        full_exit=weight == 0, role='exit' if weight == 0 else 'entry' if exposed == 0 and side == 'buy' else 'resize',
                        episode_id=episode['episode_id'] if episode else None, filled_formation_equivalent=0.,
                        status='formed', expiry_date=pd.NaT, execution_status=None, _conversions=conversions)
                    intents.append(row)
                    plan_rows.append(row)
                plans[execution] = plan_rows
            # Discard valuation caches only when no security or registered
            # entitlement can need their economic bridge.
            keep = ledger.codes() | {v['code'] for k, v in ledger.registered.items() if k not in ledger.applied and k not in ledger.cancelled and v['entitled_shares']}
            ledger.prices = {c: p for c, p in ledger.prices.items() if c in keep}
            ledger.reference_prices = {c: p for c, p in ledger.reference_prices.items() if c in keep}
            ledger.price_dates = {c: p for c, p in ledger.price_dates.items() if c in keep}
            ownership_start = {c: d for c, d in ownership_start.items() if c in ledger.obligations()}
            last_completed_state = _state(ledger)
            if progress is not None:
                progress(date, len(nav))
    except Exception as error:
        raise AccountFailure(error, date, tables(error)) from error
    result = tables()
    return result
