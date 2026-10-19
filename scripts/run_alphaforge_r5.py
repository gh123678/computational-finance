"""Single approved r5 cohort. No broker, new selector, factor or label fitting."""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys
import traceback

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_alphaforge_r3 as previous
import run_alphaforge_r4 as r4
from run_retention_development import DATA, read_subset, sha
from quant_research.backtest import Config, summarize
from quant_research.corporate_corrections import correct_limit_code_aliases
from alphaforge_r5_evidence import (EVIDENCE_ROOT, EVIDENCE_MANIFEST_SHA256,
    build_evidence, validate_actions, overlay_rights, source_inputs)
from alphaforge_r5_events import audit_internal_reference_bridges

OUT = ROOT/'output/alphaforge_case_2018_2020_r5'
R3 = previous.OUT
R4 = r4.OUT
SPEC = ROOT/'docs/superpowers/specs/2026-10-19-alphaforge-source-mapping-r5-design.md'
PLAN = ROOT/'docs/superpowers/plans/2026-10-19-alphaforge-r5-implementation.md'
ENGINEERING = ROOT/'docs/2026-10-19-alphaforge-r5-engineering.md'
RUNTIME_LOGS = Path('D:/QuantResearchEvidence/alphaforge_r5_runtime_logs_20261019')
STORAGE_PROOF = Path('D:/QuantResearchEvidence/alphaforge_r5_storage_relocation_20261019_r1/output_sha256.json')
STORAGE_PROOF_SHA = '7bdcf6f1caf7d8864a965f05152b094cb0d9a90a60f5b4e1db40f091441447a9'
PATHS = previous.PATHS
ORDER = [(path, bps) for path in PATHS for bps in (0, 10, 30)]
R3_MANIFEST_SHA = '971485ebb416f74adb060576d82c921b57aa652386dcb11956824b3191a58fae'
SPEC_SHA = '8b490eb3b75f220c3ffc8da72a34a5651f1772e698ae6f1d093a53098a26c63f'
EXTRA_PROTECTED = [
    (R4/'output_sha256.json', 'd38dcbbee08b32d9c1f6cc1ed9ccd8ad758ee66e1bbe7862567b9fa915512350', 110),
    (Path('D:/QuantResearchEvidence/alphaforge_potential_exposure_action_sources_20261019_r1/output_sha256.json'), '99e7e34100c8e913d14dbf26f0bd0374a3883b5ac35998feb7c13813511d4847', 646),
    (Path('D:/QuantResearchEvidence/alphaforge_capitalization_origin_followup_20261019_r1/output_sha256.json'), '99b046a727fe701b99795de44c629f8419af5f20c350b581cbbc4b9c6d6a155d', 115),
    (Path('D:/QuantResearchEvidence/alphaforge_000426_distribution_201808_crosscheck_20261019_r1/output_sha256.json'), 'cff4677d32dec9ba5a415a0c16541182b7857a3768ae4cdb4f57d3b22a9fa218', 78),
    (Path('D:/QuantResearchEvidence/alphaforge_000426_independent_review_20261019_r1/output_sha256.json'), '5318e47856187ee069fbfb92434b644a7f32a95f9fa42f1c334e975cfadee653', 7),
    (Path('D:/QuantResearchEvidence/alphaforge_000977_quota_impact_20261019_r1/output_sha256.json'), '3a7974ca84842ba77416b070905d6aeb9ead80743ea115120c3e657dd5fa14bb', 14),
    (Path('D:/QuantResearchEvidence/alphaforge_cancelled_reorganization_impact_20261019_r1/output_sha256.json'), '1fb55aa8f42eac80ebeb501c04fd6c3187a1b1e4ee7106e773c5ec7eed2e3282', 12),
    (Path('D:/QuantResearchEvidence/alphaforge_600999_rights_stage_source_20261019_r1/output_sha256.json'), 'fb3f3efb6110561e17deac080cfd56bbe5f89113fc51fbf43921c57d3093a820', 35),
]
REUSE = ['raw_bars.csv','common_samples.csv','schedule.csv','events.csv','selection_events.csv',
         'factor_ic.csv','factor_groups.csv','factor_ic_summary.csv','primary_invariance.json',
         'preparation_audit.json','guard_audit.json','guard_summary.json','guard_daily.csv',
         'guard_failures.csv','guard_adjustment_alerts.csv','legacy_adjustment_alerts.csv','event_registry.csv',
         *[f'targets_{p}.csv' for p in PATHS], 'reference_windows.csv', 'reference_labels.csv']


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def persist(path, value, *, exclusive=False):
    path = Path(path)
    def clean(v):
        if isinstance(v,dict):return {k:clean(x) for k,x in v.items()}
        if isinstance(v,(tuple,list)):return [clean(x) for x in v]
        if isinstance(v,float) and not math.isfinite(v):return None
        return v
    with path.open('x' if exclusive else 'w', encoding='utf-8') as stream:
        json.dump(clean(value), stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)


