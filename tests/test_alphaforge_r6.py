from copy import deepcopy
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

import alphaforge_r6_risk as risk
from alphaforge_r6_bridges import audit_risk_bridges
from alphaforge_r6_bridge_audit import audit_risk_bridge_reconstruction
from verify_alphaforge_r6 import reconstruct_risk
import run_alphaforge_r6 as run
from report_alphaforge_r6 import terminal


def fixture():
    dates=pd.bdate_range('2020-01-01',periods=70)
    frames=[]
    for code in ('B','A'):
        close=10.
        rows=[]
        for index,date in enumerate(dates):
            previous=close
            close=round(previous*(1+(.015 if code=='A' else .025)*np.sin(index+1)),5)
            rows.append(dict(ts_code=code,trade_date=date,open=close,high=close,low=close,
                close=close,pre_close=previous,vol=100.,amount=1000.,close_text=str(close),pre_close_text=str(previous)))
        frames.append(pd.DataFrame(rows))
    bars=pd.concat(frames,ignore_index=True)
    signal=dates[60]
    targets={'path':pd.DataFrame(dict(ts_code=['B','A'],trade_date=[signal]*2,signal_date=[signal]*2,
               execution_date=[dates[61]]*2,industry=['X','Y'],score=[.9,1.],target_weight=[.049,.049]))}
    schedule=pd.DataFrame(dict(signal_date=[signal],execution_date=[dates[61]]))
    events=pd.DataFrame(columns=['code','event_id','event_date','known_date','timing_verified','kind','conflict'])
    evidence=dict(event_versions=[],rights_stages=[])
    return bars,dates,targets,schedule,events,evidence


def bridge_result(inputs):
    bars,dates,targets,schedule,events,evidence=inputs
    keys=risk.target_keys(targets)
    args=(bars,dates,keys,risk.EMPTY_LABELS,events,evidence)
    result=audit_risk_bridges(*args)
    return args,result


def verify_bridge(args,result):
    return audit_risk_bridge_reconstruction(*args,result['summary'],result['coverage'],result['failures'],result['trace'])


def prepare(inputs,out):
    bars,dates,targets,schedule,_,_=inputs
    _,bridge=bridge_result(inputs)
    windows,returns,failures=risk.risk_inputs(bars,dates,risk.target_keys(targets))
    failures.to_csv(out/'quote_failures.csv',index=False)
    periods,outputs=risk.prepare_targets(targets,schedule,windows,returns,bridge['failures'],out)
    return periods,outputs,bridge


def test_61_points_60_bridges_and_60_returns_independently_reconstructed(tmp_path,monkeypatch):
    inputs=fixture()
    args,bridge=bridge_result(inputs)
    audit=verify_bridge(args,bridge)
    assert audit['formation_bridges']==120 and audit['coverage_keys']==2
    periods,outputs,bridge=prepare(inputs,tmp_path)
    bars,dates,targets,schedule,_,_=inputs
    monkeypatch.setattr(risk,'estimate',lambda *a:pytest.fail('Producer estimator used by auditor'))
    monkeypatch.setattr(risk,'risk_inputs',lambda *a:pytest.fail('Producer window used by auditor'))
    result=reconstruct_risk(bars,dates,schedule,targets,bridge['failures'],tmp_path)
    assert result['risk_inputs_passed'] and result['covariances_reconstructed']==1
    path=tmp_path/'risk_matrices/path_20200325_returns.csv'
    matrix=pd.read_csv(path,parse_dates=['date'])
    assert len(matrix)==60 and list(matrix.columns)==['date','A','B']
    assert matrix.date.iloc[0]==dates[1] and matrix.date.iloc[-1]==dates[60]
    assert list(outputs['path'].ts_code)==['A','B']


@pytest.mark.parametrize('field,value',[('close_text','NaN'),('pre_close_text','0'),('open',0),('vol',0),('amount',np.inf),('high',np.nan),('low',-1)])
def test_extra_40_days_invalid_input_stops_without_window_shortening(tmp_path,field,value):
    inputs=list(fixture())
    inputs[0].loc[(inputs[0].ts_code=='A') & (inputs[0].trade_date==inputs[1][5]),field]=value
    periods,outputs,bridge=prepare(inputs,tmp_path)
    assert periods.status.tolist()==['failed'] and outputs['path'].empty
    assert not list((tmp_path/'risk_matrices').glob('*_covariance.csv'))
    result=reconstruct_risk(inputs[0],inputs[1],inputs[3],inputs[2],bridge['failures'],tmp_path)
    assert not result['risk_inputs_passed']


