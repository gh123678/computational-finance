"""Historical integration sample, NOT a strategy backtest or live recommendation."""
import json
import pandas as pd
from .data import ROOT, TushareClient, load_token, DataError
from .audit import table
from .factors import compute_factors, rank_scores, select_targets, FACTORS


def main():
    # Fixed window in development data. Do not inspect the sealed 2024-2025 test set.
    start, end, selection_date = '20201001', '20201231', '20200930'
    client = TushareClient(load_token())
    root = ROOT / 'data' / 'audit'
    universe = pd.read_csv(root / 'universe.csv', dtype=str)
    names = pd.read_csv(root / 'name_history.csv', dtype=str)
    industry = pd.read_csv(root / 'industry_history.csv', dtype=str)
    eligible = universe.loc[(universe.list_date < '20190101') &
                           (universe.delist_date.isna() | (universe.delist_date > selection_date)) &
                           universe.ts_code.str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ)$')]
    known_names = names.loc[(names.start_date <= selection_date) &
                           (names.end_date.isna() | (names.end_date >= selection_date)) &
                           names.ann_date.notna() & (names.ann_date <= selection_date)]
    counts = known_names.groupby('ts_code').name.nunique()
    known_names = known_names.loc[known_names.ts_code.isin(counts[counts == 1].index)]
    known_names = known_names.loc[~known_names.name.str.contains('ST', case=False, na=True)]
    active = industry.loc[(industry.in_date <= selection_date) &
                          (industry.out_date.isna() | (industry.out_date > selection_date))]
    counts = active.groupby('ts_code').l1_code.nunique()
    active = active.loc[active.ts_code.isin(counts[counts == 1].index)].drop_duplicates('ts_code')
    selected = eligible.loc[eligible.ts_code.isin(known_names.ts_code)].merge(active[['ts_code', 'l1_code']], on='ts_code')
    # Deterministic industry-diverse fixture, not factor-selected and not representative.
    selected = selected.sort_values(['l1_code', 'ts_code']).groupby('l1_code', sort=True).head(1).head(30)
    if len(selected) < 20:
        raise DataError('Insufficient verifiable historical fixture assets.')
    cal = table(client.query('trade_cal', {'exchange': 'SSE', 'start_date': start, 'end_date': end}))
    calendar = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1), 'cal_date'], format='%Y%m%d')).sort_values()
    frames = []
    for code in selected.ts_code:
        params = {'ts_code': code, 'start_date': start, 'end_date': end}
        daily = table(client.query('daily', params))
        adj = table(client.query('adj_factor', params))
        if daily.empty:
            print(f'{code}: no daily bars, excluded from fixture', flush=True)
            continue
        joined = daily.merge(adj, on=['ts_code', 'trade_date'], how='left', validate='one_to_one')
        if joined.adj_factor.isna().any():
            raise DataError(f'{code}: missing adjustment factors')
        frames.append(joined)
        print(f'{code}: {len(joined)} daily bars', flush=True)
    bars = pd.concat(frames, ignore_index=True)
    factors = compute_factors(bars, calendar)
    date = end
    known = names.loc[(names.start_date <= date) & (names.end_date.isna() | (names.end_date >= date)) &
                      names.ann_date.notna() & (names.ann_date <= date)]
    counts = known.groupby('ts_code').name.nunique()
    known = known.loc[known.ts_code.isin(counts[counts == 1].index)]
    known = known.loc[~known.name.str.contains('ST', case=False, na=True)]
    active = industry.loc[(industry.in_date <= date) & (industry.out_date.isna() | (industry.out_date > date))]
    counts = active.groupby('ts_code').l1_code.nunique()
    active = active.loc[active.ts_code.isin(counts[counts == 1].index)].drop_duplicates('ts_code')
    snapshot = factors.loc[(factors.trade_date == calendar[-1]) &
                           factors.ts_code.isin(known.ts_code) & (factors.adv20_cny >= 20_000_000)].copy()
    snapshot = snapshot.merge(active[['ts_code', 'l1_code']].rename(columns={'l1_code': 'industry'}), on='ts_code')
    scored = rank_scores(snapshot)
    targets = select_targets(scored)
    output = ROOT / 'output' / 'historical_integration_sample'
    output.mkdir(parents=True, exist_ok=True)
    factors.to_csv(output / 'factors.csv', index=False)
    targets.to_csv(output / 'historical_targets_NOT_LIVE.csv', index=False)
    summary = {'purpose': 'Historical integration sample only; NOT a backtest, recommendation, or full universe.',
               'start': start, 'end': end, 'sample_selection_date': selection_date,
               'sample_rule': 'First code in each known industry, max 30; selected before the sample window.',
               'sample_assets': int(bars.ts_code.nunique()), 'bar_rows': len(bars),
               'calendar_sessions': len(calendar), 'complete_factor_rows': len(factors.dropna(subset=FACTORS)),
               'last_date_eligible': len(scored), 'last_date_targets': len(targets),
               'target_weight_sum': float(targets.target_weight.sum()),
               'limitations': ['Sample is small and deliberately industry-diverse.',
                               'Industry interval publication/vintage unverified.',
                               'No cash/share NAV ledger or corporate action accounting in this sample.',
                               'No performance metrics or evidence of profitability.']}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
