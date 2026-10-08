"""Verify completed continuous groups; never label failed groups as complete."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from quant_research.factors import weekly_schedule,biweekly_schedule


def main(small=False,revision=False):
    if small and revision:
        raise ValueError('Revision uses full study')
    name='continuous_2016_2025_dividend_r1' if revision else 'continuous_2016_2025'
    out=ROOT/'output'/('continuous_2016_2017_check' if small else name)
    summary_path=out/'summary.json'
    summary=json.loads(summary_path.read_text(encoding='utf-8'))
    frozen=json.loads((out/'frozen_protocol.json').read_text(encoding='utf-8'))
    current={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'quant_research').glob('*.py')}
    assert summary['source_sha256']==frozen['source_sha256']==current
    for file,expected in summary['data_manifest']['files_sha256'].items():
        assert hashlib.sha256((ROOT/'data'/name/file).read_bytes()).hexdigest()==expected
    for file,expected in frozen['metadata_sha256'].items():
        assert hashlib.sha256((ROOT/'data/audit'/file).read_bytes()).hexdigest()==expected
    calendar=pd.read_csv(ROOT/'data'/name/'calendar.csv',dtype={'cal_date':str})
    full=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.is_open.eq(1),'cal_date'])).sort_values()
    end=pd.Timestamp(summary['until'] or '20251231')
    study=full[(full>=pd.Timestamp('20151101'))&(full<=end)]
    expected=study[study>=pd.Timestamp('20160101')]
    factors=pd.read_csv(out/'factors.csv',usecols=['ts_code','trade_date','momentum20','reversal5','lowvol20'],parse_dates=['trade_date'])
    annual,checks=[],[]
    for item in summary['experiments']:
        label=item['strategy'];folder=out/label
        nav=pd.read_csv(folder/'nav.csv',parse_dates=['date'])
        orders=pd.read_csv(folder/'orders.csv',parse_dates=['date'])
        holdings=pd.read_csv(folder/'holdings.csv')
        monthly=pd.read_csv(folder/'monthly_returns.csv')
        costs=pd.read_csv(folder/'cost_attribution.csv')
        targets=pd.read_csv(folder/'historical_targets.csv',parse_dates=['signal_date','execution_date'])
        schedule=(biweekly_schedule if 'biweekly' in label else weekly_schedule)(study)
        schedule=schedule.loc[schedule.execution_date>=pd.Timestamp('20160101')]
        pairs=targets[['signal_date','execution_date']].drop_duplicates().reset_index(drop=True)
        assert pairs.equals(schedule[['signal_date','execution_date']].reset_index(drop=True))
        assert orders.date.isin(schedule.execution_date).all()
        columns=['momentum20','reversal5','lowvol20']
        joined=targets.merge(
            factors,left_on=['ts_code','signal_date'],right_on=['ts_code','trade_date'],suffixes=('','_source'),validate='many_to_one')
        for column in columns:
            assert joined[column+'_source'].notna().all()
            assert np.allclose(joined[column],joined[column+'_source'],atol=1e-12)
        error=(nav.equity-nav[['cash','stock_value','bonus_value','receivable']].sum(axis=1)).abs().max()
        assert error<1e-6
        assert nav.cash.min()>=0 and holdings.shares.min()>=0 and holdings.pending_shares.min()>=0
        assert pd.DatetimeIndex(nav.loc[nav.date>=pd.Timestamp('20160101'),'date']).equals(expected)
        base=nav.loc[nav.date.eq(pd.Timestamp('20151231')),'equity'].iloc[0]
        assert base==1000000
        assert np.isclose(nav.equity.iloc[-1]/base-1,item['total_return'],atol=1e-12)
        assert len(monthly)==len(expected.to_period('M').unique())
        assert np.isclose((1+monthly['return']).prod()-1,item['total_return'],atol=1e-12)
        assert np.isclose(costs.total_cost.sum(),item['total_fees']+item['total_slippage'],atol=1e-6)
        assert np.isclose(orders.fee.sum(),item['total_fees'],atol=1e-6)
        assert np.isclose(orders.slippage_cost.sum(),item['total_slippage'],atol=1e-6)
        previous=base
        for year,g in nav.loc[nav.date>=pd.Timestamp('20160101')].groupby(nav.date.dt.year):
            ending=float(g.equity.iloc[-1])
            annual.append(dict(strategy=label,year=int(year),start_equity=previous,end_equity=ending,return_value=ending/previous-1))
            previous=ending
        checks.append(dict(strategy=label,maximum_nav_identity_error=float(error),sessions=len(expected)))
    statuses=summary['experiment_statuses']
    complete=len(statuses)==12 and all(s['status']=='completed' for s in statuses) and len(checks)==12
    result=dict(status='passed' if complete else 'incomplete',checks=checks,experiment_statuses=statuses,
                summary_sha256=hashlib.sha256(summary_path.read_bytes()).hexdigest())
    (out/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    pd.DataFrame(annual).to_csv(out/'continuous_annual_returns.csv',index=False)
    print(json.dumps(result,indent=2))
    return int(not complete)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--small',action='store_true')
    parser.add_argument('--revision',action='store_true')
    args=parser.parse_args()
    raise SystemExit(main(args.small,args.revision))
