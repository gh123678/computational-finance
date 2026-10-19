"""Independent r5 loop: source-versioned rights and cancelled distributions.

Execution, cash, target sizing and retention inherit the frozen r4 semantics.
The core ledger and all preceding adapters remain immutable.
"""
import math
import numpy as np
import pandas as pd
from quant_research.accounting import Ledger as CoreLedger
from quant_research.execution import execute_order
from quant_research.backtest import Config
from dataclasses import asdict
import json
from alphaforge_r3_guard import day, lifecycle_state, suspension_evidence
from alphaforge_r5_guard import (ExposureGuard, AccountDataFailure, share_price_scope,
    obligation_scope, prune_prices)
from alphaforge_r5_events import distribution_view, rights_stage

BASE_BACKTEST_SHA256 = '0dca85c6eac4f8000a5eace03c3e90227d0a78ee738718a12555c96ae284a380'


def _source(view):
    return json.dumps(view.get('sources', []), ensure_ascii=False, default=str)


def _plan_600781(action):
    return action.code == '600781.SH' and action.ex == pd.Timestamp('2019-07-22')


class Ledger(CoreLedger):
    """Preserve research records while invalidating cancelled execution rights."""
    def __init__(self, initial_cash=1_000_000., dividend_tax=.20, *, evidence):
        super().__init__(initial_cash, dividend_tax)
        self.evidence = evidence
        self.as_of = None
        self.cancelled = set()
        self.scenario_entitlements = []
        self.revised_keys = {(v['code'], pd.Timestamp(v['ex']))
                             for v in evidence.get('event_versions', [])}

    def distribution_enabled(self, action, date):
        return ((action.code, action.ex) not in self.revised_keys or
                distribution_view(action, date, self.evidence).get('apply_distribution', True))

    def prepare_day(self, date, actions, rights, guard=None):
        self.as_of = date
        for action in actions:
            if not _plan_600781(action):
                continue
            view = distribution_view(action, date, self.evidence)
            if (view.get('apply_distribution', True) or view.get('unsupported_special', False)
                    or not view.get('pre_open_known', True) or action in self.cancelled):
                continue
            entitled = self.entitlements.pop(action, 0)
            self.cancelled.add(action)
            for item in self.scenario_entitlements:
                if item['code'] == action.code and item['ex_date'] == str(action.ex.date()):
                    item.update(status='cancelled', cancelled_date=str(date.date()),
                                cancellation_known_date=view.get('known_date'),
                                cancellation_source=_source(view))
            self.events.append(dict(date=date, code=action.code, event='distribution_cancelled',
                entitled_shares=entitled, record_date=str(action.record.date()),
                ex_date=str(action.ex.date()), version=view.get('version'),
                known_date=view.get('known_date'), source=_source(view),
                reason='known_plan_cancelled_before_execution'))
        for item in self.pending:
            if not item.get('rights_record') or item.get('stock_pay') is not None:
                continue
            issue = next((r for r in rights if r.code == item['code'] and
                          str(r.record.date()) == item['rights_record']), None)
            if issue is None:
                raise ValueError('Pending subscribed rights lost their frozen source event')
            view = rights_stage(issue, date, self.evidence, stage='listing')
            listed = view.get('list_date')
            if listed is None:
                continue
            listed = pd.Timestamp(listed)
            known = view.get('listing_known_date')
            if (not view.get('stage_usable', False) or
                    (known is not None and pd.Timestamp(known) >= listed)):
                if guard is not None:
                    row=guard.row(issue.code,date,'rights_listing',self)
                    row.update(listing_known_date=known,list_date=str(listed.date()),
                               stage_reason=view.get('reason'),event_sources=_source(view))
                    guard.stop(row,'rights_listing_source_not_usable_before_execution')
                raise ValueError('rights_listing_source_not_usable_before_execution')
            item.update(stock_pay=listed, listing_known_date=known)
            self.events.append(dict(date=date, code=issue.code, event='rights_listing_date_known',
                list_date=str(listed.date()), listing_known_date=known, source=_source(view),
                original_source=issue.source, stage_sources=_source(view),
                record_date=str(issue.record.date()), ex_date=str(issue.ex.date())))

    def record(self, date, actions):
        selected = [a for a in actions if self.distribution_enabled(a, date)]
        super().record(date, selected)
        for action in selected:
            if action.record != date or not _plan_600781(action):
                continue
            view = distribution_view(action, date, self.evidence)
            item = dict(code=action.code, recorded_date=str(date.date()),
                record_date=str(action.record.date()), ex_date=str(action.ex.date()),
                entitled_shares=self.entitlements[action], status='planned',
                version=view.get('version'), known_date=view.get('known_date'), source=_source(view))
            self.scenario_entitlements.append(item)
            self.events.append(dict(date=date, code=action.code, event='distribution_research_record',
                **{k: v for k, v in item.items() if k not in ('code', 'recorded_date', 'status')},
                reason='research_scenario_not_custody'))

    def morning(self, date, actions):
        selected = [a for a in actions if self.distribution_enabled(a, date)]
        unknown = [p for p in self.pending if p['shares'] and p.get('stock_pay') is None]
        self.pending = [p for p in self.pending if p not in unknown]
        try:
            super().morning(date, selected)
        finally:
            self.pending.extend(unknown)


