from dataclasses import asdict
import pandas as pd
import pytest

from alphaforge_r4_account import simulate_exposure, AccountRunFailure
from alphaforge_r4_guard import AccountDataFailure, prune_prices, share_price_scope
from quant_research.accounting import Action, Ledger
from quant_research.backtest import Config, simulate
from quant_research.rights import RightsIssue


def fixture():
    dates = pd.bdate_range('2020-01-02', periods=12)
    bars = pd.DataFrame(dict(trade_date=dates, ts_code='A', open=10., high=10., low=10.,
        close=10., vol=100000., amount=30000., up_limit=20., down_limit=1.,
        close_text='10.0', pre_close_text='10.0'))
    targets = pd.DataFrame(dict(execution_date=[dates[2]], signal_date=[dates[1]], ts_code='A', target_weight=.5))
    meta = pd.DataFrame([dict(ts_code='A', list_date='20100101', delist_date=None)])
    return dates, bars, targets, dict(universe=meta, full_calendar=dates,
        evidence=dict(ordinary_actions=[], status_events=[]))


def run(data, **kwargs):
    d,b,t,k = data
    config = kwargs.pop('config', Config(initial_cash=10000.,zero_trading_costs=True))
    return simulate_exposure(b,d,t,config=config,**k,**kwargs)


def normal_equal(a,b):
    for name in ('nav','orders','holdings','corporate_events'):
        if a[name].empty and b[name].empty:
            continue
        cols=b[name].columns
        pd.testing.assert_frame_equal(a[name][cols].reset_index(drop=True),b[name].reset_index(drop=True))


@pytest.mark.parametrize('bps',[0,10,30])
def test_original_execution_cash_capacity_costs_and_plain_holdings(bps):
    data=fixture();d,b,t,k=data
    t.loc[1]=[d[5],d[4],'A',.3]
    config=Config(initial_cash=10000.,slippage_bps=bps,zero_trading_costs=bps==0)
    normal_equal(run(data,config=config),simulate(b.assign(adj_factor=1.),d,t,config=config))


def test_empty_cash_account_has_no_seed_asset_or_global_gap_failure():
    d,b,t,k=fixture();b=b.iloc[5:].copy();t=t.iloc[:0]
    result=run((d,b,t,k))
    assert result['nav'].cash.eq(10000).all() and result['nav'].equity.eq(10000).all()
    assert result['holdings'].empty and result['reference_guard'].empty
    assert result['account_state']['prices']=={}


def test_invalid_unowned_quote_not_used_as_asset_or_guard_bypass_for_entry():
    data=fixture();data[1].loc[0,'pre_close_text']='INVALID'
    assert len(run(data)['nav'])==12  # before the formation-to-entry interval
    data[1].loc[2,'pre_close_text']='9.99'
    with pytest.raises(AccountRunFailure,match='unexplained_reference_change') as error:
        run(data)
    assert error.value.partial['nav'].shape[0]==2


def test_entry_checks_the_whole_signal_to_execution_bridge():
    data=fixture();d,b,t,k=data
    t.loc[0,['signal_date','execution_date']]=[d[0],d[3]]
    b.loc[1,'pre_close_text']='9.99'
    with pytest.raises(AccountRunFailure,match='unexplained_reference_change'):
        run(data)


def test_missing_unowned_execution_quote_is_rejected_without_asset_price():
    data=fixture();d,b,t,k=data;b=b.loc[b.trade_date.ne(d[2])]
    result=run((d,b,t,k))
    assert result['orders'].iloc[0].reason=='missing_execution_quote'
    assert result['orders'].shares.sum()==0 and result['account_state']['prices']=={}
    assert result['nav'].equity.eq(10000).all()


def test_held_missing_quote_requires_today_evidence():
    d,b,t,k=fixture();b=b.loc[b.trade_date.ne(d[3])]
    with pytest.raises(AccountRunFailure,match='missing_quote_without_asof_nontrade_evidence'):
        run((d,b,t,k))
    result=run((d,b,t,k),suspensions={(d[3],'A')})
    assert result['nav'].loc[result['nav'].date.eq(d[3]),'stale_value'].iloc[0]==5000


def action_data(stock=0.,cash=1.,sell=False):
    data=fixture();d,b,t,k=data
    a=Action('A',d[3],d[4],d[7] if cash else pd.NaT,d[8] if stock else pd.NaT,cash,stock,0.)
    price=(10.-cash)/(1+stock)
    b.loc[b.trade_date.ge(a.ex),['open','high','low','close']]=price
    b.loc[b.trade_date.ge(a.ex),['close_text','pre_close_text']]=str(price)
    if sell:t.loc[1]=[d[4],d[3],'A',0.]
    return data,a


