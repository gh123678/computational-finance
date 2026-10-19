"""Isolated receipt/report engineering repair. Original r5 is never edited/run."""
from pathlib import Path
import copy
import os
import shutil

import run_alphaforge_r5 as run
import report_alphaforge_r5 as original_report

PREPARATION_FILES={'event_mapping_validation.json','evidence_mapping.json','frozen_protocol.json',
    'preparation_status.json','source_bridge_coverage.csv','source_bridge_failures.csv',
    'source_bridge_summary.json','source_bridge_trace.csv','source_commit.txt'}
PINNED={
    'frozen_protocol.json':'6963dd9c88c9fd9553abb2c4615ef5be2c4b8c5488988737db7abbf044881c45',
    'preparation_sha256.json':'9255f1c0672008d01748c1fc5439cd00bcf7ec78a347482bdfac158f7f90bb1e',
    'preparation_audit.json':'6c9ba626e4c703954f94e812d467b9c2272fa714df0b43bf816e29b8823ee83f',
    'accounts_sha256.json':'b509d1c79acd699649fa5a22081b036ce7d0e267f39eaf0bbe7561528a1cc23c',
    'verification.json':'b8d88348e35ca1a86fdacf5c64f187f8c4e8e47a19a823ec0927968de645a16d'}
FAILED_REPORT_SHA='a3c840fc41bd9ef191e560125c24aca4f3212fab8e4238c17e9af3e66e83718d'


def reconstruct_receipt(out,protocol,reuse):
    """Closed membership, three separate anchors and all byte hashes required."""
    out=Path(out)
    preparation_manifest=run.read_json(out/'preparation_sha256.json')
    accounts_manifest=run.read_json(out/'accounts_sha256.json')
    expected=set(PREPARATION_FILES)|{'reused_r3/'+n for n in reuse}|{
        'source_before/'+Path(n).as_posix() for n in protocol['source_snapshot_files']}
    assert set(preparation_manifest)==expected,'Preparation member scope changed'
    assert accounts_manifest['preparation_audit.json']==run.sha(out/'preparation_audit.json'),'Original receipt changed'
    for name,member_digest in preparation_manifest.items():
        assert run.sha(out/name)==member_digest,'Preparation member bytes changed: '+name
        if name.startswith('source_before/'):
            relative=str(Path(name).relative_to('source_before'))
            assert member_digest==protocol['inputs'][relative],'Snapshot not bound to frozen input'
        elif name.startswith('reused_r3/'):
            relative=Path(name).relative_to('reused_r3').as_posix()
            assert member_digest==protocol['reused_r3'][relative],'Reuse not bound to frozen r3'
        else:
            assert member_digest==accounts_manifest[name],'Preparation member not anchored in audited cohort'
    original=run.read_json(out/'preparation_audit.json')
    preparation_digest=run.sha(out/'preparation_sha256.json')
    label_digest=protocol['reused_r3']['reference_labels.csv']
    stored=original['preparation_manifest_sha256']
    assert stored in (preparation_digest,label_digest),'Unknown receipt corruption; no repair permitted'
    corrected=copy.deepcopy(original)
    corrected['preparation_manifest_sha256']=preparation_digest
    proof=dict(status='passed',repair_scope='receipt field only; original receipt untouched',
        original_receipt_sha256=run.sha(out/'preparation_audit.json'),stored_digest=stored,
        corrected_preparation_manifest_sha256=preparation_digest,
        last_reused_label_sha256=label_digest,correction_required=stored!=preparation_digest,
        member_scope_exact=True,member_count=len(expected),all_member_bytes_rehashed=True,
        anchors=['frozen source inputs','frozen original r3 reuse','independently audited accounts manifest'],
        independent_reference_bridge_audit_rerun=False,accounts_rerun=False,
        source_or_data_edited=False,parameters_or_rules_changed=False)
    return corrected,proof


def collect_complete(out,corrected):
    audit=run.read_json(out/'verification.json');statuses=run.read_json(out/'status.json')
    summary=run.read_json(out/'summary.json');experiment=run.read_json(out/'experiment_protocol.json')
    assert audit['accounts_manifest_sha256']==run.sha(out/'accounts_sha256.json')
    assert audit['status_sha256']==run.sha(out/'status.json') and audit['summary_sha256']==run.sha(out/'summary.json')
    assert experiment['preparation_audit_sha256']==run.sha(out/'preparation_audit.json')
    assert experiment['runner_sha256']==run.sha(run.ROOT/'scripts/run_alphaforge_r5.py')
    assert [(s['path'],s['slippage_bps']) for s in statuses]==run.ORDER
    assert len(statuses)==6 and all(s['status']=='completed' and s['completed_sessions']==790 for s in statuses)
    assert audit['full_six_account_verification_passed'] and audit['engineering_verification_passed']
    assert audit['accounts_started']==audit['completed_accounts_verified']==6 and audit['year_boundaries']==12
    assert len(audit['accounts'])==6 and all(a['status']=='passed' for a in audit['accounts'])
    assert audit['research_gates_assessable'] and len(audit['gates'])==6
    assert audit['research_gates_passed']==all(audit['gates'].values()) and len(summary['experiments'])==6
    assert corrected['status']=='passed' and corrected['conditional_account_attempt_allowed']
    assert corrected['preparation_manifest_sha256']==run.sha(out/'preparation_sha256.json')
    bridge=corrected['source_bridge_audit'];source=run.read_json(out/'source_bridge_summary.json')
    assert bridge['independent_source_bridge_reconstruction'] and bridge['producer_summary_exact']
    assert bridge['source_failures_exact'] and bridge['source_trace_exact'] and bridge['coverage_exact']
    assert bridge['source_failure_count']==source['failure_count']==0 and source['passed']
    assert corrected['source_bridge_summary_sha256']==run.sha(out/'source_bridge_summary.json')
    assert corrected['verifier_sha256']==run.sha(run.ROOT/'scripts/verify_alphaforge_r5.py')
    assert audit['market_inventory_complete'] is False and audit['live_enablement'] is False
    return dict(kind='full_cohort',preparation=corrected,audit=audit,audit_file='verification.json',
        statuses=statuses,accounts_started=6,completed_accounts=6,year_boundaries=12,full=True,gates=audit['gates'])


