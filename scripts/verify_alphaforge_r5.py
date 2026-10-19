"""Independent r5 reuse/protection/stage audit; never run another account."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import math
import traceback

import pandas as pd

import run_alphaforge_r5 as run
import verify_alphaforge_case as legacy
from quant_research.backtest import Config, summarize
from alphaforge_r5_evidence import build_evidence, validate_actions
from alphaforge_r5_preparation_audit import audit_preparation_bridges

OUT,ROOT,R3=run.OUT,run.ROOT,run.R3


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,default=str,allow_nan=False)


def fingerprints(protocol, deep=False):
    for name,digest in protocol['inputs'].items():
        assert sha(ROOT/name)==digest,'Frozen input changed: '+name
    for name,digest in protocol['external_inputs'].items():
        assert sha(name)==digest,'Frozen external source changed: '+name
    for name,digest in protocol['reused_r3'].items():
        assert sha(R3/name)==digest,'Original r3 changed: '+name
    for name,digest in protocol['original_r4_inputs'].items():
        assert sha(ROOT/name)==digest,'Original r4 source changed: '+name
    for name,digest in protocol['original_r4_external_inputs'].items():
        assert sha(name)==digest,'Original r4 external source changed: '+name
    counts=[]
    for entry in protocol['prior_artifact_manifests']:
        path=Path(entry['path']);assert sha(path)==entry['sha256']
        manifest=load(path);assert len(manifest)==entry['count']
        if deep:
            for name,digest in manifest.items():
                assert sha(path.parent/name)==digest,'Protected artifact changed: '+str(path.parent/name)
        counts.append(entry['count'])
    assert counts[-10:]==[105,493,110,646,115,78,7,14,12,35] and sum(counts[:-10])==1924
    snapshot={str(p.relative_to(OUT/'source_before')) for p in (OUT/'source_before').rglob('*') if p.is_file()}
    assert snapshot==set(protocol['source_snapshot_files']), 'Source snapshot incomplete or expanded'
    for p in (OUT/'source_before').rglob('*'):
        if p.is_file():
            assert sha(p)==protocol['inputs'][str(p.relative_to(OUT/'source_before'))]
    return dict(earlier=1924,r3=105,r4_evidence=493,r4=110,additional_source_batches=907,
                total=sum(counts),manifest_members_sum_not_unique_files=True,full_member_rehash=deep)


def stage_fingerprint(name):
    manifest=load(OUT/name)
    for filename,digest in manifest.items():
        assert sha(OUT/filename)==digest,'Stage changed: '+filename
    return sha(OUT/name)


def verify_preparation():
    protocol=load(OUT/'frozen_protocol.json')
    counts=fingerprints(protocol,deep=True)
    digest=stage_fingerprint('preparation_sha256.json')
    assert protocol['approval'].startswith('Human =继续') and protocol['approval_client_date']=='2026-10-19'
    assert protocol['client_date']=='2026-10-19'
    assert protocol['approval_spec_sha256']==run.SPEC_SHA and sha(run.SPEC)==run.SPEC_SHA
    assert protocol['order']==[dict(path=p,bps=b,label=f'{p}_{b}bp') for p in legacy.PATHS for b in (0,10,30)]
    assert protocol['market_inventory_complete'] is False and protocol['live_enablement'] is False
    base=OUT/'reused_r3'
    assert set(protocol['reused_r3'])==set(run.REUSE)
    for name,digest in protocol['reused_r3'].items():
        assert sha(base/name)==digest
    common=pd.read_csv(base/'common_samples.csv',usecols=['trade_date','ts_code'],parse_dates=['trade_date'])
    assert len(common)==273794 and not common.duplicated(['trade_date','ts_code']).any()
    assert common.trade_date.nunique()==154 and common.ts_code.nunique()==2806
    assert common.groupby('trade_date').size().min()>=200
    assert load(base/'preparation_audit.json')['status']=='passed'
    assert load(base/'primary_invariance.json')['primary_targets_exact']
    for path in legacy.PATHS:
        assert sha(base/f'targets_{path}.csv')==sha(R3/f'targets_{path}.csv')
    inventory=load(base/'guard_summary.json')
    assert inventory['passed'] is False and inventory['failure_count']==16441
    assert inventory['security_session_rows']==2806*790
    assert len(pd.read_csv(base/'guard_failures.csv'))==16441
    assert load(base/'guard_audit.json')['status']=='passed'
    mapping=load(OUT/'evidence_mapping.json')
    assert mapping==build_evidence()
    assert len(mapping['ordinary_actions'])==23 and len(mapping['rights_overlay'])==1
    assert len(mapping['event_versions'])==3 and len(mapping['rights_stages'])==10
    assert len(set(x['code'] for x in mapping['status_events']))==9
    overlay=mapping['rights_overlay'][0]
    assert (overlay['code'],overlay['record'],overlay['ex'])==('600480.SH','2019-06-11','2019-06-20')
    assert all(overlay[k] is None for k in ('price','ratio','list_date'))
    bars=pd.read_csv(base/'raw_bars.csv',parse_dates=['trade_date'],
        usecols=['ts_code','trade_date','close_text','pre_close_text'],
        converters={'close_text':str,'pre_close_text':str},float_precision='round_trip')
    actions,_,_,_=run.previous.action_inputs(bars)
    full,_,calendar,schedule=run.previous.calendars()
    rows=validate_actions(actions,mapping,full)
    assert len(calendar)==790 and len(schedule)==154
    # Later state transitions have no prefilled right boundary on initial rows.
    assert all(not x.get('end_date') for x in mapping['status_events'])
    labels=pd.read_csv(base/'reference_labels.csv',usecols=['ts_code','signal_date','execution_date','R_end','R_valid'],
        parse_dates=['signal_date','execution_date','R_end'])
    events=pd.read_csv(base/'events.csv',dtype=str)
    # All original reference-label rows remain, including original invalid rows.
    # Exact byte reuse is checked above; no re-filtering on the corrected source.
    print('r5 independently rebuilding every fixed internal source bridge',flush=True)
    bridge=audit_preparation_bridges(bars,full,common,labels,events,mapping,
        load(OUT/'source_bridge_summary.json'),
        pd.read_csv(OUT/'source_bridge_coverage.csv',dtype=str),
        pd.read_csv(OUT/'source_bridge_failures.csv',dtype=str),
        pd.read_csv(OUT/'source_bridge_trace.csv',dtype=str))
    result=dict(status=bridge['status'],conditional_account_attempt_allowed=bridge['conditional_account_attempt_allowed'],market_inventory_complete=False,
        fixed_keys=273794,periods=154,fixed_securities=2806,account_sessions=790,
        exact_reuse=True,factor_label_target_recomputation=False,original_inventory_failures=16441,
        original_inventory_cells=2806*790,ordinary_source_checks=rows,source_files=len(mapping['consumed_source_files']),
        old_artifacts=counts,preparation_manifest_sha256=digest,verifier_sha256=sha(Path(__file__)),
        source_bridge_audit=bridge,source_bridge_summary_sha256=sha(OUT/'source_bridge_summary.json'),
        live_enablement=False,scope='Permission only if all original source bridges remain valid; not full market certification')
    save(OUT/'preparation_audit.json',result)
    return result


def verify_accounts():
    from verify_alphaforge_r5_account import verify_account
    protocol=load(OUT/'frozen_protocol.json');counts=fingerprints(protocol,deep=True)
    stage_fingerprint('preparation_sha256.json');digest=stage_fingerprint('accounts_sha256.json')
    assert load(OUT/'preparation_audit.json')['conditional_account_attempt_allowed']
    status=load(OUT/'status.json');summary=load(OUT/'summary.json')
    assert [(x['path'],x['slippage_bps']) for x in status]==[(p,b) for p in legacy.PATHS for b in (0,10,30)]
    experiment=load(OUT/'experiment_protocol.json')
    assert experiment['runner_sha256']==sha(ROOT/'scripts/run_alphaforge_r5.py')
    assert experiment['preparation_audit_sha256']==sha(OUT/'preparation_audit.json')
    failures=[i for i,s in enumerate(status) if s['status'] in ('failed','engineering_failure')]
    if failures:
        assert len(failures)==1
        first=failures[0]
        assert all(s['status']=='completed' for s in status[:first])
        assert all(s['status']=='not_started' for s in status[first+1:])
        assert all(not (OUT/s['strategy']).exists() for s in status[first+1:])
    else:
        assert len(status)==6 and all(s['status']=='completed' for s in status)
    bars,actions,rights,universe,suspensions,evidence,full,calendar,schedule,targets,_=run.load_account_inputs()
    records=[];annual=[];boundaries=[]
    for s in status:
        if s['status']=='not_started':continue
        folder=OUT/s['strategy'];complete=s['status']=='completed'
        assert sha(folder/'historical_targets.csv')==sha(OUT/'reused_r3'/f'targets_{s["path"]}.csv')
        bps=s['slippage_bps'];config=Config(slippage_bps=bps,zero_trading_costs=bps==0)
        audit=verify_account(folder,bars,calendar,targets[s['path']],actions,rights,
                             universe,suspensions,evidence,config,completed=complete)
        records.append(dict(strategy=s['strategy'],**audit))
        boundaries.extend(dict(strategy=s['strategy'],**x) for x in audit.get('year_boundaries',[]))
        if complete:
            nav=pd.read_csv(folder/'nav.csv',parse_dates=['date'],float_precision='round_trip')
            orders=pd.read_csv(folder/'orders.csv',parse_dates=['date'],float_precision='round_trip')
            recorded=[x for x in summary['experiments'] if x['strategy']==s['strategy']]
            assert len(recorded)==1 and recorded[0]['config']==asdict(config)
            recomputed=summarize(nav,orders,schedule.execution_date.iloc[0],pd.Timestamp('20180101'))
            for key,value in recomputed.items():
                actual=recorded[0][key]
                if isinstance(value,(float,int)):
                    assert math.isclose(actual,value,rel_tol=0,abs_tol=1e-6),(s['strategy'],key)
                else:assert actual==value,(s['strategy'],key)
            previous=1000000.
            for year,g in nav.loc[nav.date>='20180101'].groupby(nav.date.dt.year):
                ending=float(g.equity.iloc[-1]);annual.append(dict(strategy=s['strategy'],year=int(year),
                    start_equity=previous,end_equity=ending,return_value=ending/previous-1));previous=ending
        print('r5 independent account audit',s['strategy'],audit['status'],flush=True)
    full_pass=len(records)==6 and all(s['status']=='completed' for s in status)
    gates=None
    if full_pass:
        assert len(boundaries)==12
        ic=pd.read_csv(OUT/'reused_r3/factor_ic.csv',parse_dates=['signal_date'])
        stats=pd.DataFrame(summary['experiments']).set_index('strategy')
        gates,mean_ic,yearly_ic=legacy.strategy_gates(stats,pd.DataFrame(annual),ic,schedule)
    else:
        assert not (OUT/'verification.json').exists()
    fingerprints(protocol)
    if annual:pd.DataFrame(annual).to_csv(OUT/'annual_returns.csv',index=False)
    if boundaries:pd.DataFrame(boundaries).to_csv(OUT/'year_boundary_audit.csv',index=False)
    result=dict(status='passed' if full_pass else 'passed_partial_evidence_only',accounts=records,
        engineering_verification_passed=True,full_six_account_verification_passed=full_pass,
        completed_accounts_verified=sum(s['status']=='completed' for s in status),
        accounts_started=sum(s['status']!='not_started' for s in status),year_boundaries=len(boundaries),
        research_gates_assessable=full_pass,gates=gates,research_gates_passed=all(gates.values()) if gates else None,
        market_inventory_complete=False,live_enablement=False,
        enable_status='blocked_by_unverified_data_and_forward_validation',old_artifacts=counts,
        accounts_manifest_sha256=digest,verifier_sha256=sha(Path(__file__)),
        status_sha256=sha(OUT/'status.json'),summary_sha256=sha(OUT/'summary.json'))
    save(OUT/('verification.json' if full_pass else 'partial_verification.json'),result)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['preparation','accounts'],required=True)
    args=parser.parse_args();run.check_disk()
    if (OUT/'output_sha256.json').exists():raise RuntimeError('Final sealed r5; never rerun audit')
    if args.stage=='preparation' and (OUT/'preparation_audit.json').exists():
        raise RuntimeError('Existing independent preparation audit; never overwrite')
    if args.stage=='accounts' and any((OUT/n).exists() for n in ('verification.json','partial_verification.json')):
        raise RuntimeError('Existing independent account audit; never overwrite')
    with run.exclusive_stage(OUT,'independent_'+args.stage):
        try:
            result={'preparation':verify_preparation,'accounts':verify_accounts}[args.stage]()
            print(json.dumps({k:v for k,v in result.items() if k not in ('accounts','old_artifacts')},ensure_ascii=False,default=str))
        except Exception:
            with (OUT/f'failure_independent_{args.stage}.txt').open('x',encoding='utf-8') as stream:
                stream.write(traceback.format_exc())
            raise


if __name__=='__main__':main()