def simulate_exposure(bars, calendar, targets, actions=(), suspensions=None, delistings=None,
                       industries=None, config=Config(), rebalance_dates=None, rights=(), *,
                       universe=None, seed_bars=None, source_hashes=None, full_calendar=None,
                       evidence=None, progress=None):
    """targets has execution_date, signal_date, ts_code, target_weight.

    ADV capacity comes from sessions preceding execution. A target group means
    rebalance; absent groups mean hold. Explicit zero weights liquidate holdings.
    """
    if universe is None:
        raise ValueError('Reference account requires frozen universe lifecycle metadata')
    calendar = pd.DatetimeIndex(calendar)
    actions, rights = tuple(actions), tuple(rights)
    all_codes = set(bars.ts_code)
    if evidence is None or full_calendar is None:
        raise ValueError('r5 requires frozen source evidence and full calendar')
    guard = ExposureGuard(bars, calendar, full_calendar, universe, actions, rights,
                          suspensions, evidence)
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
            lifecycle_status = lifecycle_state(execution, listings[row.ts_code], delistings[row.ts_code])
            if lifecycle_status != 'listed' or execution == listings[row.ts_code]:
                raise ValueError('Target attempts lifecycle-ineligible or initial-listing purchase')
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Calendar must be sorted and unique')
    required = {'trade_date', 'ts_code', 'open', 'close', 'amount', 'vol', 'close_text', 'pre_close_text', 'up_limit', 'down_limit'}
    if not required.issubset(bars):
        raise ValueError(f'Missing market fields: {required - set(bars)}')
    bars = bars.copy()
    bars['trade_date'] = pd.to_datetime(bars.trade_date)
    if bars.duplicated(['trade_date', 'ts_code']).any() or not bars.trade_date.isin(full_calendar).all():
        raise ValueError('Duplicate or off-calendar bars')
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
    market = {d: g.set_index('ts_code').to_dict('index') for d, g in bars.loc[bars.trade_date.isin(calendar)].groupby('trade_date')}
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
    ledger = Ledger(config.initial_cash, config.dividend_tax, evidence=evidence)
    nav, fills, holdings, obligations = [], [], [], []
    recorded_cash_flow = 0.
    last_completed_state = state(ledger, rights_entitlements)
    try:
        for date in calendar:
            daily = market.get(date, {})
            ledger.prepare_day(date, actions, rights, guard)
            price_scope = share_price_scope(ledger, actions, rights_entitlements)
            economic_scope = obligation_scope(ledger, rights_entitlements)
            planned = plans.get(date, {})
            signals = targets.loc[targets.execution_date.eq(date)].set_index('ts_code').signal_date.to_dict()
            for code in sorted(price_scope | economic_scope | {c for c, w in planned.items() if w > 0}):
                guard.check_day(code, date, ledger,
                    planned_signal=signals.get(code) if planned.get(code, 0) > 0 else None,
                    rights_entitlements=rights_entitlements)
            prune_prices(ledger, actions, rights_entitlements)
            before_cash = ledger.cash
            for issue in rights:
                if issue.ex == date and rights_entitlements.get(issue, 0):
                    guard.require_rights_stage(issue, date, ledger, 'subscription')
            ledger.morning(date, actions)
            for issue in rights:
                if issue.ex == date and rights_entitlements.get(issue, 0):
                    if issue.code not in daily:
                        raise ValueError('Held rights issue needs observed ex-date valuation')
                    entitled = rights_entitlements[issue]
                    stage = rights_stage(issue, date, evidence, stage='subscription')
                    if stage.get('price') is not None:
                        allotted = math.floor(entitled * stage['quota_ratio'] + 1e-8)
                        cost = round(allotted * stage['price'], 2)
                        if allotted and ledger.cash >= cost - 1e-8:
                            ledger.cash = round(ledger.cash - cost, 2)
                            listed = stage.get('list_date')
                            listed = None if listed is None else pd.Timestamp(listed)
                            pending = dict(code=issue.code, cash=0., shares=allotted,
                                           cash_pay=pd.NaT, stock_pay=listed,
                                           lock_on_settlement=True)
                            if issue.code in ('000977.SZ', '600999.SH'):
                                pending.update(rights_record=str(issue.record.date()),
                                    rights_ex=str(issue.ex.date()), quota_ratio=stage['quota_ratio'],
                                    market_ex_ratio=stage.get('market_ex_ratio'),
                                    listing_known_date=stage.get('listing_known_date'))
                            ledger.pending.append(pending)
                            ledger.events.append(dict(date=date, code=issue.code, event='rights_subscribed',
                                                      entitled_shares=entitled, allotted_shares=allotted,
                                                      price=stage['price'], ratio=stage['quota_ratio'], cost=cost,
                                                      market_ex_ratio=stage.get('market_ex_ratio'),
                                                      terms_known_date=stage.get('terms_known_date'),
                                                      result_known_date=stage.get('result_known_date'),
                                                      listing_known_date=stage.get('listing_known_date'),
                                                      list_date=None if listed is None else str(listed.date()),
                                                      source=issue.source, original_source=issue.source,
                                                      stage_sources=_source(stage),
                                                      research_scenario='ex_date_subscription_floor_not_custody',
                                                      personal_actual_allocation_certified=False))
                        else:
                            ledger.events.append(dict(date=date, code=issue.code, event='rights_not_subscribed',
                                                      entitled_shares=entitled, reason='insufficient_cash',
                                                      source=issue.source, original_source=issue.source,
                                                      stage_sources=_source(stage)))
                    else:
                        ledger.events.append(dict(date=date, code=issue.code, event='rights_not_subscribed',
                                                  entitled_shares=entitled, source=issue.source,
                                                  original_source=issue.source, stage_sources=_source(stage)))
                        # No cash paid, no new shares credited. Raw market prices retain
                        # the dilution loss; an adjusted return must not erase it.
            rights_entitlements = {r: n for r, n in rights_entitlements.items() if r.ex > date and n}
            recorded_cash_flow += ledger.cash - before_cash
            for code, delist_date in delistings.items():
                if pd.notna(delist_date) and date >= delist_date:
                    ledger.write_off(date, code)
            mark_scope = share_price_scope(ledger, actions, rights_entitlements) | {c for c,w in planned.items() if w > 0}
            ledger.mark({c: q['open'] for c, q in daily.items() if c in mark_scope})
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
                    if code not in daily and weights.get(code, 0.) > 0 and not ledger.positions.get(code, 0):
                        # A rejected request may cite the last actual raw close for
                        # its quantity. It is never stored as an asset price.
                        last_day, last_quote = guard.previous(code, date)
                        price = None if last_quote is None else float(last_quote['close'])
                        request = 0 if price is None or not math.isfinite(price) or price <= 0 else math.floor(opening_equity * weights[code] / price / 100) * 100
                        fills.append(dict(date=date, ts_code=code, side='buy', requested=request,
                            shares=0, raw_open=np.nan, price=0., fee=0., slippage_cost=0.,
                            status='rejected', reason='missing_execution_quote', cash_after=ledger.cash,
                            role='entry', notional=0., quantity_unknown=price is None,
                            sizing_quote_date=last_day))
                        continue
                    if price is None:
                        raise ValueError(f'Cannot size exposed target {code} without a price')
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
            mark_scope = share_price_scope(ledger, actions, rights_entitlements)
            ledger.mark({c: q['close'] for c, q in daily.items() if c in mark_scope})
            ledger.record(date, actions)
            for issue in rights:
                if issue.record == date:
                    if ledger.positions[issue.code]:
                        guard.require_rights_stage(issue, date, ledger, 'record')
                    rights_entitlements[issue] = ledger.positions[issue.code]
            prune_prices(ledger, actions, rights_entitlements)
            obligations.extend(obligation_rows(date, ledger, rights_entitlements))
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
            last_completed_state = state(ledger, rights_entitlements)
            if progress is not None and len(nav) % 50 == 0:
                progress(date, len(nav))
    except Exception as error:
        partial = result_tables(nav, fills, holdings, ledger, guard, obligations, rights_entitlements)
        partial['failure_state'] = partial['account_state']
        partial['account_state'] = last_completed_state
        completed_dates = set(partial['nav'].date)
        for name in ('orders', 'holdings', 'corporate_events', 'obligations'):
            frame = partial[name]
            failed_day = frame.loc[~frame.date.isin(completed_dates)]
            if not failed_day.empty:
                partial['failure_day_'+name] = failed_day
                partial[name] = frame.loc[frame.date.isin(completed_dates)].copy()
        raise AccountRunFailure(error, date, partial) from error
    return result_tables(nav, fills, holdings, ledger, guard, obligations, rights_entitlements)


