import json

import pytest

import report_alphaforge_r5 as report


def save(path,value):
    path.write_text(json.dumps(value),encoding='utf-8')


def fixture(tmp_path):
    save(tmp_path/'preparation_sha256.json',{})
    save(tmp_path/'source_bridge_summary.json',{'passed':False,'failure_count':1})
    bridge=dict(independent_source_bridge_reconstruction=True,source_failure_count=1,
        source_bridge_passed=False,source_failures_exact=True,coverage_exact=True,
        formation_bridges=20,label_bridges=5,coverage_keys=2,original_invalid_label_keys=0)
    prep=dict(status='source_gate_failed',market_inventory_complete=False,live_enablement=False,
        verifier_sha256=report.run.sha(report.run.ROOT/'scripts/verify_alphaforge_r5.py'),
        conditional_account_attempt_allowed=False,source_bridge_audit=bridge,
        preparation_manifest_sha256=report.run.sha(tmp_path/'preparation_sha256.json'),
        source_bridge_summary_sha256=report.run.sha(tmp_path/'source_bridge_summary.json'))
    save(tmp_path/'preparation_audit.json',prep)
    (tmp_path/'source_bridge_failures.csv').write_text('kind,ts_code,formation_date,bridge_left,bridge_right,reason\nformation,A,2020-02-01,2020-01-01,2020-01-02,unknown_reference\n',encoding='utf-8')
    return prep


def test_verified_preparation_failure_is_zero_accounts_without_full_return_claim(tmp_path):
    fixture(tmp_path);result=report.collect(tmp_path)
    assert result['accounts_started']==0 and not result['full'] and result['gates'] is None
    assert len(result['statuses'])==6 and all(s['status']=='not_started' for s in result['statuses'])
    text=report.render(tmp_path,result,[dict(count=3539)])
    assert '0账户结案' in text and '没有实际账户净值' in text and '实盘不启用' in text
    assert '净收益|' not in text and '条件研究情景' in text


@pytest.mark.parametrize('name',['experiment_protocol.json','status.json','verification.json',
    'partial_verification.json','accounts_sha256.json','summary.json','annual_returns.csv'])
def test_source_failure_cannot_hide_existing_account_artifacts(tmp_path,name):
    fixture(tmp_path);(tmp_path/name).write_text('{}',encoding='utf-8')
    with pytest.raises(AssertionError):report.collect(tmp_path)


def test_zero_account_stop_requires_independent_positive_failure_count(tmp_path):
    prep=fixture(tmp_path);prep['source_bridge_audit']['source_failure_count']=0
    save(tmp_path/'preparation_audit.json',prep)
    with pytest.raises(AssertionError):report.collect(tmp_path)


def attempt(tmp_path,monkeypatch,full=False):
    prep=fixture(tmp_path);prep['status']='passed';prep['conditional_account_attempt_allowed']=True
    prep['source_bridge_audit'].update(source_bridge_passed=True,source_failure_count=0)
    save(tmp_path/'source_bridge_summary.json',{'passed':True,'failure_count':0})
    prep['source_bridge_summary_sha256']=report.run.sha(tmp_path/'source_bridge_summary.json')
    save(tmp_path/'preparation_audit.json',prep)
    monkeypatch.setattr(report.run,'verify_stage',lambda _:None)
    statuses=[dict(strategy=f'{p}_{b}bp',path=p,slippage_bps=b,status='completed' if full else 'not_started')
              for p,b in report.run.ORDER]
    if not full:statuses[0]['status']='failed'
    save(tmp_path/'status.json',statuses);save(tmp_path/'summary.json',dict(experiments=[{}]*6 if full else []))
    save(tmp_path/'accounts_sha256.json',{})
    audit=dict(market_inventory_complete=False,live_enablement=False,
        accounts_manifest_sha256=report.run.sha(tmp_path/'accounts_sha256.json'),
        status_sha256=report.run.sha(tmp_path/'status.json'),summary_sha256=report.run.sha(tmp_path/'summary.json'),
        accounts_started=6 if full else 1,completed_accounts_verified=6 if full else 0,
        full_six_account_verification_passed=full,year_boundaries=12 if full else 0,
        research_gates_assessable=full,gates={str(i):True for i in range(6)} if full else None)
    save(tmp_path/('verification.json' if full else 'partial_verification.json'),audit)
    return statuses,audit


def test_partial_failure_does_not_become_full_success(tmp_path,monkeypatch):
    attempt(tmp_path,monkeypatch);result=report.collect(tmp_path)
    assert not result['full'] and result['accounts_started']==1 and result['completed_accounts']==0
    text=report.render(tmp_path,result,[])
    assert '不构成完整六账户通过' in text and '未评估' in text


@pytest.mark.parametrize('mutation',['boundary','completed','gates'])
def test_full_success_requires_all_six_and_twelve_boundaries(tmp_path,monkeypatch,mutation):
    statuses,audit=attempt(tmp_path,monkeypatch,full=True)
    if mutation=='boundary':audit['year_boundaries']=11
    elif mutation=='completed':audit['completed_accounts_verified']=5
    else:audit['gates']=None
    save(tmp_path/'verification.json',audit)
    with pytest.raises(AssertionError):report.collect(tmp_path)


def test_existing_seal_is_rejected_before_lock_or_other_mutation(tmp_path,monkeypatch):
    monkeypatch.setattr(report.run,'OUT',tmp_path)
    (tmp_path/'output_sha256.json').write_text('{}',encoding='utf-8')
    with pytest.raises(RuntimeError,match='Existing final seal'):report.main()
    assert sorted(p.name for p in tmp_path.iterdir())==['output_sha256.json']
