import json
from pathlib import Path

import pandas as pd
import pytest

import run_alphaforge_r5 as r
from alphaforge_r5_account import simulate_exposure


def test_exclusive_lock_refuses_duplicate_without_deleting_first(tmp_path):
    with r.exclusive_stage(tmp_path,'first'):
        before=(tmp_path/'runner.lock').read_bytes()
        with pytest.raises(FileExistsError):
            with r.exclusive_stage(tmp_path,'duplicate'):
                pytest.fail('Duplicate acquired exclusive lock')
        assert (tmp_path/'runner.lock').read_bytes()==before
    assert not (tmp_path/'runner.lock').exists()


@pytest.mark.parametrize('which',['input','external','reused'])
def test_fingerprint_rejects_each_mutated_source_class(tmp_path,monkeypatch,which):
    monkeypatch.setattr(r,'ROOT',tmp_path);monkeypatch.setattr(r,'R3',tmp_path)
    p=tmp_path/'input';p.write_text('before',encoding='utf-8');digest=r.sha(p)
    protocol=dict(inputs={},external_inputs={},reused_r3={},prior_artifact_manifests=[])
    protocol[{'input':'inputs','external':'external_inputs','reused':'reused_r3'}[which]][str(p) if which=='external' else p.name]=digest
    r.verify_inputs(protocol)
    p.write_text('after',encoding='utf-8')
    with pytest.raises(RuntimeError,match='changed'):r.verify_inputs(protocol)


def test_existing_protocol_refuses_preparation_before_creating_or_hashing(tmp_path,monkeypatch):
    monkeypatch.setattr(r,'OUT',tmp_path)
    (tmp_path/'frozen_protocol.json').write_text('{}',encoding='utf-8')
    monkeypatch.setattr(r,'preservation',lambda:pytest.fail('Must reject duplicate first'))
    with pytest.raises(RuntimeError,match='do not restart'):r.freeze()


def test_first_account_data_failure_stops_whole_cohort_and_keeps_evidence(tmp_path,monkeypatch):
    import alphaforge_r5_account as account
    from test_alphaforge_r4_account import fixture
    monkeypatch.setattr(r,'OUT',tmp_path)
    monkeypatch.setattr(r,'DATA',tmp_path)
    monkeypatch.setattr(r,'ROOT',tmp_path)
    monkeypatch.setattr(r,'verify_inputs',lambda _:None)
    monkeypatch.setattr(r,'verify_stage',lambda _:None)
    monkeypatch.setattr(r,'check_disk',lambda:None)
    d,b,t,k=fixture();b.loc[2,'pre_close_text']='9.99'
    targets={p:t for p in r.PATHS}
    schedule=pd.DataFrame(dict(execution_date=[d[2]],signal_date=[d[1]]))
    monkeypatch.setattr(r,'load_account_inputs',lambda:(b,[],[],k['universe'],None,k['evidence'],d,d,schedule,targets,[]))
    directory=tmp_path/'data/audit';directory.mkdir(parents=True)
    pd.DataFrame(columns=['ts_code','in_date','out_date','l1_code']).to_csv(directory/'industry_history.csv',index=False)
    (tmp_path/'reused_r3').mkdir()
    for p in r.PATHS:t.to_csv(tmp_path/'reused_r3'/f'targets_{p}.csv',index=False)
    r.persist(tmp_path/'frozen_protocol.json',dict(order=[dict(path=p,bps=b,label=f'{p}_{b}bp') for p,b in r.ORDER]))
    r.persist(tmp_path/'preparation_audit.json',dict(conditional_account_attempt_allowed=True,market_inventory_complete=False))
    calls=[]
    def wrapped(*args,**kwargs):
        calls.append(kwargs['config'].slippage_bps)
        return simulate_exposure(*args,**kwargs)
    monkeypatch.setattr(account,'simulate_exposure',wrapped)
    r.accounts()
    statuses=r.read_json(tmp_path/'status.json')
    assert calls==[0]
    assert statuses[0]['status']=='failed' and all(s['status']=='not_started' for s in statuses[1:])
    first=tmp_path/statuses[0]['strategy']
    assert (first/'failure.txt').exists() and (first/'failure.json').exists()
    assert r.read_json(first/'failure.json')['type']=='data_or_economic_failure'
    assert len(pd.read_csv(first/'nav.csv'))==2
    assert all(not (tmp_path/s['strategy']).exists() for s in statuses[1:])


def test_source_gate_failure_never_creates_an_account_protocol(tmp_path,monkeypatch):
    monkeypatch.setattr(r,'OUT',tmp_path)
    monkeypatch.setattr(r,'verify_inputs',lambda _:None)
    monkeypatch.setattr(r,'verify_stage',lambda _:None)
    r.persist(tmp_path/'frozen_protocol.json',{})
    r.persist(tmp_path/'preparation_audit.json',dict(conditional_account_attempt_allowed=False,market_inventory_complete=False))
    monkeypatch.setattr(r,'load_account_inputs',lambda:pytest.fail('Source failure reached account data loader'))
    with pytest.raises(RuntimeError,match='gate absent'):r.accounts()
    assert not (tmp_path/'experiment_protocol.json').exists()
    assert not (tmp_path/'status.json').exists()


@pytest.mark.parametrize('which',['original_r4_inputs','original_r4_external_inputs'])
def test_inherited_frozen_r4_input_mutation_is_rejected(tmp_path,monkeypatch,which):
    monkeypatch.setattr(r,'ROOT',tmp_path)
    p=tmp_path/'old';p.write_text('original',encoding='utf-8')
    protocol=dict(inputs={},external_inputs={},reused_r3={},prior_artifact_manifests=[],
        **{which:{str(p) if which.endswith('external_inputs') else p.name:r.sha(p)}})
    r.verify_inputs(protocol);p.write_text('changed',encoding='utf-8')
    with pytest.raises(RuntimeError,match='Original r4'):r.verify_inputs(protocol)
