import pandas as pd
import pytest

from scripts.build_dividend_revision import add_record
from quant_research.accounting import Ledger, normalize_actions
from quant_research.backtest import Config, simulate


def empty_dividends():
    return pd.DataFrame(columns=['ts_code','end_date','ann_date','div_proc','stk_div','stk_bo_rate',
                                 'stk_co_rate','cash_div','cash_div_tax','record_date','ex_date',
                                 'pay_date','div_listdate','imp_ann_date'])


def test_verified_gross_dividend_credits_cash_once_at_fixed_tax():
    row=add_record(empty_dividends())
    frame=pd.DataFrame([row]).replace('',float('nan'))
    actions=normalize_actions(frame,{'001323.SZ'})
    ledger=Ledger(initial_cash=1000000.,dividend_tax=.2)
    ledger.positions['001323.SZ']=1000
    ledger.prices['001323.SZ']=31.29
    ledger.record(pd.Timestamp('20250606'),actions)
    ledger.morning(pd.Timestamp('20250609'),actions)
    assert ledger.cash==1000800.
    assert ledger.receivable==0
    assert ledger.positions['001323.SZ']==1000
    ex=[e for e in ledger.events if e['event']=='ex']
    assert len(ex)==1 and ex[0]['gross_cash']==1000 and ex[0]['assumed_tax']==200
    ledger.morning(pd.Timestamp('20250610'),actions)
    assert ledger.cash==1000800.


def test_existing_ex_date_is_rejected_even_if_terms_differ():
    row=add_record(empty_dividends())
    row['cash_div_tax']='0.9833939'
    with pytest.raises(ValueError,match='already exists'):
        add_record(pd.DataFrame([row]))


def test_observed_ex_date_prices_are_used_instead_of_gross_cash_reference():
    actions=normalize_actions(pd.DataFrame([add_record(empty_dividends())]).replace('',float('nan')),
                              {'001323.SZ'})
    dates=pd.to_datetime(['20250604','20250605','20250606','20250609'])
    bars=pd.DataFrame(dict(trade_date=dates,ts_code='001323.SZ',open=[31.29,31.29,31.29,30.30],
                           close=[31.29,31.29,31.29,29.76],adj_factor=[1.,1.,1.,1.032332976],
                           amount=100000000.,vol=10000000.,up_limit=40.,down_limit=20.))
    targets=pd.DataFrame(dict(ts_code=['001323.SZ'],signal_date=[dates[0]],
                              execution_date=[dates[1]],target_weight=[.03129]))
    run=simulate(bars,dates,targets,actions,config=Config(zero_trading_costs=True))
    nav=run['nav'].set_index('date')
    assert nav.loc[dates[-1],'cash']==969510.
    assert nav.loc[dates[-1],'stock_value']==29760.
    assert nav.loc[dates[-1],'equity']==999270.
    assert run['holdings'].loc[lambda f:f.date.eq(dates[-1]),'mark'].iloc[0]==29.76