def test_missing_old_quote_does_not_drop_stock_or_change_target_list(tmp_path):
    inputs=list(fixture())
    inputs[0]=inputs[0].loc[~((inputs[0].ts_code=='A') & (inputs[0].trade_date==inputs[1][7]))]
    periods,outputs,bridge=prepare(inputs,tmp_path)
    assert periods.status.tolist()==['failed']
    assert set(pd.read_csv(tmp_path/'risk_matrices/path_20200325_weights.csv').ts_code)=={'A','B'}
    assert len(bridge['failures'])==2
    reconstruct_risk(inputs[0],inputs[1],inputs[3],inputs[2],bridge['failures'],tmp_path)


def test_first_point_pre_close_is_outside_return_and_bridge_window(tmp_path):
    inputs=list(fixture())
    inputs[0].loc[inputs[0].trade_date==inputs[1][0],'pre_close_text']='unknown'
    periods,outputs,bridge=prepare(inputs,tmp_path)
    assert periods.status.tolist()==['passed'] and bridge['summary']['passed']
    reconstruct_risk(inputs[0],inputs[1],inputs[3],inputs[2],bridge['failures'],tmp_path)


def test_future_prices_sources_and_unused_labels_do_not_change_past_output(tmp_path):
    inputs=fixture()
    first=tmp_path/'first';first.mkdir()
    second=tmp_path/'second';second.mkdir()
    prepare(inputs,first)
    changed=deepcopy(inputs)
    changed[0].loc[changed[0].trade_date>changed[1][60],['close_text','pre_close_text']]='unknown-future'
    changed[5]['event_versions']=[dict(code='A',ex=str(changed[1][10].date()),known_date=str(changed[1][65].date()),
            event_id='future',version=99,role='special_reorganization',reference_explained=False,
            unsupported_special=True,sources=[dict(known_date=str(changed[1][65].date()))])]
    prepare(changed,second)
    assert {p.relative_to(first):p.read_bytes() for p in first.rglob('*') if p.is_file()} == {
        p.relative_to(second):p.read_bytes() for p in second.rglob('*') if p.is_file()}
    # No labels or future account equity enter either risk API.
    assert 'labels' not in risk.risk_inputs.__code__.co_varnames


def source_version(inputs,role,known_index,version=1):
    dates=inputs[1]
    return dict(code='A',ex=str(dates[10].date()),known_date=str(dates[known_index].date()),
                event_id='event',version=version,role=role,reference_explained=role=='planned_distribution',
                unsupported_special=role=='special_reorganization',
                sources=[dict(known_date=str(dates[known_index].date()),sha256='bound-source')])


@pytest.mark.parametrize('role,reason',[('cancelled','unexplained_reference_change'),
                                      ('special_reorganization','unsupported_special_reorganization_reference_bridge'),
                                      ('planned_distribution','')])
def test_formation_cutoff_applies_to_all_60_bridges(role,reason):
    inputs=list(fixture())
    # Public after the bridge but before the original formation: admissible as of formation.
    inputs[5]['event_versions']=[source_version(inputs,role,50)]
    inputs[0].loc[(inputs[0].ts_code=='A') & (inputs[0].trade_date==inputs[1][10]),'pre_close_text']='9.99'
    args,result=bridge_result(inputs)
    audit=verify_bridge(args,result)
    assert audit['source_failure_count']==int(bool(reason))
    if reason:
        assert result['failures'].reason.tolist()==[reason]


def test_unknown_tax_source_with_continuous_reference_does_not_add_stop():
    inputs=list(fixture())
    v=source_version(inputs,'ordinary_unknown_tax_source',50)
    v['reference_explained']=False
    inputs[5]['event_versions']=[v]
    args,result=bridge_result(inputs)
    assert verify_bridge(args,result)['source_bridge_passed']


def test_decimal_strings_are_compared_without_float_tolerance():
    inputs=list(fixture())
    index=inputs[0].index[(inputs[0].ts_code=='A') & (inputs[0].trade_date==inputs[1][8])][0]
    inputs[0].loc[index,'pre_close_text'] += '00000000000000000000000001'
    args,result=bridge_result(inputs)
    assert verify_bridge(args,result)['source_failure_count']==1


def test_forged_missing_bridge_or_covariance_is_rejected(tmp_path):
    inputs=fixture()
    args,result=bridge_result(inputs)
    result['coverage'].loc[0,'internal_bridges']=20
    with pytest.raises(AssertionError,match='coverage'):
        verify_bridge(args,result)
    _,_,bridge=prepare(inputs,tmp_path)
    path=tmp_path/'risk_matrices/path_20200325_covariance.csv'
    frame=pd.read_csv(path);frame.iloc[0,1]*=2;frame.to_csv(path,index=False)
    with pytest.raises(AssertionError):
        reconstruct_risk(inputs[0],inputs[1],inputs[3],inputs[2],bridge['failures'],tmp_path)


