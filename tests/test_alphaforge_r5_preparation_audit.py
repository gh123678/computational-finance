from copy import deepcopy
import json

import pandas as pd
import pytest

import alphaforge_r5_events as producer
from alphaforge_r5_preparation_audit import audit_preparation_bridges


def fixture():
    dates=pd.bdate_range('2020-01-01',periods=27)
    bars=pd.DataFrame(dict(ts_code=['A']*len(dates),trade_date=dates,
        close_text=['10']*len(dates),pre_close_text=['10']*len(dates)))
    forms=pd.DataFrame(dict(ts_code=['A'],trade_date=[dates[20]]))
    labels=pd.DataFrame(dict(ts_code=['A'],signal_date=[dates[20]],
        execution_date=[dates[21]],R_end=[dates[26]],R_valid=[True]))
    events=pd.DataFrame(columns=['code','event_id','event_date','known_date','timing_verified','kind','conflict'])
    return [bars,dates,forms,labels,events,dict(event_versions=[],rights_stages=[])]


def produce(inputs):
    return producer.audit_internal_reference_bridges(*inputs)


def verify(inputs,result):
    return audit_preparation_bridges(*inputs,result['summary'],result['coverage'],result['failures'],result['trace'])


def event(inputs,code='A',ex_index=10,known_index=9,role='cancelled',version=2):
    dates=inputs[1]
    return dict(code=code,ex=str(dates[ex_index].date()),known_date=str(dates[known_index].date()),
        event_id='old',version=version,role=role,reference_explained=role=='planned_distribution',
        unsupported_special=role=='special_reorganization',
        sources=[dict(known_date=str(dates[known_index].date()),sha256='test',path='bound.pdf')])


def test_all_internal_edges_reconstructed_without_any_r5_decision_helpers(monkeypatch):
    inputs=fixture();result=produce(inputs)
    for name in ('audit_internal_reference_bridges','select_event_version','distribution_view','rights_stage'):
        monkeypatch.setattr(producer,name,lambda *a,**k:pytest.fail('Shared producer helper invoked'))
    audit=verify(inputs,result)
    assert audit['conditional_account_attempt_allowed']
    assert audit['formation_bridges']==20 and audit['label_bridges']==5
    assert audit['coverage_keys']==2


@pytest.mark.parametrize('field,value',[('formation_bridges',19),('passed',False),('failure_count',1),('values_recomputed',True)])
def test_forged_summary_is_rejected(field,value):
    inputs=fixture();result=produce(inputs);result['summary'][field]=value
    with pytest.raises(AssertionError,match='summary'):verify(inputs,result)


def test_omitted_fixed_key_or_inner_bridge_is_rejected():
    inputs=fixture();result=produce(inputs)
    result['coverage'].loc[0,'internal_bridges']=19
    with pytest.raises(AssertionError,match='coverage'):verify(inputs,result)
    result=produce(inputs);result['coverage']=result['coverage'].iloc[1:]
    with pytest.raises(AssertionError,match='coverage'):verify(inputs,result)


def test_inner_price_break_is_a_data_stop_without_key_removal():
    inputs=fixture();inputs[0].loc[7,'pre_close_text']='9.9'
    result=produce(inputs);audit=verify(inputs,result)
    assert audit['status']=='source_gate_failed' and audit['source_failure_count']==1
    assert audit['coverage_keys']==2 and not audit['conditional_account_attempt_allowed']
    result['failures']=result['failures'].iloc[0:0]
    with pytest.raises(AssertionError,match='failures'):verify(inputs,result)


def test_cancellation_removes_only_distribution_explanation_and_never_deletes_key():
    inputs=fixture();v=event(inputs);inputs[5]['event_versions']=[v]
    inputs[4]=pd.DataFrame([dict(code='A',event_id='old',event_date=v['ex'],
        known_date=str(inputs[1][1].date()),timing_verified=True,kind='cash',conflict=False)])
    inputs[0].loc[10,'pre_close_text']='9.9'
    result=produce(inputs);audit=verify(inputs,result)
    assert not audit['source_bridge_passed'] and len(result['failures'])==1
    assert json.loads(result['trace'].effective_known_event_ids.iloc[0])==[]


def test_future_cancellation_does_not_replace_known_plan():
    inputs=fixture();plan=event(inputs,role='planned_distribution',version=1)
    cancel=event(inputs,known_index=25)
    inputs[5]['event_versions']=[plan,cancel];inputs[0].loc[10,'pre_close_text']='9.9'
    audit=verify(inputs,produce(inputs))
    assert audit['source_bridge_passed']


