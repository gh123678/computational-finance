"""Economic and execution boundary tests; no cached strategy run is launched."""
import math
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from momentum_g2_account import AccountFailure, OrdinaryLedger, fees_for, simulate_account
from momentum_g2_events import EventBook


CODE = '000001.SZ'


def case(end='2018-01-19'):
    dates = pd.bdate_range('2017-11-20', end)
    bars = pd.DataFrame(dict(trade_date=dates, ts_code=CODE, open=10., high=10.,
        low=10., close=10., pre_close=10., vol=1_000_000., amount=100_000.,
        up_limit=11., down_limit=9.))
    formation, execution = pd.Timestamp('2017-12-29'), pd.Timestamp('2018-01-01')
    schedule = pd.DataFrame([dict(signal_date=formation, execution_date=execution)])
    targets = schedule.assign(ts_code=CODE, target_weight=.049)
    universe = pd.DataFrame([dict(ts_code=CODE, list_date='20100101', delist_date=None)])
    return dict(bars=bars, full_calendar=dates, schedule=schedule, targets=targets,
                event_book=EventBook(dates), universe=universe, cost_bps=0)


def run(item, **overrides):
    return simulate_account(**dict(item, **overrides))


def add_plan(item, formation, execution, weight=.049):
    row = dict(signal_date=pd.Timestamp(formation), execution_date=pd.Timestamp(execution))
    item['schedule'] = pd.concat([item['schedule'], pd.DataFrame([row])], ignore_index=True)
    item['targets'] = pd.concat([item['targets'], pd.DataFrame([dict(row, ts_code=CODE, target_weight=weight)])], ignore_index=True)


def action(item, *, identity='ordinary-one', known='2017-12-20', record='2018-01-03',
           ex='2018-01-04', pay='2018-01-10', listing='2018-01-10', D=1., s=.1, bonus=.05,
           **extra):
    result = dict(code=CODE, event_id=identity, known_date=known, record=record, ex=ex,
        cash_pay=pay, stock_pay=listing, cash_per_share=D, stock_per_share=s,
        taxable_bonus_per_share=bonus, kind='ordinary', sources=[dict(role='frozen_fixture')])
    result.update(extra)
    return result


def set_action_prices(item, ex, D, s):
    new = (10. - D) / (1 + s)
    mask = item['bars'].trade_date.ge(pd.Timestamp(ex))
    item['bars'].loc[mask, ['open', 'high', 'low', 'close']] = new
    item['bars'].loc[mask, 'pre_close'] = round(new, 2)
    item['bars'].loc[mask, 'up_limit'] = math.ceil(new * 1.1 * 100) / 100
    item['bars'].loc[mask, 'down_limit'] = math.floor(new * .9 * 100) / 100


def test_formation_quantity_is_fixed_even_when_open_and_equity_change():
    item = case()
    day = item['schedule'].execution_date.iloc[0]
    item['bars'].loc[item['bars'].trade_date.eq(day), ['open', 'close']] = 10.5
    item['bars'].loc[item['bars'].trade_date.eq(day + pd.offsets.BDay()), 'pre_close'] = 10.5
    result = run(item)
    intent = result['intents'].iloc[0]
    order = result['orders'].iloc[0]
    assert intent.target_total_shares == intent.requested_formation_shares == 4900
    assert order.requested == order.shares == 4900
    assert order.notional == 51450.
    assert intent.equity_at_formation == 1_000_000.
    assert result['nav'].iloc[0].equity == 1_000_000.


def test_single_day_veto_expires_no_later_replay_and_initial_denominator_stays_980k():
    item = case()
    execution = item['schedule'].execution_date.iloc[0]
    item['bars'].loc[item['bars'].trade_date.eq(execution), ['vol', 'amount']] = 0.
    result = run(item)
    assert len(result['orders']) == 1 and result['orders'].iloc[0].shares == 0
    assert result['orders'].iloc[0].reason == 'final_zero_volume_veto'
    assert result['holdings'].empty
    assert result['intents'].iloc[0].status == 'expired'
    assert result['deployment'].iloc[0].denominator_cny == 980000.
    assert result['deployment'].iloc[0].unconditional_completion == 0.
    assert result['deployment'].iloc[0].whole_lot_plan_coverage == .05


