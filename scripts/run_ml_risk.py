"""Approved 12-group price-volume learning and risk-budget experiment."""
import json
import platform
import shutil
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

import lightgbm
import numpy as np
import pandas as pd
import sklearn

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from quant_research.factors import FACTORS,rank_scores,select_targets,weekly_schedule
from quant_research.universe import historical_universe
from quant_research.backtest import Config,simulate,summarize
from quant_research.accounting import normalize_actions
from quant_research.continuous import relevant_actions
from quant_research.corporate_corrections import correct_actions,correct_adjustments,correct_limit_code_aliases
from quant_research.rights import verified_rights
from quant_research.attribution import monthly_returns,cost_breakdown
from run_retention_development import sha,read_subset,DATA,SOURCE
from retention_selector import select_retention
from ml_risk_features import FEATURES,compute_asset,matured_training
from ml_risk_model import PARAMETERS,fit_model,risk_scale

OUT=ROOT/'output/open_source_ml_risk_2018_2020_r1'
SPEC=ROOT/'docs/superpowers/specs/2026-10-06-open-source-ml-risk-design.md'
PATHS=['three_weekly','three_retention','ml_retention','ml_risk']


def persist(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'frozen_protocol.json').exists():
        raise RuntimeError('Study already prepared or attempted; inspect existing state before any retry')
    lock=OUT/'runner.lock'
    with lock.open('x',encoding='utf-8') as stream:
        stream.write(str(__file__))
    try:
        return run()
    except Exception:
        (OUT/'preparation_failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    finally:
        lock.unlink()


def run():
    assert lightgbm.__version__=='4.6.0'
    frozen=json.loads((SOURCE/'frozen_protocol.json').read_text(encoding='utf-8'))
    core={p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}
    assert core==frozen['source_sha256']
    manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files_sha256'].items():
        assert sha(DATA/name)==expected,name
    for name,expected in frozen['metadata_sha256'].items():
        assert sha(ROOT/'data/audit'/name)==expected,name
    paths=[SPEC,Path(__file__),ROOT/'scripts/ml_risk_features.py',ROOT/'scripts/ml_risk_model.py',
           ROOT/'scripts/retention_selector.py',ROOT/'scripts/run_retention_development.py',
           SOURCE/'unexplained_adjustments.csv',SOURCE/'factors.csv']
    protocol=dict(source_sha256=core,metadata_sha256=frozen['metadata_sha256'],
        data_manifest_sha256=sha(DATA/'manifest.json'),inputs={str(p.relative_to(ROOT)):sha(p) for p in paths},
        features=FEATURES,parameters=PARAMETERS,risk_budget=.15,label_sessions=20,
        evaluation=['20180101','20201231'],initial_cash=1000000,
        paths=PATHS,costs=[10,0,30],versions=dict(python=platform.python_version(),
          lightgbm=lightgbm.__version__,numpy=np.__version__,pandas=pd.__version__,sklearn=sklearn.__version__))
    persist('frozen_protocol.json',protocol)
    snapshot=OUT/'source_before';snapshot.mkdir()
    for p in (ROOT/'quant_research').glob('*.py'):
        shutil.copy2(p,snapshot/p.name)
    for p in paths[1:6]:
        shutil.copy2(p,snapshot/p.name)
    full=pd.read_csv(DATA/'calendar.csv',dtype={'cal_date':str})
    full_calendar=pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    calendar=full_calendar[(full_calendar>=pd.Timestamp('20151101'))&(full_calendar<=pd.Timestamp('20201231'))]
    original_schedule=weekly_schedule(full_calendar[full_calendar>=pd.Timestamp('20151101')])
    sample_schedule=original_schedule.loc[original_schedule.execution_date.between(pd.Timestamp('20160101'),pd.Timestamp('20201231'))]
    schedule=sample_schedule.loc[sample_schedule.execution_date>=pd.Timestamp('20180101')].reset_index(drop=True)
    dates=set(sample_schedule.signal_date)
    metadata=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    names=pd.read_csv(ROOT/'data/audit/name_history.csv',dtype=str)
    sectors=pd.read_csv(ROOT/'data/audit/industry_history.csv',dtype=str)
    codes=set(metadata.loc[metadata.ts_code.str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ)$'),'ts_code'])
    print('Loading fixed 2015-2020 mainboard price-volume history',flush=True)
    bars=read_subset('daily',codes)
    bars=bars.merge(read_subset('adj_factor',codes),on=['ts_code','trade_date'],validate='one_to_one')
    bars,adjustment_corrections=correct_adjustments(bars)
    assert np.isfinite(bars[['open','high','low','close','adj_factor','vol','amount']]).all().all()
    assert bars[['open','high','low','close','adj_factor']].gt(0).all().all()
    benchmark=pd.read_csv(DATA/'benchmark.csv',parse_dates=['trade_date']).set_index('trade_date').open
    assert not benchmark.index.duplicated().any()
    issues=pd.read_csv(SOURCE/'unexplained_adjustments.csv',parse_dates=['trade_date'])
    issues=issues.loc[issues.trade_date<=pd.Timestamp('20201231')]
    issue_dates={code:g.trade_date.tolist() for code,g in issues.groupby('ts_code')}
    parts=[];return_columns={}
    print('Computing 12 past-only features and future labels',flush=True)
    for i,(code,group) in enumerate(bars.groupby('ts_code',sort=True)):
        feature,returns=compute_asset(group,calendar,dates,benchmark,issue_dates.get(code,[]))
        feature['ts_code']=code;parts.append(feature);return_columns[code]=returns
        if (i+1)%500==0:
            print('Feature securities',i+1,flush=True)
    features=pd.concat(parts,ignore_index=True)
    # Values for the original factor baseline must match the already frozen factors.
    features['momentum20']=features.ret20
    features['reversal5']=-features.ret5
    features['lowvol20']=-features.vol20
    expected_parts=[]
    for chunk in pd.read_csv(SOURCE/'factors.csv',parse_dates=['trade_date'],chunksize=150000):
        expected_parts.append(chunk.loc[chunk.trade_date.isin(dates),['trade_date','ts_code',*FACTORS]])
    expected=pd.concat(expected_parts,ignore_index=True)
    joined=features.loc[features.feature_valid].merge(expected,on=['trade_date','ts_code'],suffixes=('','_source'),validate='one_to_one')
    for f in FACTORS:
        assert np.allclose(joined[f],joined[f+'_source'],rtol=0,atol=1e-12),f
    groups={d:g for d,g in features.groupby('trade_date')}
    eligible=[]
    for d in sorted(dates):
        available=historical_universe(d,metadata,names,sectors,full_calendar)
        frame=groups[d]
        frame=frame.loc[frame.feature_valid & frame.log_adv20.ge(np.log1p(20000000))]
        eligible.append(frame.merge(available[['ts_code','industry']],on='ts_code',validate='one_to_one'))
    samples=pd.concat(eligible,ignore_index=True).sort_values(['trade_date','ts_code']).reset_index(drop=True)
    samples.to_csv(OUT/'common_samples.csv',index=False)
    returns=pd.DataFrame(return_columns,index=calendar)
    del features,parts,return_columns,expected,expected_parts,joined
    groups={d:g for d,g in samples.groupby('trade_date')}
    model_root=OUT/'models';model_root.mkdir()
    models={};training_audit=[]
    for year in (2018,2019,2020):
        fit_date=schedule.loc[schedule.execution_date.dt.year.eq(year),'signal_date'].iloc[0]
        training=matured_training(samples,fit_date)
        print('Fit model',year,'samples',len(training),'cutoff',fit_date,flush=True)
        model=fit_model(training,FEATURES)
        model_path=model_root/f'model_{year}.txt'
        # Python handles Unicode paths; the native Windows filename API does not.
        model_path.write_text(model.booster_.model_to_string(),encoding='utf-8')
        models[year]=model
        training[['trade_date','ts_code','entry_date','label_end','label','sample_weight']].to_csv(model_root/f'training_{year}.csv',index=False)
        training_audit.append(dict(year=year,fit_date=fit_date.strftime('%Y-%m-%d'),samples=len(training),
            first_signal=training.trade_date.min().strftime('%Y-%m-%d'),
            last_signal=training.trade_date.max().strftime('%Y-%m-%d'),
            latest_label_end=training.label_end.max().strftime('%Y-%m-%d'),
            model_sha256=sha(model_path)))
    persist('training_audit.json',training_audit)
    plans={p:[] for p in PATHS};previous={p:set() for p in PATHS}
    predictions=[];selection_logs=[];risk_logs=[];ic=[];risk_cov={}
    for row in schedule.itertuples(index=False):
        d=row.signal_date;year=row.execution_date.year
        frame=groups[d].copy()
        assert frame[FEATURES].notna().all().all()
        model=models[year]
        frame['prediction']=model.predict(frame[FEATURES])
        assert np.isfinite(frame.prediction).all()
        frame['score']=frame.prediction.rank(method='average',pct=True)
        frame['execution_date']=row.execution_date;frame['model_year']=year
        predictions.append(frame[['trade_date','execution_date','ts_code','prediction','score','label','label_end','label_valid','model_year']])
        observed=frame.loc[frame.label_valid]
        rank_ic=observed.prediction.corr(observed.label,method='spearman') if len(observed)>1 else np.nan
        ic.append(dict(signal_date=d,execution_date=row.execution_date,year=year,eligible=len(frame),valid_labels=len(observed),rank_ic=rank_ic))
        original=rank_scores(frame,FACTORS)
        selected={}
        selected['three_weekly']=select_targets(original)
        for path,score_frame in [('three_retention',original),('ml_retention',frame)]:
            target,events=select_retention(score_frame,previous[path])
            events['path']=path;events['signal_date']=d;selection_logs.append(events)
            selected[path]=target
        selected['ml_risk']=selected['ml_retention'].copy()
        risk_target=selected['ml_risk']
        if risk_target.empty:
            raise ValueError(f'No eligible ML targets on {d}')
        position=calendar.get_loc(d)
        covariance_values=returns.loc[calendar[position-59:position+1],risk_target.ts_code].to_numpy()
        scale,sigma,covariance=risk_scale(covariance_values,risk_target.target_weight)
        covariance_path=OUT/f'covariance_{d.strftime("%Y%m%d")}.npy'
        np.save(covariance_path,covariance)
        risk_cov[covariance_path.name]=sha(covariance_path)
        risk_target['target_weight']*=scale
        risk_logs.append(dict(signal_date=d,execution_date=row.execution_date,forecast_volatility=sigma,
                              scale=scale,target_cash=1-risk_target.target_weight.sum(),
                              covariance_file=covariance_path.name,returns_start=calendar[position-59].strftime('%Y-%m-%d')))
        for path,target in selected.items():
            target=target.copy();target['signal_date']=d;target['execution_date']=row.execution_date
            plans[path].append(target);previous[path]=set(target.ts_code)
    targets={path:pd.concat(p,ignore_index=True) for path,p in plans.items()}
    pd.concat(predictions,ignore_index=True).to_csv(OUT/'predictions.csv',index=False)
    pd.concat(selection_logs,ignore_index=True).to_csv(OUT/'selection_events.csv',index=False)
    pd.DataFrame(risk_logs).to_csv(OUT/'risk_budget.csv',index=False)
    pd.DataFrame(ic).to_csv(OUT/'rank_ic.csv',index=False)
    persist('covariance_sha256.json',risk_cov)
    for path,target in targets.items():
        target.to_csv(OUT/f'targets_{path}.csv',index=False)
    all_codes=set().union(*(set(t.ts_code) for t in targets.values()))
    print('Targets ready',len(schedule),'dates, held universe',len(all_codes),flush=True)
    bars=bars.loc[bars.ts_code.isin(all_codes)].copy()
    simulation_calendar=calendar[calendar>=pd.Timestamp('20171001')]
    limits,aliases=correct_limit_code_aliases(read_subset('stk_limit',all_codes|{'000043.SZ'}))
    bars=bars.merge(limits,on=['ts_code','trade_date'],how='left',validate='one_to_one')
    assert bars[['up_limit','down_limit']].notna().all().all()
    dividends,action_corrections=correct_actions(pd.read_csv(DATA/'dividend.csv',dtype=str))
    dividends,ignored=relevant_actions(dividends,bars)
    ignored.to_csv(OUT/'unowned_actions.csv',index=False)
    actions=normalize_actions(dividends,set(bars.ts_code))
    suspension=pd.read_csv(DATA/'suspend_d.csv',dtype=str)
    suspension.trade_date=pd.to_datetime(suspension.trade_date)
    suspensions=set(suspension.loc[suspension.suspend_type.eq('S'),['trade_date','ts_code']].itertuples(index=False,name=None))
    delistings=dict(zip(metadata.ts_code,pd.to_datetime(metadata.delist_date)))
    industries={}
    for d in simulation_calendar:
        stamp=d.strftime('%Y%m%d')
        sector=sectors.loc[(sectors.in_date<=stamp)&(sectors.out_date.isna()|(sectors.out_date>stamp))]
        counts=sector.groupby('ts_code').l1_code.nunique()
        sector=sector.loc[sector.ts_code.isin(counts[counts==1].index)].drop_duplicates('ts_code')
        industries[d]=dict(zip(sector.ts_code,sector.l1_code))
    # Complete pre-2018 histories needed for features were retained above; the
    # simulation itself must contain only sessions in its explicit calendar.
    bars=bars.loc[bars.trade_date.isin(simulation_calendar)].copy()
    summaries=[];statuses=[]
    for path in PATHS:
        for bps in (10,0,30):
            label=f'{path}_{bps}bp';folder=OUT/label;folder.mkdir()
            targets[path].to_csv(folder/'historical_targets.csv',index=False)
            status=dict(strategy=label,path=path,slippage_bps=bps,status='running');statuses.append(status)
            persist('status.json',statuses)
            config=Config(slippage_bps=bps,zero_trading_costs=bps==0)
            print('Simulate',label,flush=True)
            try:
                assert {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}==core
                held_bars=bars.loc[bars.ts_code.isin(set(targets[path].ts_code))]
                run=simulate(held_bars,simulation_calendar,targets[path],actions,suspensions,delistings,industries,config,
                             rebalance_dates=schedule.execution_date.tolist(),rights=verified_rights())
                for name,frame in run.items():
                    frame.to_csv(folder/f'{name}.csv',index=False)
                result=summarize(run['nav'],run['orders'],schedule.execution_date.iloc[0],pd.Timestamp('20180101'))
                result.update(strategy=label,path=path,config=asdict(config));summaries.append(result)
                monthly_returns(run['nav'].loc[run['nav'].date>=pd.Timestamp('20171229')].set_index('date').equity).to_csv(folder/'monthly_returns.csv')
                cost_breakdown(run['orders']).to_csv(folder/'cost_attribution.csv')
                status['status']='completed'
            except Exception as error:
                status.update(status='failed',error=str(error))
                (folder/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
            persist('summary.json',dict(source_sha256=core,experiments=summaries,experiment_statuses=statuses,
                corrections=adjustment_corrections+aliases+action_corrections,scope='Opened historical exploratory walk-forward study'))
            persist('status.json',statuses)
            print(label,status['status'],flush=True)
    return int(any(s['status']!='completed' for s in statuses))


if __name__=='__main__':
    raise SystemExit(main())
