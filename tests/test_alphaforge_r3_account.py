import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from alphaforge_r3_account import BASE_BACKTEST_SHA256, simulate_reference
from alphaforge_r3_guard import audit_reference_guard
from quant_research.accounting import Action
from quant_research.backtest import Config, simulate
from quant_research.rights import RightsIssue


HASHES = {'dividend': 'a' * 64, 'rights': 'b' * 64}


def fixture():
    dates = pd.bdate_range('2020-01-02', periods=9)
    full = pd.DatetimeIndex([pd.Timestamp('2019-12-31'), *dates])
    bars = pd.DataFrame(dict(trade_date=dates, ts_code='A', open=10., close=10.,
                             vol=100000., amount=30000., up_limit=11., down_limit=4.,
                             close_text='10.0', pre_close_text='10.0'))
    targets = pd.DataFrame(dict(execution_date=[dates[2]], signal_date=[dates[1]],
                                ts_code='A', target_weight=.5))
    universe = pd.DataFrame([dict(ts_code='A', list_date='20100101', delist_date=None)])
    seed = pd.DataFrame([dict(trade_date=full[0], ts_code='A', close_text='10.0', pre_close_text='10.0')])
    keywords = dict(universe=universe, seed_bars=seed, full_calendar=full, source_hashes=HASHES)
    return dates, bars, targets, keywords


def run(data, **kwargs):
    dates, bars, targets, keywords = data
    return simulate_reference(bars, dates, targets, config=Config(initial_cash=10000., zero_trading_costs=True),
                              **keywords, **kwargs)


def legacy(data, **kwargs):
    dates, bars, targets, _ = data
    return simulate(bars.assign(adj_factor=1.), dates, targets,
                    config=Config(initial_cash=10000., zero_trading_costs=True), **kwargs)


def assert_original_tables_equal(actual, expected):
    for name in ('nav', 'orders', 'holdings', 'corporate_events'):
        pd.testing.assert_frame_equal(actual[name], expected[name])


def test_copied_account_uses_unchanged_frozen_core_and_identical_plain_ledger():
    core = Path(__file__).resolve().parents[1] / 'quant_research/backtest.py'
    assert hashlib.sha256(core.read_bytes()).hexdigest() == BASE_BACKTEST_SHA256
    data = fixture()
    result = run(data)
    assert_original_tables_equal(result, legacy(data))
    assert not result['reference_guard'].empty
    assert result['reference_guard'].pending_shares.eq(0).all()


def test_no_adjustment_required_and_isolated_A_does_not_change_results():
    data = fixture()
    baseline = run(data)
    data[1]['adj_factor'] = [11.267] * 3 + [10.97] * 6
    changed = run(data)
    assert_original_tables_equal(changed, baseline)
    with pytest.raises(ValueError, match='Unexplained corporate action'):
        simulate(data[1], data[0], data[2])


@pytest.mark.parametrize('bps', [0, 10, 30])
def test_original_fees_capacity_slippage_and_resize_are_identical(bps):
    dates, bars, targets, keywords = fixture()
    later = pd.DataFrame(dict(execution_date=[dates[5]], signal_date=[dates[4]], ts_code='A', target_weight=.3))
    targets = pd.concat([targets, later], ignore_index=True)
    config = Config(initial_cash=10000., slippage_bps=bps, zero_trading_costs=bps == 0)
    actual = simulate_reference(bars, dates, targets, config=config, **keywords)
    expected = simulate(bars.assign(adj_factor=1.), dates, targets, config=config)
    assert_original_tables_equal(actual, expected)


def test_cash_bonus_entitlement_settlement_and_tax_match_original_ledger():
    data = fixture()
    dates, bars, _, _ = data
    action = Action('A', dates[2], dates[3], dates[5], dates[6], 1., 1., .2)
    bars.loc[bars.trade_date.ge(action.ex), ['open', 'close']] = 4.5
    bars.loc[bars.trade_date.ge(action.ex), 'close_text'] = '4.5'
    bars.loc[bars.trade_date.ge(action.ex), 'pre_close_text'] = '4.5'
    actual = run(data, actions=[action])
    expected = legacy(data, actions=[action])
    assert_original_tables_equal(actual, expected)
    ex = actual['nav'].loc[actual['nav'].date.eq(action.ex)].iloc[0]
    assert ex.bonus_value > 0 and ex.receivable > 0
    assert actual['reference_guard'].pending_shares.gt(0).any()


@pytest.mark.parametrize('subscribe', [False, True])
def test_registered_rights_scenarios_match_original_cash_and_share_ledger(subscribe):
    data = fixture()
    dates, bars, _, _ = data
    terms = dict(price=5., ratio=.3, list_date=dates[5]) if subscribe else {}
    issue = RightsIssue('A', dates[2], dates[3], 'https://official.test/rights', **terms)
    bars.loc[bars.trade_date.ge(issue.ex), ['open', 'close']] = 8.
    bars.loc[bars.trade_date.ge(issue.ex), ['close_text', 'pre_close_text']] = '8.0'
    actual = run(data, rights=[issue])
    assert_original_tables_equal(actual, legacy(data, rights=[issue]))
    event = 'rights_subscribed' if subscribe else 'rights_not_subscribed'
    assert event in actual['corporate_events'].event.tolist()


