"""Small adversarial r3 verifier cases; no historical experiment runs."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verify_alphaforge_r3 import (event_index,exact_primary_identity,independent_bridge,
                                 independent_chain,independent_features,independent_label,
                                 lifecycle,independent_guard,independent_registry,
                                 assert_six_completed,PATHS,write_json_exclusive)
from quant_research.accounting import Action


def quote_frame(n=21):
    dates=pd.bdate_range('2018-01-01',periods=n)
    prices=np.arange(n,dtype=float)+10
    frame=pd.DataFrame(dict(ts_code='A',close=prices,open=prices,
                            close_text=[str(value) for value in prices],
                            pre_close=[np.nan,*prices[:-1]],
                            pre_close_text=['',*[str(value) for value in prices[:-1]]],
                            vol=100.,amount=1000.,high=prices+1,low=prices-1))
    return dates,frame


def events(effective,known,verified=True,conflict=False):
    frame=pd.DataFrame([dict(code='A',event_id='E',event_date=effective,known_date=known,
                             timing_verified=verified,conflict=conflict)])
    return event_index(frame)['A']


def test_twenty_internal_bridges_ignore_first_reference_and_close_only_window():
    dates,q=quote_frame()
    q.loc[0,'pre_close_text']='invalid-start-outside-bridge'
    q[['open','high','low','vol','amount']]=np.nan
    result,path=independent_features(q,dates,cutoff=dates[-1])
    assert result['reference_valid']
    assert path['counts']['bridge_count']==path['counts']['valid_bridge_count']==20
    assert path['valid_quote_count']==21 and path['scale']==[1.]*21
    assert result['momentum20']==pytest.approx(2)
    assert result['reversal5']==pytest.approx(-.2)
    expected=-np.std(np.arange(11.,31.)/np.arange(10.,30.)-1,ddof=1)
    assert result['lowvol20']==pytest.approx(expected)


def test_raw_decimal_difference_cannot_be_hidden_by_float_parser():
    dates,q=quote_frame()
    q.loc[0,'close_text']='10.00000000000000001'
    q.loc[1,'pre_close_text']='10.00000000000000002'
    assert float(q.loc[0,'close_text'])==float(q.loc[1,'pre_close_text'])
    result,path=independent_features(q,dates,cutoff=dates[-1])
    assert not result['reference_valid']
    assert path['counts']['unexplained_reference_change_count']==1


def test_cash_reference_link_is_conditional_not_cash_account_wealth():
    dates,q=quote_frame()
    q.loc[5,'pre_close_text']='13.0';q.loc[5,'pre_close']=13.
    q.loc[5,'close_text']='15.0'
    known=events(dates[5],dates[4])
    result,path=independent_features(q,dates,known,dates[-1])
    assert result['reference_valid']
    assert path['scale'][5]==pytest.approx(14/13)
    assert path['counts']['known_action_count']==1
    assert path['counts']['reference_change_count']==1


def test_label_uses_each_bridge_cutoff_not_old_formation_cutoff():
    dates,q=quote_frame(6)
    q.loc[3,'pre_close_text']='10';q.loc[3,'pre_close']=10.
    known=events(dates[3],dates[2])
    assert not independent_chain(q,dates,known,dates[0])['valid']
    label,path=independent_label(q,dates,known,[100.,105.])
    assert label['R_valid']
    assert label['R_week']==pytest.approx((q.open.iloc[-1]*path['scale'][-1]/q.open.iloc[0]-1)-.05)


@pytest.mark.parametrize('known,verified',[(None,False),('2018-02-01',True),('2018-01-01',False)])
def test_unknown_or_future_event_is_risk_not_automatic_invalidation(known,verified):
    dates,q=quote_frame()
    record=events(dates[5],known,verified)
    result,path=independent_features(q,dates,record,dates[-1])
    assert result['reference_valid'] and path['counts']['event_timing_unverified_count']==1
    q.loc[5,'pre_close_text']='5'
    result,path=independent_features(q,dates,record,dates[-1])
    assert not result['reference_valid']


def test_known_conflict_blocks_even_equal_reference():
    dates,q=quote_frame()
    result,path=independent_features(q,dates,events(dates[5],dates[4],conflict=True),dates[-1])
    assert not result['reference_valid'] and path['reason']=='known_action_conflict'


def test_closed_day_event_maps_literal_interval_and_start_event_excluded():
    friday,monday=pd.Timestamp('2018-01-05'),pd.Timestamp('2018-01-08')
    record=events(pd.Timestamp('2018-01-06'),friday)
    bridge=independent_bridge('10','9',friday,monday,record,monday)
    assert bridge['valid'] and bridge['known_ids']==['E']
    outside=events(friday,friday)
    assert not independent_bridge('10','9',friday,monday,outside,monday)['valid']


def test_missing_stock_or_benchmark_label_endpoint_keeps_missing():
    dates,q=quote_frame(6)
    q.loc[0,'open']=np.nan
    label,_=independent_label(q,dates,[],[100.,101.])
    assert not label['R_valid'] and label['R_reason']=='stock_endpoint' and np.isnan(label['R_week'])
    label,_=independent_label(q,dates,[],[100.,np.nan])
    assert label['R_reason']=='benchmark_endpoint'


def identity_frames():
    old=pd.DataFrame(dict(trade_date=[pd.Timestamp('2018-01-05')]*3,ts_code=['A','B','C'],
                          industry=['I','I','J'],case_factor=[-.1,0.,.1],case_signal=[.1,0.,-.1]))
    common=old.copy();common['primary_score']=[1.,2/3,1/3]
    return common,old


def test_primary_identity_is_exact_and_industry_bound():
    common,old=identity_frames()
    assert exact_primary_identity(common,old)['exact_primary_formula']
    common.loc[0,'case_factor']=np.nextafter(common.loc[0,'case_factor'],np.inf)
    with pytest.raises(AssertionError):exact_primary_identity(common,old)


@pytest.mark.parametrize('fault',['keys','industry','rank'])
def test_exact_identity_rejects_scope_industry_or_rank_change(fault):
    common,old=identity_frames()
    if fault=='keys':common.loc[0,'ts_code']='NEW'
    elif fault=='industry':common.loc[0,'industry']='CHANGED'
    else:common.loc[0,'primary_score']=np.nextafter(1.,0.)
    with pytest.raises(AssertionError):exact_primary_identity(common,old)


def test_lifecycle_four_states_and_invalid_dates():
    listing=pd.Timestamp('2018-01-03');delisting=pd.Timestamp('2018-01-05')
    assert [lifecycle(pd.Timestamp(day),listing,delisting) for day in
            ['2018-01-02','2018-01-03','2018-01-05','2018-01-08']]==[
                'pre_listing','listed','scheduled_delisting','post_delisting']
    assert lifecycle(listing,listing,pd.NaT)=='listed'
    assert lifecycle(listing,pd.NaT,delisting)=='invalid_lifecycle'
    assert lifecycle(listing,delisting,listing)=='invalid_lifecycle'


def guard_fixture(missing_second=False,suspended=False):
    dates=pd.bdate_range('2018-01-01',periods=3)
    bars=pd.DataFrame(dict(trade_date=dates,ts_code='A',close_text=['10','11','12'],
                           pre_close_text=['9','10','11'],open=[10.,11.,12.],
                           close=[10.,11.,12.],vol=100.,amount=1000.))
    rows=[]
    for i,date in enumerate(dates[1:],1):
        rows.append(dict(date=date,ts_code='A',lifecycle='listed',has_quote=True,
            prior_quote_date=dates[i-1],prior_close_text=str(9+i),pre_close_text=str(9+i),
            reference_equal=True,event_ids='',decision='continuous_reference',reason='',suspend_type='',suspend_timing=''))
    suspension=pd.DataFrame(columns=['trade_date','ts_code','suspend_type','suspend_timing'])
    if missing_second:
        bars=bars.loc[bars.trade_date.ne(dates[2])]
        rows[-1].update(has_quote=False,pre_close_text='',reference_equal=None,
            decision='stale_mark_registered_suspension' if suspended else 'stop',
            reason='' if suspended else 'missing_quote_without_daily_suspension',
            suspend_type='S' if suspended else '',suspend_timing='全天' if suspended else '')
        if suspended:suspension=pd.DataFrame([dict(trade_date=dates[2],ts_code='A',suspend_type='S',suspend_timing='全天')])
    registry=pd.DataFrame(columns=['event_id','code','record','ex','cash_pay','stock_pay','list_date'])
    universe=pd.DataFrame([dict(ts_code='A',list_date='20170101',delist_date='')])
    return bars,dates[1:],dates,universe,registry,[],suspension,pd.DataFrame(rows)


def test_independent_guard_replays_exact_previous_session_and_daily_rows():
    args=guard_fixture()
    result,_,errors=independent_guard(*args)
    assert not errors and result['rows']==2
    corrupted=list(args);corrupted[-1]=args[-1].copy();corrupted[-1].loc[0,'prior_close_text']='10.0'
    # Equal economic decimal does not license replacing a stored original lexeme.
    with pytest.raises(AssertionError):independent_guard(*corrupted)


@pytest.mark.parametrize('suspended',[False,True])
def test_guard_missing_quote_requires_actual_same_day_s_record(suspended):
    result,_,errors=independent_guard(*guard_fixture(missing_second=True,suspended=suspended))
    assert result['rows']==2
    assert [row['reason'] for row in errors]==([] if suspended else ['missing_quote_without_daily_suspension'])


def test_guard_does_not_seed_from_any_old_surviving_quote():
    args=list(guard_fixture())
    args[0]=args[0].loc[args[0].trade_date.ne(args[2][0])]
    # Expected table still claiming a certified seed is refused immediately.
    with pytest.raises(AssertionError):independent_guard(*args)


def test_normalized_event_identity_binds_source_and_equity_dates():
    action=Action('A',pd.Timestamp('2018-01-02'),pd.Timestamp('2018-01-03'),pd.Timestamp('2018-01-04'),pd.NaT,.1)
    hashes=dict(dividend='a'*64,rights='b'*64)
    registry,errors=independent_registry([action],[],hashes)
    assert not errors and registry.iloc[0].cash_per_share==.1 and registry.iloc[0].cash_pay==pd.Timestamp('2018-01-04')
    changed,_=independent_registry([action],[],dict(hashes,dividend='c'*64))
    assert registry.iloc[0].event_id!=changed.iloc[0].event_id
    _,errors=independent_registry([action,action],[],hashes)
    assert errors[0]['reason']=='duplicate_normalized_event'


def test_incomplete_or_failed_six_account_set_cannot_get_full_success():
    statuses=[dict(strategy=f'{path}_{cost}bp',status='completed') for path in PATHS for cost in (0,10,30)]
    summary=dict(experiment_statuses=statuses,experiments=[dict(strategy=row['strategy']) for row in statuses])
    assert_six_completed(summary,statuses)
    statuses[0]['status']='failed'
    with pytest.raises(AssertionError):assert_six_completed(summary,statuses)
    with pytest.raises(AssertionError):assert_six_completed(summary,statuses[:3])


def test_audit_json_never_overwrites_existing_evidence(tmp_path):
    path=tmp_path/'audit.json';write_json_exclusive(path,dict(status='passed'))
    with pytest.raises(FileExistsError):write_json_exclusive(path,dict(status='failed'))
    assert path.read_text(encoding='utf-8').find('passed')>=0