class AccountRunFailure(RuntimeError):
    def __init__(self, error, date, partial):
        self.original = error
        self.date = date
        self.partial = partial
        super().__init__(str(error))


def plain(value):
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    if value is None or value is pd.NaT:
        return None
    return value


def state(ledger, rights):
    right_rows = []
    for issue, count in rights.items():
        if not count:
            continue
        view = rights_stage(issue, ledger.as_of, ledger.evidence, stage='record')
        listed = view.get('list_date')
        right_rows.append(dict(code=issue.code, record=str(issue.record.date()),
            ex=str(issue.ex.date()), source=issue.source, price=view.get('price'),
            original_source=issue.source, stage_sources=_source(view),
            ratio=view.get('quota_ratio'), market_ex_ratio=view.get('market_ex_ratio'),
            list_date=None if listed is None else str(pd.Timestamp(listed).date()),
            terms_known_date=view.get('terms_known_date'),
            result_known_date=view.get('result_known_date'),
            listing_known_date=view.get('listing_known_date'), entitled_shares=count))
    return dict(cash=ledger.cash, positions={c:n for c,n in ledger.positions.items() if n},
        prices=dict(ledger.prices), pending=[{k:plain(v) for k,v in p.items()} for p in ledger.pending],
        unapplied_distributions=[dict(**{k:plain(v) for k,v in asdict(a).items()}, entitled_shares=n)
            for a,n in ledger.entitlements.items() if n and a not in ledger.applied],
        unapplied_rights=right_rows,
        scenario_entitlements=[dict(item) for item in ledger.scenario_entitlements],
        cancelled_distributions=[{k:plain(v) for k,v in asdict(a).items()}
            for a in sorted(ledger.cancelled, key=lambda a:(a.ex,a.code))])


