"""One logical account across opened years; fixed existing rules, no broker use."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import traceback

import pandas as pd

from .accounting import normalize_actions
from .adjustment_audit import audit_adjustments, quarantine_factors
from .attribution import cost_breakdown, monthly_returns
from .backtest import Config, simulate, summarize
from .corporate_corrections import correct_actions, correct_adjustments, correct_limit_code_aliases
from .data import ROOT
from .datasets import dataset_config
from .factors import FACTORS, compute_factors, rank_scores, select_targets, select_buffered_targets, weekly_schedule, biweekly_schedule
from .research import read_market
from .rights import verified_rights
from .universe import historical_universe

MATRIX = [
    ('combined', FACTORS, 10), ('momentum20', ['momentum20'], 10),
    ('reversal5', ['reversal5'], 10), ('lowvol20', ['lowvol20'], 10),
    ('liquidity_control', ['adv20_cny'], 10), ('combined_slip30', FACTORS, 30),
    ('combined_slip50', FACTORS, 50), ('combined_zero_cost', FACTORS, 0),
    ('combined_rank_buffer40', FACTORS, 10), ('combined_biweekly', FACTORS, 10),
    ('combined_biweekly_zero_cost', FACTORS, 0), ('combined_biweekly_slip30', FACTORS, 30),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relevant_actions(dividends, bars):
    """No initial holdings: an event before the first quote cannot be owned."""
    first_quote = bars.groupby('ts_code').trade_date.min()
    first = dividends.ts_code.map(first_quote)
    ex = pd.to_datetime(dividends.ex_date, format='%Y%m%d')
    excluded = first.isna() | ex.lt(first)
    ignored = dividends.loc[excluded].copy()
    ignored['reason'] = 'No possible account holding before first observed quote'
    return dividends.loc[~excluded].copy(), ignored


def build_targets(snapshots, schedule, label, columns):
    buffered = label == 'combined_rank_buffer40' or 'biweekly' in label
    prior, plans = set(), []
    for row in schedule.itertuples(index=False):
        scores = rank_scores(snapshots[row.signal_date], columns=columns)
        selected = (select_buffered_targets(scores, prior, exit_rank=40)
                    if buffered else select_targets(scores))
        selected['signal_date'], selected['execution_date'] = row.signal_date, row.execution_date
        plans.append(selected)
        prior = set(selected.ts_code)
    return pd.concat(plans, ignore_index=True)


def main(until=None, revision=False):
    if until and revision:
        raise ValueError('Dividend revision uses the approved full window')
    name = 'continuous_2016_2025_dividend_r1' if revision else 'continuous_2016_2025'
    spec = dataset_config(name)
    root = ROOT / 'data' / name
    out = ROOT / 'output' / ('continuous_2016_2017_check' if until else name)
    out.mkdir(exist_ok=True)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    assert (manifest['start'], manifest['end']) == (spec['start'], spec['end'])
    for file, expected in manifest['files_sha256'].items():
        assert digest(root / file) == expected, file
    core = {p.name: digest(p) for p in (ROOT / 'quant_research').glob('*.py')}
    metadata_hash = {p.name: digest(p) for p in (ROOT / 'data/audit').glob('*.csv')}
    freeze = dict(dataset=name, until=until, initial_cash=1000000, source_sha256=core,
                  metadata_sha256=metadata_hash, data_manifest_sha256=digest(root/'manifest.json'),
                  design_sha256=digest(ROOT/'docs/superpowers/specs/2026-10-04-continuous-account-design.md'),
                  experiment_labels=[label for label, _, _ in MATRIX])
    if revision:
        freeze['revision_design_sha256'] = digest(ROOT/'docs/superpowers/specs/2026-10-05-dividend-data-revision-design.md')
    frozen_path = out / 'frozen_protocol.json'
    if frozen_path.exists():
        assert json.loads(frozen_path.read_text(encoding='utf-8')) == freeze, 'Frozen inputs changed'
    else:
        frozen_path.write_text(json.dumps(freeze, indent=2), encoding='utf-8')
    universe = pd.read_csv(ROOT/'data/audit/universe.csv', dtype=str)
    names = pd.read_csv(ROOT/'data/audit/name_history.csv', dtype=str)
    sectors = pd.read_csv(ROOT/'data/audit/industry_history.csv', dtype=str)
    full = pd.read_csv(root/'calendar.csv', dtype={'cal_date':str})
    full_calendar = pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    end = pd.Timestamp(until or spec['end'])
    calendar = full_calendar[(full_calendar >= pd.Timestamp(spec['start'])) & (full_calendar <= end)]
    print('Loading continuous market data', flush=True)
    pieces = []
    for frame in pd.read_csv(root/'daily.csv', usecols=['ts_code','trade_date','open','close','amount','vol'],
                             dtype={'ts_code':str,'trade_date':str}, chunksize=100000):
        frame = frame.loc[frame.trade_date.le(end.strftime('%Y%m%d')) & frame.ts_code.isin(universe.ts_code)].copy()
        frame.trade_date = pd.to_datetime(frame.trade_date)
        pieces.append(frame)
    bars = pd.concat(pieces, ignore_index=True)
    del pieces
    adj = read_market(root, 'adj_factor')
    bars = bars.merge(adj.loc[adj.trade_date <= end], on=['ts_code','trade_date'], validate='one_to_one')
    del adj
    limits, alias_corrections = correct_limit_code_aliases(read_market(root, 'stk_limit'))
    bars = bars.merge(limits.loc[limits.trade_date <= end], on=['ts_code','trade_date'], how='left', validate='one_to_one')
    del limits
    assert bars.adj_factor.notna().all()
    missing_limits = int(bars[['up_limit','down_limit']].isna().any(axis=1).sum())
    bars, adjustment_corrections = correct_adjustments(bars)
    dividends, action_corrections = correct_actions(pd.read_csv(root/'dividend.csv', dtype=str))
    dividends, unowned_actions = relevant_actions(dividends, bars)
    unowned_actions.to_csv(out/'unowned_prequote_actions.csv', index=False)
    actions = normalize_actions(dividends, set(bars.ts_code))
    rights = verified_rights()
    issues = audit_adjustments(bars, actions, rights)
    issues.to_csv(out/'unexplained_adjustments.csv', index=False)
    print('Computing continuous factors', flush=True)
    price = bars.loc[bars.vol.gt(0), ['ts_code','trade_date','close','adj_factor','amount','vol']].copy()
    price.trade_date = price.trade_date.dt.strftime('%Y%m%d')
    factors = compute_factors(price, calendar)
    del price
    factors, quarantine_count = quarantine_factors(factors, issues, calendar)
    factors.to_csv(out/'factors.csv', index=False)
    weekly = weekly_schedule(calendar)
    snapshots, industries = {}, {}
    # Keep the same published-event exclusions and historical industry logic.
    for date in calendar:
        stamp = date.strftime('%Y%m%d')
        sector = sectors.loc[(sectors.in_date <= stamp) & (sectors.out_date.isna() | (sectors.out_date > stamp))]
        count = sector.groupby('ts_code').l1_code.nunique()
        sector = sector.loc[sector.ts_code.isin(count[count == 1].index)].drop_duplicates('ts_code')
        industries[date] = dict(zip(sector.ts_code, sector.l1_code))
    grouped = {d:g for d,g in factors.groupby('trade_date')}
    for row in weekly.itertuples(index=False):
        available = historical_universe(row.signal_date, universe, names, sectors, full_calendar)
        frame = grouped[row.signal_date].dropna(subset=FACTORS)
        snapshots[row.signal_date] = frame.loc[frame.adv20_cny >= 20000000].merge(
            available[['ts_code','industry']], on='ts_code', validate='one_to_one')
    del factors, grouped
    first = pd.Timestamp(spec['evaluation_start'])
    schedules = {False: weekly.loc[weekly.execution_date >= first],
                 True: biweekly_schedule(calendar).loc[lambda f:f.execution_date >= first]}
    suspension = read_market(root,'suspend_d')
    suspensions = set(suspension.loc[suspension.suspend_type.eq('S'), ['trade_date','ts_code']].itertuples(index=False,name=None))
    del suspension
    delistings = dict(zip(universe.ts_code, pd.to_datetime(universe.delist_date)))
    summaries, statuses = [], []
    for label, columns, slippage in MATRIX:
        assert {p.name:digest(p) for p in (ROOT/'quant_research').glob('*.py')} == core
        folder = out/label
        folder.mkdir(exist_ok=True)
        status = dict(strategy=label, status='running')
        statuses.append(status)
        (out/'status.json').write_text(json.dumps(statuses,indent=2),encoding='utf-8')
        print('Continuous experiment:',label,flush=True)
        schedule = schedules['biweekly' in label]
        targets = build_targets(snapshots,schedule,label,columns)
        targets.to_csv(folder/'historical_targets.csv',index=False)
        config = Config(slippage_bps=slippage, zero_trading_costs=label in ('combined_zero_cost','combined_biweekly_zero_cost'))
        try:
            # Only targeted securities can become held or acquire share rights;
            # their complete price histories preserve ADV and valuation state.
            simulation_bars = bars.loc[bars.ts_code.isin(set(targets.ts_code))]
            invalid = simulation_bars.loc[(simulation_bars[['open','close','adj_factor']]<=0).any(axis=1)
                                          | (simulation_bars[['amount','vol']]<0).any(axis=1)]
            if not invalid.empty:
                invalid.to_csv(folder/'invalid_market_rows.csv',index=False)
                raise ValueError(f'Invalid source market rows: {len(invalid)}; see invalid_market_rows.csv')
            run = simulate(simulation_bars,calendar,targets,actions,suspensions,delistings,industries,config,
                           rebalance_dates=schedule.execution_date.tolist(),rights=rights)
            for file,frame in run.items():
                frame.to_csv(folder/(file+'.csv'),index=False)
            result = summarize(run['nav'],run['orders'],schedule.execution_date.iloc[0],first)
            result.update(strategy=label,config=asdict(config))
            monthly_returns(run['nav'].loc[run['nav'].date>=pd.Timestamp('2015-12-31')].set_index('date').equity).to_csv(folder/'monthly_returns.csv')
            cost_breakdown(run['orders']).to_csv(folder/'cost_attribution.csv')
            summaries.append(result)
            status['status']='completed'
            del run, simulation_bars
        except (ValueError, AssertionError, MemoryError) as error:
            status.update(status='failed',error=str(error))
            (folder/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        (out/'status.json').write_text(json.dumps(statuses,indent=2),encoding='utf-8')
        summary=dict(dataset=name,until=until,initial_capital=1000000,source_sha256=core,
                     metadata_sha256=metadata_hash,data_manifest=manifest,experiments=summaries,
                     experiment_statuses=statuses,unexplained_adjustments=len(issues),
                     quarantined_factor_rows=quarantine_count,missing_price_limit_rows=missing_limits,
                     corrections=alias_corrections+adjustment_corrections+action_corrections,
                     scope='One continuous account; opened data, no new holdout and no live recommendation')
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(label,status['status'],flush=True)
    return int(any(s['status']!='completed' for s in statuses))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--until',choices=['20171231'])
    parser.add_argument('--revision',action='store_true')
    args=parser.parse_args()
    raise SystemExit(main(args.until,args.revision))
