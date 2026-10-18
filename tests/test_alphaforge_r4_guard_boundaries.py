"""Independent boundary review of source mapping versus the actual guard."""
from copy import deepcopy

import pandas as pd
import pytest

from alphaforge_r4_evidence import build_evidence
from alphaforge_r4_account import simulate_exposure
from alphaforge_r4_guard import (AccountDataFailure, ExposureGuard, obligation_scope,
                                prune_prices, share_price_scope)
from quant_research.accounting import Action, Ledger
from quant_research.backtest import Config
from quant_research.rights import RightsIssue


@pytest.fixture(scope='module')
def evidence():
    return build_evidence()


def bars_for(code, dates, price=10.):
    return pd.DataFrame([dict(ts_code=code, trade_date=pd.Timestamp(date), open=price,
        high=price, low=price, close=price, vol=10000., amount=10000.,
        close_text=str(price), pre_close_text=str(price)) for date in dates])


def guard_for(code, bars, dates, evidence, actions=(), suspensions=None):
    meta = pd.DataFrame([dict(ts_code=code, list_date='20100101', delist_date=None)])
    return ExposureGuard(bars, pd.DatetimeIndex(dates), pd.DatetimeIndex(dates), meta,
                         actions, (), suspensions, evidence)


def holding(code):
    ledger = Ledger(10000.)
    ledger.positions[code] = 100
    ledger.prices[code] = 10.
    return ledger


def test_real_source_string_amounts_match_float_action_across_known_pause(evidence):
    # Real mapping stores Decimal-safe strings, unlike earlier numeric fixtures.
    code = '000756.SZ'
    dates = pd.DatetimeIndex(['2018-01-24', '2018-01-25', '2018-01-26'])
    bars = bars_for(code, dates[:1])
    action = Action(code, dates[1], dates[2], dates[2], pd.NaT, .03)
    ledger = holding(code)
    ledger.record(dates[1], [action])
    guard = guard_for(code, bars, dates, evidence, [action],
                      {(date, code) for date in dates[1:]})
    assert guard.check_day(code, dates[2], ledger)
    assert guard.trace[-1]['reason'] == 'stale_ordinary_action_scenario'
    assert guard.trace[-1]['theoretical_stale_mark'] == 9.97


def test_source_amount_mismatch_is_not_tolerated_even_during_daily_S(evidence):
    code = '000756.SZ'
    dates = pd.DatetimeIndex(['2018-01-24', '2018-01-25', '2018-01-26'])
    action = Action(code, dates[1], dates[2], dates[2], pd.NaT, .030000000000000002)
    ledger = holding(code)
    ledger.record(dates[1], [action])
    guard = guard_for(code, bars_for(code, dates[:1]), dates, evidence, [action],
                      {(date, code) for date in dates[1:]})
    with pytest.raises(AccountDataFailure, match='distribution_source_terms_conflict'):
        guard.check_day(code, dates[2], ledger)


def test_same_day_public_restoration_is_not_preopen_proof_despite_quoted_bar(evidence):
    code = '000950.SZ'
    dates = pd.DatetimeIndex(['2018-08-27', '2018-08-28'])
    guard = guard_for(code, bars_for(code, dates), dates, evidence)
    with pytest.raises(AccountDataFailure, match='uncertain'):
        guard.check_day(code, dates[-1], holding(code))


def test_same_day_pause_uncertainty_cannot_be_hidden_by_original_S(evidence):
    code = '000760.SZ'
    dates = pd.DatetimeIndex(['2020-07-03', '2020-07-06'])
    guard = guard_for(code, bars_for(code, dates[:1]), dates, evidence,
                      suspensions={(dates[-1], code)})
    with pytest.raises(AccountDataFailure, match='uncertain'):
        guard.check_day(code, dates[-1], holding(code))


def test_same_day_uncertain_restore_rejects_entry_with_quote(evidence):
    code = '000950.SZ'
    dates = pd.DatetimeIndex(['2018-08-27', '2018-08-28'])
    guard = guard_for(code, bars_for(code, dates), dates, evidence)
    with pytest.raises(AccountDataFailure, match='uncertain'):
        guard.check_day(code, dates[-1], Ledger(10000.), planned_signal=dates[0])


def test_cash_only_receivable_needs_no_quote_or_ghost_price_but_still_settles():
    code = 'A'
    dates = pd.bdate_range('2020-01-02', periods=3)
    ledger = Ledger(10000.)
    ledger.prices[code] = 10.
    ledger.pending.append(dict(code=code, cash=80., shares=0,
                               cash_pay=dates[-1], stock_pay=pd.NaT))
    assert share_price_scope(ledger, ()) == set()
    assert obligation_scope(ledger) == {code}
    prune_prices(ledger, ())
    assert ledger.prices == {}
    guard = guard_for(code, bars_for(code, dates[:1]), dates,
                      dict(ordinary_actions=[], status_events=[]))
    assert guard.check_day(code, dates[-1], ledger)
    assert guard.trace[-1]['reason'] == 'cash_obligation_no_stock_valuation'
    ledger.morning(dates[-1], ())
    assert ledger.cash == 10080. and ledger.receivable == 0.
    assert ledger.positions.get(code, 0) == 0 and ledger.prices == {}


