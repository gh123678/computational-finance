"""Independent raw-window, weighted Ridge, target and cash/share verification."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.covariance import LedoitWolf
from prepare_price_amount_research import ROOT, DATA, SOURCE, OLD, OUT, PATHS, FIT_DATES, persist, sha, read_subset
from price_amount_features import FEATURES, WINDOWS
from quant_research.corporate_corrections import correct_adjustments
from quant_research.factors import rank_scores, FACTORS, weekly_schedule
from quant_research.backtest import summarize
from retention_selector import select_retention
import announcement_financial_audit as audit


def main():
    stage = json.loads((OUT/'experiment_stage.json').read_text(encoding='utf-8'))
    if stage['state'] != 'completed': raise RuntimeError('All12 accounts must complete before verification')
    if (OUT/'verification.json').exists(): raise RuntimeError('Existing verification; inspect before repeat')
    prep = json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'))
    for n,h in prep['inputs'].items(): assert sha(ROOT/n)==h,n
    assert {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}==prep['source_sha256']
    for n,h in json.loads((OUT/'preparation_sha256.json').read_text(encoding='utf-8')).items(): assert sha(OUT/n)==h,n
    experiment = json.loads((OUT/'experiment_protocol.json').read_text(encoding='utf-8'))
    assert sha(ROOT/'scripts/run_price_amount_research.py')==experiment['runner_sha256']
    assert sha(OUT/'simulation_adapter_block.py.txt')==experiment['adapter_sha256']
    summary = json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    assert len(summary['experiment_statuses'])==12 and all(s['status']=='completed' for s in summary['experiment_statuses'])
    common = pd.read_csv(OUT/'common_samples.csv',parse_dates=['trade_date','D_end','reference_end'],float_precision='round_trip')
    coverage = pd.read_csv(OUT/'feature_coverage.csv',parse_dates=['trade_date'],float_precision='round_trip')
    original = pd.read_csv(OLD/'common_samples.csv',parse_dates=['trade_date','D_end','reference_end'],float_precision='round_trip')
    assert coverage[['trade_date','ts_code']].equals(original[['trade_date','ts_code']])
    original = original.set_index(['ts_code','trade_date']); indexed = common.set_index(['ts_code','trade_date'])
    for c in ['D_label','D_valid','D_end','reference_end',*FACTORS,'industry']:
        pd.testing.assert_series_equal(indexed[c], original.loc[indexed.index,c],check_names=False)
    cal = pd.read_csv(DATA/'calendar.csv',dtype={'cal_date':str})
    full = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1),'cal_date'])).sort_values()
    calendar = full[(full>='2015-11-01')&(full<='2020-12-31')]
    codes = set(coverage.ts_code)
    bars = read_subset('daily',codes).merge(read_subset('adj_factor',codes),on=['trade_date','ts_code'],validate='one_to_one')
    bars,_ = correct_adjustments(bars)
    issues = pd.read_csv(SOURCE/'unexplained_adjustments.csv',parse_dates=['trade_date'])
    observed = {c:g for c,g in coverage.groupby('ts_code')}
    expected = {c:g for c,g in common.groupby('ts_code')}
    returns = {}; max_feature_error = 0.; checked = 0
    for c,g in bars.groupby('ts_code'):
        q = g.set_index('trade_date').reindex(calendar)
        values = q[['open','high','low','close','adj_factor','vol','amount']].to_numpy()
        valid = np.isfinite(values).all(axis=1)&(values>0).all(axis=1)
        prefix = np.r_[0,np.cumsum(valid.astype(int))]
        unknown = calendar.isin(issues.loc[issues.ts_code.eq(c),'trade_date'])
        event_prefix = np.r_[0,np.cumsum(unknown.astype(int))]
        row = observed[c]; positions = calendar.get_indexer(row.trade_date); assert (positions>=0).all()
        left = np.maximum(0,positions-199)
        eligible = (positions>=199)&((prefix[positions+1]-prefix[left])==200)&((event_prefix[positions+1]-event_prefix[left])==0)
        np.testing.assert_array_equal(eligible,row.feature_valid)
        p = (q.close*q.adj_factor).to_numpy(); amount = (q.amount*1000).to_numpy()
        returns[c] = pd.Series(p,index=calendar).where(valid).pct_change(fill_method=None)
        if c not in expected: continue
        saved = expected[c]; pos = calendar.get_indexer(saved.trade_date)
        for n in WINDOWS:
            for kind,v in [('price',p),('amount',amount)]:
                sums = np.r_[0,np.cumsum(np.where(valid,v,0.))]
                calculated = (sums[pos+1]-sums[pos+1-n])/n/v[pos]-1
                error = np.max(np.abs(calculated-saved[f'{kind}_{n}'].to_numpy()))
                max_feature_error = max(max_feature_error,float(error))
                np.testing.assert_allclose(calculated,saved[f'{kind}_{n}'],rtol=0,atol=1e-10)
        checked += len(saved)
    assert checked == len(common)
    returns = pd.DataFrame(returns,index=calendar)
    predictions = pd.read_csv(OUT/'predictions.csv',parse_dates=['trade_date','execution_date'],float_precision='round_trip')
    predictions = predictions.set_index(['ts_code','trade_date'])
    model_predictions = {}; audits = []; max_prediction_error = 0.
    for year, day in FIT_DATES.items():
        fit = pd.Timestamp(day)
        candidate = common.loc[common.D_valid & common.trade_date.lt(fit) & common.D_end.lt(fit) & common.reference_end.lt(fit)]
        counts = candidate.groupby('trade_date').size(); dates = counts.loc[counts>=200].sort_index().index[-52:]
        assert len(dates)==52
        train = candidate.loc[candidate.trade_date.isin(dates)].sort_values(['trade_date','ts_code']).reset_index(drop=True)
        saved = pd.read_csv(OUT/f'training/{year}.csv',parse_dates=['trade_date','D_end','reference_end'],float_precision='round_trip')
        assert train[['trade_date','ts_code']].equals(saved[['trade_date','ts_code']])
        weights = 1/train.groupby('trade_date').ts_code.transform('size').to_numpy()
        np.testing.assert_allclose(weights,saved.sample_weight,rtol=0,atol=1e-15)
        values = train[FEATURES].to_numpy(); mean = np.sum(values*weights[:,None],axis=0)/weights.sum()
        variance = np.sum((values-mean)**2*weights[:,None],axis=0)/weights.sum()
        scales = json.loads((OUT/f'training/scales_{year}.json').read_text(encoding='utf-8'))
        np.testing.assert_allclose(mean,scales['mean'],rtol=0,atol=1e-12)
        np.testing.assert_allclose(variance,scales['variance'],rtol=1e-12,atol=1e-12)
        z = (values-mean)/np.sqrt(variance); y = train.D_label.to_numpy(); intercept = np.average(y,weights=weights)
        coefficient = np.linalg.solve(z.T@(z*weights[:,None])+10*np.eye(8),z.T@(weights*(y-intercept)))
        ridge = json.loads((OUT/f'models/ridge_{year}.json').read_text(encoding='utf-8'))
        np.testing.assert_allclose(coefficient,ridge['coefficients'],rtol=0,atol=1e-10)
        assert abs(intercept-ridge['intercept'])<1e-12
        gbm = lgb.Booster(model_str=(OUT/f'models/gbm_{year}.txt').read_text(encoding='utf-8'))
        eval_keys = predictions.index[predictions.execution_date.dt.year.eq(year)]
        frame = indexed.loc[eval_keys]; matrix = (frame[FEATURES].to_numpy()-mean)/np.sqrt(variance)
        rp = matrix@coefficient+intercept; gp = gbm.predict(matrix,num_threads=4)
        for name,pred in [('ridge',rp),('gbm',gp)]:
            observed_pred = predictions.loc[eval_keys,name+'_prediction'].to_numpy()
            max_prediction_error=max(max_prediction_error,float(np.max(np.abs(pred-observed_pred))))
            np.testing.assert_allclose(pred,observed_pred,rtol=0,atol=1e-10)
        audits.append(dict(year=year,dates=52,samples=len(train),total_weight=float(weights.sum())))
    schedule = weekly_schedule(full[full>='2015-11-01']);schedule=schedule.loc[schedule.execution_date.between('2018-01-01','2020-12-31')]
    targets = {p:pd.read_csv(OUT/f'targets_{p}.csv',parse_dates=['signal_date','execution_date','trade_date'],float_precision='round_trip') for p in PATHS}
    previous = {p:set() for p in PATHS}; ics=[]
    # Remove future annotations from the score/selection frames entirely.
    for row in schedule.itertuples(index=False):
        frame = common.loc[common.trade_date.eq(row.signal_date)]
        pred = predictions.loc[list(zip(frame.ts_code,frame.trade_date))]
        scores = {'three_retention_common200':rank_scores(frame[['trade_date','ts_code','industry',*FACTORS]],FACTORS)}
        for path,name in [('ridge_trend_retention','ridge'),('gbm_trend_risk','gbm')]:
            score=frame[['trade_date','ts_code','industry']].copy();score['score']=pd.Series(pred[name+'_prediction'].to_numpy(),index=frame.index).rank(method='average',pct=True);scores[path]=score
            mask=frame.D_valid.to_numpy();ic=pd.Series(pred[name+'_prediction'].to_numpy()[mask]).corr(frame.loc[mask,'D_label'].reset_index(drop=True),method='spearman') if mask.sum()>1 else np.nan
            ics.append(dict(model=name,signal_date=row.signal_date,rank_ic=ic))
        selected={}
        for path,score in scores.items():
            t,_=select_retention(score,previous[path]);previous[path]=set(t.ts_code);selected[path]=t
        selected['ridge_trend_risk']=selected['ridge_trend_retention'].copy()
        for path in ['ridge_trend_risk','gbm_trend_risk']:
            t=selected[path];pos=calendar.get_loc(row.signal_date);v=returns.loc[calendar[pos-59:pos+1],t.ts_code].to_numpy()
            assert v.shape==(60,len(t)) and np.isfinite(v).all()
            cov=LedoitWolf(store_precision=False).fit(v).covariance_;np.testing.assert_allclose(cov,np.load(OUT/f'covariance_{path}_{row.signal_date:%Y%m%d}.npy'),rtol=0,atol=1e-12)
            sigma=np.sqrt(float(t.target_weight.to_numpy()@cov@t.target_weight.to_numpy()*252));assert sigma>0
            t['target_weight']*=min(1,.15/sigma)
        for path,t in selected.items():
            saved=targets[path].loc[targets[path].signal_date.eq(row.signal_date)].sort_values('ts_code')
            t=t.sort_values('ts_code');assert list(t.ts_code)==list(saved.ts_code)
            np.testing.assert_allclose(t.target_weight,saved.target_weight,rtol=0,atol=1e-12)
    saved_ic=pd.read_csv(OUT/'rank_ic.csv',parse_dates=['signal_date'])
    joined=saved_ic.merge(pd.DataFrame(ics),on=['model','signal_date'],suffixes=('','_replay'),validate='one_to_one')
    np.testing.assert_allclose(joined.rank_ic,joined.rank_ic_replay,rtol=0,atol=1e-12,equal_nan=True)
    checks=[];annual=[];expected_days=calendar[calendar>='2018-01-01']
    for item in summary['experiments']:
        folder=OUT/item['strategy'];assert sha(folder/'historical_targets.csv')==sha(OUT/f'targets_{item["path"]}.csv')
        nav=pd.read_csv(folder/'nav.csv',parse_dates=['date']);orders=pd.read_csv(folder/'orders.csv',parse_dates=['date'])
        assert pd.DatetimeIndex(nav.loc[nav.date>='2018-01-01','date']).equals(expected_days)
        assert nav.loc[nav.date.eq(pd.Timestamp('2017-12-29')),'equity'].iloc[0]==1000000
        error=float((nav.equity-nav[['cash','stock_value','bonus_value','receivable']].sum(axis=1)).abs().max());assert error<1e-6
        assert nav.cash.ge(0).all() and orders.date.isin(schedule.execution_date).all()
        rejected=orders.loc[orders.status.eq('rejected')];assert rejected[['shares','fee','slippage_cost']].eq(0).all().all()
        calc=summarize(nav,orders,schedule.execution_date.iloc[0],pd.Timestamp('2018-01-01'))
        for k,v in calc.items():
            if isinstance(v,(float,int)):assert np.isclose(v,item[k],rtol=0,atol=1e-6),k
        if item['config']['zero_trading_costs']:assert orders[['fee','slippage_cost']].eq(0).all().all()
        previous_equity=1000000.
        for year,g in nav.loc[nav.date>='2018-01-01'].groupby(nav.date.dt.year):
            equity=float(g.equity.iloc[-1]);annual.append(dict(strategy=item['strategy'],year=year,return_value=equity/previous_equity-1));previous_equity=equity
        checks.append(dict(strategy=item['strategy'],sessions=len(nav),maximum_equity_error=error))
    assert len(checks)==12
    source=ROOT/'scripts/audit_continuous_flows.py';text=source.read_text(encoding='utf-8')
    assert text.count('assert len(checks) == 12 and len(boundaries) == 108')==1
    adapted=text.replace('assert len(checks) == 12 and len(boundaries) == 108','assert len(checks) == 12 and len(boundaries) == 24').replace("previous['date'].year >= 2016","previous['date'].year >= 2018")
    namespace={'__file__':str(source),'__name__':'price_amount_cash_audit'};exec(compile(adapted,str(source),'exec'),namespace);namespace['OUT']=OUT;namespace['main']()
    stats=pd.DataFrame(summary['experiments']).set_index('strategy');primary=stats.loc['ridge_trend_risk_10bp'];ic=saved_ic.loc[saved_ic.model.eq('ridge')];year_ic=ic.groupby('year').rank_ic.mean()
    gates=dict(rankIC_positive=bool(ic.rank_ic.mean()>0),two_positive_years=bool(year_ic.gt(0).sum()>=2),
        net_positive_10and30=bool(primary.total_return>0 and stats.loc['ridge_trend_risk_30bp','total_return']>0),
        beats_both_controls=bool(primary.total_return>stats.loc['three_retention_common200_10bp','total_return'] and primary.total_return>stats.loc['gbm_trend_risk_10bp','total_return']),
        drawdown=bool(primary.max_drawdown<=.25 and primary.max_drawdown<=stats.loc['ridge_trend_retention_10bp','max_drawdown']))
    pd.DataFrame(annual).to_csv(OUT/'annual_returns.csv',index=False)
    pd.DataFrame(summary['experiments']).drop(columns=['config']).to_csv(OUT/'comparison.csv',index=False)
    audit.verify_old()
    persist('verification.json',dict(status='passed',feature_rows_checked=checked,maximum_feature_error=max_feature_error,
        training_checks=audits,maximum_prediction_error=max_prediction_error,accounts=checks,
        cash_auditor_sha256=sha(source),verifier_sha256=sha(Path(__file__)),mean_rankIC=float(ic.rank_ic.mean()),yearly_rankIC=year_ic.to_dict(),
        gates=gates,research_gates_passed=all(gates.values()),broker_connected=False,
        scope='Exploratory development; engineering verification does not restore unseen holdout status'))
    print(json.dumps(dict(gates=gates,primary_net_return=float(primary.total_return),verification='passed'),ensure_ascii=False))


if __name__=='__main__':main()
