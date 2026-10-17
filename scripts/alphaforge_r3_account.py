"""Explicit approved r3 account adapter, with the frozen raw-share ledger.

The simulate body below was copied from quant_research.backtest.simulate.
Only its adjustment-factor requirement/guard is replaced by the approved,
source-bound reference/lifecycle precheck and per-exposure guard. Execution,
fees, cash/share/receivable accounting and zero-recovery write-off stay intact.
No broker, future-label input or adjustment-factor replacement is used.
"""
import math
import numpy as np
import pandas as pd
from quant_research.accounting import Ledger
from quant_research.execution import execute_order
from quant_research.backtest import Config
from alphaforge_r3_guard import (DAILY_COLUMNS, audit_reference_guard, day,
    input_fingerprint, lifecycle_state, suspension_evidence)

BASE_BACKTEST_SHA256 = '0dca85c6eac4f8000a5eace03c3e90227d0a78ee738718a12555c96ae284a380'


def simulate_reference(bars, calendar, targets, actions=(), suspensions=None, delistings=None,
                       industries=None, config=Config(), rebalance_dates=None, rights=(), *,
                       universe=None, seed_bars=None, source_hashes=None, full_calendar=None,
                       guard_audit=None):
    """targets has execution_date, signal_date, ts_code, target_weight.

    ADV capacity comes from sessions preceding execution. A target group means
    rebalance; absent groups mean hold. Explicit zero weights liquidate holdings.
    """
    if universe is None:
        raise ValueError('Reference account requires frozen universe lifecycle metadata')
    calendar = pd.DatetimeIndex(calendar)
    actions, rights = tuple(actions), tuple(rights)
    all_codes = set(bars.ts_code)
    # The root performs the all-fixed-security hard gate once. Reuse is permitted
    # only for exactly matching raw/metadata/action/suspension/calendar inputs.
    if guard_audit is None:
        guard_audit = audit_reference_guard(bars, calendar, universe, actions, suspensions, rights,
            codes=all_codes, seed_bars=seed_bars, source_hashes=source_hashes,
            full_calendar=full_calendar)
    else:
        expected = input_fingerprint(bars, calendar, universe, actions, suspensions, rights,
                                     all_codes, seed_bars, source_hashes, full_calendar)
        if guard_audit.get('summary', {}).get('input_fingerprint') != expected:
            raise ValueError('Reference precheck inputs do not match this account')
    if (not guard_audit['summary']['passed'] or not guard_audit['failures'].empty
            or guard_audit['daily'].decision.eq('stop').any()):
        raise ValueError('Reference guard precheck failed; no account was opened')
    if (guard_audit['summary']['security_session_rows'] != len(all_codes) * len(calendar)
            or set(guard_audit['daily'].ts_code) != all_codes):
        raise ValueError('Reference precheck does not cover the complete fixed account scope')
    lifecycle = universe.loc[universe.ts_code.isin(all_codes)].set_index('ts_code')
    listings = {code: day(value) for code, value in lifecycle.list_date.items()}
    declared_delistings = {code: day(value) for code, value in lifecycle.delist_date.items()}
    if delistings is not None:
        for code in all_codes:
            supplied, declared = day(delistings.get(code)), declared_delistings[code]
            if not ((pd.isna(supplied) and pd.isna(declared)) or supplied == declared):
                raise ValueError('Delisting argument conflicts with frozen universe: ' + code)
    delistings = declared_delistings
    for row in targets.itertuples(index=False):
        if row.target_weight > 0:
            execution = pd.Timestamp(row.execution_date)
            if row.ts_code not in listings:
                raise ValueError('Target security is outside fixed guard scope')
            state = lifecycle_state(execution, listings[row.ts_code], delistings[row.ts_code])
            if state != 'listed' or execution == listings[row.ts_code]:
                raise ValueError('Target attempts lifecycle-ineligible or initial-listing purchase')
    guard_days = guard_audit['daily'].groupby('date', sort=False, observed=True)
    guard_checks = []
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Calendar must be sorted and unique')
    required = {'trade_date', 'ts_code', 'open', 'close', 'amount', 'vol', 'close_text', 'pre_close_text', 'up_limit', 'down_limit'}
    if not required.issubset(bars):
        raise ValueError(f'Missing market fields: {required - set(bars)}')
    bars = bars.copy()
    bars['trade_date'] = pd.to_datetime(bars.trade_date)
    if bars.duplicated(['trade_date', 'ts_code']).any() or not bars.trade_date.isin(calendar).all():
        raise ValueError('Duplicate or off-calendar bars')
    if not np.isfinite(bars[['open', 'close', 'amount', 'vol']].to_numpy(float)).all():
        raise ValueError('Missing price/volume data')
    if (bars[['open', 'close']] <= 0).any().any() or (bars[['amount', 'vol']] < 0).any().any():
        raise ValueError('Invalid price/volume values')
    targets = targets.copy()
    for col in ['execution_date', 'signal_date']:
        targets[col] = pd.to_datetime(targets[col])
    if (targets.signal_date >= targets.execution_date).any() or not targets.execution_date.isin(calendar).all():
        raise ValueError('Targets require an earlier signal and on-calendar execution')
    if targets.duplicated(['execution_date', 'ts_code']).any():
        raise ValueError('Duplicate target')
    weights = targets.target_weight.to_numpy(float)
    if not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError('Invalid target weights')
    if (targets.groupby('execution_date').target_weight.sum() > 1 - config.cash_buffer + 1e-8).any():
        raise ValueError('Target leverage/cash buffer violation')
    market = {d: g.set_index('ts_code').to_dict('index') for d, g in bars.groupby('trade_date')}
    plans = {d: {} for d in (rebalance_dates if rebalance_dates is not None else [])}
    plans.update({d: g.set_index('ts_code').target_weight.to_dict() for d, g in targets.groupby('execution_date')})
    amount = bars.pivot(index='trade_date', columns='ts_code', values='amount').reindex(calendar)
    # Missing bars remain missing. Recent partial observations permit cautious exits,
    # whereas entry eligibility requires complete factor and liquidity windows.
    adv = (amount.rolling(20, min_periods=1).mean().shift(1) * 1000).to_dict('index')
    suspension_set = {key for key, evidence in suspension_evidence(suspensions).items()
                      if any(kind == 'S' for kind, _ in evidence)}
    delistings = {} if delistings is None else delistings
    industries = {} if industries is None else industries
    action_dates = {}
    for action in actions:
        action_dates.setdefault(action.code, []).append(action.ex)
        if calendar[0] <= action.record <= calendar[-1] and action.record not in calendar:
            raise ValueError('Record date is not in the exchange calendar')
    rights_entitlements = {}
    for issue in rights:
        if pd.isna(issue.record) or pd.isna(issue.ex) or issue.record >= issue.ex or not issue.source:
            raise ValueError('Rights issue requires verified chronological dates')
        action_dates.setdefault(issue.code, []).append(issue.ex)
    ledger = Ledger(config.initial_cash, config.dividend_tax)
    nav, fills, holdings = [], [], []
    recorded_cash_flow = 0.
    for date in calendar:
        daily = market.get(date, {})
        # No adjustment-factor substitution or old-core monkeypatch occurs.
        # The independently gated raw-reference decision is applied before any
        # morning action, sizing or trade, including pending-share exposures.
        exposure = {c for c, n in ledger.positions.items() if n}
        exposure |= {p['code'] for p in ledger.pending if p['shares']}
        planned_buys = {c for c, w in plans.get(date, {}).items() if w > 0}
        checked_day = (guard_days.get_group(date).set_index('ts_code')
                       if exposure or planned_buys else None)
        for code in sorted(exposure | planned_buys):
            checked = checked_day.loc[code]
            if checked.decision == 'stop':
                raise ValueError(f'Reference guard stopped {code} on {date.date()}: {checked.reason}')
            if checked.lifecycle in ('pre_listing', 'post_delisting'):
                raise ValueError(f'Price exposure outside lifecycle for {code} on {date.date()}')
            guard_checks.append(dict(ts_code=code, **checked.to_dict(),
                                     held_shares=ledger.positions[code],
                                     pending_shares=ledger.pending_shares(code),
                                     planned_positive_weight=code in planned_buys))
        before_cash = ledger.cash
        ledger.morning(date, actions)
        for issue in rights:
            if issue.ex == date and rights_entitlements.get(issue, 0):
                if issue.code not in daily:
                    raise ValueError('Held rights issue needs observed ex-date valuation')
                entitled = rights_entitlements[issue]
                if issue.price is not None:
                    allotted = math.floor(entitled * issue.ratio + 1e-8)
                    cost = round(allotted * issue.price, 2)
                    if allotted and ledger.cash >= cost - 1e-8:
                        ledger.cash = round(ledger.cash - cost, 2)
                        ledger.pending.append(dict(code=issue.code, cash=0., shares=allotted,
                                                   cash_pay=pd.NaT, stock_pay=issue.list_date,
                                                   lock_on_settlement=True))
                        ledger.events.append(dict(date=date, code=issue.code, event='rights_subscribed',
                                                  entitled_shares=entitled, allotted_shares=allotted,
                                                  price=issue.price, ratio=issue.ratio, cost=cost,
                                                  list_date=str(issue.list_date.date()), source=issue.source))
                    else:
                        ledger.events.append(dict(date=date, code=issue.code, event='rights_not_subscribed',
                                                  entitled_shares=entitled, reason='insufficient_cash',
                                                  source=issue.source))
                else:
                    ledger.events.append(dict(date=date, code=issue.code, event='rights_not_subscribed',
                                              entitled_shares=entitled, source=issue.source))
                    # No cash paid, no new shares credited. Raw market prices retain
                    # the dilution loss; an adjusted return must not erase it.
        recorded_cash_flow += ledger.cash - before_cash
        for code, delist_date in delistings.items():
            if pd.notna(delist_date) and date >= delist_date:
                ledger.write_off(date, code)
        ledger.mark({c: q['open'] for c, q in daily.items()})
        opening_equity = ledger.components()['equity']
        if opening_equity <= 0:
            raise ValueError('Nonpositive portfolio equity')
        sellable = {code: max(0, shares - ledger.settlement_locked.get(code, 0))
                    for code, shares in ledger.positions.items()}
        day_fees = turnover_value = slippage_cost = 0.
        if date in plans:
            weights = plans[date]
            if any(weight > 0 and pd.notna(delistings.get(code)) and date >= delistings[code] for code, weight in weights.items()):
                raise ValueError('Target attempts to buy delisted stock')
            desired = {}
            for code in set(weights) | {c for c, n in ledger.positions.items() if n}:
                price = ledger.prices.get(code)
                if price is None:
                    raise ValueError(f'Cannot size target {code} without a price')
                total = math.floor(opening_equity * weights.get(code, 0.) / price / 100) * 100
                desired[code] = max(0, total - ledger.pending_shares(code))
            # Frozen target quantities, sells before buys; no retroactive resizing.
            for side in ['sell', 'buy']:
                for code in sorted(desired):
                    held = ledger.positions[code]
                    difference = desired[code] - held
                    if (side == 'sell' and difference >= 0) or (side == 'buy' and difference <= 0):
                        continue
                    quote = daily.get(code, {})
                    raw_open = quote.get('open', np.nan)
                    free_cash = ledger.cash if side == 'sell' else round(max(0., ledger.cash - config.cash_buffer * opening_equity), 2)
                    fill = execute_order(side=side, requested=int(abs(difference)), cash=free_cash,
                                         held=int(held), sellable=int(sellable.get(code, 0)), raw_open=raw_open,
                                         up_limit=quote.get('up_limit', np.nan), down_limit=quote.get('down_limit', np.nan),
                                         suspended=(date, code) in suspension_set or quote.get('vol', 0) <= 0,
                                         prior_adv_cny=adv[date].get(code, np.nan), fees=config.fees(date),
                                         participation=config.participation)
                    delta_cash = fill.cash_after - free_cash
                    ledger.cash = round(ledger.cash + delta_cash, 2)
                    ledger.positions[code] = fill.shares_after
                    sellable[code] = fill.sellable_after
                    recorded_cash_flow += delta_cash
                    signed = 1 if side == 'sell' else -1
                    if not math.isclose(delta_cash, signed * fill.shares * fill.price - fill.fee, abs_tol=1e-7):
                        raise AssertionError('Trade cash does not reconcile')
                    slip = 0. if not fill.shares else fill.shares * (fill.price - raw_open) * (-signed)
                    role = 'entry' if side == 'buy' and held == 0 else 'exit' if side == 'sell' and weights.get(code, 0.) == 0 else 'resize'
                    fills.append(dict(date=date, ts_code=code, side=side, requested=int(abs(difference)),
                                      shares=fill.shares, raw_open=raw_open, price=fill.price,
                                      fee=fill.fee, slippage_cost=slip, status=fill.status, reason=fill.reason,
                                      cash_after=ledger.cash, role=role, notional=fill.shares * fill.price))
                    day_fees += fill.fee
                    turnover_value += fill.shares * fill.price
                    slippage_cost += slip
        ledger.mark({c: q['close'] for c, q in daily.items()})
        ledger.record(date, actions)
        for issue in rights:
            if issue.record == date:
                rights_entitlements[issue] = ledger.positions[issue.code]
        parts = ledger.components()
        if not math.isclose(parts['cash'], config.initial_cash + recorded_cash_flow, abs_tol=1e-6):
            raise AssertionError('Daily cash flow reconciliation failed')
        if parts['cash'] < -1e-7 or any(n < 0 for n in ledger.positions.values()):
            raise AssertionError('Cash/share constraint violated')
        sector_values = {}
        unknown_industry_value = stale_value = 0.
        for code in set(ledger.positions) | {p['code'] for p in ledger.pending}:
            held, pending = ledger.positions[code], ledger.pending_shares(code)
            if held + pending == 0:
                continue
            value = (held + pending) * ledger.prices[code]
            sector = industries.get(date, {}).get(code, 'UNKNOWN')
            sector_values[sector] = sector_values.get(sector, 0.) + value
            unknown_industry_value += value if sector == 'UNKNOWN' else 0.
            stale_value += value if code not in daily else 0.
            holdings.append(dict(date=date, ts_code=code, shares=held, pending_shares=pending,
                                 mark=ledger.prices[code], value=value, weight=value / parts['equity'], industry=sector))
        max_sector = max((v / parts['equity'] for k, v in sector_values.items() if k != 'UNKNOWN'), default=0.)
        nav.append(dict(date=date, **parts, fees=day_fees, slippage_cost=slippage_cost,
                        turnover=turnover_value / opening_equity, position_count=sum(n > 0 for n in ledger.positions.values()),
                        stale_value=stale_value, unknown_industry_weight=unknown_industry_value / parts['equity'],
                        max_industry_weight=max_sector, industry_target_breached=max_sector > config.industry_cap + 1e-8))
    return dict(nav=pd.DataFrame(nav), orders=pd.DataFrame(fills), holdings=pd.DataFrame(holdings),
                corporate_events=pd.DataFrame(ledger.events),
                reference_guard=pd.DataFrame(guard_checks, columns=[*DAILY_COLUMNS, 'held_shares',
                    'pending_shares', 'planned_positive_weight']))
