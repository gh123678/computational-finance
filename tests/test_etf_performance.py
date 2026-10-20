"""Metrics checked against hand-constructed continuous equity, not engine output."""
from decimal import Decimal
import math

import pytest

from quant_research.etf_trend_signal import performance


def test_continuous_year_baseline_drawdown_and_cost_not_subtracted_twice():
    values = [('20171229','100.00'),('20180102','110.00'),
              ('20181228','99.00'),('20190102','108.90')]
    nav = [dict(date=d,equity=e,market_value=e,shares=100,
                buy_notional='10.00' if i==1 else '0.00',sell_notional='0.00')
           for i,(d,e) in enumerate(values)]
    orders = [dict(filled=100,notional='10.00',fee='5.00',slippage='1.00',
                   status='filled',reason='')]
    m = performance(nav,orders)
    assert m['total_return'] == pytest.approx(.089)
    assert m['max_drawdown'] == pytest.approx(.10)
    assert m['annual_returns']['2018'] == pytest.approx(-.01)
    assert m['annual_returns']['2019'] == pytest.approx(.10)
    assert m['positive_years'] == 1
    assert Decimal(m['commission_cny']) == Decimal('5.00')
    assert Decimal(m['slippage_cny']) == Decimal('1.00')
    assert m['annualized_return_252'] == pytest.approx(1.089**84-1)
    returns = [.1,-.1,.1]
    mean = sum(returns)/3
    std = math.sqrt(sum((r-mean)**2 for r in returns)/2)
    assert m['sharpe_rf0_ddof1_252'] == pytest.approx(mean/std*math.sqrt(252))
    assert m['annualized_buy_plus_sell_turnover'] == pytest.approx(10/110*252/3)


def test_all_cash_has_undefined_sharpe_instead_of_infinite_success():
    nav = [dict(date=d,equity='100.00',market_value='0.00',shares=0,
                buy_notional='0.00',sell_notional='0.00')
           for d in ('20171229','20180102','20180103')]
    m = performance(nav,[])
    assert m['sharpe_rf0_ddof1_252'] is None
    assert m['total_return'] == 0
    assert m['max_drawdown'] == 0
    assert m['invested_close_days'] == 0