def test_pending_stock_is_price_exposure_and_unexplained_gap_stops():
    code = 'A'
    dates = pd.bdate_range('2020-01-02', periods=3)
    ledger = Ledger(10000.)
    ledger.prices[code] = 10.
    ledger.pending.append(dict(code=code, cash=0., shares=30,
                               cash_pay=pd.NaT, stock_pay=dates[-1]))
    assert share_price_scope(ledger, ()) == {code}
    guard = guard_for(code, bars_for(code, dates[:1]), dates,
                      dict(ordinary_actions=[], status_events=[]))
    with pytest.raises(AccountDataFailure, match='missing_quote_without_asof_nontrade_evidence'):
        guard.check_day(code, dates[1], ledger)


def test_unexecuted_stock_entitlement_keeps_price_until_listing_even_if_sold():
    code = 'A'
    dates = pd.bdate_range('2020-01-02', periods=3)
    ledger = holding(code)
    action = Action(code, dates[0], dates[1], pd.NaT, dates[-1], 0., .3)
    ledger.record(dates[0], [action])
    ledger.positions[code] = 0
    prune_prices(ledger, [action])
    assert ledger.prices[code] == 10.
    ledger.morning(dates[1], [action])
    assert ledger.pending_shares(code) == 30
    assert ledger.prices[code] == 10. / 1.3
    ledger.morning(dates[-1], [action])
    assert ledger.positions[code] == 30 and ledger.pending_shares(code) == 0


def test_future_restoration_end_never_licenses_prior_pause_quote(evidence):
    code = '000629.SZ'
    dates = pd.DatetimeIndex(['2018-08-14', '2018-08-15'])
    changed = deepcopy(evidence)
    # The future announcement is deliberately changed; known date remains future.
    restore = next(item for item in changed['status_events']
                   if item['code'] == code and item['state'] == 'listed')
    restore['effective_date'] = '2017-01-01'
    for source in (evidence, changed):
        guard = guard_for(code, bars_for(code, dates), dates, source)
        with pytest.raises(AccountDataFailure, match='quote_conflicts_with_official_nontrade_state'):
            guard.check_day(code, dates[-1], holding(code))


def test_unexecuted_cash_entitlement_cannot_bypass_cross_gap_source_gate_after_sale():
    code = 'A'
    dates = pd.bdate_range('2020-01-02', periods=3)
    ledger = holding(code)
    action = Action(code, dates[0], dates[1], dates[-1], pd.NaT, 1.)
    ledger.record(dates[0], [action])
    ledger.positions[code] = 0
    prune_prices(ledger, [action])
    assert not ledger.prices
    guard = guard_for(code, bars_for(code, dates[:1]), dates,
                      dict(ordinary_actions=[], status_events=[]), [action],
                      suspensions={(dates[1], code)})
    with pytest.raises(AccountDataFailure, match='unreviewed_distribution_across_quote_gap'):
        guard.check_day(code, dates[1], ledger)


def test_known_full_terms_rights_listing_on_S_day_releases_shares_but_cannot_sell():
    dates = pd.bdate_range('2020-01-02', periods=12)
    code = 'A'
    bars = bars_for(code, dates)
    bars['up_limit'], bars['down_limit'] = 20., 1.
    targets = pd.DataFrame([
        dict(execution_date=dates[2], signal_date=dates[1], ts_code=code, target_weight=.5),
        dict(execution_date=dates[7], signal_date=dates[6], ts_code=code, target_weight=0.),
    ])
    issue = RightsIssue(code, dates[3], dates[4], 'source-bound original terms',
                        price=5., ratio=.3, list_date=dates[7])
    bars.loc[bars.trade_date >= issue.ex, ['open', 'high', 'low', 'close']] = 8.
    bars.loc[bars.trade_date >= issue.ex, ['close_text', 'pre_close_text']] = '8.0'
    bars = bars.loc[bars.trade_date != issue.list_date].copy()
    meta = pd.DataFrame([dict(ts_code=code, list_date='20100101', delist_date=None)])
    result = simulate_exposure(bars, dates, targets, rights=[issue],
        universe=meta, full_calendar=dates, suspensions={(issue.list_date, code)},
        evidence=dict(ordinary_actions=[], status_events=[]),
        config=Config(initial_cash=10000., zero_trading_costs=True))
    subscribed = result['corporate_events'].loc[result['corporate_events'].event == 'rights_subscribed'].iloc[0]
    assert subscribed.allotted_shares == 150 and subscribed.cost == 750.
    listed = result['holdings'].loc[result['holdings'].date == issue.list_date].iloc[0]
    assert listed.shares == 650 and listed.pending_shares == 0
    order = result['orders'].loc[result['orders'].date == issue.list_date].iloc[0]
    assert order.side == 'sell' and order.status == 'rejected' and order.reason == 'suspended'
    assert result['account_state']['positions'][code] == 650
