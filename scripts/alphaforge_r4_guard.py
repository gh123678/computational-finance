"""r4 actual-exposure and proposed-entry guard; no selection or return inputs."""
from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal
import json
import math

import pandas as pd

from alphaforge_r3_guard import day, decimal_price, lifecycle_state, suspension_evidence
from alphaforge_r4_evidence import known_state


class AccountDataFailure(ValueError):
    def __init__(self, row):
        self.row = row
        super().__init__(f"{row['ts_code']} {pd.Timestamp(row['date']).date()}: {row['reason']}")


def share_price_scope(ledger, actions, rights_entitlements=()):
    """Include unexecuted share entitlements; never retain pure cash prices."""
    codes = {c for c, n in ledger.positions.items() if n}
    codes |= {p['code'] for p in ledger.pending if p['shares']}
    codes |= {a.code for a, n in ledger.entitlements.items()
              if n and a not in ledger.applied and a.stock_per_share}
    for issue, n in dict(rights_entitlements).items():
        if n and issue.price is not None:
            codes.add(issue.code)
    return codes


def obligation_scope(ledger, rights_entitlements=()):
    return ({a.code for a, n in ledger.entitlements.items() if n and a not in ledger.applied}
            | {p['code'] for p in ledger.pending if p['cash'] or p['shares']}
            | {r.code for r, n in dict(rights_entitlements).items() if n})


def prune_prices(ledger, actions, rights_entitlements=()):
    keep = share_price_scope(ledger, actions, rights_entitlements)
    ledger.prices = {c: p for c, p in ledger.prices.items() if c in keep}


def _serial(item):
    return {k: None if v is None or (not isinstance(v, (str, float, int)) and pd.isna(v))
            else str(v.date()) if isinstance(v, pd.Timestamp) else v for k, v in asdict(item).items()}


