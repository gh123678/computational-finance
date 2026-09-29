"""Rebuild course diagnostics from frozen development data, without rerunning trades."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from quant_research.research import diagnostics, read_market
from quant_research.factors import FACTORS, weekly_schedule
from quant_research.universe import historical_universe
from quant_research.corporate_corrections import correct_adjustments


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    dest = ROOT / 'output/project1_revision'
    dest.mkdir(exist_ok=True)
    metadata = pd.read_csv(ROOT / 'data/audit/universe.csv', dtype=str)
    names = pd.read_csv(ROOT / 'data/audit/name_history.csv', dtype=str)
    sectors = pd.read_csv(ROOT / 'data/audit/industry_history.csv', dtype=str)
    manifest = {'scope': 'Recomputed diagnostics only; portfolio accounting and saved trading results unchanged.',
                'group_rule': 'Formation-date average percentile rank; ceil(rank*5); original membership retained; at least 2 valid labels per group.',
                'ic_rule': 'At least 10 labels and nonconstant factor and return; otherwise NaN.', 'years': {},
                'code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__), ROOT/'quant_research/research.py']}}
    for year in [2018, 2019, 2020]:
        old = ROOT / f'output/development_{year}'
        source = ROOT / f'data/development_{year}'
        out = dest / str(year)
        out.mkdir(exist_ok=True)
        summary = json.loads((old/'summary.json').read_text(encoding='utf-8'))
        for name, checksum in summary['data_manifest']['files_sha256'].items():
            assert sha(source/name) == checksum, f'Changed input: {source/name}'
        for name, checksum in summary['metadata_sha256'].items():
            assert sha(ROOT/'data/audit'/name) == checksum, f'Changed metadata: {name}'
        cal = pd.read_csv(source/'calendar.csv', dtype={'cal_date': str})
        full = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1), 'cal_date'])).sort_values()
        calendar = full[(full >= pd.Timestamp(summary['data_manifest']['start'])) & (full <= pd.Timestamp(summary['data_manifest']['end']))]
        schedule = weekly_schedule(calendar)
        schedule = schedule.loc[schedule.execution_date >= pd.Timestamp(summary['first_execution'])]
        factors = pd.read_csv(old/'factors.csv', parse_dates=['trade_date'])
        bars = read_market(source, 'daily')
        bars = bars.loc[bars.ts_code.isin(metadata.ts_code) & bars.ts_code.str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ)$')].copy()
        bars = bars.merge(read_market(source, 'adj_factor'), on=['trade_date','ts_code'], validate='one_to_one')
        bars, _ = correct_adjustments(bars)
        snapshots, coverage = {}, []
        for row in schedule.itertuples(index=False):
            available = historical_universe(row.signal_date, metadata, names, sectors, full)
            date_factors = factors.loc[factors.trade_date.eq(row.signal_date)]
            eligible = date_factors.merge(available[['ts_code', 'industry']], on='ts_code', validate='one_to_one')
            frame = eligible.dropna(subset=FACTORS)
            frame = frame.loc[frame.adv20_cny >= 20_000_000].copy()
            snapshots[row.signal_date] = frame
            for factor in FACTORS:
                coverage.append(dict(date=row.signal_date, factor=factor, historical_eligible=len(available),
                                     nonmissing=int(eligible[factor].notna().sum()), selected=len(frame),
                                     coverage=float(eligible[factor].notna().sum()/len(available)) if len(available) else np.nan))
        ic, groups = diagnostics(snapshots, bars, schedule)
        ic.to_csv(out/'factor_ic.csv', index=False)
        groups.to_csv(out/'factor_groups.csv', index=False)
        pd.DataFrame(coverage).to_csv(out/'factor_coverage.csv', index=False)
        long = pd.concat(snapshots.values(), ignore_index=True).melt(id_vars=['trade_date','ts_code'], value_vars=FACTORS,
                     var_name='factor', value_name='value').rename(columns={'trade_date':'date','ts_code':'asset'})
        long.to_csv(out/'formation_factors_long.csv', index=False)
        old_ic = pd.read_csv(old/'factor_ic.csv', parse_dates=['signal_date'])
        joined = ic.merge(old_ic, on=['signal_date','factor'], suffixes=('_new','_old'))
        assert len(joined) == len(old_ic) == len(ic)
        delta = float((joined.ic_new-joined.ic_old).abs().max())
        assert delta < 1e-12
        old_g = pd.read_csv(old/'factor_groups.csv', parse_dates=['signal_date'])
        compared = groups.merge(old_g, on=['signal_date','factor','group'], suffixes=('_new','_old'))
        max_group_delta = float((compared.mean_forward_return_new-compared.mean_forward_return_old).abs().max())
        missing = int((ic.n_formed-ic.n).sum()/3)
        numeric = bars[['open','high','low','close','vol','amount','adj_factor']]
        quality = dict(rows=len(bars), duplicate_keys=int(bars.duplicated(['trade_date','ts_code']).sum()),
                       missing_numeric=int(numeric.isna().sum().sum()), nonpositive_prices=int((numeric[['open','high','low','close','adj_factor']]<=0).any(axis=1).sum()),
                       negative_volume_amount=int((numeric[['vol','amount']]<0).any(axis=1).sum()),
                       zero_volume_rows=int(bars.vol.eq(0).sum()), quarantined_rows=summary['quarantined_factor_rows'],
                       missing_price_limit_rows=summary['missing_price_limit_rows'])
        (out/'quality.json').write_text(json.dumps(quality,indent=2), encoding='utf-8')
        manifest['years'][str(year)] = dict(summary_sha256=sha(old/'summary.json'), factors_sha256=sha(old/'factors.csv'),
                                          ic_max_change=delta, group_max_change=max_group_delta, missing_labels=missing,
                                          outputs_sha256={p.name:sha(p) for p in out.glob('*') if p.is_file()})
        print(year, 'IC unchanged; missing labels:',missing,'max group change:',max_group_delta,flush=True)
    (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