def test_new_week_is_new_plan_and_cannot_complete_the_first_deployment():
    item = case()
    first = item['schedule'].execution_date.iloc[0]
    item['bars'].loc[item['bars'].trade_date.eq(first), 'open'] = 11.
    add_plan(item, '2018-01-05', '2018-01-08')
    result = run(item)
    assert result['orders'].shares.tolist() == [0, 4900]
    assert result['deployment'].iloc[0].unconditional_completion == 0.
    assert result['orders'].plan_id.nunique() == 2


def test_suspended_incomplete_adv_rejects_but_unexplained_missing_adv_stops():
    item = case()
    add_plan(item, '2018-01-05', '2018-01-08', 0.)
    missing = pd.Timestamp('2018-01-04')
    item['bars'] = item['bars'].loc[item['bars'].trade_date.ne(missing)]
    with pytest.raises(AccountFailure, match='Missing exposed'):
        run(item)
    result = run(item, suspensions={(missing, CODE)})
    exit_order = result['orders'].iloc[-1]
    assert exit_order.shares == 0
    assert exit_order.reason == 'incomplete_adv_registered_suspension'
    assert result['holdings'].iloc[-1].shares == 4900
    assert result['exit_episodes'].iloc[0].status == 'right_censored'


def test_formation_adv_is_twenty_complete_sessions_and_thousand_unit_once():
    item = case()
    formation = item['schedule'].signal_date.iloc[0]
    item['bars'].loc[item['bars'].trade_date.eq(formation), 'amount'] = 120000.
    execution = item['schedule'].execution_date.iloc[0]
    item['bars'].loc[item['bars'].trade_date.eq(execution), 'amount'] = 999999999.
    result = run(item)
    assert result['intents'].iloc[0].adv20_cny == 101000000.
    assert result['orders'].iloc[0].capacity_cny == 505000.


def test_cash_bonus_real_floor_tax_ar_and_unlisted_are_separate():
    item = case()
    row = action(item, s=.1001)
    item['event_book'] = EventBook(item['full_calendar'], [row])
    set_action_prices(item, row['ex'], 1., .1001)
    result = run(item)
    ex = result['corporate_events'].loc[lambda x: x.event.eq('ex')].iloc[0]
    assert ex.entitled_shares == 4900 and ex.bonus_shares == 490
    assert ex.gross_cash == 4900. and ex.assumed_tax == 1029.
    assert ex.fractional_shares_discarded == pytest.approx(.49)
    snapshot = result['nav'].loc[lambda x: x.date.eq(pd.Timestamp(row['ex']))].iloc[0]
    assert snapshot.cash == 951000. and snapshot.receivable == 3871.
    assert snapshot.bonus_value > 0
    settle = result['corporate_events'].loc[lambda x: x.event.eq('cash_settlement')].iloc[0]
    assert settle.cash_delta == 3871. and settle.receivable_delta == -3871.
    assert result['holdings'].iloc[-1].shares == 5390
    assert result['nav'].iloc[-1].receivable == 0.


def test_u_offsets_target_and_u_transfer_is_not_bought_again():
    item = case()
    row = action(item, D=0., s=.1, bonus=0., listing='2018-01-12')
    item['event_book'] = EventBook(item['full_calendar'], [row])
    set_action_prices(item, row['ex'], 0., .1)
    add_plan(item, '2018-01-05', '2018-01-08')
    result = run(item)
    resize = result['intents'].iloc[1]
    assert resize.formation_listed_shares == 4900
    assert resize.formation_unlisted_shares == 490
    assert resize.target_total_shares == 5300
    assert resize.requested_formation_shares == 0  # 90 shares do not form a sell lot
    assert len(result['orders']) == 1
    assert result['holdings'].iloc[-1].shares == 5390


def test_u_stays_in_exit_denominator_and_later_week_cannot_rewrite_first_intent():
    item = case()
    row = action(item, D=0., s=.1, bonus=0., listing='2018-01-12')
    item['event_book'] = EventBook(item['full_calendar'], [row])
    set_action_prices(item, row['ex'], 0., .1)
    add_plan(item, '2018-01-05', '2018-01-08', 0.)
    add_plan(item, '2018-01-12', '2018-01-15', 0.)
    result = run(item)
    episode = result['exit_episodes'].iloc[0]
    assert episode.frozen_total_shares == 5390 and episode.frozen_unlisted_shares == 490
    assert episode.first_intent_completion == pytest.approx(4900 / 5390)
    assert episode.risk_closed_date == pd.Timestamp('2018-01-15')
    assert episode.securities_risk_closed
    assert result['orders'].iloc[-1].shares == 490  # real odd-lot liquidation
    assert episode.first_plan_id != result['orders'].iloc[-1].plan_id


