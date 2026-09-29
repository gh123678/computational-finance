import pytest
from quant_research.execution import FeeSchedule, execute_order


def order(**kwargs):
    defaults = dict(side='buy', requested=1000, cash=10000., held=0, sellable=0,
                    raw_open=10., up_limit=11., down_limit=9., suspended=False,
                    prior_adv_cny=20_000_000., fees=FeeSchedule(slippage_bps=0))
    defaults.update(kwargs)
    return execute_order(**defaults)


def test_fee_reserve_and_no_leverage():
    fill = order()
    assert fill.status == 'filled'
    assert fill.shares == 900
    assert fill.cash_after >= 0
    assert fill.cash_after + fill.shares * fill.price + fill.fee == pytest.approx(10000)
    assert fill.sellable_after == 0
    assert fill.price == 10.


def test_t1_blocks_same_day_sale():
    fill = order(side='sell', held=1000, sellable=0)
    assert fill.status == 'rejected'
    assert fill.shares_after == 1000


@pytest.mark.parametrize('side,price', [('buy', 11.), ('sell', 9.)])
def test_limit_orders_do_not_fill(side, price):
    fill = order(side=side, raw_open=price, held=1000, sellable=1000)
    assert fill.reason == 'price_limit'


def test_suspension_does_not_change_cash_or_shares():
    fill = order(suspended=True)
    assert fill.cash_after == 10000
    assert fill.shares_after == 0


def test_odd_lot_full_liquidation_and_cost_conservation():
    fill = order(side='sell', requested=155, held=155, sellable=155)
    assert fill.shares == 155
    assert fill.shares_after == 0
    assert fill.cash_after == pytest.approx(10000 + 155 * fill.price - fill.fee)


def test_prior_capacity_caps_order():
    fill = order(prior_adv_cny=400_000)
    assert fill.shares * fill.price <= 400_000 * .005


def test_missing_limit_blocks_order():
    assert order(up_limit=float('nan')).status == 'rejected'
