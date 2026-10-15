"""Adversarial checks of the new verifier, not a second historical backtest."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_alphaforge_case import (PATHS, PRIMARY, independent_diagnostics,
                                   reconstruct_account, scalar_formula,
                                   strategy_gates, summarize_operations)


def ledger():
    dates = pd.to_datetime(['2017-12-29', '2018-12-28', '2019-01-02', '2020-01-02'])
    nav = pd.DataFrame(dict(date=dates, cash=[1000., 899., 899., 915.],
                            stock_value=[0., 100., 90., 132.], bonus_value=[0., 0., 18., 0.],
                            receivable=[0., 0., 16., 0.], equity=[1000., 999., 1023., 1047.],
                            fees=[0., 1., 0., 0.], slippage_cost=[0., 1., 0., 0.],
                            position_count=[0, 1, 1, 1]))
    orders = pd.DataFrame([dict(date=dates[1], ts_code='A', side='buy', shares=10,
                                price=10., raw_open=9.9, fee=1., slippage_cost=1.,
                                status='filled', reason='', cash_after=899., notional=100.)])
    events = pd.DataFrame([
        dict(date=dates[2], code='A', event='ex', gross_cash=20., assumed_tax=4., bonus_shares=2.),
        dict(date=dates[3], code='A', event='cash_settlement', cash=16.),
        dict(date=dates[3], code='A', event='stock_settlement', shares=2.),
    ])
    holdings = pd.DataFrame(dict(date=dates[1:], ts_code='A', shares=[10, 10, 12],
                                pending_shares=[0, 2, 0], mark=[10., 9., 11.]))
    return nav, orders, events, holdings


def test_rebuilds_pending_shares_receivable_and_two_year_boundaries():
    nav, orders, events, holdings = ledger()
    result, boundaries = reconstruct_account(nav, orders, events, holdings, initial_cash=1000)
    assert result['sessions'] == 4 and result['maximum_cash_error'] == 0
    assert result['maximum_receivable_error'] == 0
    assert result['gross_traded_notional_cny'] == 100
    assert len(boundaries) == 2 and boundaries[-1]['prior_receivable'] == 16


@pytest.mark.parametrize('tamper', ['cash', 'shares', 'pending', 'receivable', 'missing_holdings', 'order_cash'])
def test_rejects_distinct_ledger_corruption(tamper):
    nav, orders, events, holdings = ledger()
    if tamper == 'cash':
        nav.loc[2, 'cash'] += .01
    elif tamper == 'shares':
        holdings.loc[1, 'shares'] -= 1
    elif tamper == 'pending':
        holdings.loc[1, 'pending_shares'] = 0
    elif tamper == 'receivable':
        nav.loc[2, 'receivable'] += 1
    elif tamper == 'missing_holdings':
        holdings = holdings.iloc[:1].copy()
    elif tamper == 'order_cash':
        orders.loc[0, 'cash_after'] += .01
    with pytest.raises(AssertionError):
        reconstruct_account(nav, orders, events, holdings, initial_cash=1000)


def test_rejected_order_cannot_consume_fee_or_quantity():
    nav, orders, events, holdings = ledger()
    rejected = orders.iloc[0].copy()
    rejected[['shares', 'notional', 'slippage_cost']] = 0
    rejected['status'] = 'rejected'
    rejected['fee'] = 1
    orders = pd.concat([orders, rejected.to_frame().T], ignore_index=True)
    orders['date'] = pd.to_datetime(orders.date)
    for name in ('shares', 'fee', 'slippage_cost'):
        orders[name] = pd.to_numeric(orders[name])
    with pytest.raises(AssertionError):
        reconstruct_account(nav, orders, events, holdings, initial_cash=1000)


def test_actual_turnover_includes_initial_purchase_and_zero_trade_days():
    nav, orders, _, _ = ledger()
    operation = summarize_operations(nav, orders)
    assert operation['formal_sessions'] == 3
    assert operation['filled_buy_notional_cny'] == 100
    assert operation['filled_sell_notional_cny'] == 0
    assert operation['annualized_half_turnover_prior_equity'] == pytest.approx(.05 * 252 / 3)
    assert operation['initial_execution_notional_cny'] == 100
    assert operation['subsequent_execution_notional_cny'] == 0
    assert operation['total_fees_cny'] == 1 and operation['total_slippage_cny'] == 1


def gate_inputs():
    stats = pd.DataFrame([
        dict(strategy=PRIMARY + '_10bp', total_return=.2, max_drawdown=.25),
        dict(strategy=PRIMARY + '_30bp', total_return=.1, max_drawdown=.2),
        dict(strategy=PATHS[1] + '_10bp', total_return=.1, max_drawdown=.2),
    ]).set_index('strategy')
    annual = pd.DataFrame(dict(strategy=PRIMARY + '_10bp', year=[2018, 2019, 2020],
                               return_value=[-.1, .2, .3]))
    signals = pd.to_datetime(['2017-12-29', '2018-12-28', '2020-01-03'])
    schedule = pd.DataFrame(dict(signal_date=signals,
                                 execution_date=pd.to_datetime(['2018-01-02', '2019-01-02', '2020-01-06'])))
    ic = pd.DataFrame(dict(signal_date=signals, factor='case_signal', rank_ic=[.01, .02, .03]))
    return stats, annual, ic, schedule


def test_gates_use_execution_year_and_include_exact_drawdown_boundary():
    gates, mean, yearly = strategy_gates(*gate_inputs())
    assert all(gates.values()) and mean == pytest.approx(.02)
    assert set(yearly.index) == {2018, 2019, 2020}


@pytest.mark.parametrize('field', ['zero_stress_return', 'control_tie', 'drawdown', 'one_positive_return_year',
                                    'zero_mean_ic', 'one_positive_ic_year'])
def test_no_posthoc_promotion_or_relaxation_of_failed_gate(field):
    stats, annual, ic, schedule = gate_inputs()
    if field == 'zero_stress_return':
        stats.loc[PRIMARY + '_30bp', 'total_return'] = 0
    elif field == 'control_tie':
        stats.loc[PATHS[1] + '_10bp', 'total_return'] = .2
    elif field == 'drawdown':
        stats.loc[PRIMARY + '_10bp', 'max_drawdown'] = .25000001
    elif field == 'one_positive_return_year':
        annual['return_value'] = [-.1, 0., .3]
    elif field == 'zero_mean_ic':
        ic['rank_ic'] = [-.02, 0., .02]
    elif field == 'one_positive_ic_year':
        ic['rank_ic'] = [-.01, 0., .1]
    gates, _, _ = strategy_gates(stats, annual, ic, schedule)
    assert not all(gates.values())


def test_independent_formula_keeps_epsilon_branch_and_volume_units():
    normal = scalar_formula(np.arange(10.) + 1, np.arange(10.) + 10)
    assert normal['case_rho'] == pytest.approx(1)
    assert normal['case_factor'] == pytest.approx(np.log(2))
    assert normal['case_signal'] == -normal['case_factor']
    tiny = scalar_formula(10 + np.arange(10.) * 1e-7, np.arange(10.) + 10)
    assert tiny['case_guard']
    assert tiny['case_rho'] == pytest.approx(100 * 1e-7 * 82.5, rel=1e-7)


def test_diagnostic_membership_does_not_rerank_after_label_loss():
    date = pd.Timestamp('2018-01-05')
    n = 20
    samples = pd.DataFrame(dict(trade_date=date, ts_code=[str(i) for i in range(n)],
                                case_factor=np.arange(n), case_signal=-np.arange(n),
                                three_score=np.arange(n) / n,
                                D_label=np.arange(n) / 100, D_valid=True))
    samples.loc[0:1, 'D_valid'] = False
    schedule = pd.DataFrame(dict(signal_date=[date], execution_date=[date + pd.Timedelta(days=3)]))
    ic, groups = independent_diagnostics(samples, schedule)
    first = groups.loc[groups.factor.eq('case_factor') & groups.group.eq(1)].iloc[0]
    assert first.n_formed == 4 and first.n == 2
    assert first.mean_forward_return == pytest.approx(.025)
    assert ic.loc[ic.factor.eq('case_signal'), 'rank_ic'].iloc[0] == pytest.approx(-1)