def test_source_future_perturbation_leaves_past_formation_and_state_unchanged():
    item = case(end='2018-01-05')
    row = action(item, known='2018-01-10', record='2018-01-11', ex='2018-01-12')
    one = run(item, event_book=EventBook(item['full_calendar'], [row]))
    row['stock_per_share'] = .9
    two = run(item, event_book=EventBook(item['full_calendar'], [row]))
    pd.testing.assert_frame_equal(one['nav'], two['nav'])
    pd.testing.assert_frame_equal(one['intents'], two['intents'])


def test_cancelled_before_ex_creates_no_cash_shares_or_completion():
    item = case()
    row = action(item)
    cancel = dict(row, known_date='2018-01-04', kind='cancelled', status='cancelled', version=2)
    item['event_book'] = EventBook(item['full_calendar'], [row, cancel])
    result = run(item)
    assert result['corporate_events'].event.tolist() == ['record', 'cancelled']
    assert result['nav'].receivable.eq(0.).all()
    assert result['holdings'].iloc[-1].shares == 4900


def test_unsupported_future_or_conflicting_actual_exposure_stops_with_partial():
    item = case()
    row = action(item, known='2018-01-03', kind='unsupported')
    # action helper's default kind must be replaced after construction.
    row['kind'] = 'unsupported'
    item['event_book'] = EventBook(item['full_calendar'], [row])
    with pytest.raises(AccountFailure, match='Undefined/conflicting') as found:
        run(item)
    assert found.value.date == pd.Timestamp('2018-01-03')
    assert found.value.partial_result['nav'].date.max() == pd.Timestamp('2018-01-02')
    assert found.value.partial_result['account_state']['positions'][CODE] == 4900


def test_no_source_and_late_known_registration_are_not_ordinary_zero_defaults():
    item = case()
    row = action(item)
    row['sources'] = []
    with pytest.raises(AccountFailure, match='source'):
        run(item, event_book=EventBook(item['full_calendar'], [row]))
    row = action(item, known='2018-01-04')
    with pytest.raises(AccountFailure, match='unavailable by registration|unavailable/future provenance'):
        run(item, event_book=EventBook(item['full_calendar'], [row]))


def test_form_to_execution_conversion_is_frozen_and_original_units_counted():
    item = case()
    # The initial plan is formed before an ordinary stock split; only 5000
    # shares can be requested in new units after lot rounding of 4900*1.03.
    row = action(item, record='2017-12-29', ex='2018-01-01', D=0., s=.03, bonus=0.)
    item['event_book'] = EventBook(item['full_calendar'], [row])
    set_action_prices(item, row['ex'], 0., .03)
    result = run(item)
    order = result['orders'].iloc[0]
    assert order.requested == 5000
    assert order.formation_equivalent_shares == pytest.approx(5000 / 1.03)
    assert result['deployment'].iloc[0].filled_formation_reference_cny == pytest.approx(5000 / 1.03 * 10)


def test_newly_known_conversion_cannot_reinterpret_frozen_request():
    item = case()
    row = action(item, known='2018-01-01', record='2017-12-29', ex='2018-01-01', D=0., s=.03, bonus=0.)
    set_action_prices(item, row['ex'], 0., .03)
    with pytest.raises(AccountFailure, match='unavailable by registration|unavailable/future provenance'):
        run(item, event_book=EventBook(item['full_calendar'], [row]))


def test_effective_delisting_does_not_cash_out_last_quote():
    item = case()
    item['universe']['delist_date'] = '20180105'
    with pytest.raises(AccountFailure, match='no last-price cash-out') as found:
        run(item)
    state = found.value.partial_result['account_state']
    assert state['cash'] == 951000. and state['positions'][CODE] == 4900


