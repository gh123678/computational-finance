"""Daily raw-share ledger and weekly target execution; no broker operations."""
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd
from .accounting import Ledger
from .execution import execute_order, FeeSchedule


@dataclass(frozen=True)
class Config:
    initial_cash: float = 1_000_000.
    slippage_bps: float = 10.
    commission: float = .0003
    minimum_commission: float = 5.
    cash_buffer: float = .02
    dividend_tax: float = .20
    participation: float = .005
    industry_cap: float = .25
    zero_trading_costs: bool = False

    def __post_init__(self):
        if not 0 <= self.cash_buffer < 1 or not 0 < self.participation <= 1 or not 0 < self.industry_cap <= 1:
            raise ValueError('Invalid risk configuration')

    def fees(self, date):
        date = pd.Timestamp(date)
        if not pd.Timestamp('2015-08-01') <= date <= pd.Timestamp('2025-12-31'):
            raise ValueError('Fee table restricted to historical research through 2025')
        if self.zero_trading_costs:
            return FeeSchedule(0., 0., 0., 0., 0.)
        return FeeSchedule(self.commission, self.minimum_commission,
                           .001 if date < pd.Timestamp('2023-08-28') else .0005,
                           .00002 if date < pd.Timestamp('2022-04-29') else .00001,
                           self.slippage_bps)


def simulate(bars, calendar, targets, actions=(), suspensions=None, delistings=None,
             industries=None, config=Config(), rebalance_dates=None, rights=()):
    """targets has execution_date, signal_date, ts_code, target_weight.

    ADV capacity comes from sessions preceding execution. A target group means
    rebalance; absent groups mean hold. Explicit zero weights liquidate holdings.
    """
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Calendar must be sorted and unique')
    required = {'trade_date', 'ts_code', 'open', 'close', 'amount', 'vol', 'adj_factor', 'up_limit', 'down_limit'}
    if not required.issubset(bars):
        raise ValueError(f'Missing market fields: {required - set(bars)}')
    bars = bars.copy()
    bars['trade_date'] = pd.to_datetime(bars.trade_date)
    if bars.duplicated(['trade_date', 'ts_code']).any() or not bars.trade_date.isin(calendar).all():
        raise ValueError('Duplicate or off-calendar bars')
    if not np.isfinite(bars[['open', 'close', 'adj_factor', 'amount', 'vol']].to_numpy(float)).all():
        raise ValueError('Missing price/volume data')
    if (bars[['open', 'close', 'adj_factor']] <= 0).any().any() or (bars[['amount', 'vol']] < 0).any().any():
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
    suspension_set = set() if suspensions is None else suspensions
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
    last_adj = {}
    recorded_cash_flow = 0.
    for date in calendar:
        daily = market.get(date, {})
        for code, quote in daily.items():
            if ledger.positions[code] and code in last_adj:
                old_date, old_factor = last_adj[code]
                changed = abs(quote['adj_factor'] / old_factor - 1) > 1e-5
                explained = any(old_date < ex <= date for ex in action_dates.get(code, []))
                if changed and not explained:
                    raise ValueError(f'Unexplained corporate action for held {code} on {date.date()}')
            last_adj[code] = (date, quote['adj_factor'])
        before_cash = ledger.cash
        ledger.morning(date, actions)
        for issue in rights:
            if issue.ex == date and rights_entitlements.get(issue, 0):
                if issue.code not in daily:
                    raise ValueError('Held rights issue needs observed ex-date valuation')
                ledger.events.append(dict(date=date, code=issue.code, event='rights_not_subscribed',
                                          entitled_shares=rights_entitlements[issue], source=issue.source))
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
        sellable = dict(ledger.positions)
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
                corporate_events=pd.DataFrame(ledger.events))


def summarize(nav, orders, first_execution, evaluation_start=None):
    start = nav.index[nav.date.ge(pd.Timestamp(evaluation_start))][0] if evaluation_start else nav.index[nav.date.eq(first_execution)][0]
    if start == 0:
        raise ValueError('Need a pre-execution NAV observation')
    frame = nav.iloc[start-1:].copy()
    equity = frame.equity
    returns = equity.pct_change().dropna()
    drawdown = 1 - equity / equity.cummax()
    trades = orders.loc[orders.shares.gt(0)] if not orders.empty else orders
    result = dict(total_return=float(equity.iloc[-1] / equity.iloc[0] - 1), max_drawdown=float(drawdown.max()),
                sessions=len(returns), start=frame.date.iloc[0].strftime('%Y-%m-%d'), end=frame.date.iloc[-1].strftime('%Y-%m-%d'),
                final_equity=float(equity.iloc[-1]), total_fees=float(frame.fees.sum()),
                total_slippage=float(frame.slippage_cost.sum()), gross_turnover=float(frame.turnover.sum()),
                filled_orders=len(trades), rejected_orders=int(orders.status.eq('rejected').sum()) if not orders.empty else 0,
                industry_breach_days=int(frame.industry_target_breached.sum()),
                stale_valuation_days=int(frame.stale_value.gt(0).sum()),
                average_cash_weight=float((frame.cash / frame.equity).iloc[1:].mean()),
                average_positions=float(frame.position_count.iloc[1:].mean()))
    if len(returns) >= 126:
        volatility = float(returns.std(ddof=1) * np.sqrt(252))
        result.update(annualized_return=float((equity.iloc[-1] / equity.iloc[0]) ** (252 / len(returns)) - 1),
                      annualized_volatility=volatility,
                      sharpe_rf0=float(returns.mean() * 252 / volatility) if volatility > 0 else None)
    else:
        result['annualized_metrics_withheld'] = 'Short engineering window; no annualized performance claim.'
    return result
