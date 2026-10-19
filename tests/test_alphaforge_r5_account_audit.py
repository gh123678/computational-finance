"""Independent audit catches internally consistent but economically false logs."""
import json
from dataclasses import asdict

import pandas as pd
import pytest

from alphaforge_r5_account import simulate_exposure, AccountRunFailure
from verify_alphaforge_r5_account import verify_account
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


def dated_case(start, end, code):
    case=fixture()
    dates=pd.bdate_range(start,end)
    full=pd.DatetimeIndex([dates[0]-pd.offsets.BDay(),*dates])
    case.update(dates=dates,full=full)
    case['bars']=pd.DataFrame(dict(trade_date=full,ts_code=code,open=10.,high=11.,low=7.,close=10.,
        vol=100000.,amount=30000.,up_limit=11.,down_limit=4.,close_text='10.0',pre_close_text='10.0'))
    case['targets']=pd.DataFrame([dict(execution_date=dates[2],signal_date=dates[1],ts_code=code,target_weight=.49)])
    case['universe']=pd.DataFrame([dict(ts_code=code,list_date='20100101',delist_date=None)])
    return case


def raw_action(action):
    return {k:(str(v.date()) if isinstance(v,pd.Timestamp) else None if v is pd.NaT else v)
            for k,v in asdict(action).items()}


def raw_version(action, version, known, role, *, apply=True, special=False):
    item=raw_action(action)
    item.update(event_id=action.code+'|'+str(action.ex.date()),version=version,known_date=known,
        role=role,printed_date=known,ordinary=apply,apply_distribution=apply,
        reference_explained=apply,unsupported_special=special,original_action=raw_action(action),
        sources=[dict(known_date=known,role=role,url='frozen:'+role)])
    if special:
        item['stock_per_share']='0'
        item['company_total_expansion_per_original_share']='0.5641598'
    return item


def cancellation_case():
    case=dated_case('2019-07-16','2019-07-26','600781.SH')
    action=Action('600781.SH',pd.Timestamp('2019-07-19'),pd.Timestamp('2019-07-22'),
                  pd.Timestamp('2019-07-22'),pd.NaT,.1,0.,0.)
    case['actions']=(action,)
    case['evidence']['event_versions']=[
        raw_version(action,1,'2019-07-16','planned_distribution'),
        raw_version(action,2,'2019-07-20','cancelled',apply=False)]
    return case


@pytest.mark.parametrize('missing',[False,True])
def test_cancelled_plan_keeps_research_record_without_cash_or_ex_mark(tmp_path,missing):
    case=cancellation_case()
    if missing:
        date=pd.Timestamp('2019-07-22')
        case['bars']=case['bars'].loc[case['bars'].trade_date.ne(date)]
        case['suspension']=pd.DataFrame([dict(trade_date=date,ts_code='600781.SH',suspend_type='S',suspend_timing='')])
    result,failure=run(case)
    assert failure is None
    assert result['corporate_events'].event.tolist()==['distribution_research_record','distribution_cancelled']
    assert result['corporate_events'].entitled_shares.tolist()==[400,400]
    assert result['nav'].receivable.eq(0).all()
    assert result['nav'].cash.iloc[-1]==result['nav'].cash.iloc[2]
    assert result['holdings']['mark'].eq(10).all()
    archive=result['account_state']['scenario_entitlements'][0]
    assert archive['recorded_date']=='2019-07-19' and archive['cancelled_date']=='2019-07-22'
    assert archive['status']=='cancelled' and archive['cancellation_known_date']=='2019-07-20'
    save(tmp_path,result)
    assert audit(tmp_path,case)['corporate_events_checked']==2


