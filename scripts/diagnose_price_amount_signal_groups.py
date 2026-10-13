"""Authorized descriptive groups on frozen predictions; no new trade strategy."""
from pathlib import Path
import json
import hashlib
import shutil
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'output/price_amount_ridge_2018_2020_r1'
OUT = ROOT/'output/price_amount_signal_groups_20261014_r1'


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def save(n,x): (OUT/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    if OUT.exists(): raise RuntimeError('Existing diagnostic; inspect without overwrite')
    OUT.mkdir()
    paths = [BASE/'predictions.csv',BASE/'common_samples.csv',BASE/'targets_ridge_trend_risk.csv',
             BASE/'targets_gbm_trend_risk.csv',BASE/'output_sha256.json',Path(__file__)]
    hashes = {str(p.relative_to(ROOT)):sha(p) for p in paths}
    save('protocol.json',dict(approval='User20261014 好的你继续 after recommendation to first diagnose frozen signals',
        inputs=hashes,models=['ridge','gbm'],prediction_groups='10 fixed percentile groups, ties remain together',
        cohorts=['full_pool','highest_score20_no_sector_or_retention_constraints','frozen_actual_targets'],
        supplementary_past20_groups=['nonpositive','positive'],
        date_weighting='Each formation date equal; within date each validlabel equal; no missingvalue fill',
        comparison='Paired same-date cohorts; unknownlabel counts retained',
        purpose='Development diagnostic only; no thresholdselection, calibratorfit, newmodel or account'))
    frozen = json.loads((BASE/'output_sha256.json').read_text(encoding='utf-8'))
    for n,h in frozen.items(): assert sha(BASE/n)==h,n
    predictions = pd.read_csv(BASE/'predictions.csv',parse_dates=['trade_date','execution_date'],float_precision='round_trip')
    cols = ['trade_date','ts_code','D_label','D_valid','momentum20','reversal5','industry']
    common = pd.read_csv(BASE/'common_samples.csv',usecols=cols,parse_dates=['trade_date'],float_precision='round_trip')
    frame = predictions.merge(common,on=['trade_date','ts_code'],validate='one_to_one')
    assert len(frame)==len(predictions) and not frame.duplicated(['trade_date','ts_code']).any()
    frame['year']=frame.execution_date.dt.year
    assert frame.year.isin([2018,2019,2020]).all()
    assert frame.loc[frame.D_valid,'D_label'].notna().all()
    weekly=[];cohorts=[];selected_rows=[]; selection_stats=[]
    for model,path in [('ridge','ridge_trend_risk'),('gbm','gbm_trend_risk')]:
        part=frame.copy();part['prediction']=part[model+'_prediction']
        assert np.isfinite(part.prediction).all()
        part['percentile']=part.groupby('trade_date').prediction.rank(method='average',pct=True)
        part['group']=np.ceil(part.percentile*10).clip(1,10).astype(int)
        part['past20_group']=np.where(part.momentum20>0,'positive','nonpositive')
        target=pd.read_csv(BASE/f'targets_{path}.csv',usecols=['signal_date','execution_date','ts_code'],parse_dates=['signal_date','execution_date'])
        keys=set(zip(target.ts_code,target.signal_date))
        part['actual_target']=[(c,d) in keys for c,d in zip(part.ts_code,part.trade_date)]
        assert part.actual_target.sum()==len(target)
        highest=part.sort_values(['trade_date','prediction','ts_code'],ascending=[True,False,True]).groupby('trade_date',sort=False).head(20)
        top_keys=set(zip(highest.ts_code,highest.trade_date))
        part['highest20']=[(c,d) in top_keys for c,d in zip(part.ts_code,part.trade_date)]
        selected_rows.append(part[['trade_date','execution_date','year','ts_code','prediction','percentile','group',
                                  'past20_group','momentum20','D_valid','D_label','actual_target','highest20']].assign(model=model))
        for (year,date,group),g in part.groupby(['year','trade_date','group']):
            valid=g.loc[g.D_valid]
            weekly.append(dict(model=model,year=year,trade_date=date,group=int(group),total=len(g),known=len(valid),
                 missing=int((~g.D_valid).sum()),predicted_mean=float(g.prediction.mean()),
                 observed_mean=float(valid.D_label.mean()) if len(valid) else None,
                 past20_mean=float(g.momentum20.mean())))
        for name,g in [('full_pool',part),('highest_score20_no_sector_or_retention_constraints',highest),
                       ('frozen_actual_targets',part.loc[part.actual_target])]:
            for (year,date),day in g.groupby(['year','trade_date']):
                valid=day.loc[day.D_valid]
                cohorts.append(dict(model=model,cohort=name,year=year,trade_date=date,total=len(day),
                    known=len(valid),missing=int((~day.D_valid).sum()),mean_percentile=float(day.percentile.mean()),
                    predicted_mean=float(day.prediction.mean()),observed_mean=float(valid.D_label.mean()) if len(valid) else None,
                    past20_mean=float(day.momentum20.mean())))
        targets=part.loc[part.actual_target]
        for year,g in targets.groupby('year'):
            selection_stats.append(dict(model=model,year=year,target_records=len(g),
                highest20_overlap_fraction=float(g.highest20.mean()),target_percentile_mean=float(g.percentile.mean()),
                negative_prediction_fraction=float(g.prediction.lt(0).mean())))
    weekly=pd.DataFrame(weekly);cohorts=pd.DataFrame(cohorts)
    weekly.to_csv(OUT/'weekly_decile_statistics.csv',index=False)
    cohorts.to_csv(OUT/'weekly_cohort_statistics.csv',index=False)
    pd.concat(selected_rows).to_csv(OUT/'group_membership_and_labels.csv',index=False)
    yearly=weekly.groupby(['model','year','group']).agg(valid_weeks=('observed_mean','count'),
        total_records=('total','sum'),known_records=('known','sum'),missing_records=('missing','sum'),
        mean_weekly_excess=('observed_mean','mean'),mean_prediction=('predicted_mean','mean'),mean_past20=('past20_mean','mean')).reset_index()
    overall=weekly.groupby(['model','group']).agg(valid_weeks=('observed_mean','count'),
        mean_weekly_excess=('observed_mean','mean'),mean_prediction=('predicted_mean','mean')).reset_index()
    cohort_summary=cohorts.groupby(['model','cohort','year']).agg(valid_weeks=('observed_mean','count'),
        known_records=('known','sum'),missing_records=('missing','sum'),mean_weekly_excess=('observed_mean','mean'),
        mean_prediction=('predicted_mean','mean'),mean_percentile=('mean_percentile','mean'),mean_past20=('past20_mean','mean')).reset_index()
    yearly.to_csv(OUT/'yearly_deciles.csv',index=False);overall.to_csv(OUT/'overall_deciles.csv',index=False)
    cohort_summary.to_csv(OUT/'yearly_cohorts.csv',index=False)
    paired=[]
    for model,g in cohorts.groupby('model'):
        piv=g.pivot(index=['year','trade_date'],columns='cohort',values='observed_mean')
        for a,b in [('highest_score20_no_sector_or_retention_constraints','frozen_actual_targets'),
                    ('highest_score20_no_sector_or_retention_constraints','full_pool')]:
            matched=piv[[a,b]].dropna();diff=matched[a]-matched[b]
            paired.append(dict(model=model,comparison=a+' minus '+b,paired_weeks=len(matched),
                               mean_difference=float(diff.mean()),year_mean_difference=diff.groupby('year').mean().to_dict()))
    save('selection_statistics.json',selection_stats);save('paired_cohort_comparisons.json',paired)
    for n,h in hashes.items():assert sha(ROOT/n)==h,n
    for n,h in frozen.items():assert sha(BASE/n)==h,n
    save('verification.json',dict(frozen463_artifacts_unchanged=True,inputs_unchanged=True,new_training=0,
        new_backtests=0,new_filters=0,diagnostic_only=True,missinglabels_not_zero=True,
        limitations='Raw top20 ignores sector and retention; nextweekexcess is price label not cashnet; no causal or holdout proof'))
    print(yearly.loc[yearly.group.isin([1,10])].to_string(index=False))
    print(cohort_summary.to_string(index=False));print(json.dumps(paired,ensure_ascii=False))


if __name__=='__main__':main()