def obligation_rows(date, ledger, rights):
    snapshot = state(ledger, rights)
    rows=[]
    for key,kind in [('unapplied_distributions','unapplied_distribution'),
                     ('unapplied_rights','unapplied_rights'),('pending','pending')]:
        for value in snapshot[key]:
            rows.append(dict(date=date, code=value['code'], kind=kind,
                             payload=json.dumps(value, ensure_ascii=False)))
    return rows


def result_tables(nav, fills, holdings, ledger, guard, obligations, rights):
    return dict(nav=pd.DataFrame(nav, columns=['date','cash','stock_value','bonus_value','receivable','equity',
            'fees','slippage_cost','turnover','position_count','stale_value','unknown_industry_weight',
            'max_industry_weight','industry_target_breached']),
        orders=pd.DataFrame(fills, columns=['date','ts_code','side','requested','shares','raw_open','price',
            'fee','slippage_cost','status','reason','cash_after','role','notional','quantity_unknown','sizing_quote_date']),
        holdings=pd.DataFrame(holdings, columns=['date','ts_code','shares','pending_shares','mark','value','weight','industry']),
        corporate_events=pd.DataFrame(ledger.events, columns=['date','code','event','entitled_shares','gross_cash',
            'assumed_tax','bonus_shares','fractional_shares_discarded','cash','shares','allotted_shares',
            'price','ratio','cost','list_date','source','reason','record_date','ex_date','version','known_date',
            'market_ex_ratio','terms_known_date','result_known_date','listing_known_date',
            'original_source','stage_sources','research_scenario','personal_actual_allocation_certified']),
        reference_guard=pd.DataFrame(guard.trace),
        obligations=pd.DataFrame(obligations, columns=['date','code','kind','payload']),
        account_state=state(ledger,rights))