def test_future_cancellation_changes_do_not_erase_earlier_research_record(tmp_path):
    case=cancellation_case()
    case['dates']=case['dates'][case['dates']<='2019-07-19']
    result,failure=run(case)
    assert failure is None
    save(tmp_path,result)
    baseline=audit(tmp_path,case)
    case['evidence']['event_versions'][1]['known_date']='2030-01-01'
    case['evidence']['event_versions'][1]['sources'][0]['known_date']='2030-01-01'
    assert audit(tmp_path,case)==baseline
    assert result['account_state']['scenario_entitlements'][0]['status']=='planned'


def test_consistent_cancelled_plan_ghost_cash_is_rejected(tmp_path):
    case=cancellation_case();result,failure=run(case)
    mask=result['nav'].date.ge('2019-07-22')
    result['nav'].loc[mask,['cash','equity']]+=40.
    result['account_state']['cash']+=40.
    save(tmp_path,result)
    with pytest.raises(AssertionError,match='NAV'):
        audit(tmp_path,case)


def test_cancellation_cannot_explain_a_later_raw_reference_break(tmp_path):
    case=cancellation_case()
    case['bars'].loc[case['bars'].trade_date.eq('2019-07-22'),'pre_close_text']='9.9'
    result,failure=run(case)
    assert failure is not None and 'unexplained_reference_change' in failure['reason']
    save(tmp_path,result,failure)
    assert audit(tmp_path,case,completed=False)['data_stop_independently_reproduced'] is True


def special_case():
    case=dated_case('2019-12-23','2020-01-03','601258.SH')
    action=Action('601258.SH',pd.Timestamp('2019-12-27'),pd.Timestamp('2019-12-30'),pd.NaT,
                  pd.Timestamp('2019-12-31'),0.,.5641598,0.)
    case['actions']=(action,)
    case['evidence']['event_versions']=[raw_version(action,1,'2019-12-24','special_reorganization',apply=False,special=True)]
    return case


@pytest.mark.parametrize('missing',[False,True])
def test_special_reorganization_actual_holdings_stop_even_when_quoted(tmp_path,missing):
    case=special_case()
    if missing:
        date=pd.Timestamp('2019-12-27')
        case['bars']=case['bars'].loc[case['bars'].trade_date.ne(date)]
        case['suspension']=pd.DataFrame([dict(trade_date=date,ts_code='601258.SH',suspend_type='S',suspend_timing='')])
    result,failure=run(case)
    assert failure is not None and failure['date']=='2019-12-27'
    assert 'unsupported_special_reorganization' in failure['reason']
    assert result['corporate_events'].empty and result['nav'].bonus_value.eq(0).all()
    save(tmp_path,result,failure)
    record=audit(tmp_path,case,completed=False)
    assert record['data_stop_independently_reproduced'] is True


@pytest.mark.parametrize('stage',['2019-12-27','2019-12-30','2019-12-31'])
def test_special_planned_bridge_stops_on_each_stage_with_no_prior_position(tmp_path,stage):
    case=special_case();day=pd.Timestamp(stage)
    case['targets']=pd.DataFrame([dict(execution_date=day,signal_date=day-pd.offsets.BDay(),ts_code='601258.SH',target_weight=.49)])
    result,failure=run(case)
    assert failure is not None and failure['date']==stage
    assert result['orders'].empty
    save(tmp_path,result,failure)
    assert audit(tmp_path,case,completed=False)['data_stop_independently_reproduced'] is True


def test_unexposed_special_diagnostic_never_gives_ordinary_bonus_or_stale_discount(tmp_path):
    case=special_case();case['targets']=case['targets'].iloc[:0]
    result,failure=run(case)
    assert failure is None and result['corporate_events'].empty
    assert result['account_state']['pending']==[] and result['account_state']['prices']=={}
    save(tmp_path,result)
    assert audit(tmp_path,case)['status']=='passed'