@pytest.mark.parametrize('bps', [0, 10, 30])
def test_frozen_transaction_scenario_and_float_half_cent_order(bps):
    item = case()
    result = run(item, cost_bps=bps)
    order = result['orders'].iloc[0]
    fee = fees_for(bps)
    assert order.fee == fee.cost(order.notional, 'buy')
    assert order.cash_after == round(1_000_000. - order.notional - order.fee, 2)
    assert fee.cost(16666.67, 'buy') == (0. if bps == 0 else 5.33)
    assert round(2.675, 2) == 2.67


def test_exit_reversal_keeps_same_episode_and_right_censoring():
    item = case(end='2018-01-11')
    add_plan(item, '2018-01-05', '2018-01-08', 0.)
    item['bars'].loc[item['bars'].trade_date.eq(pd.Timestamp('2018-01-08')), 'open'] = 9.
    add_plan(item, '2018-01-09', '2018-01-10', .049)
    result = run(item)
    episode = result['exit_episodes'].iloc[0]
    assert len(result['exit_episodes']) == 1
    assert episode.first_intent_completion == 0.
    assert episode.reversal_date == pd.Timestamp('2018-01-09')
    assert not episode.complete_five_session_window and not episode.securities_risk_closed


def test_cash_receivable_survives_securities_exit_without_daily_price_dependency():
    item = case()
    row = action(item, D=1., s=0., bonus=0.)
    item['event_book'] = EventBook(item['full_calendar'], [row])
    set_action_prices(item, row['ex'], 1., 0.)
    add_plan(item, '2018-01-03', '2018-01-04', 0.)
    item['bars'] = item['bars'].loc[~item['bars'].trade_date.between('2018-01-05', '2018-01-09')]
    result = run(item)
    assert result['exit_episodes'].iloc[0].settlement_receivable_at_risk_close == 3920.
    assert result['nav'].iloc[-1].cash == 999020.
    assert result['nav'].iloc[-1].receivable == 0.


def test_cash_and_shares_are_continuous_across_year_boundary():
    item = case(end='2019-01-04')
    result = run(item)
    year_end = result['nav'].loc[lambda x: x.date.eq(pd.Timestamp('2018-12-31'))].iloc[0]
    year_start = result['nav'].loc[lambda x: x.date.eq(pd.Timestamp('2019-01-01'))].iloc[0]
    assert year_end.cash == year_start.cash == 951000.
    assert year_end.stock_value == year_start.stock_value == 49000.


def test_same_target_weekly_resize_uses_actual_cost_specific_equity():
    item = case()
    add_plan(item, '2018-01-05', '2018-01-08')
    zero = run(item)
    paid = run(item, cost_bps=30)
    assert zero['intents'].iloc[1].target_total_shares == 4900
    assert paid['intents'].iloc[1].equity_at_formation < 1_000_000.
    assert paid['intents'].iloc[1].target_total_shares == 4800
    assert paid['orders'].iloc[-1].side == 'sell' and paid['orders'].iloc[-1].shares == 100


def test_sell_before_buy_and_exact_frozen_cash_buffer_with_twenty_slots():
    item = case()
    codes = [f'{i:06d}.SZ' for i in range(1, 21)]
    template = item['bars'].copy()
    item['bars'] = pd.concat([template.assign(ts_code=c) for c in codes], ignore_index=True)
    item['targets'] = pd.concat([item['targets'].assign(ts_code=c) for c in codes], ignore_index=True)
    item['universe'] = pd.DataFrame([dict(ts_code=c, list_date='20100101', delist_date=None) for c in codes])
    result = run(item, cost_bps=30)
    assert len(result['orders']) == 20
    assert result['nav'].cash.min() >= 20000.
    assert result['orders'].ts_code.tolist() == sorted(codes)
    assert result['orders'].iloc[-1].shares < result['orders'].iloc[-1].requested


def test_two_raw_ordinary_events_never_sum_economics():
    item = case()
    one, two = action(item), action(item, identity='different-source-same-effective', D=.5)
    with pytest.raises(AccountFailure, match='Multiple ordinary'):
        run(item, event_book=EventBook(item['full_calendar'], [one, two]))


