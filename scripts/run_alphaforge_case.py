"""Frozen single published formula, two paths, six real-share accounts; no search."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import traceback

import numpy as np
import pandas as pd

from run_retention_development import ROOT, DATA, SOURCE, sha, read_subset
import announcement_financial_audit as audit
import run_ml_risk as original
from alphaforge_case_factor import compute_asset, formula_10
from alphaforge_case_diagnostics import diagnostics, summarize_ic
from quant_research.corporate_corrections import correct_adjustments
from quant_research.factors import rank_scores, FACTORS, weekly_schedule
from retention_selector import select_retention

OUT = ROOT/'output/alphaforge_case_2018_2020_r1'
OLD = ROOT/'output/price_amount_ridge_2018_2020_r1'
LABEL = ROOT/'output/label_horizon_coverage_2018_2020_r1'
PATHS = ['case_negative_retention_common200', 'three_retention_case_common200']
SPEC = ROOT/'docs/superpowers/specs/2026-10-15-alphaforge-case-design.md'
PLAN = ROOT/'docs/superpowers/plans/2026-10-15-alphaforge-case-implementation.md'
PAPER = Path('D:/QuantResearchEvidence/paper_reproduction_selection_20261015_r1')


def persist(name, value):
    audit.write_json(OUT/name, value)


def old_manifests():
    return [LABEL/'output_sha256.json',
            ROOT/'output/open_source_ml_risk_2018_2020_r1/output_sha256.json',
            OLD/'output_sha256.json']


def verify_prior():
    counts = {}
    for manifest in old_manifests():
        files = json.loads(manifest.read_text(encoding='utf-8'))
        for name, expected in files.items():
            if sha(manifest.parent/name) != expected:
                raise RuntimeError('Prior artifact changed: '+str(manifest.parent/name))
        counts[manifest.parent.name] = len(files)
    return counts


def verify_inputs(protocol):
    for name, expected in protocol['inputs'].items():
        if sha(ROOT/name) != expected:
            raise RuntimeError('Frozen input changed: '+name)
    for name, expected in protocol['external_inputs'].items():
        if sha(Path(name)) != expected:
            raise RuntimeError('Frozen external source changed: '+name)
    if {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')} != protocol['source_sha256']:
        raise RuntimeError('Frozen core changed')
    for name, expected in protocol['prior_artifact_manifests'].items():
        if sha(ROOT/name) != expected:
            raise RuntimeError('Prior manifest changed: '+name)
    return verify_prior()


def schedule_and_calendar():
    full = pd.read_csv(DATA/'calendar.csv', dtype={'cal_date':str})
    full = pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    calendar = full[(full>='2015-11-01') & (full<='2020-12-31')]
    schedule = weekly_schedule(full[full>='2015-11-01'])
    schedule = schedule.loc[schedule.execution_date.between('2018-01-01','2020-12-31')].reset_index(drop=True)
    return calendar, schedule


def prepare():
    if (OUT/'frozen_protocol.json').exists():
        raise RuntimeError('Existing preparation attempt: inspect, do not overwrite')
    previous = verify_prior()
    prior = json.loads((LABEL/'frozen_protocol.json').read_text(encoding='utf-8'))
    core = {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}
    if core != prior['source_sha256']:
        raise RuntimeError('Core differs from frozen original')
    data_manifest = json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    for name, expected in data_manifest['files_sha256'].items():
        if sha(DATA/name) != expected:
            raise RuntimeError('Frozen data changed: '+name)
    sources = [SPEC, PLAN, ROOT/'docs/2026-10-15-paper-reproduction-selection.md',
               Path(__file__), ROOT/'scripts/alphaforge_case_factor.py',
               ROOT/'scripts/alphaforge_case_diagnostics.py', ROOT/'scripts/verify_alphaforge_case.py',
               ROOT/'scripts/run_retention_development.py', ROOT/'scripts/run_ml_risk.py',
               ROOT/'scripts/retention_selector.py', ROOT/'scripts/audit_continuous_flows.py']
    sources += sorted((ROOT/'tests').glob('test_alphaforge_case*.py'))
    inputs = sources + [OLD/'common_samples.csv', OLD/'frozen_protocol.json',
                        LABEL/'frozen_protocol.json', DATA/'manifest.json', SOURCE/'unexplained_adjustments.csv']
    inputs += [DATA/name for name in data_manifest['files_sha256']]
    inputs += [ROOT/'data/audit'/name for name in prior['metadata_sha256']]
    for name, expected in prior['metadata_sha256'].items():
        if sha(ROOT/'data/audit'/name) != expected:
            raise RuntimeError('Frozen metadata changed: '+name)
    external = [PAPER/'AlphaForge-2406.18394v5.pdf', PAPER/'alphagen__data__expression.py',
                PAPER/'alphagen_qlib__stock_data.py', PAPER/'manifest.json']
    protocol = dict(primary=PATHS[0], paths=PATHS, costs=[0,10,30], initial_cash=1000000,
        evaluation_start='2018-01-01', evaluation_end='2020-12-31', window=10,
        input_close='raw CNY', input_volume='raw vol lots * 100 shares',
        adjustment_policy='exclude any adjustment-factor change within the ten observations',
        primary_signal='negative published signed-log correlation, fixed before outcomes',
        epsilon=1e-6, minimum_formed_per_date=200, financial_fields_consumed=False,
        approval='Human: 好的，你一直去运行 after single-case scope on2026-10-15',
        versions=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__),
        source_sha256=core, inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs},
        external_inputs={str(p):sha(p) for p in external},
        prior_artifact_manifests={str(p.relative_to(ROOT)):sha(p) for p in old_manifests()},
        prior_artifacts_verified=previous, scope='Retrospective local adaptation, not whole AlphaForge reproduction')
    persist('frozen_protocol.json',protocol)
    snapshot = OUT/'source_before'; snapshot.mkdir()
    for p in sources + list((ROOT/'quant_research').glob('*.py')):
        shutil.copy2(p,snapshot/p.name)
    calendar,schedule = schedule_and_calendar()
    schedule.to_csv(OUT/'schedule.csv',index=False)
    columns = ['trade_date','ts_code','industry','D_label','D_valid','D_end','reference_end',*FACTORS]
    base = pd.read_csv(OLD/'common_samples.csv', usecols=columns,
                       parse_dates=['trade_date','D_end','reference_end'],float_precision='round_trip')
    base = base.loc[base.trade_date.isin(schedule.signal_date)].copy()
    if base.duplicated(['trade_date','ts_code']).any():
        raise RuntimeError('Duplicate original common200 record')
    codes = set(base.ts_code)
    persist('preparation_status.json',dict(state='quotes',pid=os.getpid(),codes=len(codes)))
    print('Read frozen common200 and past quotes',flush=True)
    bars = read_subset('daily',codes).merge(read_subset('adj_factor',codes),
                    on=['ts_code','trade_date'],validate='one_to_one')
    bars = bars.loc[bars.trade_date.isin(calendar)].copy()
    bars,corrections = correct_adjustments(bars)
    dates = {c:sorted(g.trade_date) for c,g in base.groupby('ts_code')}
    parts=[]; precision=[]
    for i,(code,group) in enumerate(bars.groupby('ts_code',sort=True)):
        f=compute_asset(group,calendar,dates[code]);f['ts_code']=code;parts.append(f)
        # Deterministic first valid window per code, chosen without outcomes.
        first=f.loc[f.case_valid].head(1)
        if len(first):
            d=first.iloc[0].trade_date;pos=calendar.get_loc(d)
            q=group.set_index('trade_date').reindex(calendar).iloc[pos-9:pos+1]
            c=q.close.to_numpy();v=q.vol.to_numpy()*100
            a=formula_10(c,v,dtype=np.float64);b=formula_10(c,v,dtype=np.float32)
            precision.append(dict(ts_code=code,trade_date=d,factor64=a['factor'],factor32=b['factor'],
                                  absolute_difference=abs(a['factor']-b['factor']),
                                  guard64=a['guard'],guard32=b['guard']))
        if (i+1)%500==0:
            print('Prepared assets',i+1,flush=True)
    features=pd.concat(parts,ignore_index=True).rename(columns={
        'factor':'case_factor','signal':'case_signal','rho':'case_rho','guard':'case_guard',
        'nlvar':'case_nlvar','nrvar':'case_nrvar'})
    coverage=base.merge(features,on=['trade_date','ts_code'],how='left',validate='one_to_one')
    if len(coverage)!=len(base) or coverage.case_valid.isna().any():
        raise RuntimeError('Incomplete factor alignment')
    coverage.to_csv(OUT/'feature_coverage.csv',index=False)
    common=coverage.loc[coverage.case_valid].copy()
    counts=common.groupby('trade_date').size().reindex(schedule.signal_date,fill_value=0)
    if counts.min()<200:
        raise RuntimeError('Fewer than 200 formed stocks: '+str(counts[counts<200].to_dict()))
    scores=rank_scores(common[['trade_date','ts_code','industry',*FACTORS]],FACTORS)
    common=common.merge(scores[['trade_date','ts_code','score']].rename(columns={'score':'three_score'}),
                        on=['trade_date','ts_code'],validate='one_to_one')
    common.to_csv(OUT/'common_samples.csv',index=False)
    pd.DataFrame(precision).to_csv(OUT/'float_precision_audit.csv',index=False)
    ic,groups=diagnostics(common,schedule)
    ic.to_csv(OUT/'factor_ic.csv',index=False);groups.to_csv(OUT/'factor_groups.csv',index=False)
    ic_summary=summarize_ic(ic)
    if isinstance(ic_summary,pd.DataFrame):
        ic_summary.to_csv(OUT/'factor_ic_summary.csv',index=False)
    else:
        persist('factor_ic_summary.json',ic_summary)
    plans={p:[] for p in PATHS};previous={p:set() for p in PATHS};events_all=[]
    for row in schedule.itertuples(index=False):
        frame=common.loc[common.trade_date.eq(row.signal_date)]
        for path,factor in [(PATHS[0],'case_signal'),(PATHS[1],'three_score')]:
            s=frame[['trade_date','ts_code','industry']].copy()
            s['score']=frame[factor].rank(method='average',pct=True) if path==PATHS[0] else frame[factor]
            target,events=select_retention(s,previous[path]);previous[path]=set(target.ts_code)
            if target.empty:raise RuntimeError('Empty target '+path)
            target['signal_date']=row.signal_date;target['execution_date']=row.execution_date
            plans[path].append(target);events['path']=path;events['signal_date']=row.signal_date;events_all.append(events)
    for path,rows in plans.items():
        pd.concat(rows,ignore_index=True).to_csv(OUT/f'targets_{path}.csv',index=False)
    pd.concat(events_all,ignore_index=True).to_csv(OUT/'selection_events.csv',index=False)
    persist('feature_summary.json',dict(original_rows=len(base),common_rows=len(common),
        minimum_formed=int(counts.min()),schedule_rows=len(schedule),reasons=coverage.reason.value_counts().to_dict(),
        guard_rows=int(common.case_guard.sum()),adjustment_corrections=corrections,
        precision_windows=len(precision),maximum_float_precision_difference=max(x['absolute_difference'] for x in precision)))
    verify_inputs(protocol)
    persist('preparation_status.json',dict(state='completed',pid=os.getpid(),common_rows=len(common),models_started=False))
    files={p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='runner.lock'}
    persist('preparation_sha256.json',files)
    print('Preparation complete:',len(common),'rows /',len(schedule),'weeks',flush=True)


def accounts():
    if (OUT/'experiment_protocol.json').exists():
        raise RuntimeError('Existing account attempt: inspect, do not overwrite')
    prepared=json.loads((OUT/'preparation_status.json').read_text(encoding='utf-8'))
    if prepared['state']!='completed':raise RuntimeError('Preparation incomplete')
    protocol=json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'))
    verify_inputs(protocol)
    for name,expected in json.loads((OUT/'preparation_sha256.json').read_text(encoding='utf-8')).items():
        if sha(OUT/name)!=expected:raise RuntimeError('Prepared artifact changed: '+name)
    expected=json.loads((LABEL/'frozen_protocol.json').read_text(encoding='utf-8'))['inputs']['scripts\\run_ml_risk.py']
    if sha(Path(original.__file__))!=expected:raise RuntimeError('Original account adapter changed')
    source=Path(original.__file__).read_text(encoding='utf-8')
    block=source[source.index('    all_codes=set().union'):source.index('    return int(any(s[')]
    block='\n'.join(line[4:] if line.startswith('    ') else line for line in block.splitlines())
    (OUT/'simulation_adapter_block.py.txt').write_text(block,encoding='utf-8')
    persist('experiment_protocol.json',dict(paths=PATHS,primary=PATHS[0],costs=[0,10,30],
        runner_sha256=sha(Path(__file__)),adapter_sha256=sha(OUT/'simulation_adapter_block.py.txt')))
    calendar,schedule=schedule_and_calendar()
    targets={p:pd.read_csv(OUT/f'targets_{p}.csv',parse_dates=['trade_date','signal_date','execution_date'],
                          float_precision='round_trip') for p in PATHS}
    codes=set().union(*(set(t.ts_code) for t in targets.values()))
    bars=read_subset('daily',codes).merge(read_subset('adj_factor',codes),on=['trade_date','ts_code'],validate='one_to_one')
    bars=bars.loc[bars.trade_date.isin(calendar)].copy()
    bars,adjustment_corrections=correct_adjustments(bars)
    metadata=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    sectors=pd.read_csv(ROOT/'data/audit/industry_history.csv',dtype=str)
    core=protocol['source_sha256']
    persist('experiment_stage.json',dict(state='accounts',pid=os.getpid(),expected_accounts=6))
    namespace=dict(vars(original));namespace.update(locals());namespace.update(OUT=OUT,PATHS=PATHS,persist=persist)
    exec(compile(block,str(Path(original.__file__))+'#frozen_account_adapter','exec'),namespace)
    statuses=namespace['statuses'];failed=any(s['status']!='completed' for s in statuses)
    verify_inputs(protocol)
    persist('experiment_stage.json',dict(state='failed' if failed else 'completed',pid=os.getpid(),
                                        accounts=len(statuses),independent_verification_pending=True))
    if failed:raise RuntimeError('One or more accounts failed; original failure logs retained')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['prepare','accounts','all'],default='all')
    args=parser.parse_args();OUT.mkdir(exist_ok=True)
    if shutil.disk_usage(OUT.resolve()).free<6*1024**3:raise RuntimeError('6GiB disk floor reached')
    lock=OUT/'runner.lock'
    with lock.open('x',encoding='utf-8') as stream:json.dump(dict(pid=os.getpid(),stage=args.stage),stream)
    try:
        if args.stage in ('prepare','all'):prepare()
        if args.stage in ('accounts','all'):accounts()
    except Exception:
        name=f'failure_{args.stage}_{pd.Timestamp.now():%Y%m%dT%H%M%S}.txt'
        (OUT/name).write_text(traceback.format_exc(),encoding='utf-8')
        persist('last_failure.json',dict(stage=args.stage,pid=os.getpid(),failure=name))
        raise
    finally:lock.unlink()


if __name__=='__main__':main()
