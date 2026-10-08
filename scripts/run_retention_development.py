"""Approved single candidate, three costs, one 2016-2020 continuous account."""
import hashlib
import json
import shutil
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from quant_research.factors import FACTORS,rank_scores,select_targets
from quant_research.universe import historical_universe
from quant_research.backtest import Config,simulate,summarize
from quant_research.accounting import normalize_actions
from quant_research.continuous import relevant_actions
from quant_research.corporate_corrections import correct_actions,correct_adjustments,correct_limit_code_aliases
from quant_research.rights import verified_rights
from quant_research.attribution import monthly_returns,cost_breakdown
from retention_selector import select_retention

SOURCE=ROOT/'output/continuous_2016_2025_dividend_r1'
DATA=ROOT/'data/continuous_2016_2025_dividend_r1'
OUT=ROOT/'output/retention_threshold_development_2016_2020_r1'
SPEC=ROOT/'docs/superpowers/specs/2026-10-06-retention-threshold-design.md'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def read_subset(name,codes,columns=None):
    parts=[]
    for chunk in pd.read_csv(DATA/f'{name}.csv',dtype={'ts_code':str,'trade_date':str},usecols=columns,chunksize=150000):
        parts.append(chunk.loc[chunk.ts_code.isin(codes)&chunk.trade_date.le('20201231')].copy())
    frame=pd.concat(parts,ignore_index=True)
    frame.trade_date=pd.to_datetime(frame.trade_date)
    return frame


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'status.json').exists():
        raise RuntimeError('Existing run status: inspect rather than duplicate or overwrite')
    lock=OUT/'runner.lock'
    with lock.open('x',encoding='utf-8') as stream:
        stream.write('Single approved research process')
    try:
        return run()
    except Exception:
        (OUT/'preparation_failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    finally:
        lock.unlink()


def run():
    frozen=json.loads((SOURCE/'frozen_protocol.json').read_text(encoding='utf-8'))
    core={p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}
    assert core==frozen['source_sha256'],'Original core must stay unchanged'
    manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files_sha256'].items():
        assert sha(DATA/name)==expected,name
    for name,expected in frozen['metadata_sha256'].items():
        assert sha(ROOT/'data/audit'/name)==expected,name
    snapshot=OUT/'source_before'
    snapshot.mkdir()
    for p in (ROOT/'quant_research').glob('*.py'):
        shutil.copy2(p,snapshot/p.name)
    paths=[SPEC,ROOT/'scripts/retention_selector.py',Path(__file__),SOURCE/'factors.csv',SOURCE/'summary.json',
           SOURCE/'combined/historical_targets.csv',SOURCE/'combined_biweekly/historical_targets.csv']
    protocol=dict(source_sha256=core,data_manifest_sha256=sha(DATA/'manifest.json'),
                  metadata_sha256=frozen['metadata_sha256'],inputs={str(p.relative_to(ROOT)):sha(p) for p in paths},
                  start='20160101',end='20201231',warmup='20151101',initial_cash=1000000,
                  candidate=dict(gap=.05,max_active_replacements=5),cost_scenarios=[10,0,30])
    (OUT/'frozen_protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    full=pd.read_csv(DATA/'calendar.csv',dtype={'cal_date':str})
    full_calendar=pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    calendar=full_calendar[(full_calendar>=pd.Timestamp('20151101'))&(full_calendar<=pd.Timestamp('20201231'))]
    saved=pd.read_csv(SOURCE/'combined/historical_targets.csv',parse_dates=['signal_date','execution_date'])
    saved=saved.loc[saved.execution_date.le(pd.Timestamp('20201231'))]
    schedule=saved[['signal_date','execution_date']].drop_duplicates().sort_values('execution_date')
    dates=set(schedule.signal_date)
    pieces=[]
    print('Read frozen development factors and reconstruct targets',flush=True)
    for chunk in pd.read_csv(SOURCE/'factors.csv',parse_dates=['trade_date'],chunksize=150000):
        pieces.append(chunk.loc[chunk.trade_date.isin(dates)])
    factors=pd.concat(pieces,ignore_index=True)
    factors.to_csv(OUT/'signal_factors.csv',index=False)
    groups={d:g for d,g in factors.groupby('trade_date')}
    metadata=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    names=pd.read_csv(ROOT/'data/audit/name_history.csv',dtype=str)
    sectors=pd.read_csv(ROOT/'data/audit/industry_history.csv',dtype=str)
    previous=set();plans=[];logs=[];turns=[]
    for row in schedule.itertuples(index=False):
        d=row.signal_date
        available=historical_universe(d,metadata,names,sectors,full_calendar)
        frame=groups[d].dropna(subset=FACTORS)
        frame=frame.loc[frame.adv20_cny.ge(20000000)].merge(available[['ts_code','industry']],on='ts_code',validate='one_to_one')
        scores=rank_scores(frame)
        original=select_targets(scores).sort_values('ts_code').reset_index(drop=True)
        old=saved.loc[saved.signal_date.eq(d)].sort_values('ts_code').reset_index(drop=True)
        assert original.ts_code.tolist()==old.ts_code.tolist()
        assert np.allclose(original.score,old.score,rtol=0,atol=1e-12)
        selected,events=select_retention(scores,previous)
        selected['signal_date']=d;selected['execution_date']=row.execution_date
        events['signal_date']=d;events['execution_date']=row.execution_date
        codes=set(selected.ts_code)
        turns.append(dict(signal_date=d,execution_date=row.execution_date,
                          previous_count=len(previous),selected_count=len(codes),
                          retained_count=len(previous&codes),changed_count=len(codes-previous),
                          active_replacements=int(events.kind.eq('active_replace').sum()),
                          forced_exits=int(events.kind.eq('forced_exit').sum()),
                          retention=len(previous&codes)/len(previous) if previous else np.nan))
        previous=codes;plans.append(selected);logs.append(events)
    targets=pd.concat(plans,ignore_index=True)
    targets.to_csv(OUT/'historical_targets.csv',index=False)
    pd.concat(logs,ignore_index=True).to_csv(OUT/'selection_events.csv',index=False)
    pd.DataFrame(turns).to_csv(OUT/'target_transitions.csv',index=False)
    assert len(plans)==255
    codes=set(targets.ts_code)
    print(f'Target checks passed: {len(plans)} dates, {len(codes)} securities',flush=True)
    bars=read_subset('daily',codes,['ts_code','trade_date','open','close','amount','vol'])
    bars=bars.merge(read_subset('adj_factor',codes),on=['ts_code','trade_date'],validate='one_to_one')
    limits,aliases=correct_limit_code_aliases(read_subset('stk_limit',codes|{'000043.SZ'}))
    bars=bars.merge(limits,on=['ts_code','trade_date'],how='left',validate='one_to_one')
    bars,adj_corrections=correct_adjustments(bars)
    dividends,action_corrections=correct_actions(pd.read_csv(DATA/'dividend.csv',dtype=str))
    dividends,ignored=relevant_actions(dividends,bars)
    ignored.to_csv(OUT/'unowned_actions.csv',index=False)
    actions=normalize_actions(dividends,set(bars.ts_code))
    suspension=pd.read_csv(DATA/'suspend_d.csv',dtype=str)
    suspension.trade_date=pd.to_datetime(suspension.trade_date)
    suspensions=set(suspension.loc[suspension.suspend_type.eq('S'),['trade_date','ts_code']].itertuples(index=False,name=None))
    delistings=dict(zip(metadata.ts_code,pd.to_datetime(metadata.delist_date)))
    industries={}
    for d in calendar:
        stamp=d.strftime('%Y%m%d')
        sector=sectors.loc[(sectors.in_date<=stamp)&(sectors.out_date.isna()|(sectors.out_date>stamp))]
        counts=sector.groupby('ts_code').l1_code.nunique()
        sector=sector.loc[sector.ts_code.isin(counts[counts==1].index)].drop_duplicates('ts_code')
        industries[d]=dict(zip(sector.ts_code,sector.l1_code))
    results=[];statuses=[]
    for label,bps in [('combined_retention_gap05_cap5',10),('combined_retention_gap05_cap5_zero_cost',0),('combined_retention_gap05_cap5_slip30',30)]:
        folder=OUT/label;folder.mkdir()
        targets.to_csv(folder/'historical_targets.csv',index=False)
        status=dict(strategy=label,status='running');statuses.append(status)
        (OUT/'status.json').write_text(json.dumps(statuses,indent=2),encoding='utf-8')
        config=Config(slippage_bps=bps,zero_trading_costs=bps==0)
        print('Running',label,flush=True)
        try:
            assert {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}==core
            run=simulate(bars,calendar,targets,actions,suspensions,delistings,industries,config,
                         rebalance_dates=schedule.execution_date.tolist(),rights=verified_rights())
            for name,frame in run.items():
                frame.to_csv(folder/f'{name}.csv',index=False)
            result=summarize(run['nav'],run['orders'],schedule.execution_date.iloc[0],pd.Timestamp('20160101'))
            result.update(strategy=label,config=asdict(config));results.append(result)
            monthly_returns(run['nav'].loc[run['nav'].date>=pd.Timestamp('20151231')].set_index('date').equity).to_csv(folder/'monthly_returns.csv')
            cost_breakdown(run['orders']).to_csv(folder/'cost_attribution.csv')
            status['status']='completed'
        except Exception as error:
            status.update(status='failed',error=str(error))
            (folder/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        summary=dict(experiments=results,experiment_statuses=statuses,source_sha256=core,
                     corrections=aliases+adj_corrections+action_corrections,scope='Opened development data, one approved candidate; no live broker')
        (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        (OUT/'status.json').write_text(json.dumps(statuses,indent=2),encoding='utf-8')
        print(label,status['status'],flush=True)
    return int(any(s['status']!='completed' for s in statuses))


if __name__=='__main__':
    raise SystemExit(main())
