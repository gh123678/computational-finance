"""Verify the approved outputs and report all pre-registered gates."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from quant_research.backtest import summarize
from quant_research.factors import weekly_schedule
from run_retention_development import sha

OUT=ROOT/'output/retention_threshold_development_2016_2020_r1'
SOURCE=ROOT/'output/continuous_2016_2025_dividend_r1'


def main():
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    protocol=json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'))
    assert len(summary['experiments'])==3
    assert len(summary['experiment_statuses'])==3
    assert all(s['status']=='completed' for s in summary['experiment_statuses'])
    assert protocol['source_sha256']=={p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}
    for name,expected in protocol['inputs'].items():
        assert sha(ROOT/name)==expected,name
    for name,expected in protocol['source_sha256'].items():
        assert sha(OUT/'source_before'/name)==expected,name
    for name,expected in protocol['metadata_sha256'].items():
        assert sha(ROOT/'data/audit'/name)==expected
    manifest_path=ROOT/'data/continuous_2016_2025_dividend_r1/manifest.json'
    assert sha(manifest_path)==protocol['data_manifest_sha256']
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    for name,expected in manifest['files_sha256'].items():
        assert sha(manifest_path.parent/name)==expected,name
    full=pd.read_csv(manifest_path.parent/'calendar.csv',dtype={'cal_date':str})
    calendar=pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    study=calendar[(calendar>=pd.Timestamp('20151101'))&(calendar<=pd.Timestamp('20201231'))]
    # Scheduling is formed on the full original calendar, then truncated by execution.
    full_study=calendar[calendar>=pd.Timestamp('20151101')]
    schedule=weekly_schedule(full_study)
    schedule=schedule.loc[schedule.execution_date.between(pd.Timestamp('20160101'),pd.Timestamp('20201231'))].reset_index(drop=True)
    expected_days=study[study>=pd.Timestamp('20160101')]
    targets=pd.read_csv(OUT/'historical_targets.csv',parse_dates=['signal_date','execution_date'])
    pairs=targets[['signal_date','execution_date']].drop_duplicates().reset_index(drop=True)
    assert pairs.equals(schedule)
    assert not targets.duplicated(['execution_date','ts_code']).any()
    assert targets.target_weight.eq(.049).all()
    assert targets.groupby('execution_date').size().le(20).all()
    assert targets.groupby(['execution_date','industry']).target_weight.sum().le(.25+1e-12).all()
    factors=pd.read_csv(OUT/'signal_factors.csv',parse_dates=['trade_date'])
    joined=targets.merge(factors,left_on=['signal_date','ts_code'],right_on=['trade_date','ts_code'],suffixes=('','_source'),validate='many_to_one')
    for f in ['momentum20','reversal5','lowvol20','adv20_cny']:
        assert np.allclose(joined[f],joined[f+'_source'],rtol=0,atol=1e-12)
    transitions=pd.read_csv(OUT/'target_transitions.csv')
    assert transitions.active_replacements.le(5).all()
    events=pd.read_csv(OUT/'selection_events.csv')
    active=events.loc[events.kind.eq('active_replace')]
    assert (active.new_score>active.old_score+.05).all()
    checks=[];annual=[];metrics=[]
    for item in summary['experiments']:
        label=item['strategy'];folder=OUT/label
        assert sha(folder/'historical_targets.csv')==sha(OUT/'historical_targets.csv')
        nav=pd.read_csv(folder/'nav.csv',parse_dates=['date'])
        orders=pd.read_csv(folder/'orders.csv',parse_dates=['date'])
        holdings=pd.read_csv(folder/'holdings.csv')
        assert pd.DatetimeIndex(nav.loc[nav.date.ge(pd.Timestamp('20160101')),'date']).equals(expected_days)
        assert nav.loc[nav.date.eq(pd.Timestamp('20151231')),'equity'].iloc[0]==1000000
        assert orders.date.isin(schedule.execution_date).all()
        error=(nav.equity-nav[['cash','stock_value','bonus_value','receivable']].sum(axis=1)).abs().max()
        assert error<1e-6 and nav.cash.min()>=0
        assert holdings.shares.min()>=0 and holdings.pending_shares.min()>=0
        recomputed=summarize(nav,orders,schedule.execution_date.iloc[0],pd.Timestamp('20160101'))
        for key,value in recomputed.items():
            if isinstance(value,(float,int)):
                assert np.isclose(value,item[key],rtol=0,atol=1e-6),key
        assert abs(orders.fee.sum()-item['total_fees'])<1e-6
        assert abs(orders.slippage_cost.sum()-item['total_slippage'])<1e-6
        monthly=pd.read_csv(folder/'monthly_returns.csv')
        assert len(monthly)==60
        assert np.isclose((1+monthly['return']).prod()-1,item['total_return'],rtol=0,atol=1e-12)
        costs=pd.read_csv(folder/'cost_attribution.csv')
        assert abs(costs.total_cost.sum()-item['total_fees']-item['total_slippage'])<1e-6
        metrics.append(dict(strategy=label,**recomputed))
        previous=1000000.
        for year,g in nav.loc[nav.date.ge(pd.Timestamp('20160101'))].groupby(nav.date.dt.year):
            ending=float(g.equity.iloc[-1])
            annual.append(dict(strategy=label,year=int(year),return_value=ending/previous-1,end_equity=ending))
            previous=ending
        checks.append(dict(strategy=label,maximum_nav_error=float(error),evaluation_sessions=len(expected_days)))
    comparison_inputs={}
    for label in ['combined','combined_biweekly','combined_zero_cost','combined_biweekly_zero_cost']:
        for filename in ['nav.csv','orders.csv']:
            path=SOURCE/label/filename
            comparison_inputs[str(path.relative_to(ROOT))]=sha(path)
        nav=pd.read_csv(SOURCE/label/'nav.csv',parse_dates=['date'])
        nav=nav.loc[nav.date.le(pd.Timestamp('20201231'))]
        orders=pd.read_csv(SOURCE/label/'orders.csv',parse_dates=['date'])
        orders=orders.loc[orders.date.le(pd.Timestamp('20201231'))]
        result=summarize(nav,orders,pd.Timestamp('20160104'),pd.Timestamp('20160101'))
        metrics.append(dict(strategy=label,**result))
        previous=1000000.
        for year,g in nav.loc[nav.date.ge(pd.Timestamp('20160101'))].groupby(nav.date.dt.year):
            ending=float(g.equity.iloc[-1])
            annual.append(dict(strategy=label,year=int(year),return_value=ending/previous-1,end_equity=ending))
            previous=ending
    stats=pd.DataFrame(metrics).set_index('strategy')
    stats.to_csv(OUT/'comparison.csv')
    pd.DataFrame(annual).to_csv(OUT/'annual_returns.csv',index=False)
    base=stats.loc['combined_retention_gap05_cap5'];bw=stats.loc['combined_biweekly'];old=stats.loc['combined']
    stress=stats.loc['combined_retention_gap05_cap5_slip30']
    gates=dict(turnover_halved=bool(base.gross_turnover<=old.gross_turnover*.5),
               net_positive_and_beats_biweekly=bool(base.total_return>0 and base.total_return>bw.total_return),
               drawdown_not_above_biweekly=bool(base.max_drawdown<=bw.max_drawdown),
               slip30_net_positive=bool(stress.total_return>0))
    result=dict(status='passed',checks=checks,gates=gates,research_gates_passed=all(gates.values()),
                comparison_input_sha256=comparison_inputs,
                summary_sha256=sha(OUT/'summary.json'),core_unchanged=True,
                mean_target_retention=float(transitions.retention.mean()),
                active_replacements=len(active),forced_exits=int(events.kind.eq('forced_exit').sum()))
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print(stats[['total_return','max_drawdown','gross_turnover','total_fees','total_slippage']].to_string())


if __name__=='__main__':
    main()
