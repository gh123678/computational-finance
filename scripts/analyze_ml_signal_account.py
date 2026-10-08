"""Read-only attribution of the frozen ML accounts and prediction horizons."""
import json
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from run_retention_development import ROOT,DATA,sha,read_subset
from quant_research.corporate_corrections import correct_adjustments

SOURCE=ROOT/'output/open_source_ml_risk_2018_2020_r1'
OUT=ROOT/'output/ml_signal_account_diagnosis_20261006'


def ledger_attribution(folder):
    nav=pd.read_csv(folder/'nav.csv',parse_dates=['date']).set_index('date')
    assert nav.index.is_monotonic_increasing and not nav.index.has_duplicates
    h=pd.read_csv(folder/'holdings.csv',parse_dates=['date'])
    trades=pd.read_csv(folder/'orders.csv',parse_dates=['date'])
    events=pd.read_csv(folder/'corporate_events.csv',parse_dates=['date'])
    values=h.pivot(index='date',columns='ts_code',values='value').reindex(nav.index).fillna(0)
    delta=values-values.shift(1,fill_value=0)
    t=trades.copy()
    t['cash_flow']=np.where(t.side.eq('buy'),-1,1)*(t.shares*t.price).fillna(0)-t.fee
    cash=t.pivot_table(index='date',columns='ts_code',values='cash_flow',aggfunc='sum').reindex(index=nav.index,columns=values.columns).fillna(0)
    corporate=pd.DataFrame(0.,index=nav.index,columns=values.columns)
    for e in events.to_dict('records'):
        if e['event']=='ex':
            corporate.loc[e['date'],e['code']]+=e['gross_cash']-e['assumed_tax']
        elif e['event']=='rights_subscribed':
            corporate.loc[e['date'],e['code']]-=e['cost']
    pnl=delta+cash+corporate
    expected=nav.equity-nav.equity.shift(1,fill_value=1000000.)
    error=float((pnl.sum(axis=1)-expected).abs().max())
    assert error<1e-6,(folder.name,error)
    assert abs(pnl.sum().sum()-(nav.equity.iloc[-1]-1000000))<1e-6
    rows=[]
    for year in (2018,2019,2020):
        a=pnl.loc[pnl.index.year==year].sum()
        f=t.loc[t.date.dt.year.eq(year)].groupby('ts_code')[['fee','slippage_cost']].sum().reindex(a.index).fillna(0)
        for code,value in a.items():
            if abs(value)>1e-9 or f.loc[code].abs().sum()>0:
                rows.append(dict(strategy=folder.name,year=year,ts_code=code,net_pnl=float(value),
                    fee=float(f.loc[code,'fee']),slippage=float(f.loc[code,'slippage_cost']),
                    same_fills_before_explicit_costs=float(value+f.loc[code].sum())))
    attribution=pd.DataFrame(rows)
    annual=[];previous=1000000.
    for year in (2018,2019,2020):
        days=nav.loc[nav.index.year==year];end=float(days.equity.iloc[-1])
        f=trades.loc[trades.date.dt.year.eq(year)]
        annual.append(dict(strategy=folder.name,year=year,start_equity=previous,end_equity=end,
            return_value=end/previous-1,net_pnl=end-previous,cost=float(f.fee.sum()+f.slippage_cost.sum()),
            same_fills_before_explicit_costs=end-previous+float(f.fee.sum()+f.slippage_cost.sum())))
        assert abs(attribution.loc[attribution.year.eq(year)].net_pnl.sum()-(end-previous))<1e-6
        previous=end
    # Presence episodes; still-held final episodes are explicitly censored.
    episodes=[]
    active=(h.shares+h.pending_shares).gt(0)
    positions={d:i for i,d in enumerate(nav.index)}
    final=nav.index[-1]
    for code,g in h.loc[active].groupby('ts_code'):
        dates=g.date.sort_values().tolist();start=prev=dates[0]
        for d in dates[1:]:
            if positions[d]!=positions[prev]+1:
                episodes.append(dict(strategy=folder.name,ts_code=code,start=start,end=prev,
                                     sessions=positions[prev]-positions[start]+1,censored=False))
                start=d
            prev=d
        episodes.append(dict(strategy=folder.name,ts_code=code,start=start,end=prev,
                             sessions=positions[prev]-positions[start]+1,censored=prev==final))
    return attribution,annual,episodes,error