def test_special_event_stops_even_with_equal_quotes():
    inputs=fixture();inputs[5]['event_versions']=[event(inputs,role='special_reorganization',version=1)]
    result=produce(inputs);audit=verify(inputs,result)
    assert audit['source_failure_count']==1
    assert result['failures'].reason.iloc[0]=='unsupported_special_reorganization_reference_bridge'


def test_formation_close_includes_same_day_publication_but_label_cannot_borrow_signal_cutoff():
    inputs=fixture();dates=inputs[1]
    # Later-published explanation is available by the formation signal close.
    inputs[0].loc[10,'pre_close_text']='9.9'
    inputs[4]=pd.DataFrame([dict(code='A',event_id='cash',event_date=str(dates[10].date()),
        known_date=str(dates[20].date()),timing_verified=True,kind='cash',conflict=False)])
    assert verify(inputs,produce(inputs))['source_bridge_passed']
    # A label edge cannot use a result published after that edge's rear day.
    inputs=fixture();inputs[0].loc[23,'pre_close_text']='9.9'
    inputs[4]=pd.DataFrame([dict(code='A',event_id='cash',event_date=str(dates[23].date()),
        known_date=str(dates[24].date()),timing_verified=True,kind='cash',conflict=False)])
    result=produce(inputs)
    assert verify(inputs,result)['source_failure_count']==1
    assert result['failures'].cutoff.iloc[0]==dates[23]


def test_original_invalid_label_retained_as_diagnostic_not_new_source_failure():
    inputs=fixture();inputs[3].loc[0,'R_valid']=False
    inputs[0].loc[23,'pre_close_text']='9.9'
    result=produce(inputs);audit=verify(inputs,result)
    assert audit['source_bridge_passed'] and audit['original_invalid_label_keys']==1
    assert audit['diagnostic_invalid_label_bridges']==1 and audit['coverage_keys']==2
    inputs[3].loc[0,'R_end']=pd.NaT
    audit=verify(inputs,produce(inputs))
    assert audit['label_bridges']==0 and audit['coverage_keys']==2


@pytest.mark.parametrize('field,value',[('cutoff','2020-12-31'),('source_versions','[]'),('previous_close_text','11')])
def test_trace_timing_source_or_quote_tampering_rejected(field,value):
    inputs=fixture();inputs[5]['event_versions']=[event(inputs)]
    result=produce(inputs);result['trace'][field]=value
    with pytest.raises(AssertionError,match='trace'):verify(inputs,result)


def test_source_with_future_attached_document_rejected():
    inputs=fixture();v=event(inputs);v['sources'][0]['known_date']='2099-01-01'
    inputs[5]['event_versions']=[v]
    result=produce(inputs)
    with pytest.raises(AssertionError,match='Future source'):verify(inputs,result)


@pytest.mark.parametrize('known_index,passed',[(9,True),(20,True),(21,False)])
def test_rights_market_reference_requires_result_known_by_formation_cutoff(known_index,passed):
    inputs=fixture();code='000977.SZ'
    inputs[0]['ts_code']=code;inputs[2]['ts_code']=code;inputs[3]['ts_code']=code
    dates=inputs[1];ex=str(dates[10].date());known=str(dates[known_index].date())
    inputs[0].loc[10,'pre_close_text']='9.9'
    inputs[4]=pd.DataFrame([dict(code=code,event_id='old_rights',event_date=ex,
        known_date=None,timing_verified=False,kind='rights',conflict=False)])
    inputs[5]['rights_stages']=[dict(code=code,ex=ex,event_id='new_rights',
        result_known_date=known,sources=[dict(role='actual_result',known_date=known,path='result.pdf',sha256='test')])]
    result=produce(inputs);audit=verify(inputs,result)
    assert audit['source_bridge_passed']==passed


def test_duplicate_formation_key_rejected_and_outside_calendar_preserves_coverage():
    inputs=fixture();inputs[2]=pd.concat([inputs[2],inputs[2]],ignore_index=True)
    with pytest.raises(ValueError,match='duplicated'):produce(inputs)
    inputs=fixture();inputs[2].loc[0,'trade_date']=inputs[1][5]
    result=produce(inputs);audit=verify(inputs,result)
    assert not audit['source_bridge_passed'] and audit['coverage_keys']==2


def test_real_csv_round_trip_preserves_missing_quote_diagnostics(tmp_path):
    inputs=fixture();inputs[0].loc[10,'pre_close_text']=''
    result=produce(inputs)
    for name in ('coverage','failures','trace'):
        result[name].to_csv(tmp_path/f'{name}.csv',index=False)
        result[name]=pd.read_csv(tmp_path/f'{name}.csv',dtype=str)
    assert verify(inputs,result)['source_failure_count']==1