def quota_case():
    case=dated_case('2020-03-04','2020-04-02','000977.SZ')
    issue=RightsIssue('000977.SZ',pd.Timestamp('2020-03-10'),pd.Timestamp('2020-03-19'),
                      'frozen_original_result_catalogue',12.92,.1177945,pd.Timestamp('2020-03-27'))
    case['rights']=(issue,)
    case['evidence']['rights_stages']=[dict(code=issue.code,record='2020-03-10',ex='2020-03-19',
        event_id='000977_quota',price='12.92',quota_ratio='0.12',market_ex_ratio='0.1177945',
        list_date='2020-03-27',terms_known_date='2020-03-06',result_known_date='2020-03-19',
        listing_known_date='2020-03-26',original_subscription_authorized=True,
        original_subscription_terms=dict(price='12.92',ratio='0.1177945',list_date='2020-03-27'),
        sources=[dict(role=role,known_date=known,url='frozen:'+role,publication_time_intraday_certified=False)
                 for role,known in [('issuance','2020-03-06'),('actual_result','2020-03-19'),('listing','2020-03-26')]])]
    # Buy on March 9: March 6's date-only source is prior evidence at execution.
    case['targets'].loc[0,['signal_date','execution_date']]=[pd.Timestamp('2020-03-06'),pd.Timestamp('2020-03-09')]
    return case


def test_individual_quota_floor_cash_and_later_listing_are_independently_rebuilt(tmp_path):
    case=quota_case();result,failure=run(case)
    assert failure is None
    sub=result['corporate_events'].loc[result['corporate_events'].event.eq('rights_subscribed')].iloc[0]
    assert sub.entitled_shares==400 and sub.allotted_shares==48 and sub.cost==620.16
    assert sub.ratio==.12 and pd.isna(sub.market_ex_ratio) and pd.isna(sub.list_date)
    assert sub.personal_actual_allocation_certified==False
    pending=result['obligations'].loc[(result['obligations'].date.eq('2020-03-26')) & result['obligations'].kind.eq('pending')]
    payload=json.loads(pending.payload.iloc[0])
    assert payload['shares']==48 and payload['stock_pay'] is None and payload['listing_known_date'] is None
    assert payload['quota_ratio']==.12 and payload['market_ex_ratio'] is None
    known=result['corporate_events'].loc[result['corporate_events'].event.eq('rights_listing_date_known')].iloc[0]
    assert str(known.date.date())=='2020-03-27' and known.list_date=='2020-03-27'
    assert result['account_state']['positions']=={'000977.SZ':448}
    save(tmp_path,result)
    assert audit(tmp_path,case)['corporate_events_checked']==3


def test_future_listing_source_perturbation_cannot_change_prepublication_pending(tmp_path):
    case=quota_case();case['dates']=case['dates'][case['dates']<='2020-03-25']
    result,failure=run(case)
    assert failure is None
    save(tmp_path,result);baseline=audit(tmp_path,case)
    stage=case['evidence']['rights_stages'][0]
    stage['listing_known_date']='2030-01-01';stage['list_date']='2030-01-02'
    stage['sources'][-1]['known_date']='2030-01-01'
    assert audit(tmp_path,case)==baseline


def test_consistent_future_listing_prefill_in_obligation_is_rejected(tmp_path):
    case=quota_case();case['dates']=case['dates'][case['dates']<='2020-03-25']
    result,failure=run(case)
    assert failure is None
    pending=result['obligations'].kind.eq('pending')
    def forge(text):
        payload=json.loads(text);payload['stock_pay']='2020-03-27';payload['listing_known_date']='2020-03-26'
        return json.dumps(payload)
    result['obligations'].loc[pending,'payload']=result['obligations'].loc[pending,'payload'].map(forge)
    result['account_state']['pending'][0].update(stock_pay='2020-03-27',listing_known_date='2020-03-26')
    save(tmp_path,result)
    with pytest.raises(AssertionError,match='Obligations'):
        audit(tmp_path,case)


