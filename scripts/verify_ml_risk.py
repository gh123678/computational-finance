"""Independent verification of predictions, time boundaries and all accounts."""
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from quant_research.factors import FACTORS,rank_scores,select_targets,weekly_schedule
from quant_research.universe import historical_universe
from quant_research.backtest import summarize
from run_retention_development import sha,read_subset,DATA,SOURCE
from quant_research.corporate_corrections import correct_adjustments
from retention_selector import select_retention
from ml_risk_features import FEATURES,matured_training

OUT=ROOT/'output/open_source_ml_risk_2018_2020_r1'


def main():
    protocol=json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'))
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    assert {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}==protocol['source_sha256']
    for name,expected in protocol['inputs'].items():
        assert sha(ROOT/name)==expected,name
        snapshot=OUT/'source_before'/Path(name).name
        if name.startswith('scripts/'):
            assert sha(snapshot)==expected,name
    for name,expected in protocol['source_sha256'].items():
        assert sha(OUT/'source_before'/name)==expected,name
    for name,expected in protocol['metadata_sha256'].items():
        assert sha(ROOT/'data/audit'/name)==expected
    assert sha(DATA/'manifest.json')==protocol['data_manifest_sha256']
    manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files_sha256'].items():
        assert sha(DATA/name)==expected,name
    samples=pd.read_csv(OUT/'common_samples.csv',parse_dates=['trade_date','entry_date','label_end'],float_precision='round_trip')
    assert samples.feature_valid.all() and np.isfinite(samples[FEATURES]).all().all()
    assert not samples.duplicated(['trade_date','ts_code']).any()
    audit=json.loads((OUT/'training_audit.json').read_text(encoding='utf-8'))
    train_checks=[]
    for item in audit:
        year=item['year'];fit_date=pd.Timestamp(item['fit_date'])
        reconstructed=matured_training(samples,fit_date)
        saved=pd.read_csv(OUT/f'models/training_{year}.csv',parse_dates=['trade_date','entry_date','label_end'],float_precision='round_trip')
        assert saved[['trade_date','ts_code']].equals(reconstructed[['trade_date','ts_code']].reset_index(drop=True))
        assert len(saved)==item['samples'] and saved.label_end.lt(fit_date).all()
        assert saved.label_end.max()==pd.Timestamp(item['latest_label_end'])
        assert np.allclose(saved.label,reconstructed.label,rtol=0,atol=1e-12)
        assert np.allclose(saved.groupby('trade_date').sample_weight.sum(),1.,atol=1e-12)
        assert sha(OUT/f'models/model_{year}.txt')==item['model_sha256']
        train_checks.append(dict(year=year,samples=len(saved),fit_date=item['fit_date'],latest_label_end=item['latest_label_end']))
    models={i['year']:lgb.Booster(model_str=(OUT/f'models/model_{i["year"]}.txt').read_text(encoding='utf-8')) for i in audit}
    predictions=pd.read_csv(OUT/'predictions.csv',parse_dates=['trade_date','execution_date','label_end'],float_precision='round_trip')
    full=pd.read_csv(DATA/'calendar.csv',dtype={'cal_date':str})
    calendar=pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    full_study=calendar[calendar>=pd.Timestamp('20151101')]
    schedule=weekly_schedule(full_study)
    schedule=schedule.loc[schedule.execution_date.between(pd.Timestamp('20180101'),pd.Timestamp('20201231'))].reset_index(drop=True)
    metadata=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    names=pd.read_csv(ROOT/'data/audit/name_history.csv',dtype=str)
    sectors=pd.read_csv(ROOT/'data/audit/industry_history.csv',dtype=str)
    source_issues=pd.read_csv(SOURCE/'unexplained_adjustments.csv',parse_dates=['trade_date'])
    targets={p:pd.read_csv(OUT/f'targets_{p}.csv',parse_dates=['trade_date','signal_date','execution_date'],float_precision='round_trip') for p in protocol['paths']}
    previous={p:set() for p in protocol['paths']};max_prediction_error=0.
    risk=pd.read_csv(OUT/'risk_budget.csv',parse_dates=['signal_date','execution_date'],float_precision='round_trip').set_index('signal_date')
    cov_hash=json.loads((OUT/'covariance_sha256.json').read_text())
    risk_codes=set(targets['ml_retention'].ts_code)
    prices=read_subset('daily',risk_codes).merge(read_subset('adj_factor',risk_codes),on=['ts_code','trade_date'],validate='one_to_one')
    prices,_=correct_adjustments(prices)
    valid=prices[['open','high','low','close','adj_factor']].gt(0).all(axis=1)&prices.vol.gt(0)&prices.amount.gt(0)
    prices['adjusted_close']=(prices.close*prices.adj_factor).where(valid)
    closing=prices.pivot(index='trade_date',columns='ts_code',values='adjusted_close').reindex(full_study)
    historical_returns=closing/closing.shift(1)-1
    ic_checks=[]
    for row in schedule.itertuples(index=False):
        d=row.signal_date;year=row.execution_date.year
        frame=samples.loc[samples.trade_date.eq(d)].copy()
        available=historical_universe(d,metadata,names,sectors,calendar)
        assert set(frame.ts_code).issubset(set(available.ts_code))
        assert frame.log_adv20.ge(np.log1p(20000000)).all()
        for issue in source_issues.itertuples(index=False):
            if issue.trade_date in full_study:
                pos=full_study.get_loc(issue.trade_date)
                if d in full_study[pos:pos+61]:
                    assert issue.ts_code not in set(frame.ts_code)
        pred=predictions.loc[predictions.trade_date.eq(d)].sort_values('ts_code').reset_index(drop=True)
        frame=frame.sort_values('ts_code').reset_index(drop=True)
        assert pred.ts_code.tolist()==frame.ts_code.tolist()
        expected=models[year].predict(frame[FEATURES],num_threads=4)
        error=float(np.max(np.abs(expected-pred.prediction)))
        assert error<1e-12,(d,error)
        max_prediction_error=max(max_prediction_error,error)
        frame['score']=pd.Series(expected).rank(method='average',pct=True).to_numpy()
        # Replay decisions without any future label or future-date annotations.
        original=rank_scores(frame[['trade_date','ts_code','industry',*FACTORS]],FACTORS)
        rebuilt={'three_weekly':select_targets(original)}
        rebuilt['three_retention'],_=select_retention(original,previous['three_retention'])
        rebuilt['ml_retention'],_=select_retention(frame[['trade_date','ts_code','industry','score']],previous['ml_retention'])
        rebuilt['ml_risk']=rebuilt['ml_retention'].copy()
        scale=float(risk.loc[d,'scale']);sigma=float(risk.loc[d,'forecast_volatility'])
        assert 0<scale<=1 and np.isclose(scale,min(1.,.15/sigma),rtol=0,atol=1e-12)
        path=OUT/risk.loc[d,'covariance_file']
        assert sha(path)==cov_hash[path.name]
        covariance=np.load(path)
        pos=full_study.get_loc(d)
        input_returns=historical_returns.loc[full_study[pos-59:pos+1],rebuilt['ml_retention'].ts_code].to_numpy()
        assert input_returns.shape==(60,len(rebuilt['ml_retention'])) and np.isfinite(input_returns).all()
        rebuilt_covariance=LedoitWolf(store_precision=False).fit(input_returns).covariance_
        assert np.allclose(covariance,rebuilt_covariance,rtol=0,atol=1e-14)
        w=rebuilt['ml_retention'].target_weight.to_numpy()
        assert np.isclose(np.sqrt(252*w@covariance@w),sigma,rtol=0,atol=1e-12)
        assert sigma*scale<=.15+1e-12
        rebuilt['ml_risk']['target_weight']*=scale
        for p,target in rebuilt.items():
            observed=targets[p].loc[targets[p].signal_date.eq(d)].sort_values('ts_code').reset_index(drop=True)
            target=target.sort_values('ts_code').reset_index(drop=True)
            assert target.ts_code.tolist()==observed.ts_code.tolist(),(p,d)
            assert np.allclose(target.target_weight,observed.target_weight,rtol=0,atol=1e-12)
            assert target.groupby('industry').target_weight.sum().le(.25+1e-12).all()
            previous[p]=set(target.ts_code)
        valid=frame.label_valid
        ic_checks.append(dict(signal_date=d,year=year,rank_ic=pd.Series(expected[valid]).corr(frame.loc[valid,'label'].reset_index(drop=True),method='spearman')))
    saved_ic=pd.read_csv(OUT/'rank_ic.csv',parse_dates=['signal_date','execution_date'])
    rebuilt_ic=pd.DataFrame(ic_checks)
    assert np.allclose(rebuilt_ic.rank_ic,saved_ic.rank_ic,rtol=0,atol=1e-12,equal_nan=True)
    annual_ic=saved_ic.groupby('year').rank_ic.mean()
    expected_days=calendar[(calendar>=pd.Timestamp('20180101'))&(calendar<=pd.Timestamp('20201231'))]
    account_checks=[];annual=[]
    for item in summary['experiments']:
        label=item['strategy'];folder=OUT/label
        assert sha(folder/'historical_targets.csv')==sha(OUT/f'targets_{item["path"]}.csv')
        nav=pd.read_csv(folder/'nav.csv',parse_dates=['date'])
        orders=pd.read_csv(folder/'orders.csv',parse_dates=['date'])
        holdings=pd.read_csv(folder/'holdings.csv')
        assert nav.loc[nav.date.eq(pd.Timestamp('20171229')),'equity'].iloc[0]==1000000
        assert pd.DatetimeIndex(nav.loc[nav.date.ge(pd.Timestamp('20180101')),'date']).equals(expected_days)
        assert orders.date.isin(schedule.execution_date).all()
        error=(nav.equity-nav[['cash','stock_value','bonus_value','receivable']].sum(axis=1)).abs().max()
        assert error<1e-6 and nav.cash.min()>=0 and holdings.shares.min()>=0 and holdings.pending_shares.min()>=0
        result=summarize(nav,orders,schedule.execution_date.iloc[0],pd.Timestamp('20180101'))
        for key,value in result.items():
            if isinstance(value,(float,int)):
                assert np.isclose(item[key],value,rtol=0,atol=1e-6),key
        assert abs(orders.fee.sum()-item['total_fees'])<1e-6
        assert abs(orders.slippage_cost.sum()-item['total_slippage'])<1e-6
        monthly=pd.read_csv(folder/'monthly_returns.csv')
        assert len(monthly)==36 and np.isclose((1+monthly['return']).prod()-1,item['total_return'],rtol=0,atol=1e-12)
        if item['config']['zero_trading_costs']:
            assert orders.fee.eq(0).all() and orders.slippage_cost.eq(0).all()
        prev=1000000.
        for year,g in nav.loc[nav.date.ge(pd.Timestamp('20180101'))].groupby(nav.date.dt.year):
            ending=float(g.equity.iloc[-1])
            annual.append(dict(strategy=label,year=int(year),return_value=ending/prev-1,end_equity=ending))
            prev=ending
        account_checks.append(dict(strategy=label,max_nav_error=float(error),evaluation_sessions=len(expected_days)))
    all_complete=len(summary['experiment_statuses'])==12 and len(account_checks)==12 and all(s['status']=='completed' for s in summary['experiment_statuses'])
    stats=pd.DataFrame(summary['experiments']).set_index('strategy')
    gates={}
    needed=['ml_risk_10bp','ml_risk_30bp','three_retention_10bp','ml_retention_10bp']
    if all(label in stats.index for label in needed):
        risk_net=stats.loc['ml_risk_10bp'];stress=stats.loc['ml_risk_30bp']
        gates=dict(rank_ic_positive=bool(saved_ic.rank_ic.mean()>0),
            positive_ic_at_least_two_years=bool((annual_ic>0).sum()>=2),
            base_and_stress_net_positive=bool(risk_net.total_return>0 and stress.total_return>0),
            beats_three_retention=bool(risk_net.total_return>stats.loc['three_retention_10bp','total_return']),
            drawdown_budget=bool(risk_net.max_drawdown<=.25 and risk_net.max_drawdown<=stats.loc['ml_retention_10bp','max_drawdown']))
    verification=dict(status='passed' if all_complete else 'incomplete',account_checks=account_checks,
        training_checks=train_checks,maximum_prediction_replay_error=max_prediction_error,
        covariance_input_reconstruction='All signal dates: 60 common past returns and shrinkage covariance reproduced',
        selection_without_future_annotations='All four target code and weight sequences reproduced after removing future labels and dates',
        summary_sha256=sha(OUT/'summary.json'),mean_rank_ic=float(saved_ic.rank_ic.mean()),
        annual_rank_ic={str(k):float(v) for k,v in annual_ic.items()},gates=gates,
        research_gates_passed=all_complete and bool(gates) and all(gates.values()),
        scope='Opened historical study; temporal leakage checks do not restore holdout independence')
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
    pd.DataFrame(annual).to_csv(OUT/'annual_returns.csv',index=False)
    print(json.dumps(verification,indent=2))


if __name__=='__main__':
    main()
