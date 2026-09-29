import pandas as pd
import pytest
from quant_research.attribution import monthly_returns, cost_breakdown


def test_monthly_returns_compound_to_total_and_exclude_baseline_only_month():
    equity = pd.Series([100., 90., 110., 99.], index=pd.to_datetime(['2019-12-31','2020-01-02','2020-01-31','2020-02-03']))
    result = monthly_returns(equity)
    assert result.index.astype(str).tolist() == ['2020-01','2020-02']
    assert result.iloc[0] == pytest.approx(.1)
    assert result.iloc[1] == pytest.approx(-.1)
    assert (1+result).prod()-1 == pytest.approx(-.01)


def test_cost_breakdown_reconciles_and_excludes_rejections():
    orders = pd.DataFrame({'shares':[100,100,0], 'role':['entry','exit','resize'],
                          'notional':[1000,1100,0], 'fee':[5,6,0], 'slippage_cost':[1,2,0]})
    result = cost_breakdown(orders)
    assert result.total_cost.sum() == 14
    assert result.cost_share.sum() == pytest.approx(1)
    assert result.orders.sum() == 2