def test_personal_quota_cannot_be_replaced_with_market_ex_ratio(tmp_path):
    case=quota_case();result,failure=run(case)
    assert failure is None
    save(tmp_path,result)
    case['evidence']['rights_stages'][0]['quota_ratio']='0.1177945'
    with pytest.raises(AssertionError,match='personal quota'):
        audit(tmp_path,case)


def test_unusable_rights_record_source_failure_replays_day_after_new_purchase(tmp_path):
    case=quota_case()
    case['targets'].loc[0,['signal_date','execution_date']]=[pd.Timestamp('2020-03-09'),pd.Timestamp('2020-03-10')]
    stage=case['evidence']['rights_stages'][0]
    stage['terms_known_date']='2020-03-10';stage['sources'][0]['known_date']='2020-03-10'
    result,failure=run(case)
    assert failure is not None and 'rights_record_source_not_usable_asof' in failure['reason']
    assert result['orders'].empty and result['account_state']['positions']=={}
    save(tmp_path,result,failure)
    assert audit(tmp_path,case,completed=False)['data_stop_independently_reproduced'] is True


def test_stop_must_match_reason_and_code_not_merely_any_independent_failure(tmp_path):
    case=fixture();case['bars']=case['bars'].loc[case['bars'].trade_date.ne(case['dates'][4])]
    result,failure=run(case)
    stops=result['reference_guard'].decision.eq('stop')
    result['reference_guard'].loc[stops,'reason']='unexplained_reference_change'
    save(tmp_path,result,failure)
    with pytest.raises(AssertionError,match='Independent stop differs'):
        audit(tmp_path,case,completed=False)


@pytest.mark.parametrize('kind',['pending_share','pending_cash','unapplied_cash'])
def test_special_stops_economic_obligation_after_all_tradable_shares_sold(tmp_path,kind):
    original=special_case()
    case=dated_case('2019-12-18','2020-01-03','601258.SH')
    case['evidence']=original['evidence']
    ex=pd.Timestamp('2020-01-02' if kind=='unapplied_cash' else '2019-12-24')
    prior=Action('601258.SH',pd.Timestamp('2019-12-23'),ex,
        pd.Timestamp('2020-01-06') if kind!='pending_share' else pd.NaT,
        pd.Timestamp('2020-01-06') if kind=='pending_share' else pd.NaT,
        0. if kind=='pending_share' else 1.,.1 if kind=='pending_share' else 0.,0.)
    case['actions']=(prior,*original['actions'])
    case['targets']=pd.concat([case['targets'],pd.DataFrame([dict(
        signal_date=pd.Timestamp('2019-12-25'),execution_date=pd.Timestamp('2019-12-26'),
        ts_code='601258.SH',target_weight=0.)])],ignore_index=True)
    result,failure=run(case)
    assert failure is not None and failure['date']=='2019-12-27'
    assert result['account_state']['positions']=={}
    assert 'unsupported_special_reorganization' in failure['reason']
    save(tmp_path,result,failure)
    assert audit(tmp_path,case,completed=False)['data_stop_independently_reproduced'] is True


@pytest.mark.parametrize('code,ex,stock',[
    ('000711.SZ','2018-05-28',.1),('002301.SZ','2018-05-28',.1),
    ('002647.SZ','2018-06-01',.1),('002485.SZ','2018-06-12',.1),
    ('002856.SZ','2018-06-20',.1),('002668.SZ','2018-07-06',.1),
    ('002602.SZ','2018-10-31',.1),('002470.SZ','2018-06-19',0.),
])
@pytest.mark.parametrize('missing',[False,True])
def test_unresolved_tax_and_publication_keys_keep_existing_quote_gap_boundary(tmp_path,code,ex,stock,missing):
    ex=pd.Timestamp(ex)
    case=dated_case(ex-pd.offsets.BDay(5),ex+pd.offsets.BDay(4),code)
    case['actions']=(Action(code,ex-pd.offsets.BDay(),ex,ex+pd.offsets.BDay(2),
                           ex+pd.offsets.BDay() if stock else pd.NaT,.1,stock,0.),)
    if missing:
        case['bars']=case['bars'].loc[case['bars'].trade_date.ne(ex)]
        case['suspension']=pd.DataFrame([dict(trade_date=ex,ts_code=code,suspend_type='S',suspend_timing='')])
    result,failure=run(case)
    assert (failure is not None)==missing
    if missing:
        assert 'unreviewed_distribution_across_quote_gap' in failure['reason']
    save(tmp_path,result,failure)
    record=audit(tmp_path,case,completed=not missing)
    assert record['data_stop_independently_reproduced'] is (True if missing else None)


