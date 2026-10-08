"""Independent raw-label, model, risk, selection and account verification."""
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.covariance import LedoitWolf

from run_horizon_coverage import ROOT,DATA,SOURCE,OLD,OUT,FEATURES,sha,read_subset
from horizon_labels import training_samples
from retention_selector import select_retention
from quant_research.corporate_corrections import correct_adjustments
from quant_research.backtest import summarize
from quant_research.factors import weekly_schedule


def read(name,dates=()):return pd.read_csv(OUT/name,parse_dates=list(dates),float_precision='round_trip')


def main():
    proto=json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'))
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    assert {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}==proto['source_sha256']
    for n,h in proto['inputs'].items():assert sha(ROOT/n)==h,n
    for n,h in proto['old_hashes'].items():assert sha(OLD/n)==h,n
    assert sha(OLD/'output_sha256.json')==proto['old_output_manifest_sha256']
    for n,h in json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))['files_sha256'].items():assert sha(DATA/n)==h,n
    for n,h in proto['metadata_sha256'].items():assert sha(ROOT/'data/audit'/n)==h,n
    assert sha(OUT/'simulation_adapter_block.py.txt')==proto['simulation_block_sha256']
    for n,h in proto['source_sha256'].items():assert sha(OUT/'source_before'/n)==h,n
    for n,h in proto['inputs'].items():
        p=OUT/'source_before'/__import__('pathlib').Path(n).name
        if p.exists():assert sha(p)==h,n
    samples=read('common_samples.csv',['trade_date','entry_date','label_end','reference_end',*['%s_end'%v for v in 'ABCD']])
    old=pd.read_csv(OLD/'common_samples.csv',parse_dates=['trade_date'],float_precision='round_trip')
    assert samples[['trade_date','ts_code']].equals(old[['trade_date','ts_code']])
    assert np.array_equal(samples[FEATURES].to_numpy(),old[FEATURES].to_numpy())
    assert samples.A_valid.equals(old.label_valid) and np.allclose(samples.A_label,old.label,rtol=0,atol=1e-12,equal_nan=True)
    cal=pd.read_csv(DATA/'calendar.csv',dtype={'cal_date':str})
    full=pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1),'cal_date'])).sort_values()
    calendar=full[(full>=pd.Timestamp('20151101'))&(full<=pd.Timestamp('20201231'))]
    schedule=weekly_schedule(full[full>=pd.Timestamp('20151101')]);schedule['next_execution']=schedule.execution_date.shift(-1)
    mapped=schedule.set_index('signal_date')
    codes=set(samples.ts_code)
    bars=read_subset('daily',codes).merge(read_subset('adj_factor',codes),on=['trade_date','ts_code'],validate='one_to_one')
    bars,_=correct_adjustments(bars)
    index=pd.read_csv(DATA/'benchmark.csv',parse_dates=['trade_date']).set_index('trade_date').open.reindex(calendar).to_numpy()
    issues=pd.read_csv(SOURCE/'unexplained_adjustments.csv',parse_dates=['trade_date'])
    arrays={};returns={}
    for c,g in bars.groupby('ts_code'):
        q=g.set_index('trade_date').reindex(calendar)
        present=calendar.isin(g.trade_date);numeric=q[['open','high','low','close','adj_factor','vol','amount']].to_numpy()
        valid=np.isfinite(numeric).all(axis=1)&(numeric>0).all(axis=1)
        unknown=calendar.isin(issues.loc[issues.ts_code.eq(c),'trade_date'])
        arrays[c]=(present,valid,(q.open*q.adj_factor).to_numpy(),unknown)
        returns[c]=(q.close*q.adj_factor).where(valid).pct_change(fill_method=None)
    returns=pd.DataFrame(returns,index=calendar);del bars
    print('Verify every label directly against raw quote arrays',flush=True)
    checked=0;reason_totals=[];coverage={v:0 for v in 'ABCD'}
    for chunk in pd.read_csv(OUT/'label_audit.csv',parse_dates=['trade_date','entry_date','label_end','reference_end'],chunksize=100000,float_precision='round_trip'):
        for c,g in chunk.groupby('ts_code',sort=False):
            present,valid,opening,unknown=arrays[c]
            start=calendar.get_indexer(mapped.loc[g.trade_date,'execution_date'])
            end20=calendar.get_indexer(g.trade_date)+21
            weekly=calendar.get_indexer(mapped.loc[g.trade_date,'next_execution'])
            end=np.where(g.variant.isin(['A','C']),end20,weekly)
            outside=(start<0)|(end<0)|(end>=len(calendar))
            x=np.clip(start,0,len(calendar)-1);y=np.clip(end,0,len(calendar)-1)
            def counts(mask):
                p=np.r_[0,np.cumsum(mask.astype(int))]
                return (p[y]-p[x+1])>0
            missing=(~present[x]|~present[y])&~outside
            invalid=((present[x]&~valid[x])|(present[y]&~valid[y]))&~outside
            mid_missing=counts(~present)&~outside;mid_invalid=counts(present&~valid)&~outside
            pu=np.r_[0,np.cumsum(unknown.astype(int))];u=(pu[y+1]-pu[x]>0)&~outside
            ibad=(~np.isfinite(index[x])|~np.isfinite(index[y])|(index[x]<=0)|(index[y]<=0))&~outside
            ok=~(outside|missing|invalid|u|ibad|(g.variant.isin(['A','B']).to_numpy()&(mid_missing|mid_invalid)))
            for name,value in [('outside_period',outside),('endpoint_missing',missing),('endpoint_invalid',invalid),
                               ('middle_missing',mid_missing),('middle_invalid',mid_invalid),('unknown_adjustment',u),('benchmark_invalid',ibad),('label_valid',ok)]:
                assert np.array_equal(g[name].to_numpy(),value),(c,name)
            expected=np.full(len(g),np.nan)
            expected[ok]=opening[y[ok]]/opening[x[ok]]-1-(index[y[ok]]/index[x[ok]]-1)
            assert np.allclose(expected,g.label,rtol=0,atol=1e-12,equal_nan=True),c
            expected_end=pd.Series(pd.NaT,index=range(len(g)),dtype='datetime64[ns]');expected_end.loc[~outside]=calendar[end[~outside]].to_numpy()
            assert np.array_equal(expected_end.to_numpy(),g.label_end.to_numpy(),equal_nan=True)
            for v in 'ABCD':coverage[v]+=int(g.loc[g.variant.eq(v),'label_valid'].sum())
        checked+=len(chunk)
        reason_totals.append(chunk.groupby(['variant','reason']).size().rename('samples').reset_index())
    assert checked==4*len(samples)
    pd.concat(reason_totals).groupby(['variant','reason']).samples.sum().to_csv(OUT/'label_reason_totals.csv')
    audit=json.loads((OUT/'training_audit.json').read_text(encoding='utf-8'));models={}
    for t in audit:
        v=t['variant'];year=t['year'];fit=pd.Timestamp(t['fit_date']);train=training_samples(samples,v,fit)
        saved=read(f'models/training_{v}_{year}.csv',['trade_date','label_end','reference_end'])
        assert saved[['trade_date','ts_code']].equals(train[['trade_date','ts_code']].reset_index(drop=True))
        assert saved.label_end.lt(fit).all() and saved.reference_end.lt(fit).all()
        assert np.allclose(saved.label,train.label,rtol=0,atol=1e-12)
        assert np.allclose(saved.sample_weight,train.sample_weight,rtol=0,atol=1e-12)
        assert np.allclose(saved.groupby('trade_date').sample_weight.sum(),1,atol=1e-12)
        path=OUT/f'models/{v}_{year}.txt';assert sha(path)==t['model_sha256']
        models[v,year]=lgb.Booster(model_str=path.read_text(encoding='utf-8'))
    prediction=read('predictions.csv',['trade_date','execution_date']);risk=read('risk_budget.csv',['signal_date'])
    targets={p:read(f'targets_{p}.csv',['trade_date','signal_date','execution_date']) for p in proto['paths']}
    hashes=json.loads((OUT/'covariance_sha256.json').read_text());previous={v:set() for v in 'BCD'};max_error=0.;ic=[]
    for (v,d),g in prediction.groupby(['variant','trade_date'],sort=True):
        frame=samples.loc[samples.trade_date.eq(d)].sort_values('ts_code').reset_index(drop=True)
        g=g.sort_values('ts_code').reset_index(drop=True);assert g.ts_code.tolist()==frame.ts_code.tolist()
        pred=models[v,int(g.execution_date.iloc[0].year)].predict(frame[FEATURES],num_threads=4)
        error=float(np.max(np.abs(pred-g.prediction)));assert error<1e-12;max_error=max(max_error,error)
        selection=frame[['trade_date','ts_code','industry']].copy();selection['score']=pd.Series(pred).rank(method='average',pct=True)
        t,_=select_retention(selection,previous[v]);previous[v]=set(t.ts_code)
        pos=calendar.get_loc(d);values=returns.loc[calendar[pos-59:pos+1],t.ts_code].to_numpy();assert np.isfinite(values).all()
        covariance=LedoitWolf(store_precision=False).fit(values).covariance_;w=t.target_weight.to_numpy()
        sigma=float(np.sqrt(252*w@covariance@w));scale=min(1.,.15/sigma)
        r=risk.loc[risk.variant.eq(v)&risk.signal_date.eq(d)].iloc[0];path=OUT/r.covariance_file
        assert sha(path)==hashes[path.name] and np.allclose(np.load(path),covariance,rtol=0,atol=1e-14)
        assert np.isclose(sigma,r.forecast_volatility,rtol=0,atol=1e-12) and np.isclose(scale,r.scale,rtol=0,atol=1e-12)
        for p in ('retention','risk'):
            observed=targets[v+'_'+p].loc[targets[v+'_'+p].signal_date.eq(d)].sort_values('ts_code').reset_index(drop=True)
            rebuilt=t.sort_values('ts_code').reset_index(drop=True)
            assert observed.ts_code.tolist()==rebuilt.ts_code.tolist()
            assert np.allclose(observed.target_weight,rebuilt.target_weight*(scale if p=='risk' else 1),rtol=0,atol=1e-12)
            assert observed.groupby('industry').target_weight.sum().le(.25+1e-12).all()
        for lab,kind in [(v,'native'),('D','common_week_endpoint')]:
            mask=frame[lab+'_valid'].to_numpy();value=pd.Series(pred[mask]).corr(frame.loc[mask,lab+'_label'].reset_index(drop=True),method='spearman') if mask.sum()>1 else np.nan
            ic.append(dict(variant=v,kind=kind,signal_date=d,rank_ic=value))
    saved_ic=read('rank_ic.csv',['signal_date','execution_date'])
    match=saved_ic.merge(pd.DataFrame(ic),on=['variant','kind','signal_date'],validate='one_to_one',suffixes=('','_replay'))
    assert np.allclose(match.rank_ic,match.rank_ic_replay,rtol=0,atol=1e-12,equal_nan=True)
    account_checks=[];annual=[]
    for t in summary['experiments']:
        f=OUT/t['strategy'];nav=pd.read_csv(f/'nav.csv',parse_dates=['date']);orders=pd.read_csv(f/'orders.csv',parse_dates=['date'])
        assert sha(f/'historical_targets.csv')==sha(OUT/f'targets_{t["path"]}.csv')
        expected=calendar[calendar>=pd.Timestamp('20180101')]
        assert pd.DatetimeIndex(nav.loc[nav.date.ge(pd.Timestamp('20180101')),'date']).equals(expected)
        assert nav.loc[nav.date.eq(pd.Timestamp('20171229')),'equity'].iloc[0]==1000000
        assert orders.date.isin(schedule.execution_date).all() and nav.cash.ge(0).all()
        h=pd.read_csv(f/'holdings.csv');assert h.shares.ge(0).all() and h.pending_shares.ge(0).all()
        err=float((nav.equity-nav[['cash','stock_value','bonus_value','receivable']].sum(axis=1)).abs().max());assert err<1e-6
        calculated=summarize(nav,orders,pd.Timestamp('20180102'),pd.Timestamp('20180101'))
        for k,value in calculated.items():
            if isinstance(value,(float,int)):assert np.isclose(value,t[k],rtol=0,atol=1e-6),(t['strategy'],k)
        monthly=pd.read_csv(f/'monthly_returns.csv');assert len(monthly)==36 and np.isclose((1+monthly['return']).prod()-1,t['total_return'],atol=1e-12)
        if t['config']['zero_trading_costs']:assert orders.fee.eq(0).all() and orders.slippage_cost.eq(0).all()
        prev=1000000.
        for year,g in nav.loc[nav.date.ge(pd.Timestamp('20180101'))].groupby(nav.date.dt.year):
            end=float(g.equity.iloc[-1]);annual.append(dict(strategy=t['strategy'],year=year,return_value=end/prev-1,end_equity=end));prev=end
        account_checks.append(dict(strategy=t['strategy'],sessions=len(expected),max_nav_error=err))
    complete=len(account_checks)==18 and len(summary['experiment_statuses'])==18 and all(t['status']=='completed' for t in summary['experiment_statuses'])
    stats=pd.DataFrame(summary['experiments']).set_index('strategy');oldstats=pd.DataFrame(json.loads((OLD/'summary.json').read_text(encoding='utf-8'))['experiments']).set_index('strategy')
    d_ic=saved_ic.loc[saved_ic.variant.eq('D')&saved_ic.kind.eq('native')];annual_ic=d_ic.groupby('year').rank_ic.mean();gates={}
    if all(k in stats.index for k in ['D_risk_10bp','D_risk_30bp','D_retention_10bp']):
        base=stats.loc['D_risk_10bp']
        gates=dict(rank_ic_positive=bool(d_ic.rank_ic.mean()>0),two_positive_years=bool(annual_ic.gt(0).sum()>=2),
            net_positive_base_stress=bool(base.total_return>0 and stats.loc['D_risk_30bp','total_return']>0),
            beats_controls=bool(base.total_return>oldstats.loc['three_retention_10bp','total_return'] and base.total_return>oldstats.loc['ml_risk_10bp','total_return']),
            drawdown_budget=bool(base.max_drawdown<=.25 and base.max_drawdown<=stats.loc['D_retention_10bp','max_drawdown']))
    result=dict(status='passed' if complete else 'incomplete',label_rows_verified=checked,label_valid_counts=coverage,
        maximum_prediction_replay_error=max_error,training_models=len(audit),account_checks=account_checks,
        mean_D_rank_ic=float(d_ic.rank_ic.mean()),annual_D_rank_ic=annual_ic.to_dict(),gates=gates,research_gates_passed=complete and bool(gates) and all(gates.values()),summary_sha256=sha(OUT/'summary.json'))
    (OUT/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8');pd.DataFrame(annual).to_csv(OUT/'annual_returns.csv',index=False)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