@contextmanager
def exclusive_stage(out, stage):
    lock = Path(out)/'runner.lock'
    persist(lock, dict(pid=os.getpid(), stage=stage), exclusive=True)
    try:
        yield
    finally:
        lock.unlink()


def check_disk(out=OUT):
    for path in (ROOT, Path(out).resolve()):
        if shutil.disk_usage(path).free < 6*1024**3:
            raise RuntimeError('6GiB disk floor: '+str(path))


def check_manifest(path, expected=None, count=None):
    path = Path(path)
    if expected is not None and sha(path) != expected:
        raise RuntimeError('Protected manifest changed: '+str(path))
    contents = read_json(path)
    if count is not None and len(contents) != count:
        raise RuntimeError('Protected manifest scope changed: '+str(path))
    for name, digest in contents.items():
        if sha(path.parent/name) != digest:
            raise RuntimeError('Protected artifact changed: '+str(path.parent/name))
    return dict(path=str(path), sha256=sha(path), count=len(contents))


def preservation():
    return [*r4.preservation(), *[check_manifest(*row) for row in EXTRA_PROTECTED]]


def verify_inputs(protocol):
    for filename, digest in protocol['inputs'].items():
        if sha(ROOT/filename) != digest:
            raise RuntimeError('Frozen input changed: '+filename)
    for filename, digest in protocol['external_inputs'].items():
        if sha(Path(filename)) != digest:
            raise RuntimeError('External input changed: '+filename)
    for row in protocol['prior_artifact_manifests']:
        if sha(Path(row['path'])) != row['sha256']:
            raise RuntimeError('Protected manifest changed')
    for filename, digest in protocol['reused_r3'].items():
        if sha(R3/filename) != digest:
            raise RuntimeError('Audited r3 input changed: '+filename)
    for filename, digest in protocol.get('original_r4_inputs', {}).items():
        if sha(ROOT/filename) != digest:
            raise RuntimeError('Original r4 input changed: '+filename)
    for filename, digest in protocol.get('original_r4_external_inputs', {}).items():
        if sha(Path(filename)) != digest:
            raise RuntimeError('Original r4 external input changed: '+filename)


def verify_stage(name):
    for filename, digest in read_json(OUT/name).items():
        if sha(OUT/filename) != digest:
            raise RuntimeError('Stage artifact changed: '+filename)