def test_personal_quota_insufficient_cash_rejects_entire_research_subscription(tmp_path):
    case=quota_case();case['targets'].loc[0,'target_weight']=.9
    result,failure=run(case)
    assert failure is None
    event=result['corporate_events'].loc[result['corporate_events'].event.eq('rights_not_subscribed')].iloc[0]
    assert event.entitled_shares==900 and event.reason=='insufficient_cash'
    assert result['account_state']['pending']==[] and result['account_state']['positions']=={'000977.SZ':900}
    save(tmp_path,result)
    assert audit(tmp_path,case)['status']=='passed'


def test_later_listing_release_stays_locked_and_odd_lot_sells_next_day(tmp_path):
    case=quota_case()
    case['targets']=pd.concat([case['targets'],pd.DataFrame([
        dict(signal_date=pd.Timestamp('2020-03-26'),execution_date=pd.Timestamp('2020-03-27'),ts_code='000977.SZ',target_weight=0.),
        dict(signal_date=pd.Timestamp('2020-03-27'),execution_date=pd.Timestamp('2020-03-30'),ts_code='000977.SZ',target_weight=0.),
    ])],ignore_index=True)
    result,failure=run(case)
    assert failure is None
    sold=result['orders'].loc[result['orders'].side.eq('sell')]
    assert sold.shares.tolist()==[400,48]
    assert result['holdings'].loc[result['holdings'].date.eq('2020-03-27'),'shares'].iloc[0]==48
    assert result['account_state']['positions']=={}
    save(tmp_path,result)
    assert audit(tmp_path,case)['status']=='passed'


def test_same_day_cancellation_source_cannot_be_assumed_preopen(tmp_path):
    case=cancellation_case()
    source=case['evidence']['event_versions'][1]
    source['known_date']='2019-07-22';source['sources'][0]['known_date']='2019-07-22'
    result,failure=run(case)
    assert failure is not None and 'distribution_source_not_usable_preopen' in failure['reason']
    assert result['account_state']['scenario_entitlements'][0]['status']=='planned'
    save(tmp_path,result,failure)
    assert audit(tmp_path,case,completed=False)['independent_stop_reason']=='distribution_source_not_usable_preopen'


def test_600999_keeps_original_terms_and_prior_only_listing_knowledge(tmp_path):
    case=dated_case('2020-07-03','2020-08-05','600999.SH')
    issue=RightsIssue('600999.SH',pd.Timestamp('2020-07-09'),pd.Timestamp('2020-07-20'),
        'frozen_original_600999',7.46,.3,pd.Timestamp('2020-07-31'))
    case['rights']=(issue,)
    case['evidence']['rights_stages']=[dict(code=issue.code,record='2020-07-09',ex='2020-07-20',event_id='600999',
        price='7.46',quota_ratio='0.3',market_ex_ratio=None,list_date='2020-07-31',
        terms_known_date='2020-07-07',result_known_date='2020-07-20',listing_known_date='2020-07-28',
        original_subscription_authorized=True,original_subscription_terms=dict(price='7.46',ratio='0.3',list_date='2020-07-31'),
        sources=[dict(role=role,known_date=known,url='frozen:'+role,publication_time_intraday_certified=False)
            for role,known in [('issuance','2020-07-07'),('actual_result','2020-07-20'),('listing','2020-07-28')]])]
    result,failure=run(case)
    assert failure is None
    subscribed=result['corporate_events'].loc[result['corporate_events'].event.eq('rights_subscribed')].iloc[0]
    assert subscribed.ratio==.3 and subscribed.price==7.46 and subscribed.cost==895.2
    assert subscribed.allotted_shares==120 and pd.isna(subscribed.result_known_date) and pd.isna(subscribed.list_date)
    known=result['corporate_events'].loc[result['corporate_events'].event.eq('rights_listing_date_known')].iloc[0]
    assert known.date==pd.Timestamp('2020-07-29') and known.list_date=='2020-07-31'
    save(tmp_path,result)
    assert audit(tmp_path,case)['status']=='passed'