class ExposureGuard:
    def __init__(self, bars, calendar, full_calendar, universe, actions, rights,
                 suspensions, evidence):
        self.calendar = pd.DatetimeIndex(calendar)
        self.full = pd.DatetimeIndex(full_calendar)
        if self.calendar.has_duplicates or not self.calendar.is_monotonic_increasing:
            raise ValueError('Account calendar is not sorted and unique')
        if self.full.has_duplicates or not self.full.is_monotonic_increasing:
            raise ValueError('Full calendar is not sorted and unique')
        if bars.duplicated(['ts_code', 'trade_date']).any():
            raise ValueError('Duplicate raw quote')
        self.groups = {c: g.set_index('trade_date').sort_index() for c, g in bars.groupby('ts_code')}
        if universe.ts_code.duplicated().any():
            raise ValueError('Duplicate lifecycle metadata')
        self.meta = universe.set_index('ts_code').to_dict('index')
        self.actions = defaultdict(list)
        self.rights = defaultdict(list)
        for a in actions:
            self.actions[a.code].append(a)
        for r in rights:
            self.rights[r.code].append(r)
        self.suspensions = suspension_evidence(suspensions)
        self.evidence = evidence
        self.allow = {(r['code'], pd.Timestamp(r['ex'])): r for r in evidence['ordinary_actions']}
        self.trace = []

    def quote(self, code, date):
        group = self.groups.get(code)
        if group is None or date not in group.index:
            return None
        return group.loc[date].to_dict()

    def previous(self, code, date):
        group = self.groups.get(code)
        if group is None:
            return pd.NaT, None
        pos = group.index.searchsorted(date, side='left') - 1
        if pos < 0:
            return pd.NaT, None
        return group.index[pos], group.iloc[pos].to_dict()

    def row(self, code, date, role, ledger=None):
        return dict(date=date, ts_code=code, role=role, decision='allow', reason='',
                    has_quote=self.quote(code, date) is not None, prior_quote_date=pd.NaT,
                    prior_close_text='', pre_close_text='', theoretical_stale_mark=None,
                    observed_reference=None, gap_days='[]', interval_actions='[]',
                    nontrade_evidence='', lifecycle='',
                    held_shares=0 if ledger is None else ledger.positions.get(code, 0),
                    pending_shares=0 if ledger is None else ledger.pending_shares(code))

    def stop(self, row, reason):
        row.update(decision='stop', reason=reason)
        self.trace.append(dict(row))
        raise AccountDataFailure(dict(row))

    def _state(self, code, date, row):
        m = self.meta.get(code, {})
        state = lifecycle_state(date, day(m.get('list_date')), day(m.get('delist_date')))
        row['lifecycle'] = state
        if state in ('invalid_lifecycle', 'pre_listing', 'post_delisting'):
            self.stop(row, 'price_exposure_or_plan_outside_lifecycle')
        return known_state(code, date, self.evidence)

    def _nontrade(self, code, date, row):
        official = self._state(code, date, row)
        if official is not None and not official.get('pre_open_known', True):
            self.stop(row, 'official_state_publication_or_boundary_uncertain')
        original = self.suspensions.get((date, code), [])
        if any(kind == 'S' for kind, _ in original):
            return 'original_daily_S:' + json.dumps(original, ensure_ascii=False)
        if official is not None and official.get('state') not in ('listed', 'delisting_board'):
            if not official.get('usable_for_missing_quote', False):
                self.stop(row, 'official_state_publication_or_boundary_uncertain')
            return 'official_state:' + json.dumps(official, ensure_ascii=False, default=str)
        self.stop(row, 'missing_quote_without_asof_nontrade_evidence')

    def _valid_quote(self, quote, row):
        close = decimal_price(quote.get('close_text'))
        ref = decimal_price(quote.get('pre_close_text'))
        row.update(pre_close_text=quote.get('pre_close_text'), observed_reference=str(ref))
        if close is None or ref is None:
            self.stop(row, 'invalid_raw_close_or_pre_close')
        for field in ('open', 'high', 'low', 'close', 'vol', 'amount'):
            try:
                value = float(quote[field])
                okay = math.isfinite(value) and (value > 0 if field in ('open', 'high', 'low', 'close') else value >= 0)
            except (KeyError, ValueError, TypeError):
                okay = False
            if not okay:
                self.stop(row, 'invalid_quote_' + field)
        if float(close) != float(quote['close']):
            self.stop(row, 'raw_text_numeric_close_conflict')
        if (quote['low'] > min(quote['open'], quote['close']) or
                quote['high'] < max(quote['open'], quote['close']) or quote['low'] > quote['high']):
            self.stop(row, 'inconsistent_OHLC')
        return close, ref

    def _ordinary_allowed(self, a, cutoff, row):
        allow = self.allow.get((a.code, a.ex))
        if allow is None:
            self.stop(row, 'unreviewed_distribution_across_quote_gap')
        if not allow.get('ordinary', False) or allow.get('special_distribution', False) or not allow.get('sources'):
            self.stop(row, 'special_or_unsourced_distribution_across_quote_gap')
        if pd.Timestamp(allow['known_date']) > cutoff:
            self.stop(row, 'distribution_source_not_known_by_gap_day')
        pos = self.full.get_indexer([a.record, a.ex])
        if pos[0] < 0 or pos[1] != pos[0] + 1:
            self.stop(row, 'nonadjacent_distribution_record_ex')
        for field in ('record', 'ex', 'cash_pay', 'stock_pay'):
            v = allow.get(field)
            expected = pd.NaT if v is None else pd.Timestamp(v)
            actual = getattr(a, field)
            if not ((pd.isna(expected) and pd.isna(actual)) or expected == actual):
                self.stop(row, 'distribution_source_date_conflict')
        for field in ('cash_per_share', 'stock_per_share', 'taxable_bonus_per_share'):
            if Decimal(str(getattr(a, field))) != Decimal(str(allow[field])):
                self.stop(row, 'distribution_source_terms_conflict')

    def _interval(self, code, left, date, gap, row, quote_present):
        ordinary, rights = [], []
        for a in self.actions[code]:
            dates = [a.record, a.ex, a.cash_pay, a.stock_pay]
            if any(pd.notna(d) and left < d <= date for d in dates):
                ordinary.append(a)
        for r in self.rights[code]:
            if any(pd.notna(d) and left < d <= date for d in (r.record, r.ex, r.list_date)):
                rights.append(r)
        row['interval_actions'] = json.dumps([_serial(a) for a in ordinary + rights], default=str)
        if gap:
            for a in ordinary:
                self._ordinary_allowed(a, date, row)
            for r in rights:
                # Original rights scenario needs an observed ex-date, not an
                # inferred stale rights valuation. No aggregate ratio is added.
                quoted_ex = quote_present and r.ex == date and r.record <= left
                known_listing_release = (r.price is not None and r.ratio is not None
                    and pd.notna(r.list_date) and r.ex <= left
                    and not any(left < d <= date for d in (r.record, r.ex)))
                if not (quoted_ex or known_listing_release):
                    self.stop(row, 'rights_obligation_across_unquoted_equity_date')
        return ordinary, rights

    def _bridge(self, code, date, row, require_quote=False):
        quote = self.quote(code, date)
        official = self._state(code, date, row)
        if (official is not None and not official.get('pre_open_known', True)
                and (quote is not None or not require_quote)):
            self.stop(row, 'official_state_publication_or_boundary_uncertain')
        if (official is not None and official.get('state') not in ('listed', 'delisting_board')
                and quote is not None):
            # State helper returns only active nontrade/uncertain states.
            self.stop(row, 'quote_conflicts_with_official_nontrade_state')
        if row['lifecycle'] == 'scheduled_delisting':
            if require_quote or row['role'] in ('planned', 'entry_bridge'):
                self.stop(row, 'planned_purchase_on_delisting')
            if any(a.record == date or a.ex == date for a in self.actions[code]):
                self.stop(row, 'delisting_equity_date_conflict')
            row.update(reason='original_zero_recovery_delisting_scenario')
            self.trace.append(dict(row))
            return True
        if quote is None and require_quote:
            row.update(decision='reject', reason='no_execution_quote')
            self.trace.append(dict(row))
            return False
        left, previous = self.previous(code, date)
        row['prior_quote_date'] = left
        if previous is None or decimal_price(previous.get('close_text')) is None:
            self.stop(row, 'missing_actual_prior_quote_for_exposure_or_entry')
        prior = decimal_price(previous['close_text'])
        row['prior_close_text'] = previous['close_text']
        gap_days = self.full[(self.full > left) & (self.full < date)]
        gap = len(gap_days) > 0 or quote is None
        missing_days = [*gap_days, *([] if quote is not None else [date])]
        explanations = []
        for missing in missing_days:
            if self.quote(code, missing) is not None:
                self.stop(row, 'unexpected_quote_in_gap_index')
            explanations.append(dict(date=str(missing.date()), source=self._nontrade(code, missing, row)))
        row['gap_days'] = json.dumps(explanations, ensure_ascii=False)
        self._state(code, date, row)
        ordinary, rights = self._interval(code, left, date, gap, row, quote is not None)
        ex_actions = [a for a in ordinary if left < a.ex <= date]
        ex_rights = [r for r in rights if left < r.ex <= date]
        theoretical = float(prior)
        for a in sorted(ex_actions, key=lambda a: a.ex):
            theoretical = (theoretical - a.cash_per_share) / (1 + a.stock_per_share)
        row['theoretical_stale_mark'] = theoretical
        if theoretical <= 0:
            self.stop(row, 'invalid_theoretical_ex_price')
        if quote is None:
            row.update(reason='stale_ordinary_action_scenario' if ex_actions else 'stale_nontrade_mark',
                       nontrade_evidence=explanations[-1]['source'])
        else:
            _, ref = self._valid_quote(quote, row)
            if ref != prior and not (ex_actions or ex_rights):
                self.stop(row, 'unexplained_reference_change')
            row['reason'] = ('registered_action_across_gap' if gap and (ex_actions or ex_rights)
                             else 'registered_action_reference' if ex_actions or ex_rights
                             else 'continuous_reference')
        self.trace.append(dict(row))
        return True

    def check_day(self, code, date, ledger, *, planned_signal=None, rights_entitlements=()):
        price = code in share_price_scope(ledger, (), rights_entitlements)
        economic = code in obligation_scope(ledger, rights_entitlements)
        planned = planned_signal is not None
        row = self.row(code, date, 'price' if price else 'cash_obligation' if economic else 'planned', ledger)
        if price:
            self._bridge(code, date, row)
        elif economic:
            # Dates and terms are validated in normalized immutable Action;
            # settle all pending cash even after the shares have been sold.
            quote = self.quote(code, date)
            left, previous = self.previous(code, date)
            active = [a for a,n in ledger.entitlements.items()
                      if a.code == code and n and a not in ledger.applied]
            if quote is None and active:
                if previous is None:
                    self.stop(row, 'unapplied_cash_entitlement_without_prior_record')
                for a in active:
                    if any(pd.notna(d) and left < d <= date for d in (a.record,a.ex,a.cash_pay)):
                        self._ordinary_allowed(a,date,row)
            row.update(reason='cash_obligation_no_stock_valuation')
            self.trace.append(dict(row))
        if planned:
            entry = self.row(code, date, 'planned', ledger)
            if self.quote(code, date) is None:
                return self._bridge(code, date, entry, require_quote=True)
            signal = pd.Timestamp(planned_signal)
            if signal >= date or self.quote(code, signal) is None:
                self.stop(entry, 'entry_formation_anchor_missing')
            for d in self.full[(self.full > signal) & (self.full <= date)]:
                item = self.row(code, d, 'entry_bridge', ledger)
                self._bridge(code, d, item)
            return True
        return True
