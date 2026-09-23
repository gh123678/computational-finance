import pandas as pd
import pytest
from quant_research.accounting import Action
from quant_research.backtest import simulate, Config


def fixture():
    dates = pd.bdate_range('2020-01-02', '2020-01-10')
    bars = pd.DataFrame({'trade_date': dates, 'ts_code': 'A', 'open': 10., 'close': 10.,
                         'amount': 30000., 'vol': 100000., 'adj_factor': 1., 'up_limit': 11., 'down_limit': 4.})
    targets = pd.DataFrame({'execution_date': [dates[2]], 'signal_date': [dates[1]],
                            'ts_code': ['A'], 'target_weight': [.5]})
    return dates, bars, targets


def test_cash_share_ledger_reconciles_with_delayed_company_action():
    dates, bars, targets = fixture()
    ex = pd.Timestamp('2020-01-07')
    bars.loc[bars.trade_date >= ex, ['open', 'close']] = 4.5
    bars.loc[bars.trade_date >= ex, 'adj_factor'] = 10 / 4.5
    action = Action('A', dates[2], ex, pd.Timestamp('2020-01-09'), pd.Timestamp('2020-01-10'), 1., 1.)
    config = Config(initial_cash=10000, slippage_bps=0, commission=0, minimum_commission=0, dividend_tax=0)
    result = simulate(bars, dates, targets, [action], config=config)
    nav = result['nav'].set_index('date')
    # Buy transfer fee remains; all non-price cash/share movements conserve NAV.
    assert nav.loc[ex, 'equity'] == pytest.approx(nav.loc[dates[2], 'equity'])
    assert nav.loc[ex, 'bonus_value'] == 2250
    assert nav.loc[ex, 'receivable'] == 500
    assert nav.loc[dates[-1], 'bonus_value'] == 0
    assert nav.loc[dates[-1], 'equity'] == pytest.approx(nav.loc[ex, 'equity'])
    assert result['holdings'].iloc[-1].shares == 1000


def test_unexplained_adjustment_change_stops_run():
    dates, bars, targets = fixture()
    bars.loc[3:, 'adj_factor'] = 2.
    with pytest.raises(ValueError, match='Unexplained corporate action'):
        simulate(bars, dates, targets)


def test_future_close_change_cannot_affect_prior_fills_or_nav():
    dates, bars, targets = fixture()
    first = simulate(bars, dates, targets)
    changed = bars.copy()
    changed.loc[5:, 'close'] = 100.
    second = simulate(changed, dates, targets)
    pd.testing.assert_frame_equal(first['orders'], second['orders'])
    pd.testing.assert_frame_equal(first['nav'].iloc[:5], second['nav'].iloc[:5])


def test_same_day_signal_is_rejected():
    dates, bars, targets = fixture()
    targets.signal_date = targets.execution_date
    with pytest.raises(ValueError, match='earlier signal'):
        simulate(bars, dates, targets)


def test_delisting_zero_recovery_does_not_disappear_silently():
    dates, bars, targets = fixture()
    result = simulate(bars, dates, targets, delistings={'A': dates[4]})
    assert result['nav'].iloc[4].stock_value == 0
    assert 'delisting_zero_recovery' in result['corporate_events'].event.tolist()


def test_fee_dates_are_historical_not_current():
    config = Config()
    assert config.fees('2020-12-31').sell_tax == .001
    assert config.fees('2022-04-28').transfer == .00002
    assert config.fees('2022-04-29').transfer == .00001
    assert config.fees('2023-08-27').sell_tax == .001
    assert config.fees('2023-08-28').sell_tax == .0005


def test_empty_scheduled_portfolio_exits_instead_of_silently_holding():
    dates, bars, targets = fixture()
    result = simulate(bars, dates, targets, rebalance_dates=[dates[2], dates[4]])
    assert result['nav'].iloc[4].stock_value == 0
    assert result['orders'].side.tolist() == ['buy', 'sell']


def test_blocked_sale_retains_the_position_and_records_rejection():
    dates, bars, targets = fixture()
    bars.loc[4, 'down_limit'] = 10.
    result = simulate(bars, dates, targets, rebalance_dates=[dates[2], dates[4]])
    assert result['nav'].iloc[4].stock_value > 0
    assert result['orders'].iloc[-1].reason == 'price_limit'