def main():
    out=run.OUT;side=out/'report_e1';doc=run.ROOT/'docs/2026-10-19-alphaforge-r5-results.md'
    if (out/'output_sha256.json').exists() or side.exists() or doc.exists() or (out/'report.md').exists():
        raise RuntimeError('Existing seal or e1 delivery; never repeat')
    run.check_disk()
    with run.exclusive_stage(out,'report_receipt_e1'):
        for name,expected in PINNED.items():assert run.sha(out/name)==expected,'Cohort anchor changed: '+name
        protocol=run.read_json(out/'frozen_protocol.json');run.verify_inputs(protocol)
        run.verify_stage('preparation_sha256.json');run.verify_stage('accounts_sha256.json')
        corrected,proof=reconstruct_receipt(out,protocol,run.REUSE)
        assert proof['correction_required'],'This e1 only applies to the observed label-digest shadowing'
        result=collect_complete(out,corrected);preserved=run.preservation()
        side.mkdir();snapshot=side/'source_before';snapshot.mkdir()
        sources=[Path(__file__),run.ROOT/'tests/test_alphaforge_r5_receipt_e1.py',
            run.ROOT/'docs/2026-10-19-alphaforge-r5-receipt-incident.md']
        source_map={str(p.relative_to(run.ROOT)):run.sha(p) for p in sources}
        for p in sources:
            dest=snapshot/p.relative_to(run.ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        test_log=run.RUNTIME_LOGS/'engineering_receipt_e1.log'
        failure_log=run.RUNTIME_LOGS/'report.log';assert run.sha(failure_log)==FAILED_REPORT_SHA
        shutil.copy2(test_log,side/'engineering_receipt_e1.log');shutil.copy2(failure_log,side/'original_report_failure.log')
        run.persist(side/'frozen_protocol.json',dict(version='report-receipt-e1',source_commit=os.environ['REPORT_E1_SOURCE_COMMIT'],
            inputs=source_map,original_cohort_anchors=PINNED,test_log_sha256=run.sha(test_log),
            original_report_failure_sha256=FAILED_REPORT_SHA,scope=proof['repair_scope'],
            original_protocol_unchanged=True,original_receipt_unchanged=True,accounts_rerun=False),exclusive=True)
        run.persist(side/'preparation_receipt_e1.json',proof,exclusive=True)
        report=original_report.render(out,result,preserved)
        report+='\n## 报告凭证工程修订e1\n\n原结案程序因准备清单指纹与凭证字段不一致而拒绝封存，完整失败保留于`report_e1/original_report_failure.log`。'
        report+='原准备核验器复用了digest变量，误将最后一份复用标签的指纹存为准备清单指纹；原凭证与冻结源码保持不变。'
        report+='独立e1按完整成员范围重验全部准备字节，并分别绑定冻结源码、原r3复用及已独立审计的账户清单。'
        report+='校正证明为`report_e1/preparation_receipt_e1.json`，未重跑准备/账户或修改数值、数据和规则。此修订仅修复报告凭证，不改变六项收益关卡的失败结论。\n'
        report+='\n[收益、成本、分层图与新旧前缀评估](C:/Users/Admin/Documents/ChatGPT/计算金融/docs/2026-10-19-alphaforge-r5-evaluation.md)另存，图表已视觉核对。\n'
        for p in (out/'report.md',doc):
            with p.open('x',encoding='utf-8') as stream:stream.write(report)
        run.persist(out/'final_experiment_status.json',result['statuses'],exclusive=True)
        run.persist(out/'final_outcome.json',dict(kind='full_cohort_research_failed',accounts_started=6,completed_accounts=6,
            year_boundaries=12,research_gates_assessable=True,gates=result['gates'],research_gates_passed=False,
            reporting_revision='receipt-e1',original_preparation_receipt_stored_digest_valid=False,
            corrected_receipt_verified=True,accounts_rerun=False,market_inventory_complete=False,live_enablement=False),exclusive=True)
        logs=out/'logs';logs.mkdir()
        for p in run.RUNTIME_LOGS.glob('*.log'):
            if p.name not in ('report.log','report_e1.log'):shutil.copy2(p,logs/p.name)
        run.persist(out/'final_preservation_check.json',dict(status='passed',manifests=preserved),exclusive=True)
        run.verify_inputs(protocol)
        for name,expected in source_map.items():assert run.sha(run.ROOT/name)==expected
        run.persist(out/'output_sha256.json',{p.relative_to(out).as_posix():run.sha(p) for p in out.rglob('*')
            if p.is_file() and p.name!='runner.lock'},exclusive=True)
        print('r5 receipt-e1 report',str(doc),'final manifest',run.sha(out/'output_sha256.json'),flush=True)


if __name__=='__main__':main()