def test_precheck_failure_in_never_held_date_prevents_any_account_open():
    data = fixture()
    data[1].loc[0, 'pre_close_text'] = '9.9'
    with pytest.raises(ValueError, match='no account was opened'):
        run(data)


def test_reused_precheck_binds_raw_text_and_rejects_stale_input():
    data = fixture()
    dates, bars, _, kwargs = data
    checked = audit_reference_guard(bars, dates, kwargs['universe'], seed_bars=kwargs['seed_bars'],
                                    source_hashes=HASHES, full_calendar=kwargs['full_calendar'])
    assert_original_tables_equal(run(data, guard_audit=checked), run(data))
    bars.loc[4, 'pre_close_text'] = '9.99999999999999999999'
    with pytest.raises(ValueError, match='inputs do not match'):
        run(data, guard_audit=checked)


def test_csv_json_cached_precheck_can_be_reused_without_A_or_limit_binding(tmp_path):
    data = fixture()
    dates, bars, _, kwargs = data
    checked = audit_reference_guard(bars, dates, kwargs['universe'], seed_bars=kwargs['seed_bars'],
                                    source_hashes=HASHES, full_calendar=kwargs['full_calendar'])
    cached = {}
    for name in ('daily', 'failures', 'adjustment_alerts', 'event_registry'):
        path = tmp_path / (name + '.csv')
        checked[name].to_csv(path, index=False)
        cached[name] = pd.read_csv(path, parse_dates=['date', 'prior_quote_date'] if name == 'daily' else None,
                                   dtype=str if name == 'event_registry' else None)
    path = tmp_path / 'summary.json'
    path.write_text(json.dumps(checked['summary']), encoding='utf-8')
    cached['summary'] = json.loads(path.read_text(encoding='utf-8'))
    assert cached['daily'].has_quote.dtype == bool
    bars['extra_limit_field'] = 123.
    assert_original_tables_equal(run(data, guard_audit=cached), run(data))
    # Raw quote lexemes, in contrast to a diagnostic CSV's numeric-looking
    # cells, must survive the source loader without float inference.
    bars['close_text'] = bars.close_text.astype(float)
    with pytest.raises(ValueError, match='inputs do not match'):
        run(data, guard_audit=cached)


def test_delisting_zero_recovery_is_retained_and_later_absence_is_domain_coverage():
    data = list(fixture())
    dates, bars, _, kwargs = data
    kwargs['universe'].loc[0, 'delist_date'] = str(dates[5].date())
    data[1] = bars.loc[bars.trade_date.lt(dates[5])]
    actual = run(data)
    assert actual['nav'].loc[actual['nav'].date.ge(dates[5]), 'stock_value'].eq(0).all()
    assert actual['corporate_events'].event.eq('delisting_zero_recovery').sum() == 1
    assert actual['reference_guard'].lifecycle.eq('scheduled_delisting').any()


def test_frozen_universe_prevents_delisting_override():
    data = fixture()
    with pytest.raises(ValueError, match='conflicts with frozen universe'):
        run(data, delistings={'A': data[0][4]})


def test_listing_initial_anchor_is_not_a_tradable_target():
    data = fixture()
    dates, _, targets, kwargs = data
    kwargs['universe'].loc[0, 'list_date'] = str(dates[0].date())
    kwargs['seed_bars'] = kwargs['seed_bars'].iloc[:0]
    targets.loc[0, 'execution_date'] = dates[0]
    targets.loc[0, 'signal_date'] = pd.Timestamp('2019-12-31')
    with pytest.raises(ValueError, match='initial-listing purchase'):
        run(data)


def test_suspension_stale_mark_and_rejected_order_match_old_scenario():
    data = list(fixture())
    dates = data[0]
    data[1] = data[1].loc[data[1].trade_date.ne(dates[4])]
    suspensions = pd.DataFrame([dict(trade_date=dates[4], ts_code='A', suspend_type='S', suspend_timing='')])
    actual = run(data, suspensions=suspensions, rebalance_dates=[dates[2], dates[4]])
    expected = legacy(data, suspensions={(dates[4], 'A')}, rebalance_dates=[dates[2], dates[4]])
    assert_original_tables_equal(actual, expected)
    assert actual['nav'].loc[actual['nav'].date.eq(dates[4]), 'stale_value'].iloc[0] > 0
    assert actual['orders'].iloc[-1].status == 'rejected'


def test_future_price_perturbation_cannot_change_prior_account_outputs():
    data = fixture()
    original = run(data)
    dates, bars, _, _ = data
    bars.loc[bars.trade_date.ge(dates[6]), ['open', 'close']] = 10.5
    bars.loc[bars.trade_date.ge(dates[6]), 'close_text'] = '10.5'
    bars.loc[bars.trade_date.gt(dates[6]), 'pre_close_text'] = '10.5'
    changed = run(data)
    pd.testing.assert_frame_equal(original['orders'], changed['orders'])
    pd.testing.assert_frame_equal(original['nav'].iloc[:6], changed['nav'].iloc[:6])