def test_late_listing_is_unknown_until_source_available_and_is_not_prespent():
    item = case()
    one = action(item, D=0., bonus=0., listing=None)
    two = dict(one, known_date='2018-01-10', stock_pay='2018-01-12', version=2)
    item['event_book'] = EventBook(item['full_calendar'], [one, two])
    set_action_prices(item, one['ex'], 0., .1)
    result = run(item)
    pending = result['obligations'].loc[lambda x: x.kind.eq('pending')]
    early = pending.loc[pending.date.eq(pd.Timestamp('2018-01-05'))].iloc[0]
    assert pd.isna(early.stock_pay) and early.shares == 490
    announcement = result['corporate_events'].loc[lambda x: x.event.eq('stock_pay_known')].iloc[0]
    assert announcement.date == pd.Timestamp('2018-01-10')
    assert announcement.settlement_date == pd.Timestamp('2018-01-12')
    assert result['holdings'].iloc[-1].shares == 5390


def test_unknown_capitalization_tax_origin_is_disclosed_and_missing_bridge_stops():
    item = case()
    row = action(item, D=0., bonus=0., account_guard='capitalization_tax_origin_unknown')
    item['event_book'] = EventBook(item['full_calendar'], [row])
    set_action_prices(item, row['ex'], 0., .1)
    normal = run(item)
    assert normal['holdings'].iloc[-1].shares == 5390
    ex = pd.Timestamp(row['ex'])
    item['bars'] = item['bars'].loc[item['bars'].trade_date.ne(ex)]
    with pytest.raises(AccountFailure, match='Unknown capitalization'):
        run(item, suspensions={(ex, CODE)})


def test_fixed_tax_cannot_finance_with_negative_cash():
    ledger = OrdinaryLedger()
    ledger.cash = 0.
    ledger.positions[CODE] = 100
    row = action(case(), D=0., s=1., bonus=1.)
    from momentum_g2_account import _event
    row = _event(row)
    ledger.record(pd.Timestamp(row['record_date']), {row['event_id']: row})
    ledger.morning(pd.Timestamp(row['ex_date']), {row['event_id']: row})
    with pytest.raises(ValueError, match='Cash insufficient'):
        ledger.morning(pd.Timestamp(row['div_listdate']), {row['event_id']: row})


def test_raw_preclose_conflict_stops_and_does_not_depend_on_vendor_adjustment():
    item = case()
    item['bars']['adj_factor'] = np.linspace(1., 100., len(item['bars']))
    clean = run(item)
    assert clean['nav'].equity.eq(1_000_000.).all()
    item['bars'].loc[item['bars'].trade_date.eq(pd.Timestamp('2018-01-03')), 'pre_close'] = 9.99
    with pytest.raises(AccountFailure, match='pre-close bridge') as found:
        run(item)
    assert found.value.partial_result['nav'].date.max() == pd.Timestamp('2018-01-02')


def test_zero_amount_positive_volume_is_conflict_and_never_suspension():
    item = case()
    execution = item['schedule'].execution_date.iloc[0]
    item['bars'].loc[item['bars'].trade_date.eq(execution), 'amount'] = 0.
    with pytest.raises(AccountFailure, match='Conflicting zero'):
        run(item)


def test_future_numbers_and_unused_names_do_not_enter_account():
    item = case()
    baseline = run(item)
    future = item['bars'].iloc[[0]].assign(trade_date=pd.Timestamp('2021-01-01'), open=-1., close=-1.)
    irrelevant = item['bars'].assign(ts_code='600000.SH', open=-1., close=-1.)
    item['bars'] = pd.concat([item['bars'], future, irrelevant], ignore_index=True)
    result = run(item, full_calendar=item['full_calendar'].append(pd.DatetimeIndex(['2021-01-01'])))
    pd.testing.assert_frame_equal(baseline['nav'], result['nav'])


def test_preclose_display_is_decimal_half_up_while_cash_stays_float_round():
    item = case()
    row = action(item, D=.015, s=0., bonus=0.)
    item['event_book'] = EventBook(item['full_calendar'], [row])
    # 10 - .015 is exactly 9.985 under the frozen display convention.
    mask = item['bars'].trade_date.ge(pd.Timestamp(row['ex']))
    item['bars'].loc[mask, ['open', 'high', 'low', 'close', 'pre_close']] = 9.99
    item['bars'].loc[mask, ['up_limit', 'down_limit']] = [11., 9.]
    result = run(item)
    assert result['corporate_events'].loc[lambda x: x.event.eq('ex')].iloc[0].gross_cash == 73.5