def freeze():
    if (OUT/'frozen_protocol.json').exists():
        raise RuntimeError('Existing frozen r5; do not restart preparation')
    if sha(SPEC) != SPEC_SHA:
        raise RuntimeError('Approved r5 design fingerprint changed')
    print('r5 verifying all protected original manifests', flush=True)
    prior = preservation()
    if read_json(R3/'preparation_audit.json')['status'] != 'passed':
        raise RuntimeError('r3 independent preparation must have passed')
    sources = [Path(__file__), SPEC, PLAN, ENGINEERING, *sorted((ROOT/'scripts').glob('alphaforge_r5_*.py')),
        ROOT/'scripts/verify_alphaforge_r5.py', ROOT/'scripts/verify_alphaforge_r5_account.py',
        ROOT/'scripts/report_alphaforge_r5.py', *sorted((ROOT/'tests').glob('test_alphaforge_r5*.py')),
        ROOT/'scripts/run_alphaforge_r3.py', ROOT/'scripts/alphaforge_r3_guard.py',
        ROOT/'scripts/run_retention_development.py', ROOT/'scripts/run_alphaforge_case.py',
        ROOT/'scripts/run_alphaforge_r2.py', ROOT/'scripts/verify_alphaforge_case.py',
        *sorted((ROOT/'quant_research').glob('*.py'))]
    # Include imported scientific preparation helpers from the frozen r3 closure.
    inherited = read_json(R3/'frozen_protocol.json')
    inherited_r4 = read_json(R4/'frozen_protocol.json')
    r4.verify_inputs(inherited_r4)
    sources = list(dict.fromkeys([*sources,
        *[ROOT/n for n in inherited['inputs'] if n.endswith('.py')],
        *[ROOT/n for n in inherited_r4['inputs'] if n.endswith('.py')]]))
    inputs = [*sources, *[DATA/n for n in ['dividend.csv','suspend_d.csv','calendar.csv','stk_limit.csv']],
              *[ROOT/'data/audit'/n for n in ['universe.csv','industry_history.csv','name_history.csv']]]
    evidence = build_evidence()
    external = source_inputs(evidence)
    check_manifest(STORAGE_PROOF, STORAGE_PROOF_SHA, 10)
    external[str(STORAGE_PROOF)]=STORAGE_PROOF_SHA
    for name,digest in read_json(STORAGE_PROOF).items():external[str(STORAGE_PROOF.parent/name)]=digest
    for log in RUNTIME_LOGS.glob('*.log'):
        if log.name.startswith(('engineering','root_integration')):external[str(log)]=sha(log)
    if str(RUNTIME_LOGS/'engineering_final.log') not in external:
        raise RuntimeError('Final engineering evidence absent')
    protocol = dict(version='r5', approval='Human =继续 on client date 2026-10-19 after complete r5 proposal',
        approval_spec_sha256=sha(SPEC), approval_client_date='2026-10-19', client_date='2026-10-19', source_commit=os.environ.get('R5_SOURCE_COMMIT','recorded_in_source_commit.txt'),
        initial_cash=1000000, fixed_keys=273794, periods=154, fixed_securities=2806, account_sessions=790,
        minimum_formed=200, window=10, epsilon=1e-6, paths=list(PATHS), costs=[0,10,30],
        order=[dict(path=p,bps=b,label=f'{p}_{b}bp') for p,b in ORDER], label='R_week',
        market_inventory_complete=False, conditional_account_attempt_allowed=False,
        live_enablement=False, enable_status='blocked_by_unverified_data_and_forward_validation',
        inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs}, external_inputs=external,
        source_snapshot_files=[str(p.relative_to(ROOT)) for p in sources],
        reused_r3={n:sha(R3/n) for n in REUSE}, prior_artifact_manifests=prior,
        original_r4_inputs=inherited_r4['inputs'], original_r4_external_inputs=inherited_r4['external_inputs'],
        corrected_mapping_events=['600781.SH:2019-07-22','601258.SH:2019-12-30','000977.SZ:2020-03-19'],
        ordinary_source_keys=23, original_ordinary_source_keys=3, new_cash_source_keys=20,
        account_information_timing='strictly earlier date-only sources for preopen stage knowledge',
        reference_information_timing='original formation cutoff inclusive; label each endpoint inclusive',
        rights_scenario='prior issuance quota, ex-date research cash debit, pending unknown listing date until public update; not actual success known preopen',
        versions=dict(python=platform.python_version(),pandas=pd.__version__),
        rule='actual price exposure / active economic obligations / proposed execution guards; original inventory retained',
        research='conditional retrospective single case; no strict unseen holdout or complete economic certification')
    snapshot = OUT/'source_before'; snapshot.mkdir()
    for p in sources:
        dest = snapshot/p.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dest)
    persist(OUT/'frozen_protocol.json', protocol, exclusive=True)
    with (OUT/'source_commit.txt').open('x',encoding='utf-8') as stream:stream.write(protocol['source_commit'])
    return protocol, evidence