def horizons(predictions,targets):
    all_codes=set().union(*(set(t.ts_code) for t in targets.values()))
    bars=read_subset('daily',all_codes)
    bars=bars.merge(read_subset('adj_factor',all_codes),on=['trade_date','ts_code'],validate='one_to_one')
    bars,_=correct_adjustments(bars)
    valid=bars[['open','high','low','close','adj_factor']].gt(0).all(axis=1)&bars.vol.gt(0)&bars.amount.gt(0)
    bars['adjusted_open']=(bars.open*bars.adj_factor).where(valid)
    raw_cal=pd.read_csv(DATA/'calendar.csv',dtype={'cal_date':str})
    calendar=pd.DatetimeIndex(pd.to_datetime(raw_cal.loc[raw_cal.is_open.eq(1),'cal_date'])).sort_values()
    assert calendar.is_monotonic_increasing and not calendar.has_duplicates
    calendar=calendar[(calendar>=pd.Timestamp('20171201'))&(calendar<=pd.Timestamp('20201231'))]
    opening=bars.pivot(index='trade_date',columns='ts_code',values='adjusted_open').reindex(calendar)
    benchmark=pd.read_csv(DATA/'benchmark.csv',parse_dates=['trade_date']).set_index('trade_date').open
    issues=pd.read_csv(ROOT/'output/continuous_2016_2025_dividend_r1/unexplained_adjustments.csv',parse_dates=['trade_date'])
    dates=predictions[['trade_date','execution_date']].drop_duplicates().sort_values('execution_date').reset_index(drop=True)
    rows=[]
    for p,target in targets.items():
        for i,r in dates.iterrows():
            d=r.trade_date;entry=r.execution_date
            # End at the next scheduled opening, without reading beyond 2020.
            exit_date=dates.execution_date.iloc[i+1] if i+1<len(dates) else pd.NaT
            selected=target.loc[target.signal_date.eq(d),'ts_code'].tolist()
            annotation=predictions.loc[predictions.trade_date.eq(d)&predictions.ts_code.isin(selected)].set_index('ts_code').reindex(selected)
            for code,a in annotation.iterrows():
                weekly=weekly_excess=np.nan
                if pd.notna(exit_date):
                    window=opening.loc[entry:exit_date,code]
                    assert len(window)>=2 and window.index[0]==entry and window.index[-1]==exit_date
                    unexplained=issues.loc[issues.ts_code.eq(code)&issues.trade_date.between(entry,exit_date)]
                    if window.notna().all() and unexplained.empty:
                        weekly=float(window.iloc[-1]/window.iloc[0]-1)
                        weekly_excess=weekly-float(benchmark.loc[exit_date]/benchmark.loc[entry]-1)
                rows.append(dict(path=p,signal_date=d,execution_date=entry,year=entry.year,ts_code=code,
                    next_execution=exit_date,week_raw_price_return=weekly,week_excess_price_return=weekly_excess,
                    twenty_excess_label=float(a.label) if a.label_valid else np.nan))
    detail=pd.DataFrame(rows)
    signals=detail.groupby(['path','year','signal_date']).agg(targets=('ts_code','size'),
        weekly_valid=('week_raw_price_return','count'),twenty_valid=('twenty_excess_label','count'),
        weekly_raw=('week_raw_price_return','mean'),weekly_excess=('week_excess_price_return','mean'),
        twenty_excess=('twenty_excess_label','mean')).reset_index()
    yearly=signals.groupby(['path','year']).agg(signals=('signal_date','size'),targets=('targets','sum'),
        weekly_valid=('weekly_valid','sum'),twenty_valid=('twenty_valid','sum'),
        mean_weekly_raw=('weekly_raw','mean'),mean_weekly_excess=('weekly_excess','mean'),
        mean_twenty_excess=('twenty_excess','mean')).reset_index()
    return detail,signals,yearly


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'verification.json').exists():
        raise RuntimeError('Existing completed diagnosis; inspect rather than overwrite')
    lock=OUT/'diagnosis.lock'
    with lock.open('x'):
        pass
    try:
        run()
    except Exception:
        (OUT/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');raise
    finally:
        lock.unlink()


def run():
    frozen=json.loads((SOURCE/'output_sha256.json').read_text(encoding='utf-8'))
    # Verify every frozen study artifact before any read-only analysis.
    for name,expected in frozen.items():assert sha(SOURCE/name)==expected,name
    protocol=json.loads((SOURCE/'frozen_protocol.json').read_text(encoding='utf-8'))
    assert sha(DATA/'manifest.json')==protocol['data_manifest_sha256']
    data_manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in data_manifest['files_sha256'].items():assert sha(DATA/name)==expected,name
    assert {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}==protocol['source_sha256']
    summary=json.loads((SOURCE/'summary.json').read_text(encoding='utf-8'))
    predictions=pd.read_csv(SOURCE/'predictions.csv',parse_dates=['trade_date','execution_date'])
    targets={p:pd.read_csv(SOURCE/f'targets_{p}.csv',parse_dates=['signal_date']) for p in ['three_weekly','three_retention','ml_retention']}
    all_attribution=[];annual=[];episodes=[];checks=[]
    for r in summary['experiments']:
        print('Reconstruct',r['strategy'],flush=True)
        a,y,e,error=ledger_attribution(SOURCE/r['strategy'])
        all_attribution.append(a);annual.extend(y);episodes.extend(e)
        checks.append(dict(strategy=r['strategy'],maximum_daily_pnl_error=error))
    pd.concat(all_attribution).to_csv(OUT/'asset_annual_pnl.csv',index=False)
    annual=pd.DataFrame(annual);annual.to_csv(OUT/'annual_account_pnl.csv',index=False)
    episodes=pd.DataFrame(episodes);episodes.to_csv(OUT/'holding_presence_episodes.csv',index=False)
    print('Compare fixed 20-session labels with next scheduled weekly opening',flush=True)
    detail,signals,yearly=horizons(predictions,targets)
    detail.to_csv(OUT/'target_horizon_labels.csv',index=False)
    signals.to_csv(OUT/'signal_horizon_means.csv',index=False)
    yearly.to_csv(OUT/'annual_horizon_means.csv',index=False)
    benchmark=pd.read_csv(DATA/'benchmark.csv',parse_dates=['trade_date']).set_index('trade_date').close.sort_index()
    assert benchmark.index.is_monotonic_increasing and not benchmark.index.has_duplicates
    benchmark_annual=[]
    for year in (2018,2019,2020):
        previous_date=benchmark.index[benchmark.index<pd.Timestamp(f'{year}0101')][-1]
        ending_date=benchmark.index[benchmark.index.year==year][-1]
        assert previous_date.year==year-1 and previous_date.month==12 and ending_date.month==12
        previous=benchmark.loc[previous_date];ending=benchmark.loc[ending_date]
        benchmark_annual.append(dict(year=year,start_date=previous_date,end_date=ending_date,
                                    start_index=float(previous),end_index=float(ending),price_index_return=float(ending/previous-1)))
    pd.DataFrame(benchmark_annual).to_csv(OUT/'benchmark_annual.csv',index=False)
    # The same benchmark scalar cannot change a same-date Spearman ordering.
    rank_checks=[]
    for d,g in predictions.groupby('trade_date'):
        g=g.loc[g.label_valid]
        if len(g)>1:
            a=g.prediction.corr(g.label,method='spearman')
            b=g.prediction.corr(g.label+.1,method='spearman')
            assert np.isclose(a,b,rtol=0,atol=1e-12)
            rank_checks.append(dict(signal_date=d,rank_ic=float(a),translated_rank_ic=float(b)))
    pd.DataFrame(rank_checks).to_csv(OUT/'rank_translation_invariance.csv',index=False)
    assert len(checks)==12
    for name,expected in frozen.items():assert sha(SOURCE/name)==expected,name
    verification=dict(status='passed',account_checks=checks,source_output_manifest_sha256=sha(SOURCE/'output_sha256.json'),
        source_artifacts_unchanged=len(frozen),rank_translation_checks=len(rank_checks),
        raw_data_sha256={n:sha(DATA/n) for n in ['daily.csv','adj_factor.csv','benchmark.csv','calendar.csv']},
        diagnostic_source_sha256=sha(Path(__file__)),scope='Attribution only; no new portfolios, no parameter search, no causal decomposition')
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
    print('Attribution verified; frozen study unchanged',flush=True)


if __name__=='__main__':
    main()
