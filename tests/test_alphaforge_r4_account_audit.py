"""Independent audit catches internally consistent but economically false logs."""
import json
from dataclasses import asdict

import pandas as pd
import pytest

from alphaforge_r4_account import simulate_exposure, AccountRunFailure
from verify_alphaforge_r4_account import verify_account
from quant_research.accounting import Action
from quant_research.backtest import Config
from quant_research.rights import RightsIssue


def fixture():
    dates=pd.bdate_range('2020-01-02',periods=10)
    full=pd.DatetimeIndex([pd.Timestamp('2019-12-31'),*dates])
    bars=pd.DataFrame(dict(trade_date=full,ts_code='A',open=10.,high=11.,low=9.,close=10.,
        vol=100000.,amount=30000.,up_limit=11.,down_limit=4.,close_text='10.0',pre_close_text='10.0'))
    targets=pd.DataFrame(dict(execution_date=[dates[2]],signal_date=[dates[1]],ts_code='A',target_weight=.49))
    universe=pd.DataFrame([dict(ts_code='A',list_date='20100101',delist_date=None)])
    suspension=pd.DataFrame(columns=['trade_date','ts_code','suspend_type','suspend_timing'])
    evidence=dict(ordinary_actions=[],status_events=[],rights_overlay=[])
    return dict(dates=dates,full=full,bars=bars,targets=targets,universe=universe,suspension=suspension,
                evidence=evidence,actions=(),rights=(),config=Config(initial_cash=10000.,slippage_bps=10))


def run(case):
    try:
        result=simulate_exposure(case['bars'],case['dates'],case['targets'],case['actions'],case['suspension'],
            config=case['config'],rights=case['rights'],universe=case['universe'],
            full_calendar=case['full'],evidence=case['evidence'])
        return result,None
    except AccountRunFailure as failure:
        return failure.partial,dict(date=str(failure.date.date()),reason=str(failure.original),type=type(failure.original).__name__)


def save(folder,result,failure=None):
    for name,frame in result.items():
        if isinstance(frame,pd.DataFrame):
            frame.to_csv(folder/(name+'.csv'),index=False)
    (folder/'account_state.json').write_text(json.dumps(result['account_state']),encoding='utf-8')
    if failure is not None:
        (folder/'failure.json').write_text(json.dumps(failure),encoding='utf-8')


def audit(folder,case,completed=True):
    return verify_account(folder,case['bars'],case['dates'],case['targets'],case['actions'],case['rights'],
        case['universe'],case['suspension'],case['evidence'],case['config'],completed=completed)


def test_plain_account_reconstructs_orders_cash_and_true_marks(tmp_path):
    case=fixture();result,failure=run(case)
    assert failure is None
    save(tmp_path,result)
    record=audit(tmp_path,case)
    assert record['status']=='passed' and record['days']==10
    assert record['orders_checked']==1 and not record['full_six_account_verification_passed']


def test_consistent_forged_mark_and_nav_is_rejected(tmp_path):
    case=fixture();result,failure=run(case)
    row=result['holdings'].index[-1]
    result['holdings'].loc[row,'mark']+=1.
    result['holdings'].loc[row,'value']=result['holdings'].loc[row,'shares']*result['holdings'].loc[row,'mark']
    day=result['nav'].index[-1]
    result['nav'].loc[day,'stock_value']=result['holdings'].loc[row,'value']
    result['nav'].loc[day,'equity']=result['nav'].loc[day,['cash','stock_value','bonus_value','receivable']].sum()
    result['holdings'].loc[row,'weight']=result['holdings'].loc[row,'value']/result['nav'].loc[day,'equity']
    save(tmp_path,result)
    with pytest.raises(AssertionError,match='Holdings'):
        audit(tmp_path,case)


def cash_case():
    case=fixture();dates=case['dates']
    case['actions']=(Action('A',dates[3],dates[4],dates[8],pd.NaT,1.,0.,0.),)
    case['targets']=pd.concat([case['targets'],pd.DataFrame([dict(execution_date=dates[5],signal_date=dates[4],ts_code='A',target_weight=0.)])],ignore_index=True)
    mask=case['bars'].trade_date>=dates[4]
    case['bars'].loc[mask,['open','close']]=9.
    case['bars'].loc[mask,'close_text']='9.0'
    case['bars'].loc[mask,'pre_close_text']='9.0'
    case['bars'].loc[mask,'low']=8.
    return case