def preparation():
    protocol, evidence = freeze()
    dest = OUT/'reused_r3'; dest.mkdir()
    for name in REUSE:
        shutil.copy2(R3/name,dest/name)
    persist(OUT/'evidence_mapping.json',evidence,exclusive=True)
    bars = pd.read_csv(dest/'raw_bars.csv', parse_dates=['trade_date'],
        usecols=['ts_code','trade_date','close_text','pre_close_text'],
        converters={'close_text':str,'pre_close_text':str},float_precision='round_trip')
    actions, rights, _, _ = previous.action_inputs(bars)
    full, _, simulation, _ = previous.calendars()
    validations = validate_actions(actions,evidence,full)
    overlaid = overlay_rights(rights,evidence)
    persist(OUT/'event_mapping_validation.json',dict(ordinary=validations, original_rights=len(rights),
        overlaid_rights=len(overlaid), original_rights_date_overlay_only=True, rights_quota_revision_only='000977.SZ',
        staged_rights_dates=True, market_inventory_complete=False),exclusive=True)
    common=pd.read_csv(dest/'common_samples.csv',usecols=['ts_code','trade_date'],parse_dates=['trade_date'],float_precision='round_trip')
    labels=pd.read_csv(dest/'reference_labels.csv',usecols=['ts_code','signal_date','execution_date','R_end','R_valid'],
        parse_dates=['signal_date','execution_date','R_end'],float_precision='round_trip')
    events=pd.read_csv(dest/'events.csv',dtype=str)
    print('r5 auditing fixed formation and outcome internal source bridges',flush=True)
    bridge_audit=audit_internal_reference_bridges(bars,full,common,labels,events,evidence)
    persist(OUT/'source_bridge_summary.json',bridge_audit['summary'],exclusive=True)
    for name in ('coverage','failures','trace'):
        frame=bridge_audit[name]
        if frame.empty and not len(frame.columns):
            frame=pd.DataFrame(columns=['kind','ts_code','formation_date','bridge_left','bridge_right','cutoff','reason','passed'])
        frame.to_csv(OUT/f'source_bridge_{name}.csv',index=False)
    persist(OUT/'preparation_status.json',dict(state='awaiting_independent_audit',
        source_bridge_passed=bool(bridge_audit['summary']['passed']),
        fixed_keys=273794, periods=154, account_sessions=len(simulation), accounts_started=0),exclusive=True)
    verify_inputs(protocol)
    persist(OUT/'preparation_sha256.json',{p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*')
        if p.is_file() and p.name!='runner.lock'},exclusive=True)


def load_account_inputs():
    base=OUT/'reused_r3'
    bars=pd.read_csv(base/'raw_bars.csv',parse_dates=['trade_date'],
        converters={'close_text':str,'pre_close_text':str},float_precision='round_trip')
    actions,rights,_,corrections=previous.action_inputs(bars)
    evidence=read_json(OUT/'evidence_mapping.json')
    rights=overlay_rights(rights,evidence)
    limits,aliases=correct_limit_code_aliases(read_subset('stk_limit',set(bars.ts_code)|{'000043.SZ'}))
    bars=bars.merge(limits,on=['ts_code','trade_date'],how='left',validate='one_to_one')
    universe=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    suspensions=pd.read_csv(DATA/'suspend_d.csv',dtype=str)
    full,_,calendar,schedule=previous.calendars()
    targets={p:pd.read_csv(base/f'targets_{p}.csv',parse_dates=['trade_date','signal_date','execution_date'],
                          float_precision='round_trip') for p in PATHS}
    return bars,actions,rights,universe,suspensions,evidence,full,calendar,schedule,targets,corrections+aliases


def save_account(folder, result):
    for name, value in result.items():
        if isinstance(value,pd.DataFrame):
            value.to_csv(folder/f'{name}.csv',index=False)
        else:
            persist(folder/f'{name}.json',value,exclusive=True)