def test_new_source_full_terms_do_not_authorize_original_no_subscription(tmp_path):
    case=fixture();dates=case['dates']
    issue=RightsIssue('A',dates[3],dates[4],'frozen_no_terms')
    case['rights']=(issue,)
    case['evidence']['rights_stages']=[dict(code='A',record=str(dates[3].date()),ex=str(dates[4].date()),
        price=5.,quota_ratio=.3,market_ex_ratio=.29,list_date=str(dates[7].date()),
        terms_known_date='2019-12-01',result_known_date='2019-12-02',listing_known_date='2019-12-03',
        original_subscription_authorized=False,sources=[dict(role=role,known_date=known)
            for role,known in [('issuance','2019-12-01'),('actual_result','2019-12-02'),('listing','2019-12-03')]])]
    result,failure=run(case)
    assert failure is None and result['corporate_events'].event.tolist()==['rights_not_subscribed']
    assert result['account_state']['pending']==[]
    save(tmp_path,result)
    assert audit(tmp_path,case)['status']=='passed'


def test_auditor_never_invokes_simulator_guard_or_producer_asof_helpers(tmp_path,monkeypatch):
    case=quota_case();result,failure=run(case)
    assert failure is None
    save(tmp_path,result)
    def forbidden(*args,**kwargs):
        raise RuntimeError('Independent auditor invoked a producer')
    for module,name in [('alphaforge_r5_account','simulate_exposure'),('alphaforge_r5_account','Ledger'),
                        ('alphaforge_r5_guard','ExposureGuard'),('alphaforge_r5_events','distribution_view'),
                        ('alphaforge_r5_events','rights_stage')]:
        monkeypatch.setattr(module+'.'+name,forbidden)
    record=audit(tmp_path,case)
    assert record['account_simulation_imported'] is False and record['guard_module_imported'] is False


def test_future_listing_doc_cannot_enter_subscription_stage_evidence_even_if_cash_matches(tmp_path):
    case=quota_case();result,failure=run(case)
    assert failure is None
    mask=result['corporate_events'].event.eq('rights_subscribed')
    result['corporate_events'].loc[mask,'stage_sources']=json.dumps(case['evidence']['rights_stages'][0]['sources'])
    save(tmp_path,result)
    with pytest.raises(AssertionError,match='Corporate event'):
        audit(tmp_path,case)


def test_research_registration_archive_cannot_be_deleted_when_nav_is_identical(tmp_path):
    case=cancellation_case();result,failure=run(case)
    assert failure is None
    result['account_state']['scenario_entitlements']=[]
    save(tmp_path,result)
    with pytest.raises(AssertionError,match='Research scenario entitlement archive'):
        audit(tmp_path,case)


def test_empty_account_cannot_broaden_production_23_source_key_permission(tmp_path):
    case=fixture();result,failure=run(case)
    assert failure is None
    save(tmp_path,result)
    case['evidence'].update(schema_version=5,ordinary_actions=[dict(code='000711.SZ',ex='2018-05-28')])
    with pytest.raises(AssertionError,match='23-source-key scope'):
        audit(tmp_path,case)
