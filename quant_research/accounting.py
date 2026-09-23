"""Corporate-action ledger with separate entitlement, ex-date and settlement.

Dividend tax is a declared fixed-rate scenario, not actual holding-period tax.
Bonus-share taxable face value defaults to a declared CNY 1 scenario.
"""
from dataclasses import dataclass
from collections import defaultdict
import math
import pandas as pd


@dataclass(frozen=True)
class Action:
    code: str
    record: pd.Timestamp
    ex: pd.Timestamp
    cash_pay: pd.Timestamp
    stock_pay: pd.Timestamp
    cash_per_share: float = 0.
    stock_per_share: float = 0.
    taxable_bonus_per_share: float = 0.

    def __post_init__(self):
        if pd.isna(self.record) or pd.isna(self.ex) or self.record >= self.ex:
            raise ValueError('Company action requires record date strictly before ex-date')
        if any(not math.isfinite(x) or x < 0 for x in [self.cash_per_share, self.stock_per_share, self.taxable_bonus_per_share]):
            raise ValueError('Invalid corporate action amounts')
        if self.cash_per_share and (pd.isna(self.cash_pay) or self.cash_pay < self.ex):
            raise ValueError('Missing/invalid cash settlement date')
        if self.stock_per_share and (pd.isna(self.stock_pay) or self.stock_pay < self.ex):
            raise ValueError('Missing/invalid stock listing date')


def normalize_actions(frame, codes):
    actions = []
    if frame.empty:
        return actions
    frame = frame.loc[frame.ts_code.isin(codes) & frame.div_proc.eq('实施')].copy()
    seen = {}
    for row in frame.to_dict('records'):
        def date(field):
            return pd.to_datetime(row[field], format='%Y%m%d') if pd.notna(row.get(field)) else pd.NaT
        def amount(field):
            value = row.get(field)
            return 0. if pd.isna(value) else float(value)
        action = Action(row['ts_code'], date('record_date'), date('ex_date'), date('pay_date'),
                        date('div_listdate'), amount('cash_div_tax'), amount('stk_div'), amount('stk_bo_rate'))
        key = (action.code, action.ex)
        if key in seen:
            equivalent = all((pd.isna(value) and pd.isna(getattr(seen[key], field))) or value == getattr(seen[key], field)
                             for field, value in vars(action).items())
            if not equivalent:
                raise ValueError(f'Conflicting corporate actions for {key}')
            continue
        seen[key] = action
        actions.append(action)
    return sorted(actions, key=lambda a: (a.ex, a.code))


class Ledger:
    def __init__(self, initial_cash=1_000_000., dividend_tax=.20, bonus_face_value=1.):
        if not math.isfinite(initial_cash) or initial_cash <= 0 or not 0 <= dividend_tax <= 1 or bonus_face_value < 0:
            raise ValueError('Invalid ledger parameters')
        self.cash = float(initial_cash)
        self.positions = defaultdict(int)
        self.prices = {}
        self.dividend_tax = dividend_tax
        self.bonus_face_value = bonus_face_value
        self.entitlements = {}
        self.pending = []
        self.events = []
        self.applied = set()

    def record(self, date, actions):
        for action in actions:
            if action.record == date:
                if self.pending_shares(action.code):
                    raise ValueError('Overlapping unlisted bonus-share entitlements need manual reconciliation')
                self.entitlements[action] = self.positions[action.code]

    def morning(self, date, actions):
        for action in actions:
            if action.ex != date:
                continue
            if action in self.applied:
                raise ValueError('Corporate action applied twice')
            self.applied.add(action)
            shares = self.entitlements.get(action, 0)
            # Reference-price adjustment is needed even when the stock is suspended.
            if action.code in self.prices:
                self.prices[action.code] = (self.prices[action.code] - action.cash_per_share) / (1 + action.stock_per_share)
                if self.prices[action.code] <= 0:
                    raise ValueError('Invalid ex-action reference price')
            if not shares:
                continue
            gross = round(shares * action.cash_per_share, 2)
            tax = round((gross + shares * action.taxable_bonus_per_share * self.bonus_face_value) * self.dividend_tax, 2)
            bonus = math.floor(shares * action.stock_per_share + 1e-8)
            pay = action.cash_pay if gross else action.stock_pay
            cash_due = gross - tax
            if cash_due and pd.isna(pay):
                raise ValueError('Missing date for dividend/tax settlement')
            self.pending.append(dict(code=action.code, cash=cash_due, shares=bonus,
                                     cash_pay=pay, stock_pay=action.stock_pay))
            self.events.append(dict(date=date, code=action.code, event='ex', entitled_shares=shares,
                                    gross_cash=gross, assumed_tax=tax, bonus_shares=bonus,
                                    fractional_shares_discarded=shares * action.stock_per_share - bonus))
        for item in self.pending:
            if item['cash'] and item['cash_pay'] <= date:
                self.cash = round(self.cash + item['cash'], 2)
                self.events.append(dict(date=date, code=item['code'], event='cash_settlement', cash=item['cash']))
                item['cash'] = 0.
            if item['shares'] and item['stock_pay'] <= date:
                self.positions[item['code']] += item['shares']
                self.events.append(dict(date=date, code=item['code'], event='stock_settlement', shares=item['shares']))
                item['shares'] = 0
        self.pending = [item for item in self.pending if item['cash'] or item['shares']]
        if self.cash < -1e-8:
            raise ValueError('Cash insufficient for corporate-action tax scenario')

    def pending_shares(self, code):
        return sum(p['shares'] for p in self.pending if p['code'] == code)

    @property
    def receivable(self):
        return sum(p['cash'] for p in self.pending)

    def mark(self, quotes):
        for code, price in quotes.items():
            if not math.isfinite(price) or price <= 0:
                raise ValueError('Invalid market price')
            self.prices[code] = float(price)

    def components(self):
        all_codes = set(self.positions) | {p['code'] for p in self.pending}
        held_value = bonus_value = 0.
        for code in all_codes:
            held, bonus = self.positions[code], self.pending_shares(code)
            if not held and not bonus:
                continue
            if code not in self.prices:
                raise ValueError(f'No valuation for holding {code}')
            held_value += held * self.prices[code]
            bonus_value += bonus * self.prices[code]
        return dict(cash=self.cash, stock_value=held_value, bonus_value=bonus_value,
                    receivable=self.receivable, equity=self.cash + held_value + bonus_value + self.receivable)

    def write_off(self, date, code):
        """Explicit zero-recovery scenario at delisting; not an observed recovery."""
        lost = self.positions[code] + self.pending_shares(code)
        if lost:
            self.events.append(dict(date=date, code=code, event='delisting_zero_recovery', shares=lost))
        self.positions[code] = 0
        for item in self.pending:
            if item['code'] == code:
                item['shares'] = 0