def test_cash_receivable_survives_sale_and_settles_from_frozen_entitlement(tmp_path):
    case=cash_case();result,failure=run(case)
    assert failure is None
    day=result['nav'].loc[result['nav'].date.eq(case['dates'][6])].iloc[0]
    assert day.stock_value==0 and day.receivable>0
    save(tmp_path,result)
    assert audit(tmp_path,case)['corporate_events_checked']==2


def test_forged_tax_and_matching_nav_cannot_pass(tmp_path):
    case=cash_case();result,failure=run(case)
    row=result['corporate_events'].event.eq('ex')
    result['corporate_events'].loc[row,'assumed_tax']+=1.
    mask=result['nav'].date.between(case['dates'][4],case['dates'][7])
    result['nav'].loc[mask,['receivable','equity']]-=1.
    save(tmp_path,result)
    with pytest.raises(AssertionError,match='Corporate event'):
        audit(tmp_path,case)


def test_fee_log_is_recomputed_from_historical_scenario(tmp_path):
    case=fixture();result,failure=run(case)
    result['orders'].loc[0,'fee']+=1.
    result['orders'].loc[0,'cash_after']-=1.
    result['nav'].loc[result['nav'].date>=case['dates'][2],['cash','equity']]-=1.
    save(tmp_path,result)
    with pytest.raises(AssertionError,match='Order'):
        audit(tmp_path,case)


def test_rejection_reason_is_independently_verified(tmp_path):
    case=fixture()
    case['bars'].loc[case['bars'].trade_date.eq(case['dates'][2]),'open']=11.
    result,failure=run(case)
    assert failure is None and result['orders'].reason.iloc[0]=='price_limit'
    save(tmp_path,result)
    assert audit(tmp_path,case)['orders_checked']==1
    result['orders'].loc[0,'reason']='suspended'
    save(tmp_path,result)
    with pytest.raises(AssertionError,match='Order'):
        audit(tmp_path,case)


def test_real_failure_only_signs_completed_prefix(tmp_path):
    case=fixture()
    case['bars']=case['bars'].loc[case['bars'].trade_date.ne(case['dates'][4])]
    result,failure=run(case)
    assert failure is not None
    save(tmp_path,result,failure)
    record=audit(tmp_path,case,completed=False)
    assert record['status']=='passed_partial' and record['days']==4
    assert not record['completed_account']
    with pytest.raises(AssertionError):
        audit(tmp_path,case,completed=True)


def test_future_state_announcement_does_not_change_earlier_audit(tmp_path):
    case=fixture();result,failure=run(case)
    save(tmp_path,result)
    baseline=audit(tmp_path,case)
    case['evidence']['status_events']=[dict(code='A',state='suspended_listing',known_date='2030-01-02',effective_date='2020-01-01')]
    assert audit(tmp_path,case)==baseline


def test_stale_bonus_listing_during_pause_and_rejected_sale_are_rebuilt(tmp_path):
    case=fixture();dates=case['dates']
    action=Action('A',dates[3],dates[4],pd.NaT,dates[5],0.,.3,0.)
    case['actions']=(action,)
    source={key:str(value.date()) if isinstance(value,pd.Timestamp) else None if value is pd.NaT else value
            for key,value in asdict(action).items()}
    source.update(known_date='2019-12-01',ordinary=True,special_distribution=False,sources=['frozen_test_source'])
    case['evidence']['ordinary_actions']=[source]
    case['bars']=case['bars'].loc[~case['bars'].trade_date.isin(dates[4:6])].copy()
    later=case['bars'].trade_date>=dates[6]
    case['bars'].loc[later,['open','close']]=8.
    case['bars'].loc[later,'close_text']='8.0'
    case['bars'].loc[later,'pre_close_text']='8.0'
    case['bars'].loc[later,'low']=7.
    case['bars'].loc[case['bars'].trade_date.eq(dates[6]),'pre_close_text']='7.69'
    case['suspension']=pd.DataFrame([dict(trade_date=d,ts_code='A',suspend_type='S',suspend_timing='') for d in dates[4:6]])
    case['targets']=pd.concat([case['targets'],pd.DataFrame([dict(execution_date=dates[5],signal_date=dates[3],ts_code='A',target_weight=0.)])],ignore_index=True)
    result,failure=run(case)
    assert failure is None
    paused=result['nav'].loc[result['nav'].date.eq(dates[4])].iloc[0]
    assert paused.bonus_value>0 and paused.stale_value>0
    assert result['orders'].iloc[-1].reason=='suspended'
    save(tmp_path,result)
    record=audit(tmp_path,case)
    assert record['corporate_events_checked']==2


