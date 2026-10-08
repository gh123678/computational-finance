"""Approved B/C/D fixed models and 18 new accounts; original study read-only."""
import json
import shutil
import traceback
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

import run_ml_risk as original
from run_retention_development import ROOT,DATA,SOURCE,sha,read_subset
from horizon_labels import asset_labels,training_samples
from ml_risk_features import FEATURES
from ml_risk_model import PARAMETERS,fit_model,risk_scale
from retention_selector import select_retention

OLD=original.OUT
OUT=ROOT/'output/label_horizon_coverage_2018_2020_r1'
SPEC=ROOT/'docs/superpowers/specs/2026-10-07-label-horizon-coverage-design.md'
PATHS=[f'{v}_{p}' for v in ('B','C','D') for p in ('retention','risk')]


def persist(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'frozen_protocol.json').exists():raise RuntimeError('Existing attempt: inspect before retry')
    lock=OUT/'runner.lock'
    with lock.open('x'):pass
    try:return run()
    except Exception:
        (OUT/'preparation_failure.txt').write_text(traceback.format_exc(),encoding='utf-8');raise
    finally:lock.unlink()


def run():
    assert lgb.__version__=='4.6.0'
    old_hashes=json.loads((OLD/'output_sha256.json').read_text(encoding='utf-8'))
    for n,h in old_hashes.items():assert sha(OLD/n)==h,n
    frozen=json.loads((OLD/'frozen_protocol.json').read_text(encoding='utf-8'))
    core={p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')};assert core==frozen['source_sha256']
    for n,h in json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))['files_sha256'].items():assert sha(DATA/n)==h,n
    for n,h in frozen['metadata_sha256'].items():assert sha(ROOT/'data/audit'/n)==h,n
    source=Path(original.__file__).read_text(encoding='utf-8')
    block=source[source.index('    all_codes=set().union'):source.index('    return int(any(s[')]
    block='\n'.join(line[4:] if line.startswith('    ') else line for line in block.splitlines())
    (OUT/'simulation_adapter_block.py.txt').write_text(block,encoding='utf-8')
    inputs=[SPEC,Path(__file__),ROOT/'scripts/horizon_labels.py',Path(original.__file__),
            ROOT/'scripts/ml_risk_model.py',ROOT/'scripts/retention_selector.py',SOURCE/'unexplained_adjustments.csv']
    protocol=dict(source_sha256=core,metadata_sha256=frozen['metadata_sha256'],data_manifest_sha256=sha(DATA/'manifest.json'),
        inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs},old_output_manifest_sha256=sha(OLD/'output_sha256.json'),
        old_hashes=old_hashes,simulation_block_sha256=sha(OUT/'simulation_adapter_block.py.txt'),
        paths=PATHS,parameters=PARAMETERS,primary='D_risk',evaluation=['20180101','20201231'],initial_cash=1000000,
        common_maturity='reference t+21 end strictly before fit date for all variants',lightgbm=lgb.__version__)
    persist('frozen_protocol.json',protocol)
    snap=OUT/'source_before';snap.mkdir()
    for p in inputs[:-1]:shutil.copy2(p,snap/p.name)
    for p in (ROOT/'quant_research').glob('*.py'):shutil.copy2(p,snap/p.name)
    full=pd.read_csv(DATA/'calendar.csv',dtype={'cal_date':str})
    full_calendar=pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    calendar=full_calendar[(full_calendar>=pd.Timestamp('20151101'))&(full_calendar<=pd.Timestamp('20201231'))]
    all_schedule=original.weekly_schedule(full_calendar[full_calendar>=pd.Timestamp('20151101')])
    all_schedule['next_execution']=all_schedule.execution_date.shift(-1)
    sample_schedule=all_schedule.loc[all_schedule.execution_date.between(pd.Timestamp('20160101'),pd.Timestamp('20201231'))]
    schedule=sample_schedule.loc[sample_schedule.execution_date>=pd.Timestamp('20180101')].reset_index(drop=True)
    samples=pd.read_csv(OLD/'common_samples.csv',parse_dates=['trade_date','entry_date','label_end'],float_precision='round_trip')
    codes=set(samples.ts_code)
    print('Load frozen common pool and corrected quotes',flush=True)
    bars=read_subset('daily',codes).merge(read_subset('adj_factor',codes),on=['ts_code','trade_date'],validate='one_to_one')
    bars,adjustment_corrections=original.correct_adjustments(bars)
    benchmark=pd.read_csv(DATA/'benchmark.csv',parse_dates=['trade_date']).set_index('trade_date').open
    issues=pd.read_csv(SOURCE/'unexplained_adjustments.csv',parse_dates=['trade_date'])
    issue_dates={c:g.trade_date.tolist() for c,g in issues.groupby('ts_code')}
    sample_dates={c:set(g.trade_date) for c,g in samples.groupby('ts_code')}
    compact=[];returns={};first=True
    for i,(code,g) in enumerate(bars.groupby('ts_code',sort=True)):
        selected_schedule=sample_schedule.loc[sample_schedule.signal_date.isin(sample_dates[code])]
        labels=asset_labels(g,calendar,selected_schedule,benchmark,issue_dates.get(code,[]));labels['ts_code']=code
        labels.to_csv(OUT/'label_audit.csv',mode='w' if first else 'a',header=first,index=False);first=False
        compact.append(labels[['trade_date','ts_code','variant','label','label_valid','label_end','reference_end']])
        quotes=g.set_index('trade_date').reindex(calendar)
        valid=np.isfinite(quotes[['open','high','low','close','adj_factor','vol','amount']]).all(axis=1)&quotes[['open','high','low','close','adj_factor','vol','amount']].gt(0).all(axis=1)
        returns[code]=(quotes.close*quotes.adj_factor).where(valid).pct_change(fill_method=None)
        if (i+1)%500==0:print('Label assets',i+1,flush=True)
    labels=pd.concat(compact,ignore_index=True)
    for v in ('A','B','C','D'):
        part=labels.loc[labels.variant.eq(v),['trade_date','ts_code','label','label_valid','label_end','reference_end']]
        renamed=part.rename(columns={'label':v+'_label','label_valid':v+'_valid','label_end':v+'_end'})
        if v!='A':renamed=renamed.drop(columns='reference_end')
        samples=samples.merge(renamed,on=['trade_date','ts_code'],validate='one_to_one')
    assert samples.A_valid.equals(samples.label_valid)
    assert np.allclose(samples.A_label,samples.label,rtol=0,atol=1e-12,equal_nan=True)
    assert samples.A_end.equals(samples.label_end)
    samples.to_csv(OUT/'common_samples.csv',index=False)
    del labels,compact
    returns=pd.DataFrame(returns,index=calendar)
    models={};training_audit=[];(OUT/'models').mkdir()
    old_training=json.loads((OLD/'training_audit.json').read_text(encoding='utf-8'))
    for year in (2018,2019,2020):
        fit_date=schedule.loc[schedule.execution_date.dt.year.eq(year),'signal_date'].iloc[0]
        a=training_samples(samples,'A',fit_date)
        old=pd.read_csv(OLD/f'models/training_{year}.csv',parse_dates=['trade_date','entry_date','label_end'],float_precision='round_trip')
        assert a[['trade_date','ts_code']].reset_index(drop=True).equals(old[['trade_date','ts_code']])
        assert np.allclose(a.label,old.label,rtol=0,atol=1e-12) and np.allclose(a.sample_weight,old.sample_weight,rtol=0,atol=1e-12)
        for v in ('B','C','D'):
            train=training_samples(samples,v,fit_date)
            print('Fit',v,year,len(train),'reference cutoff',fit_date,flush=True)
            model=fit_model(train,FEATURES);path=OUT/f'models/{v}_{year}.txt'
            path.write_text(model.booster_.model_to_string(),encoding='utf-8');models[v,year]=model
            train[['trade_date','ts_code','label','label_end','reference_end','sample_weight']].to_csv(OUT/f'models/training_{v}_{year}.csv',index=False)
            training_audit.append(dict(variant=v,year=year,fit_date=str(fit_date.date()),samples=len(train),
                old_A_samples=len(a),latest_label_end=str(train.label_end.max().date()),latest_reference_end=str(train.reference_end.max().date()),model_sha256=sha(path)))
    persist('training_audit.json',training_audit)
    plans={p:[] for p in PATHS};previous={v:set() for v in ('B','C','D')};predictions=[];ics=[];risk_logs=[];events_all=[];cov_hash={}
    groups={d:g for d,g in samples.groupby('trade_date')}
    for row in schedule.itertuples(index=False):
        d=row.signal_date;frame=groups[d]
        for v in ('B','C','D'):
            pred=models[v,row.execution_date.year].predict(frame[FEATURES]);assert np.isfinite(pred).all()
            scores=frame[['trade_date','ts_code','industry']].copy();scores['score']=pd.Series(pred,index=frame.index).rank(method='average',pct=True)
            target,events=select_retention(scores,previous[v]);previous[v]=set(target.ts_code)
            events['variant']=v;events['signal_date']=d;events_all.append(events)
            pos=calendar.get_loc(d);scale,sigma,cov=risk_scale(returns.loc[calendar[pos-59:pos+1],target.ts_code],target.target_weight)
            cov_path=OUT/f'covariance_{v}_{d:%Y%m%d}.npy';np.save(cov_path,cov);cov_hash[cov_path.name]=sha(cov_path)
            risk_logs.append(dict(variant=v,signal_date=d,scale=scale,forecast_volatility=sigma,target_cash=1-target.target_weight.sum()*scale,covariance_file=cov_path.name))
            for p in ('retention','risk'):
                t=target.copy();t['signal_date']=d;t['execution_date']=row.execution_date
                if p=='risk':t.target_weight*=scale
                plans[v+'_'+p].append(t)
            predictions.append(pd.DataFrame(dict(trade_date=d,execution_date=row.execution_date,variant=v,ts_code=frame.ts_code.to_numpy(),prediction=pred)))
            for label_v,kind in [(v,'native'),('D','common_week_endpoint')]:
                mask=frame[label_v+'_valid'].to_numpy()
                observed=frame.loc[mask,label_v+'_label'].reset_index(drop=True)
                ic=pd.Series(pred[mask]).corr(observed,method='spearman') if mask.sum()>1 else np.nan
                ics.append(dict(variant=v,kind=kind,signal_date=d,execution_date=row.execution_date,year=row.execution_date.year,eligible=len(frame),valid_labels=int(mask.sum()),rank_ic=ic))
    targets={p:pd.concat(t,ignore_index=True) for p,t in plans.items()}
    for p,t in targets.items():t.to_csv(OUT/f'targets_{p}.csv',index=False)
    pd.concat(predictions,ignore_index=True).to_csv(OUT/'predictions.csv',index=False)
    pd.concat(events_all,ignore_index=True).to_csv(OUT/'selection_events.csv',index=False)
    pd.DataFrame(ics).to_csv(OUT/'rank_ic.csv',index=False);pd.DataFrame(risk_logs).to_csv(OUT/'risk_budget.csv',index=False)
    persist('covariance_sha256.json',cov_hash)
    old_summary=json.loads((OLD/'summary.json').read_text(encoding='utf-8'))
    refs=[]
    for r in old_summary['experiments']:
        new_name=r['strategy'].replace('ml_retention','A_retention').replace('ml_risk','A_risk')
        refs.append(dict(label=new_name,original_strategy=r['strategy'],folder=str((OLD/r['strategy']).relative_to(ROOT)),result=r))
    persist('references.json',refs)
    metadata=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    sectors=pd.read_csv(ROOT/'data/audit/industry_history.csv',dtype=str)
    namespace=dict(vars(original));namespace.update(locals());namespace.update(OUT=OUT,PATHS=PATHS,persist=persist)
    exec(compile(block,str(Path(original.__file__))+'#account_block','exec'),namespace)
    for n,h in old_hashes.items():assert sha(OLD/n)==h,n
    return int(any(s['status']!='completed' for s in namespace['statuses']))


if __name__=='__main__':raise SystemExit(main())
