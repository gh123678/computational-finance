"""Approved fixed-key reference-price study; never edit or restart frozen runs."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import traceback

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_retention_development import DATA, SOURCE, read_subset, sha
import run_alphaforge_case as r1
import run_alphaforge_r2 as r2
from alphaforge_case_factor import _evaluate
from alphaforge_case_diagnostics import diagnostics, summarize_ic
from quant_research.accounting import normalize_actions
from quant_research.backtest import Config, summarize
from quant_research.continuous import relevant_actions
from quant_research.corporate_corrections import correct_actions, correct_limit_code_aliases
from quant_research.factors import FACTORS, rank_scores, weekly_schedule
from quant_research.rights import verified_rights
from quant_research.attribution import monthly_returns, cost_breakdown
from retention_selector import select_retention

OUT = ROOT/'output/alphaforge_case_2018_2020_r3'
R2 = ROOT/'output/alphaforge_case_2018_2020_r2'
DECISION = ROOT/'output/alphaforge_000998_revision_decision_20261016_r1'
SPEC = ROOT/'docs/superpowers/specs/2026-10-16-alphaforge-reference-r3-design.md'
PLAN = ROOT/'docs/superpowers/plans/2026-10-17-alphaforge-r3-implementation.md'
PATHS = r1.PATHS


def persist(name, value):
    path = OUT/name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def old_manifests():
    return [*r2.old_manifests(), R2/'output_sha256.json',
            ROOT/'output/alphaforge_000998_crosscheck_20261016_r1/output_sha256.json',
            DECISION/'output_sha256.json']


def verify_prior():
    entries = []
    for path in old_manifests():
        files = json.loads(path.read_text(encoding='utf-8'))
        for name, expected in files.items():
            if sha(path.parent/name) != expected:
                raise RuntimeError('Protected artifact changed: '+str(path.parent/name))
        entries.append(dict(path=str(path), sha256=sha(path), count=len(files)))
    if sum(x['count'] for x in entries) != 1924:
        raise RuntimeError('Protected artifact scope changed')
    return entries


def check_disk():
    for path in [ROOT, OUT.resolve()]:
        if shutil.disk_usage(path).free < 6*1024**3:
            raise RuntimeError('6GiB disk floor: '+str(path))


def verify_inputs(protocol):
    for name, expected in protocol['inputs'].items():
        if sha(ROOT/name) != expected:
            raise RuntimeError('Frozen input changed: '+name)
    for name, expected in protocol['external_inputs'].items():
        if sha(Path(name)) != expected:
            raise RuntimeError('External frozen input changed: '+name)
    core = {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}
    if core != protocol['source_sha256']:
        raise RuntimeError('Original core changed')
    for record in protocol['prior_artifact_manifests']:
        if sha(Path(record['path'])) != record['sha256']:
            raise RuntimeError('Protected manifest changed')


def verify_artifacts(name):
    for path, expected in json.loads((OUT/name).read_text(encoding='utf-8')).items():
        if sha(OUT/path) != expected:
            raise RuntimeError('Stage artifact changed: '+path)


def calendars():
    frame = pd.read_csv(DATA/'calendar.csv', dtype={'cal_date':str})
    full = pd.DatetimeIndex(pd.to_datetime(frame.loc[frame.is_open.eq(1), 'cal_date'])).sort_values()
    calendar = full[(full >= '2015-11-01') & (full <= '2020-12-31')]
    schedule = weekly_schedule(full[full >= '2015-11-01'])
    schedule['next_execution'] = schedule.execution_date.shift(-1)
    schedule = schedule.loc[schedule.execution_date.between('2018-01-01', '2020-12-31')].reset_index(drop=True)
    assert len(schedule) == 154
    return full, calendar, calendar[calendar >= '2017-10-01'], schedule


def load_raw(codes):
    """Same numeric CSV parsing as r2; preserve untouched reference lexemes."""
    columns = ['ts_code','trade_date','open','high','low','close','pre_close','vol','amount']
    pieces = []
    for chunk in pd.read_csv(DATA/'daily.csv', usecols=columns,
            dtype={'ts_code':str,'trade_date':str}, converters={'close':str,'pre_close':str},
            chunksize=150000):
        part = chunk.loc[chunk.ts_code.isin(codes) & chunk.trade_date.between('20151101','20201231')].copy()
        if part.empty:
            continue
        part['close_text'] = part.close.astype('string')
        part['pre_close_text'] = part.pre_close.astype('string')
        part['close'] = pd.to_numeric(part.close, errors='coerce')
        part['pre_close'] = pd.to_numeric(part.pre_close, errors='coerce')
        part['trade_date'] = pd.to_datetime(part.trade_date, format='%Y%m%d')
        pieces.append(part)
    result = pd.concat(pieces, ignore_index=True)
    if result.duplicated(['ts_code','trade_date']).any():
        raise RuntimeError('Duplicate raw quote')
    return result


def action_inputs(bars):
    raw = pd.read_csv(DATA/'dividend.csv', dtype=str)
    corrected, corrections = correct_actions(raw)
    corrected, ignored = relevant_actions(corrected, bars)
    corrected = corrected.loc[pd.to_datetime(corrected.ex_date).le(pd.Timestamp('20201231'))]
    actions = normalize_actions(corrected, set(bars.ts_code))
    rights = [r for r in verified_rights() if r.code in set(bars.ts_code) and r.ex <= pd.Timestamp('20201231')]
    return actions, rights, ignored, corrections


def freeze():
    if (OUT/'frozen_protocol.json').exists():
        raise RuntimeError('Existing r3 preparation; inspect rather than restart')
    prior = verify_prior()
    previous_protocol = json.loads((R2/'frozen_protocol.json').read_text(encoding='utf-8'))
    r2.verify_inputs(previous_protocol)
    sources = [Path(__file__), SPEC, PLAN,
        *sorted((ROOT/'scripts').glob('alphaforge_r3_*.py')),
        ROOT/'scripts/verify_alphaforge_r3.py', ROOT/'scripts/report_alphaforge_r3.py',
        *sorted((ROOT/'tests').glob('test_alphaforge_r3*.py')),
        ROOT/'scripts/alphaforge_case_factor.py', ROOT/'scripts/alphaforge_case_diagnostics.py',
        ROOT/'scripts/alphaforge_case_r2_features.py',
        ROOT/'scripts/alphaforge_r2_events.py', ROOT/'scripts/retention_selector.py',
        ROOT/'scripts/run_retention_development.py', ROOT/'scripts/run_alphaforge_case.py',
        ROOT/'scripts/run_alphaforge_r2.py', ROOT/'scripts/verify_alphaforge_case.py']
    sources = list(dict.fromkeys([*sources, *[ROOT/p for p in previous_protocol['inputs'] if Path(p).suffix == '.py']]))
    data_files = [DATA/name for name in json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))['files_sha256']]
    inputs = list(dict.fromkeys([*sources, DATA/'manifest.json', *data_files,
        *[ROOT/'data/audit'/name for name in ['universe.csv','industry_history.csv','name_history.csv']],
        R2/'common_samples.csv', R2/'events.csv', *[R2/f'targets_{p}.csv' for p in PATHS],
        SOURCE/'unexplained_adjustments.csv']))
    protocol = dict(approval='Human 继续 on2026-10-17 after explicit r3 design and approval question',
        scope='Conditional retrospective reference-price study; not corrected vendor factors or unseen holdout',
        fixed_keys=273794, periods=154, minimum_formed=200, primary=PATHS[0], paths=PATHS,
        costs=[0,10,30], initial_cash=1000000, window=10, epsilon=1e-6,
        source_sha256={p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')},
        inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs}, external_inputs={},
        prior_artifact_manifests=prior, label='R_week', legacy_pool_indirect_adjustment_dependency=True,
        old_primary_values_used_only_for_comparison=True, fundamental_signals_consumed=False,
        event_versions='r2 evidence rows; economic actions normalized and deduplicated by immutable core',
        live_enablement=False, versions=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__))
    persist('frozen_protocol.json', protocol)
    snapshot = OUT/'source_before'; snapshot.mkdir()
    for p in [*sources, *sorted((ROOT/'quant_research').glob('*.py'))]:
        folder = snapshot/('tests' if p.parent.name == 'tests' else 'core' if p.parent.name == 'quant_research' else 'source')
        folder.mkdir(exist_ok=True)
        shutil.copy2(p, folder/p.name)
    return protocol


def primary_formula(group, calendar, dates):
    """Keep r2 vector reduction layout using an unused real raw amount column."""
    g = group.set_index('trade_date').reindex(calendar)
    data = g[['close','vol','amount']].to_numpy(float)
    windows = []
    for date in dates:
        position = calendar.get_loc(date)
        values = data[position-9:position+1]
        if len(values) != 10 or not np.isfinite(values[:,:2]).all() or not (values[:,:2] > 0).all():
            raise RuntimeError('Fixed primary window missing: '+str(date))
        windows.append(values)
    values = _evaluate(np.asarray(windows)[:,:,0], np.asarray(windows)[:,:,1]*100.)
    result = pd.DataFrame({'trade_date':dates})
    for name, value in values.items():
        result['case_'+name] = value
    return result


def prepare():
    from alphaforge_r3_reference import compute_reference_windows, weekly_reference_labels
    protocol = freeze()
    _, calendar, _, schedule = calendars()
    schedule.to_csv(OUT/'schedule.csv', index=False)
    base = pd.read_csv(R2/'common_samples.csv', usecols=['trade_date','ts_code','industry'], parse_dates=['trade_date'])
    assert len(base) == 273794 and not base.duplicated(['trade_date','ts_code']).any()
    persist('preparation_status.json', dict(state='quotes',pid=os.getpid(),fixed_keys=len(base)))
    print('r3 loading raw quotes; no adjustment factors consumed', flush=True)
    bars = load_raw(set(base.ts_code))
    bars.to_csv(OUT/'raw_bars.csv', index=False)
    actions, rights, ignored, corrections = action_inputs(bars)
    ignored.to_csv(OUT/'unowned_actions.csv', index=False)
    persist('action_input_summary.json', dict(normalized_actions=len(actions),rights=len(rights),corrections=corrections))
    events = pd.read_csv(R2/'events.csv', parse_dates=['event_date','known_date'])
    if not set(events.timing_verified.dropna().unique()).issubset({True,False}):
        raise RuntimeError('Event Boolean parsing failed')
    events['conflict'] = False  # normalize_actions above rejects contradictory same-code/ex terms.
    events.to_csv(OUT/'events.csv', index=False)
    benchmark = pd.read_csv(DATA/'benchmark.csv', parse_dates=['trade_date']).set_index('trade_date').open
    by_code = {c:g for c,g in events.groupby('code')}
    dates = {c:sorted(g.trade_date) for c,g in base.groupby('ts_code')}
    features, labels, cases = [], [], []
    for i,(code,group) in enumerate(bars.groupby('ts_code', sort=True)):
        event = by_code.get(code, events.iloc[:0])
        q=group.set_index('trade_date').reindex(calendar)
        fields=q[['open','high','low','close','vol','amount']].to_numpy(float)
        complete=pd.Series(np.isfinite(fields).all(axis=1)&(fields>0).all(axis=1),index=calendar).rolling(21,min_periods=21).sum()
        if not complete.loc[dates[code]].eq(21).all():
            raise RuntimeError('Fixed 21-quote raw completeness failed: '+code)
        features.append(compute_reference_windows(group,calendar,dates[code],event))
        lab = weekly_reference_labels(group,calendar,schedule,benchmark,event)
        labels.append(lab.loc[lab.signal_date.isin(dates[code])])
        case = primary_formula(group,calendar,dates[code]);case['ts_code']=code;cases.append(case)
        if (i+1)%250 == 0:
            print('r3 reference assets',i+1,flush=True)
            persist('preparation_status.json',dict(state='features',pid=os.getpid(),completed_assets=i+1))
    windows = pd.concat(features, ignore_index=True)
    label = pd.concat(labels, ignore_index=True)
    windows.to_csv(OUT/'reference_windows.csv',index=False)
    label.to_csv(OUT/'reference_labels.csv',index=False)
    common = base.merge(windows,on=['trade_date','ts_code'],validate='one_to_one')
    if len(common) != len(base) or not common.reference_valid.eq(True).all():
        persist('preparation_connection_failure.json',dict(rows=len(common),expected=len(base),
            reasons=common.loc[~common.reference_valid.eq(True),'reason'].value_counts().to_dict()))
        raise RuntimeError('Fixed keys fail complete reference window; no keys removed')
    common = common.merge(pd.concat(cases,ignore_index=True),on=['trade_date','ts_code'],validate='one_to_one')
    common = common.merge(label[['signal_date','ts_code','R_week','R_valid','R_end','R_reason']].rename(
        columns={'signal_date':'trade_date'}),on=['trade_date','ts_code'],validate='one_to_one')
    common['primary_score'] = common.groupby('trade_date').case_signal.rank(method='average',pct=True)
    ranked = rank_scores(common[['trade_date','ts_code','industry',*FACTORS]],FACTORS)
    common = common.merge(ranked[['trade_date','ts_code','score']].rename(columns={'score':'three_score'}),on=['trade_date','ts_code'],validate='one_to_one')
    if len(common) != 273794 or common.groupby('trade_date').size().min() < 200:
        raise RuntimeError('Fixed same-pool coverage changed')
    old = pd.read_csv(R2/'common_samples.csv', usecols=['trade_date','ts_code','case_factor','case_signal'],parse_dates=['trade_date'],float_precision='round_trip')
    comparison = common.merge(old,on=['trade_date','ts_code'],suffixes=('','_r2'),validate='one_to_one')
    for name in ['case_factor','case_signal']:
        if not np.array_equal(comparison[name].to_numpy(),comparison[name+'_r2'].to_numpy()):
            raise RuntimeError('Strict r2 primary value mismatch: '+name)
    previous_pct=comparison.groupby('trade_date').case_signal_r2.rank(method='average',pct=True)
    if not np.array_equal(comparison.primary_score.to_numpy(),previous_pct.to_numpy()):
        raise RuntimeError('Strict r2 primary percentile mismatch')
    previous = {p:set() for p in PATHS};plans={p:[] for p in PATHS};selection=[]
    for row in schedule.itertuples(index=False):
        frame=common.loc[common.trade_date.eq(row.signal_date)]
        for path,value in zip(PATHS,['primary_score','three_score']):
            scores=frame[['trade_date','ts_code','industry']].copy();scores['score']=frame[value]
            target,log=select_retention(scores,previous[path]);previous[path]=set(target.ts_code)
            target['signal_date']=row.signal_date;target['execution_date']=row.execution_date;plans[path].append(target)
            log['path']=path;log['signal_date']=row.signal_date;selection.append(log)
    for path,pieces in plans.items():
        target=pd.concat(pieces,ignore_index=True)
        if path==PATHS[0]:
            old=pd.read_csv(R2/f'targets_{path}.csv',parse_dates=['trade_date','signal_date','execution_date'],float_precision='round_trip')
            keys=['signal_date','execution_date','ts_code'];fields=keys+['industry','target_weight','score']
            pd.testing.assert_frame_equal(target[fields].sort_values(keys).reset_index(drop=True),old[fields].sort_values(keys).reset_index(drop=True),check_exact=True)
        target.to_csv(OUT/f'targets_{path}.csv',index=False)
    pd.concat(selection,ignore_index=True).to_csv(OUT/'selection_events.csv',index=False)
    common.to_csv(OUT/'common_samples.csv',index=False)
    memory=common.rename(columns={'R_week':'D_label','R_valid':'D_valid'})
    ic,groups=diagnostics(memory,schedule)
    ic['label_definition']='R_week';groups['label_definition']='R_week'
    ic.to_csv(OUT/'factor_ic.csv',index=False);groups.to_csv(OUT/'factor_groups.csv',index=False)
    summarize_ic(ic).to_csv(OUT/'factor_ic_summary.csv',index=False)
    persist('primary_invariance.json',dict(status='passed',formula_exact=True,percentiles_exact=True,
        primary_targets_exact=True,fixed_keys=273794,diagnostics_internal_alias='R_week->D_label only in memory, never old D values'))
    verify_inputs(protocol)
    persist('preparation_status.json',dict(state='completed',pid=os.getpid(),fixed_keys=len(common),accounts_started=0))
    persist('preparation_sha256.json',{p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='runner.lock'})


def read_prepared_bars():
    return pd.read_csv(OUT/'raw_bars.csv',parse_dates=['trade_date'],
        converters={'close_text':str,'pre_close_text':str},float_precision='round_trip')


def precheck():
    from alphaforge_r3_guard import audit_reference_guard
    protocol=json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'));verify_inputs(protocol)
    if (OUT/'guard_summary.json').exists():raise RuntimeError('Existing r3 precheck, do not repeat')
    if json.loads((OUT/'preparation_audit.json').read_text(encoding='utf-8'))['status']!='passed':
        raise RuntimeError('Independent preparation audit required')
    verify_artifacts('preparation_sha256.json')
    full,_,simulation,_=calendars();bars=read_prepared_bars();codes=set(bars.ts_code)
    actions,rights,_,_=action_inputs(bars)
    universe=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    suspension=pd.read_csv(DATA/'suspend_d.csv',dtype=str)
    seed_day=full[full<simulation[0]][-1];seed=bars.loc[bars.trade_date.eq(seed_day)]
    print('r3 full-domain guard precheck; no returns/accounts',flush=True)
    result=audit_reference_guard(bars.loc[bars.trade_date.isin(simulation)],simulation,universe,actions,suspension,rights,
        codes=codes,seed_bars=seed,full_calendar=full,source_hashes={'dividend':sha(DATA/'dividend.csv'),'rights':sha(ROOT/'quant_research/rights.py')})
    for key,name in [('daily','guard_daily.csv'),('failures','guard_failures.csv'),
                     ('adjustment_alerts','guard_adjustment_alerts.csv'),('event_registry','event_registry.csv')]:
        result[key].to_csv(OUT/name,index=False)
    legacy=pd.read_csv(SOURCE/'unexplained_adjustments.csv')
    legacy=legacy.loc[legacy.ts_code.isin(codes)&pd.to_datetime(legacy.trade_date).between(simulation.min(),simulation.max())]
    legacy.to_csv(OUT/'legacy_adjustment_alerts.csv',index=False)
    persist('guard_summary.json',result['summary']);verify_inputs(protocol)
    persist('guard_sha256.json',{name:sha(OUT/name) for name in ['guard_daily.csv','guard_failures.csv',
        'guard_adjustment_alerts.csv','event_registry.csv','legacy_adjustment_alerts.csv','guard_summary.json','preparation_audit.json']})
    persist('experiment_stage.json',dict(state='precheck_passed' if result['summary']['passed'] else 'blocked_guard',accounts_started=0))
    if not result['summary']['passed']:raise RuntimeError('Reference guard data gate failed; no accounts started')


def accounts():
    from alphaforge_r3_account import simulate_reference
    protocol=json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'));verify_inputs(protocol)
    if (OUT/'experiment_protocol.json').exists():raise RuntimeError('Existing r3 accounts, do not restart')
    for name in ['preparation_audit.json','guard_audit.json']:
        if json.loads((OUT/name).read_text(encoding='utf-8'))['status']!='passed':raise RuntimeError('Independent gate missing: '+name)
    if not json.loads((OUT/'guard_summary.json').read_text(encoding='utf-8'))['passed']:raise RuntimeError('Guard failed')
    verify_artifacts('preparation_sha256.json');verify_artifacts('guard_sha256.json')
    full,_,simulation,schedule=calendars();bars=read_prepared_bars()
    targets={p:pd.read_csv(OUT/f'targets_{p}.csv',parse_dates=['trade_date','signal_date','execution_date'],float_precision='round_trip') for p in PATHS}
    all_codes=set().union(*(set(t.ts_code) for t in targets.values()))
    actions,rights,_,corrections=action_inputs(bars)
    fixed_codes=set(bars.ts_code)
    limits,aliases=correct_limit_code_aliases(read_subset('stk_limit',fixed_codes|{'000043.SZ'}))
    bars=bars.merge(limits,on=['ts_code','trade_date'],how='left',validate='one_to_one')
    universe=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str);sectors=pd.read_csv(ROOT/'data/audit/industry_history.csv',dtype=str)
    industries={}
    for d in simulation:
        stamp=d.strftime('%Y%m%d');sector=sectors.loc[(sectors.in_date<=stamp)&(sectors.out_date.isna()|(sectors.out_date>stamp))]
        counts=sector.groupby('ts_code').l1_code.nunique();sector=sector.loc[sector.ts_code.isin(counts[counts==1].index)].drop_duplicates('ts_code')
        industries[d]=dict(zip(sector.ts_code,sector.l1_code))
    suspensions=pd.read_csv(DATA/'suspend_d.csv',dtype=str)
    delistings=dict(zip(universe.ts_code,pd.to_datetime(universe.delist_date)))
    seed=bars.loc[bars.trade_date.eq(full[full<simulation[0]][-1])]
    guard_cache=dict(summary=json.loads((OUT/'guard_summary.json').read_text(encoding='utf-8')),
        daily=pd.read_csv(OUT/'guard_daily.csv',parse_dates=['date','prior_quote_date']),
        failures=pd.read_csv(OUT/'guard_failures.csv'),
        adjustment_alerts=pd.read_csv(OUT/'guard_adjustment_alerts.csv'),
        event_registry=pd.read_csv(OUT/'event_registry.csv'))
    persist('experiment_protocol.json',dict(paths=PATHS,costs=[0,10,30],runner_sha256=sha(Path(__file__)),live_enablement=False))
    statuses=[];summaries=[]
    for path in PATHS:
        for bps in (10,0,30):
            label=f'{path}_{bps}bp';folder=OUT/label;folder.mkdir()
            targets[path].to_csv(folder/'historical_targets.csv',index=False)
            status=dict(strategy=label,path=path,slippage_bps=bps,status='running');statuses.append(status);persist('status.json',statuses)
            config=Config(slippage_bps=bps,zero_trading_costs=bps==0)
            print('r3 simulate',label,flush=True)
            try:
                run=simulate_reference(bars.loc[bars.trade_date.isin(simulation)],simulation,targets[path],actions,suspensions,delistings,industries,config,
                    rebalance_dates=schedule.execution_date.tolist(),rights=rights,universe=universe,seed_bars=seed,full_calendar=full,
                    source_hashes={'dividend':sha(DATA/'dividend.csv'),'rights':sha(ROOT/'quant_research/rights.py')},guard_audit=guard_cache)
                for name,frame in run.items():frame.to_csv(folder/f'{name}.csv',index=False)
                result=summarize(run['nav'],run['orders'],schedule.execution_date.iloc[0],pd.Timestamp('20180101'))
                result.update(strategy=label,path=path,config=asdict(config));summaries.append(result);status['status']='completed'
                monthly_returns(run['nav'].loc[run['nav'].date>=pd.Timestamp('20171229')].set_index('date').equity).to_csv(folder/'monthly_returns.csv')
                cost_breakdown(run['orders']).to_csv(folder/'cost_attribution.csv')
            except Exception as error:
                status.update(status='failed',error=str(error));(folder/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
            persist('status.json',statuses)
            persist('summary.json',dict(experiments=summaries,experiment_statuses=statuses,corrections=corrections+aliases,
                scope='Conditional retrospective R_week study; legacy pool dependency and unresolved data certification; live disabled'))
            verify_inputs(protocol)
    persist('experiment_stage.json',dict(state='completed' if all(s['status']=='completed' for s in statuses) else 'failed_accounts',accounts_started=len(statuses)))
    if any(s['status']!='completed' for s in statuses):raise RuntimeError('One or more r3 accounts failed; evidence retained')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['prepare','precheck','accounts'],required=True)
    args=parser.parse_args()
    if not OUT.is_dir():raise RuntimeError('Create dedicated D evidence junction before running')
    check_disk()
    lock=OUT/'runner.lock'
    with lock.open('x',encoding='utf-8') as stream:json.dump(dict(pid=os.getpid(),stage=args.stage),stream)
    try:
        {'prepare':prepare,'precheck':precheck,'accounts':accounts}[args.stage]()
    except Exception:
        name=f'failure_{args.stage}_{pd.Timestamp.now():%Y%m%dT%H%M%S}.txt'
        (OUT/name).write_text(traceback.format_exc(),encoding='utf-8')
        persist('last_failure.json',dict(stage=args.stage,pid=os.getpid(),failure=name))
        raise
    finally:
        lock.unlink()


if __name__=='__main__':main()