def test_cash_entitlement_survives_sale_and_settles_later():
    data,a=action_data(sell=True);result=run(data,actions=[a])
    ex=result['nav'].loc[result['nav'].date.eq(a.ex)].iloc[0]
    assert ex.stock_value==0 and ex.receivable==400
    assert result['account_state']['prices']=={} and result['nav'].iloc[-1].receivable==0
    normal_equal(result,simulate(data[1].assign(adj_factor=1.),data[0],data[2],actions=[a],config=Config(initial_cash=10000.,zero_trading_costs=True)))


def test_future_stock_entitlement_retains_seed_even_after_selling():
    data,a=action_data(stock=.3,cash=0.)
    ledger=Ledger(10000);ledger.positions['A']=500;ledger.prices['A']=10.
    ledger.record(a.record,[a]);ledger.positions['A']=0
    prune_prices(ledger,[a]);assert 'A' in ledger.prices
    ledger.morning(a.ex,[a]);assert ledger.pending_shares('A')==150
    assert share_price_scope(ledger,[a])=={'A'}


def test_unowned_cached_negative_ex_adjustment_is_removed():
    data,a=action_data(cash=11.)
    # Unrelated security can have a stale price below its much later dividend.
    data[2].drop(data[2].index,inplace=True)
    result=run(data,actions=[a])
    assert result['nav'].cash.eq(10000.).all()


@pytest.mark.parametrize('stock,cash',[(0.,1.),(.3,0.)])
def test_reviewed_ordinary_action_across_pause_and_listing_while_paused(stock,cash):
    data,a=action_data(stock=stock,cash=cash);d,b,t,k=data
    k['evidence']['ordinary_actions']=[dict(asdict(a),known_date=str(d[0].date()),ordinary=True,sources=['fixture'])]
    for r in k['evidence']['ordinary_actions']:
        for f in ['record','ex','cash_pay','stock_pay']:
            r[f]=None if pd.isna(r[f]) else str(r[f].date())
    missing=set(d[3:10]);b=b.loc[~b.trade_date.isin(missing)]
    t.loc[1]=[d[8],d[7],'A',0.]
    result=run((d,b,t,k),actions=[a],suspensions={(day,'A') for day in missing})
    assert result['reference_guard'].reason.eq('registered_action_across_gap').any()
    if stock:
        assert result['holdings'].pending_shares.gt(0).any()
        order=result['orders'].loc[result['orders'].date.eq(d[8])].iloc[0]
        assert order.status=='rejected' and order.reason=='suspended'


def test_unreviewed_action_in_held_gap_stops_instead_of_repeating():
    data,a=action_data();d,b,t,k=data;b=b.loc[b.trade_date.ne(a.ex)]
    with pytest.raises(AccountRunFailure,match='unreviewed_distribution_across_quote_gap'):
        run((d,b,t,k),actions=[a],suspensions={(a.ex,'A')})


def test_nonadjacent_allowlisted_action_still_stops():
    data,a=action_data();d,b,t,k=data
    a=Action('A',d[2],d[4],d[7],pd.NaT,1.)
    k['evidence']['ordinary_actions']=[dict(asdict(a),known_date=str(d[0].date()),ordinary=True,sources=['fixture'])]
    b=b.loc[b.trade_date.ne(a.ex)]
    with pytest.raises(AccountRunFailure,match='nonadjacent_distribution_record_ex'):
        run((d,b,t,k),actions=[a],suspensions={(a.ex,'A')})


@pytest.mark.parametrize('subscribe',[False,True])
def test_original_rights_scenario_preserved(subscribe):
    data=fixture();d,b,t,k=data
    terms=dict(price=5.,ratio=.3,list_date=d[7]) if subscribe else {}
    r=RightsIssue('A',d[3],d[4],'official',**terms)
    b.loc[b.trade_date.ge(r.ex),['open','high','low','close']]=8.
    b.loc[b.trade_date.ge(r.ex),['close_text','pre_close_text']]='8.0'
    result=run(data,rights=[r])
    normal_equal(result,simulate(b.assign(adj_factor=1.),d,t,rights=[r],config=Config(initial_cash=10000.,zero_trading_costs=True)))