@pytest.mark.parametrize('subscribe',[False,True])
def test_rights_individual_terms_and_listing_cash_are_rebuilt(tmp_path,subscribe):
    case=fixture();dates=case['dates']
    terms=dict(price=5.,ratio=.3,list_date=dates[7]) if subscribe else {}
    case['rights']=(RightsIssue('A',dates[3],dates[4],'frozen_test_source',**terms),)
    later=case['bars'].trade_date>=dates[4]
    case['bars'].loc[later,['open','close']]=8.
    case['bars'].loc[later,'close_text']='8.0'
    case['bars'].loc[later,'pre_close_text']='8.0'
    case['bars'].loc[later,'low']=7.
    result,failure=run(case)
    assert failure is None
    save(tmp_path,result)
    record=audit(tmp_path,case)
    assert record['corporate_events_checked']==(2 if subscribe else 1)


def test_absent_execution_quote_retains_explicit_rejected_original_plan(tmp_path):
    case=fixture();date=case['dates'][2]
    case['bars']=case['bars'].loc[case['bars'].trade_date.ne(date)]
    result,failure=run(case)
    assert failure is None
    assert result['orders'].reason.tolist()==['missing_execution_quote']
    save(tmp_path,result)
    assert audit(tmp_path,case)['orders_checked']==1


def sold_before_ex_case():
    case=fixture();dates=case['dates']
    case['actions']=(Action('A',dates[3],dates[6],dates[8],pd.NaT,1.,0.,0.),)
    case['targets']=pd.concat([case['targets'],pd.DataFrame([dict(execution_date=dates[4],signal_date=dates[3],ts_code='A',target_weight=0.)])],ignore_index=True)
    return case


def test_unsourced_unapplied_cash_right_across_gap_stops_without_stock_price_duty(tmp_path):
    case=sold_before_ex_case()
    case['bars']=case['bars'].loc[case['bars'].trade_date.ne(case['dates'][6])]
    result,failure=run(case)
    assert failure is not None and 'unreviewed_distribution' in failure['reason']
    assert result['account_state']['positions']=={} and result['account_state']['prices']=={}
    save(tmp_path,result,failure)
    record=audit(tmp_path,case,completed=False)
    assert record['data_stop_independently_reproduced'] is True


def test_independent_audit_catches_cash_source_gate_even_when_all_money_matches(tmp_path):
    case=sold_before_ex_case();result,failure=run(case)
    assert failure is None
    save(tmp_path,result)
    # No shares remain, so removing this raw quote changes no ledger amount.
    # It still changes the missing-quote source gate for unexecuted cash rights.
    case['bars']=case['bars'].loc[case['bars'].trade_date.ne(case['dates'][6])]
    with pytest.raises(AssertionError,match='Unreviewed ordinary action'):
        audit(tmp_path,case)


def test_pending_cash_after_sale_needs_no_quote_or_suspension_proof(tmp_path):
    case=cash_case()
    case['bars']=case['bars'].loc[~case['bars'].trade_date.isin(case['dates'][6:8])]
    result,failure=run(case)
    assert failure is None
    assert result['holdings'].loc[result['holdings'].date.isin(case['dates'][6:8])].empty
    save(tmp_path,result)
    record=audit(tmp_path,case)
    assert record['status']=='passed' and record['corporate_events_checked']==2