def test_ordinary_monetary_half_cent_retains_python_float_round():
    from momentum_g2_account import _event
    ledger = OrdinaryLedger()
    ledger.positions[CODE] = 1
    row = _event(action(case(), D=2.675, s=0., bonus=0.))
    ledger.record(row['record_date'], {row['event_id']: row})
    ledger.morning(row['ex_date'], {row['event_id']: row})
    event = ledger.events[-1]
    assert event['gross_cash'] == 2.67
    assert event['assumed_tax'] == .53
    assert ledger.receivable() == pytest.approx(2.14)


def test_next_plan_sells_execute_before_buys_and_proceeds_are_cash():
    item = case()
    other = '000002.SZ'
    template = item['bars'].assign(ts_code=other)
    item['bars'] = pd.concat([item['bars'], template], ignore_index=True)
    item['universe'] = pd.concat([item['universe'], item['universe'].assign(ts_code=other)], ignore_index=True)
    add_plan(item, '2018-01-05', '2018-01-08', 0.)
    last = item['targets'].iloc[[-1]].assign(ts_code=other, target_weight=.049)
    item['targets'] = pd.concat([item['targets'], last], ignore_index=True)
    result = run(item)
    day = result['orders'].loc[lambda x: x.date.eq(pd.Timestamp('2018-01-08'))]
    assert day.side.tolist() == ['sell', 'buy']
    assert day.iloc[0].cash_after == day.iloc[1].cash_before == 1_000_000.


def test_settled_registration_does_not_keep_a_phantom_exposure():
    item = case()
    row = action(item, D=1., s=0., bonus=0.)
    future = action(item, identity='irrelevant_after_settlement', known='2018-01-15',
        record='2018-01-16', ex='2018-01-17', kind='unsupported')
    item['event_book'] = EventBook(item['full_calendar'], [row, future])
    set_action_prices(item, row['ex'], 1., 0.)
    add_plan(item, '2018-01-03', '2018-01-04', 0.)
    item['universe']['delist_date'] = '20180115'
    result = run(item)
    assert result['holdings'].loc[lambda x: x.date.gt(pd.Timestamp('2018-01-04'))].empty
    assert result['nav'].date.max() == pd.Timestamp('2018-01-19')
    assert result['account_state']['positions'] == {}
    assert result['account_state']['prices'] == {}


def test_actual_registry_event_with_unknown_publication_stops_without_future_terms():
    item = case()
    row = action(item, known=None)
    # No price discontinuity is necessary to expose missing provenance.
    with pytest.raises(AccountFailure, match='unavailable/future provenance') as found:
        run(item, event_book=EventBook(item['full_calendar'], [row]))
    assert found.value.date == pd.Timestamp(row['ex'])


@pytest.mark.parametrize('timing,kind,filled', [('', 'S', 0), ('09:30-10:30', 'S', 0),
    ('09:30:00-10:30:00', 'S', 0), ('14:00-15:00', 'S', 4900),
    ('09:00-09:30', 'S', 4900), ('', 'R', 4900)])
def test_daily_suspension_timing_decodes_the_actual_opening(timing, kind, filled):
    item = case()
    execution = item['schedule'].execution_date.iloc[0]
    suspensions = pd.DataFrame([dict(trade_date=execution, ts_code=CODE,
                                   suspend_type=kind, suspend_timing=timing)])
    result = run(item, suspensions=suspensions)
    assert result['orders'].iloc[0].shares == filled


def test_unparseable_relevant_suspension_timing_is_a_data_stop():
    item = case()
    execution = item['schedule'].execution_date.iloc[0]
    suspensions = pd.DataFrame([dict(trade_date=execution, ts_code=CODE,
                                   suspend_type='S', suspend_timing='sometime after open')])
    with pytest.raises(AccountFailure, match='Unknown intraday suspension'):
        run(item, suspensions=suspensions)


def test_intraday_suspension_cannot_explain_an_entire_missing_daily_bar():
    item = case()
    missing = pd.Timestamp('2018-01-03')
    item['bars'] = item['bars'].loc[item['bars'].trade_date.ne(missing)]
    suspensions = pd.DataFrame([dict(trade_date=missing, ts_code=CODE,
                                   suspend_type='S', suspend_timing='14:00-15:00')])
    with pytest.raises(AccountFailure, match='Missing exposed'):
        run(item, suspensions=suspensions)