def accounts():
    from alphaforge_r5_account import simulate_exposure, AccountRunFailure
    protocol=read_json(OUT/'frozen_protocol.json');verify_inputs(protocol);verify_stage('preparation_sha256.json')
    audit=read_json(OUT/'preparation_audit.json')
    if not audit['conditional_account_attempt_allowed'] or audit['market_inventory_complete']:
        raise RuntimeError('Independent conditional gate absent or falsely certified inventory')
    if (OUT/'experiment_protocol.json').exists():
        raise RuntimeError('Existing r5 account attempt; never repeat')
    persist(OUT/'experiment_protocol.json',dict(order=protocol['order'], live_enablement=False,
        runner_sha256=sha(Path(__file__)),preparation_audit_sha256=sha(OUT/'preparation_audit.json')),exclusive=True)
    statuses=[dict(strategy=f'{p}_{b}bp',path=p,slippage_bps=b,status='not_started') for p,b in ORDER]
    persist(OUT/'status.json',statuses)
    bars,actions,rights,universe,suspensions,evidence,full,calendar,schedule,targets,corrections=load_account_inputs()
    sectors=pd.read_csv(ROOT/'data/audit/industry_history.csv',dtype=str);industries={}
    for d in calendar:
        stamp=d.strftime('%Y%m%d');sector=sectors.loc[(sectors.in_date<=stamp)&(sectors.out_date.isna()|(sectors.out_date>stamp))]
        counts=sector.groupby('ts_code').l1_code.nunique();sector=sector.loc[sector.ts_code.isin(counts[counts==1].index)].drop_duplicates('ts_code')
        industries[d]=dict(zip(sector.ts_code,sector.l1_code))
    summaries=[]
    for status in statuses:
        check_disk()
        label=status['strategy'];path=status['path'];bps=status['slippage_bps'];folder=OUT/label;folder.mkdir()
        shutil.copy2(OUT/'reused_r3'/f'targets_{path}.csv',folder/'historical_targets.csv')
        status['status']='running';persist(OUT/'status.json',statuses)
        config=Config(slippage_bps=bps,zero_trading_costs=bps==0)
        # Codes never targeted cannot become assets. Full unfiltered inventory
        # and quote input remain frozen, retained and independently audited.
        possible=set(targets[path].ts_code)
        account_bars=bars.loc[bars.ts_code.isin(possible)]
        print('r5 starting fixed account',label,'possible assets',len(possible),flush=True)
        def progress(date,count):
            print(label,'completed sessions',count,str(date.date()),flush=True)
        try:
            result=simulate_exposure(account_bars,calendar,targets[path],actions,suspensions,
                industries=industries,config=config,rebalance_dates=schedule.execution_date.tolist(),
                rights=rights,universe=universe,full_calendar=full,evidence=evidence,progress=progress)
            save_account(folder,result)
            summary=summarize(result['nav'],result['orders'],schedule.execution_date.iloc[0],pd.Timestamp('20180101'))
            summary.update(strategy=label,path=path,config=asdict(config));summaries.append(summary)
            status.update(status='completed',completed_sessions=len(result['nav']))
        except AccountRunFailure as error:
            save_account(folder,error.partial)
            kind='data_or_economic_failure' if isinstance(error.original,ValueError) else 'engineering_failure'
            failure=dict(date=str(error.date.date()),reason=str(error.original),type=kind,
                         guard_row=getattr(error.original,'row',None),completed_sessions=len(error.partial['nav']))
            persist(folder/'failure.json',failure,exclusive=True)
            (folder/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
            status.update(status='failed',**failure)
            print('r5 fail-fast',label,kind,failure['date'],failure['reason'],flush=True)
        except Exception:
            status.update(status='engineering_failure',error=traceback.format_exc())
            (folder/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        persist(OUT/'status.json',statuses)
        persist(OUT/'summary.json',dict(experiments=summaries,experiment_statuses=statuses,
            corrections=corrections,market_inventory_complete=False,live_enablement=False))
        verify_inputs(protocol)
        if status['status']!='completed':
            break
    completed=sum(s['status']=='completed' for s in statuses)
    persist(OUT/'experiment_stage.json',dict(state='completed' if completed==6 else 'stopped_first_failure',
        accounts_started=sum(s['status']!='not_started' for s in statuses),completed_accounts=completed,
        market_inventory_complete=False),exclusive=True)
    persist(OUT/'accounts_sha256.json',{p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*')
        if p.is_file() and p.name!='runner.lock' and ('reused_r3' not in p.parts)
        and 'source_before' not in p.parts and p.name!='preparation_sha256.json'},exclusive=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['preparation','accounts'],required=True)
    args=parser.parse_args()
    if not OUT.is_dir() or OUT.resolve()==OUT:
        raise RuntimeError('Dedicated D directory and C junction required')
    if (OUT/'output_sha256.json').exists():
        raise RuntimeError('Final sealed r5; never alter or restart')
    if (OUT/('frozen_protocol.json' if args.stage=='preparation' else 'experiment_protocol.json')).exists():
        raise RuntimeError('Existing r5 stage; do not restart')
    check_disk()
    with exclusive_stage(OUT,args.stage):
        try:
            {'preparation':preparation,'accounts':accounts}[args.stage]()
        except Exception:
            path=OUT/f'failure_{args.stage}_{os.getpid()}.txt'
            with path.open('x',encoding='utf-8') as stream:stream.write(traceback.format_exc())
            raise


if __name__=='__main__':main()
