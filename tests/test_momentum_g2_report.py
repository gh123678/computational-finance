import pandas as pd
import pytest

from report_momentum_g2 import performance, execution_gate, economic_gates, industry_exposure


def test_metrics_include_true_initial_point_and_continuous_annual_denominators():
    nav = pd.DataFrame({'date': ['2017-12-29', '2018-12-28', '2019-12-31', '2020-12-31'],
                        'equity': [1_000_000., 900_000., 1_080_000., 1_188_000.],
                        'one_way_turnover': [0., .5, .2, .1]})
    m = performance(nav, pd.DataFrame({'fee': [5., 6.]}))
    assert m['total_return'] == pytest.approx(.188)
    assert m['max_drawdown'] == pytest.approx(.1)
    assert m['annual_returns'] == pytest.approx({'2018': -.1, '2019': .2, '2020': .1})
    assert m['annualized_one_way_turnover'] == pytest.approx(.8 * 252 / 3)
    assert m['fees'] == 11 and m['positive_years'] == 2


def test_high_fill_ratio_does_not_erase_right_censoring_or_locked_residual():
    dep = pd.DataFrame({'unconditional_completion': [.99]})
    for window, closed in [(False, True), (True, False)]:
        ep = pd.DataFrame({'complete_five_session_window': [window],
                           'first_intent_completion': [.99], 'securities_risk_closed': [closed]})
        assert not execution_gate(dep, ep)['passed']
    assert not execution_gate(dep, pd.DataFrame())['passed']


def test_pressure_cost_and_fixed_control_are_not_replaced_by_zero_cost():
    metrics = {'momentum_10bp': {'total_return': .2, 'max_drawdown': .25, 'positive_years': 2},
               'momentum_30bp': {'total_return': -.001}, 'control_10bp': {'total_return': .21}}
    gates = economic_gates(metrics)
    assert not gates['main30_positive'] and not gates['main10_above_fixed_control10']
    assert gates['main10_drawdown_le25']


def test_daily_industry_uses_valid_interval_and_preserves_unknown():
    holdings = pd.DataFrame(dict(date=['2018-01-02', '2018-01-03', '2018-01-04'], ts_code='000001.SZ', value=100., weight=.1))
    history = pd.DataFrame([dict(ts_code='000001.SZ', in_date='20180102', out_date='20180103', l1_code='OLD'),
                            dict(ts_code='000001.SZ', in_date='20180103', out_date='20180104', l1_code='NEW')])
    result = industry_exposure(holdings, history)
    assert result.industry.tolist() == ['OLD', 'NEW', 'UNKNOWN_OR_AMBIGUOUS']
    assert result.ambiguous_or_missing.tolist() == [False, False, True]
