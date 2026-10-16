"""Approved reference/event filter r2; all other case/account rules stay frozen."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import traceback

import numpy as np
import pandas as pd

import run_alphaforge_case as r1
import run_ml_risk as original
import announcement_financial_audit as audit
from run_retention_development import ROOT, DATA, SOURCE, sha, read_subset
from alphaforge_case_factor import formula_10
from alphaforge_case_r2_features import compute_asset
from alphaforge_r2_events import build_events
from alphaforge_case_diagnostics import diagnostics, summarize_ic
from quant_research.corporate_corrections import correct_adjustments, correct_actions
from quant_research.factors import rank_scores, FACTORS
from quant_research.rights import verified_rights
from retention_selector import select_retention

OUT=ROOT/'output/alphaforge_case_2018_2020_r2'
OLD=r1.OLD
LABEL=r1.LABEL
PATHS=r1.PATHS
SPEC=ROOT/'docs/superpowers/specs/2026-10-16-alphaforge-event-filter-r2-design.md'
PLAN=ROOT/'docs/superpowers/plans/2026-10-16-alphaforge-r2-implementation.md'


def persist(name,value):
    audit.write_json(OUT/name,value)


def old_manifests():
    return r1.old_manifests()+[r1.OUT/'output_sha256.json']


def verify_prior():
    counts={}
    for path in old_manifests():
        files=json.loads(path.read_text(encoding='utf-8'))
        for name,expected in files.items():
            if sha(path.parent/name)!=expected:raise RuntimeError('Prior artifact changed: '+str(path.parent/name))
        counts[path.parent.name]=len(files)
    return counts


def verify_inputs(protocol):
    for name,expected in protocol['inputs'].items():
        if sha(ROOT/name)!=expected:raise RuntimeError('Frozen input changed: '+name)
    for name,expected in protocol['external_inputs'].items():
        if sha(Path(name))!=expected:raise RuntimeError('External source changed: '+name)
    if {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}!=protocol['source_sha256']:
        raise RuntimeError('Original core changed')
    for name,expected in protocol['prior_artifact_manifests'].items():
        if sha(ROOT/name)!=expected:raise RuntimeError('Prior manifest changed: '+name)
    return verify_prior()


def read_quotes(codes,calendar):
    """Preserve Decimal reference inputs before numeric conversion, no filling."""
    columns=['ts_code','trade_date','open','high','low','close','pre_close','vol','amount']
    parts=[]
    for chunk in pd.read_csv(DATA/'daily.csv',usecols=columns,
            dtype={'ts_code':str,'trade_date':str},
            converters={'close':str,'pre_close':str},chunksize=150000):
        frame=chunk.loc[chunk.ts_code.isin(codes)&chunk.trade_date.between('20151101','20201231')].copy()
        if frame.empty:continue
        frame['close_text']=frame.close.astype('string');frame['pre_close_text']=frame.pre_close.astype('string')
        frame['close']=pd.to_numeric(frame.close,errors='coerce')
        frame['pre_close']=pd.to_numeric(frame.pre_close,errors='coerce')
        frame['trade_date']=pd.to_datetime(frame.trade_date,format='%Y%m%d')
        parts.append(frame)
    quotes=pd.concat(parts,ignore_index=True)
    quotes=quotes.merge(read_subset('adj_factor',codes),on=['ts_code','trade_date'],validate='one_to_one')
    quotes=quotes.loc[quotes.trade_date.isin(calendar)].copy()
    return correct_adjustments(quotes)


def prepare():
    if (OUT/'frozen_protocol.json').exists():raise RuntimeError('Existing r2 preparation; inspect without restarting')
    prior_counts=verify_prior()
    baseline=json.loads((LABEL/'frozen_protocol.json').read_text(encoding='utf-8'))
    core={p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}
    if core!=baseline['source_sha256']:raise RuntimeError('Original core changed')
    manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files_sha256'].items():
        if sha(DATA/name)!=expected:raise RuntimeError('Data changed: '+name)
    sources=[SPEC,PLAN,Path(__file__),ROOT/'scripts/alphaforge_case_r2_features.py',
        ROOT/'scripts/alphaforge_r2_events.py',ROOT/'scripts/verify_alphaforge_r2.py',
        ROOT/'scripts/run_alphaforge_case.py',ROOT/'scripts/verify_alphaforge_case.py',
        ROOT/'scripts/alphaforge_case_factor.py',ROOT/'scripts/alphaforge_case_diagnostics.py',
        ROOT/'scripts/run_ml_risk.py',ROOT/'scripts/run_retention_development.py',
        ROOT/'scripts/retention_selector.py']
    sources+=sorted((ROOT/'tests').glob('test_alphaforge*r2*.py'))
    inputs=sources+[OLD/'common_samples.csv',OLD/'frozen_protocol.json',LABEL/'frozen_protocol.json',
        DATA/'manifest.json',SOURCE/'unexplained_adjustments.csv',r1.OUT/'feature_coverage.csv']
    inputs+=[DATA/name for name in manifest['files_sha256']]
    inputs+=[ROOT/'data/audit'/name for name in baseline['metadata_sha256']]
    for name,expected in baseline['metadata_sha256'].items():
        if sha(ROOT/'data/audit'/name)!=expected:raise RuntimeError('Metadata changed: '+name)
    external=list(json.loads((r1.OUT/'frozen_protocol.json').read_text(encoding='utf-8'))['external_inputs'])
    external+=[str(Path('D:/QuantResearchEvidence')/folder/name) for folder,name in [
        ('alphaforge_event_crosscheck_20261016_r1','crosscheck.json'),
        ('alphaforge_method_evidence_20261016_r1','method_review.json'),
        ('alphaforge_filter_preview_20261016_r1_attempt2','boolean_parsing_check.json')]]
    protocol=dict(primary=PATHS[0],paths=PATHS,costs=[0,10,30],initial_cash=1000000,window=10,
        internal_transitions=9,minimum_formed_per_date=200,epsilon=1e-6,
        input_close='raw CNY',input_volume='raw vol * 100 shares',
        eligibility='Decimal raw-reference continuity and known-date-bounded registered actions',
        primary_signal='negative published signed-log correlation, unchanged from r1',
        fundamental_signals_consumed=False,corporate_action_terms_consumed=True,
        approval='Human 继续 after explicit r2 design and approval question on2026-10-16',
        source_sha256=core,inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs},
        external_inputs={name:sha(Path(name)) for name in external},
        prior_artifact_manifests={str(p.relative_to(ROOT)):sha(p) for p in old_manifests()},
        prior_artifacts_verified=prior_counts,
        versions=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__),
        scope='Retrospective r2 local case; daily known dates do not certify historical vintages')
    persist('frozen_protocol.json',protocol)
    snapshot=OUT/'source_before';snapshot.mkdir()
    for p in sources+list((ROOT/'quant_research').glob('*.py')):shutil.copy2(p,snapshot/p.name)
    calendar,schedule=r1.schedule_and_calendar()
    assert len(schedule)==154
    schedule.to_csv(OUT/'schedule.csv',index=False)
    columns=['trade_date','ts_code','industry','D_label','D_valid','D_end','reference_end',*FACTORS]
    base=pd.read_csv(OLD/'common_samples.csv',usecols=columns,
        parse_dates=['trade_date','D_end','reference_end'],float_precision='round_trip')
    base=base.loc[base.trade_date.isin(schedule.signal_date)].copy()
    if base.duplicated(['trade_date','ts_code']).any():raise RuntimeError('Duplicate base key')
    codes=set(base.ts_code)
    raw_actions=pd.read_csv(DATA/'dividend.csv',dtype=str)
    raw_actions.to_csv(OUT/'raw_event_versions.csv',index=False)
    _,action_corrections=correct_actions(raw_actions)
    persist('event_corrections.json',action_corrections)
    events=build_events(raw_actions,rights=verified_rights())
    events=events.loc[events.code.isin(codes)&events.event_date.between(calendar.min(),calendar.max())].copy()
    events.to_csv(OUT/'events.csv',index=False)
    persist('event_mapping_summary.json',dict(rows=len(events),
        known_date_fields=events.known_date_field.value_counts(dropna=False).to_dict(),
        timing_reasons=events.timing_reason.value_counts(dropna=False).to_dict(),
        timing_verified=int(events.timing_verified.sum()),
        not_a_historical_vintage_certification=True))
    persist('preparation_status.json',dict(state='quotes',pid=os.getpid(),codes=len(codes)))
    print('r2 read frozen raw quotes and reference text',flush=True)
    bars,corrections=read_quotes(codes,calendar)
    dates={c:sorted(g.trade_date) for c,g in base.groupby('ts_code')}
    event_groups={c:g for c,g in events.groupby('code')}
    pieces=[];precision=[];first_transition=True
    for i,(code,group) in enumerate(bars.groupby('ts_code',sort=True)):
        f,transitions=compute_asset(group,calendar,dates[code],event_groups.get(code,events.iloc[:0]))
        f['ts_code']=code;pieces.append(f)
        if len(transitions):
            transitions.to_csv(OUT/'reference_transitions.csv',mode='w' if first_transition else 'a',
                               header=first_transition,index=False)
            first_transition=False
        first=f.loc[f.case_valid].head(1)
        if len(first):
            d=first.iloc[0].trade_date;pos=calendar.get_loc(d)
            q=group.set_index('trade_date').reindex(calendar).iloc[pos-9:pos+1]
            a=formula_10(q.close.to_numpy(),q.vol.to_numpy()*100,dtype=np.float64)
            b=formula_10(q.close.to_numpy(),q.vol.to_numpy()*100,dtype=np.float32)
            precision.append(dict(ts_code=code,trade_date=d,factor64=a['factor'],factor32=b['factor'],
                absolute_difference=abs(a['factor']-b['factor']),guard64=a['guard'],guard32=b['guard']))
        if (i+1)%500==0:
            print('r2 feature assets',i+1,flush=True)
            persist('preparation_status.json',dict(state='features',pid=os.getpid(),completed_assets=i+1))
    features=pd.concat(pieces,ignore_index=True).rename(columns={'factor':'case_factor','signal':'case_signal',
        'rho':'case_rho','guard':'case_guard','nlvar':'case_nlvar','nrvar':'case_nrvar'})
    coverage=base.merge(features,on=['trade_date','ts_code'],how='left',validate='one_to_one')
    if len(coverage)!=len(base) or coverage.case_valid.isna().any():raise RuntimeError('Incomplete r2 alignment')
    coverage.to_csv(OUT/'feature_coverage.csv',index=False)
    prior=pd.read_csv(r1.OUT/'feature_coverage.csv',usecols=['trade_date','ts_code','case_valid','case_factor'],
        parse_dates=['trade_date'],float_precision='round_trip')
    comparison=coverage[['trade_date','ts_code','case_valid','case_factor','reason']].merge(
        prior,on=['trade_date','ts_code'],suffixes=('_r2','_r1'),validate='one_to_one')
    intersection=comparison.case_valid_r2 & comparison.case_valid_r1
    error=float((comparison.loc[intersection,'case_factor_r2']-comparison.loc[intersection,'case_factor_r1']).abs().max())
    if error>1e-12:raise RuntimeError('Shared r1/r2 formula values differ')
    comparison.to_csv(OUT/'r1_pool_comparison.csv',index=False)
    common=coverage.loc[coverage.case_valid].copy()
    counts=common.groupby('trade_date').size().reindex(schedule.signal_date,fill_value=0)
    if counts.min()<200:raise RuntimeError('Fewer than 200 formed stocks: '+str(counts[counts<200].to_dict()))
    old_score=rank_scores(common[['trade_date','ts_code','industry',*FACTORS]],FACTORS)
    common=common.merge(old_score[['trade_date','ts_code','score']].rename(columns={'score':'three_score'}),
        on=['trade_date','ts_code'],validate='one_to_one')
    common.to_csv(OUT/'common_samples.csv',index=False)
    pd.DataFrame(precision).to_csv(OUT/'float_precision_audit.csv',index=False)
    ic,groups=diagnostics(common,schedule)
    ic.to_csv(OUT/'factor_ic.csv',index=False);groups.to_csv(OUT/'factor_groups.csv',index=False)
    summarize_ic(ic).to_csv(OUT/'factor_ic_summary.csv',index=False)
    plans={p:[] for p in PATHS};previous={p:set() for p in PATHS};selection=[]
    for row in schedule.itertuples(index=False):
        frame=common.loc[common.trade_date.eq(row.signal_date)]
        for path,factor in [(PATHS[0],'case_signal'),(PATHS[1],'three_score')]:
            s=frame[['trade_date','ts_code','industry']].copy()
            s['score']=frame[factor].rank(method='average',pct=True) if path==PATHS[0] else frame[factor]
            target,records=select_retention(s,previous[path]);previous[path]=set(target.ts_code)
            if target.empty:raise RuntimeError('Empty r2 target')
            target['signal_date']=row.signal_date;target['execution_date']=row.execution_date;plans[path].append(target)
            records['path']=path;records['signal_date']=row.signal_date;selection.append(records)
    for path,rows in plans.items():pd.concat(rows,ignore_index=True).to_csv(OUT/f'targets_{path}.csv',index=False)
    pd.concat(selection,ignore_index=True).to_csv(OUT/'selection_events.csv',index=False)
    persist('feature_summary.json',dict(original_rows=len(base),common_rows=len(common),
        minimum_formed=int(counts.min()),schedule_rows=len(schedule),reasons=coverage.reason.value_counts().to_dict(),
        guard_rows=int(common.case_guard.sum()),adjustment_corrections=corrections,
        precision_windows=len(precision),maximum_float_precision_difference=max(v['absolute_difference'] for v in precision),
        r1_intersection_rows=int(intersection.sum()),maximum_r1_formula_difference=error,
        eligibility_changed_rows=int(comparison.case_valid_r1.ne(comparison.case_valid_r2).sum()),
        event_timing_unverified_formation_rows=int(coverage.event_timing_unverified_count.gt(0).sum()),
        isolated_factor_change_rows=int(common.isolated_factor_change_no_observed_reference_break.sum())))
    verify_inputs(protocol)
    persist('preparation_status.json',dict(state='completed',pid=os.getpid(),common_rows=len(common),models_started=False))
    persist('preparation_sha256.json',{p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*')
        if p.is_file() and p.name!='runner.lock'})
    print('r2 preparation complete',len(common),'rows /',len(schedule),'weeks',flush=True)


def accounts():
    if (OUT/'experiment_protocol.json').exists():raise RuntimeError('Existing r2 accounts; inspect without restarting')
    protocol=json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'))
    verify_inputs(protocol)
    if json.loads((OUT/'preparation_status.json').read_text(encoding='utf-8'))['state']!='completed':
        raise RuntimeError('Preparation incomplete')
    audit_result=json.loads((OUT/'preparation_audit.json').read_text(encoding='utf-8'))
    if audit_result['status']!='passed':raise RuntimeError('Independent r2 preparation audit missing')
    for name,expected in json.loads((OUT/'preparation_sha256.json').read_text(encoding='utf-8')).items():
        if sha(OUT/name)!=expected:raise RuntimeError('Prepared artifact changed: '+name)
    expected=json.loads((LABEL/'frozen_protocol.json').read_text(encoding='utf-8'))['inputs']['scripts\\run_ml_risk.py']
    if sha(Path(original.__file__))!=expected:raise RuntimeError('Original adapter changed')
    source=Path(original.__file__).read_text(encoding='utf-8')
    block=source[source.index('    all_codes=set().union'):source.index('    return int(any(s[')]
    block='\n'.join(line[4:] if line.startswith('    ') else line for line in block.splitlines())
    (OUT/'simulation_adapter_block.py.txt').write_text(block,encoding='utf-8')
    persist('experiment_protocol.json',dict(paths=PATHS,primary=PATHS[0],costs=[0,10,30],
        runner_sha256=sha(Path(__file__)),adapter_sha256=sha(OUT/'simulation_adapter_block.py.txt')))
    calendar,schedule=r1.schedule_and_calendar()
    targets={p:pd.read_csv(OUT/f'targets_{p}.csv',parse_dates=['trade_date','signal_date','execution_date'],
        float_precision='round_trip') for p in PATHS}
    codes=set().union(*(set(t.ts_code) for t in targets.values()))
    bars=read_subset('daily',codes).merge(read_subset('adj_factor',codes),on=['ts_code','trade_date'],validate='one_to_one')
    bars=bars.loc[bars.trade_date.isin(calendar)].copy();bars,adjustment_corrections=correct_adjustments(bars)
    metadata=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    sectors=pd.read_csv(ROOT/'data/audit/industry_history.csv',dtype=str);core=protocol['source_sha256']
    persist('experiment_stage.json',dict(state='accounts',pid=os.getpid(),expected_accounts=6))
    namespace=dict(vars(original));namespace.update(locals());namespace.update(OUT=OUT,PATHS=PATHS,persist=persist)
    exec(compile(block,str(Path(original.__file__))+'#frozen_account_adapter','exec'),namespace)
    statuses=namespace['statuses'];failed=any(s['status']!='completed' for s in statuses)
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    summary['scope']='Retrospective 2018-2020 r2 fixed formula and same-pool control; not an unseen holdout or fitted walk-forward model'
    persist('summary.json',summary)
    verify_inputs(protocol)
    persist('experiment_stage.json',dict(state='failed' if failed else 'completed',pid=os.getpid(),
        accounts=len(statuses),independent_verification_pending=True))
    if failed:raise RuntimeError('One or more r2 accounts failed; evidence retained')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['prepare','accounts'],required=True)
    args=parser.parse_args();OUT.mkdir(exist_ok=True)
    if shutil.disk_usage(OUT.resolve()).free<6*1024**3:raise RuntimeError('6GiB floor reached')
    lock=OUT/'runner.lock'
    with lock.open('x',encoding='utf-8') as f:json.dump(dict(pid=os.getpid(),stage=args.stage),f)
    try:
        prepare() if args.stage=='prepare' else accounts()
    except Exception:
        name=f'failure_{args.stage}_{pd.Timestamp.now():%Y%m%dT%H%M%S}.txt'
        (OUT/name).write_text(traceback.format_exc(),encoding='utf-8')
        persist('last_failure.json',dict(stage=args.stage,pid=os.getpid(),failure=name));raise
    finally:lock.unlink()


if __name__=='__main__':main()