def test_original_nav_weights_are_not_normalized_and_scale_only_reduces():
    generator=np.random.default_rng(4)
    values=generator.normal(0,.08,size=(60,2))
    w=np.array([.049,.049])
    scale,sigma,_=risk.estimate(values,w)
    scale_full,sigma_full,_=risk.estimate(values,w/w.sum())
    assert np.isclose(sigma_full,sigma/w.sum())
    assert 0<scale<=1 and scale_full<scale
    scale,_,_=risk.estimate(values*.01,w)
    assert scale==1
    with pytest.raises(ValueError,match='variance'):
        risk.estimate(np.zeros((60,2)),w)


def test_empty_targets_are_cash_intent_without_fitting(tmp_path,monkeypatch):
    bars,dates,targets,schedule,events,evidence=fixture()
    base=targets['path'].iloc[:0]
    monkeypatch.setattr(risk,'estimate',lambda *a:pytest.fail('Empty covariance fit'))
    rows,outputs=risk.prepare_targets({'path':base},schedule,{}, {},pd.DataFrame(),tmp_path)
    assert rows.status.tolist()==['no_positive_targets'] and outputs['path'].empty


def test_constant_quotes_fail_preparation_without_default_scale(tmp_path):
    inputs=list(fixture())
    for name in ('open','high','low','close','pre_close'):
        inputs[0][name]=10.
    inputs[0]['close_text']='10'
    inputs[0]['pre_close_text']='10'
    periods,outputs,bridge=prepare(inputs,tmp_path)
    assert periods.status.tolist()==['failed'] and periods.scale.isna().all()
    assert outputs['path'].empty
    result=reconstruct_risk(inputs[0],inputs[1],inputs[3],inputs[2],bridge['failures'],tmp_path)
    assert not result['risk_inputs_passed']


def test_known_conflict_stops_even_when_quotes_are_continuous():
    inputs=list(fixture())
    date=inputs[1][8]
    inputs[4]=pd.DataFrame([dict(code='A',event_id='conflict',event_date=str(date.date()),
        known_date=str(date.date()),timing_verified=True,kind='cash',conflict=True)])
    args,result=bridge_result(inputs)
    assert verify_bridge(args,result)['source_failure_count']==1
    assert result['failures'].reason.tolist()==['known_action_conflict']


def test_stage_artifact_mutation_is_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(run,'OUT',tmp_path)
    stage=tmp_path/'risk_periods.csv';stage.write_text('original')
    run.save(tmp_path/'preparation_sha256.json',{'risk_periods.csv':run.sha(stage)})
    run.verify_stage('preparation_sha256.json')
    stage.write_text('changed')
    with pytest.raises(RuntimeError,match='Stage artifact'):
        run.verify_stage('preparation_sha256.json')


def test_stage_input_and_duplicate_lock_protection(tmp_path,monkeypatch):
    monkeypatch.setattr(run,'OUT',tmp_path)
    p=tmp_path/'input';p.write_text('original')
    protocol=dict(inputs={str(p):run.sha(p)},protected_manifests=[],source_snapshot={})
    run.verify_inputs(protocol)
    p.write_text('changed')
    with pytest.raises(RuntimeError,match='Frozen input'):
        run.verify_inputs(protocol)
    with run.r5.exclusive_stage(tmp_path,'first'):
        with pytest.raises(FileExistsError):
            with run.r5.exclusive_stage(tmp_path,'second'):
                pytest.fail('Duplicate lock acquired')
    assert not (tmp_path/'runner.lock').exists()


def test_preparation_failure_cannot_start_account_or_claim_six_results(tmp_path,monkeypatch):
    monkeypatch.setattr(run,'OUT',tmp_path)
    monkeypatch.setattr(run,'verify_inputs',lambda *a:None)
    monkeypatch.setattr(run,'verify_stage',lambda *a:None)
    run.save(tmp_path/'frozen_protocol.json',{})
    run.save(tmp_path/'preparation_audit.json',dict(status='risk_input_gate_failed',
             conditional_account_attempt_allowed=False,market_inventory_complete=False,
             live_enablement=False,independent_reconstruction_passed=True))
    with pytest.raises(RuntimeError,match='permission'):
        run.accounts()
    assert not (tmp_path/'experiment_protocol.json').exists()
    assert terminal(tmp_path)['accounts_started']==0
    run.save(tmp_path/'verification.json',dict(full_six_account_verification_passed=True))
    with pytest.raises(AssertionError):
        terminal(tmp_path)


def test_windows_do_not_consume_duplicate_or_negative_target_keys():
    bars,dates,targets,schedule,_,_=fixture()
    targets['path']=pd.concat([targets['path'],targets['path'].iloc[:1]],ignore_index=True)
    with pytest.raises(ValueError,match='Duplicate target'):
        risk.target_keys(targets)


def test_relocation_is_explicit_prefix_only():
    assert run.relocated(run.OLD_ROOT/'data/a.csv')==run.ROOT/'data/a.csv'
    assert run.relocated('D:/QuantResearchEvidence/original.pdf')==Path('D:/QuantResearchEvidence/original.pdf')
