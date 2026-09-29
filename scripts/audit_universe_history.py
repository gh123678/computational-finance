"""Audit every development signal date for historical name and industry coverage."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.factors import FACTORS, rank_scores, weekly_schedule


def unique_active(frame, date, value):
    stamp = date.strftime('%Y%m%d')
    active = frame.loc[(frame.start_date <= stamp) &
                       (frame.end_date.isna() | frame.end_date.ge(stamp))].copy()
    counts = active.groupby('ts_code')[value].nunique()
    return active.loc[active.ts_code.isin(counts[counts.eq(1)].index)].drop_duplicates('ts_code')


def audit_year(year, metadata, names, industries):
    dataset = f'development_{year}'
    data = ROOT / 'data' / dataset
    output = ROOT / 'output' / dataset
    calendar_raw = pd.read_csv(data / 'calendar.csv', dtype={'cal_date': str})
    calendar = pd.DatetimeIndex(pd.to_datetime(
        calendar_raw.loc[calendar_raw.is_open.eq(1), 'cal_date'], format='%Y%m%d')).sort_values()
    factors = pd.read_csv(output / 'factors.csv', parse_dates=['trade_date'])
    schedule = weekly_schedule(calendar)
    schedule = schedule.loc[schedule.execution_date.ge(pd.Timestamp(f'{year}-01-01')) &
                            schedule.execution_date.le(pd.Timestamp(f'{year}-12-31'))]
    coverage, candidates, industry_candidates = [], [], []
    for row in schedule.itertuples(index=False):
        date, stamp = row.signal_date, row.signal_date.strftime('%Y%m%d')
        listed = metadata.loc[(metadata.list_date <= stamp) &
                              (metadata.delist_date.isna() | metadata.delist_date.gt(stamp))].copy()
        listed_dates = pd.to_datetime(listed.list_date, format='%Y%m%d')
        age = calendar.searchsorted(date, side='right') - calendar.searchsorted(listed_dates)
        mature = listed.loc[age >= 120].copy()

        active_names = names.loc[(names.start_date <= stamp) &
                                 (names.end_date.isna() | names.end_date.ge(stamp)) &
                                 names.ann_date.notna() & names.ann_date.le(stamp)].copy()
        name_counts = active_names.groupby('ts_code').name.nunique()
        known_names = active_names.loc[active_names.ts_code.isin(name_counts[name_counts.eq(1)].index)].drop_duplicates('ts_code')
        non_st = known_names.loc[~known_names.name.str.contains('ST|^PT', case=False, na=True)]
        risk_codes = set(active_names.loc[
            active_names.name.str.contains('ST|^PT', case=False, na=False), 'ts_code'])

        active_industry = industries.loc[(industries.in_date <= stamp) &
                                         (industries.out_date.isna() | industries.out_date.gt(stamp))].copy()
        industry_counts = active_industry.groupby('ts_code').l1_code.nunique()
        known_industry = active_industry.loc[
            active_industry.ts_code.isin(industry_counts[industry_counts.eq(1)].index)].drop_duplicates('ts_code')

        factor = factors.loc[factors.trade_date.eq(date)].dropna(subset=FACTORS + ['adv20_cny'])
        liquid = factor.loc[factor.adv20_cny.ge(20_000_000)].copy()
        old_final_codes = set(mature.ts_code) & set(non_st.ts_code) & set(known_industry.ts_code)
        revised_codes = (set(mature.ts_code) - risk_codes) & set(known_industry.ts_code)
        old_final_factor = liquid.loc[liquid.ts_code.isin(old_final_codes)]
        revised_factor = liquid.loc[liquid.ts_code.isin(revised_codes)]

        missing_name_codes = set(mature.ts_code) - set(known_names.ts_code)
        missing_industry_codes = set(mature.ts_code) - set(known_industry.ts_code)
        missing_name_liquid = liquid.loc[liquid.ts_code.isin(missing_name_codes)].copy()

        rank_pool = liquid.loc[liquid.ts_code.isin(set(mature.ts_code) & set(known_industry.ts_code))].copy()
        ranked = rank_scores(rank_pool, columns=FACTORS).sort_values(
            ['score', 'ts_code'], ascending=[False, True]).reset_index(drop=True)
        ranked['unconstrained_rank'] = np.arange(1, len(ranked) + 1)
        at_risk = ranked.loc[ranked.ts_code.isin(missing_name_codes) & ranked.unconstrained_rank.le(40)]
        for item in at_risk.itertuples(index=False):
            meta = metadata.loc[metadata.ts_code.eq(item.ts_code)].iloc[0]
            candidates.append(dict(year=year, signal_date=str(date.date()), ts_code=item.ts_code,
                                   provider_current_name=meta['name'], unconstrained_rank=int(item.unconstrained_rank),
                                   score=float(item.score), adv20_cny=float(item.adv20_cny)))

        industry_rank_pool = liquid.loc[
            liquid.ts_code.isin(set(mature.ts_code) - risk_codes)].copy()
        industry_ranked = rank_scores(industry_rank_pool, columns=FACTORS).sort_values(
            ['score', 'ts_code'], ascending=[False, True]).reset_index(drop=True)
        industry_ranked['unconstrained_rank'] = np.arange(1, len(industry_ranked) + 1)
        industry_at_risk = industry_ranked.loc[
            industry_ranked.ts_code.isin(missing_industry_codes) &
            industry_ranked.unconstrained_rank.le(40)]
        for item in industry_at_risk.itertuples(index=False):
            meta = metadata.loc[metadata.ts_code.eq(item.ts_code)].iloc[0]
            industry_candidates.append(dict(
                year=year, signal_date=str(date.date()), ts_code=item.ts_code,
                provider_current_name=meta['name'], unconstrained_rank=int(item.unconstrained_rank),
                score=float(item.score), adv20_cny=float(item.adv20_cny)))

        coverage.append(dict(
            year=year, signal_date=str(date.date()), execution_date=str(row.execution_date.date()),
            listed_mainboard=len(listed), age_eligible=len(mature),
            known_name=len(set(mature.ts_code) & set(known_names.ts_code)),
            known_non_st_name=len(set(mature.ts_code) & set(non_st.ts_code)),
            known_industry=len(set(mature.ts_code) & set(known_industry.ts_code)),
            active_st_pt=len(set(mature.ts_code) & risk_codes),
            old_final_historical_eligible=len(old_final_codes),
            revised_historical_eligible=len(revised_codes),
            old_factor_liquidity_eligible=len(old_final_factor),
            revised_factor_liquidity_eligible=len(revised_factor),
            missing_name_age_eligible=len(missing_name_codes),
            missing_name_factor_liquid=len(missing_name_liquid),
            missing_industry_age_eligible=len(missing_industry_codes),
            missing_name_unconstrained_top40=len(at_risk),
            missing_industry_unconstrained_top40=len(industry_at_risk)))
    return coverage, candidates, industry_candidates


def main():
    audit = ROOT / 'data' / 'audit'
    metadata = pd.read_csv(audit / 'universe.csv', dtype=str)
    metadata = metadata.loc[metadata.market.eq('主板') &
                            metadata.ts_code.str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ)$')].copy()
    names = pd.read_csv(audit / 'name_history.csv', dtype=str)
    industries = pd.read_csv(audit / 'industry_history.csv', dtype=str)
    coverage, candidates, industry_candidates = [], [], []
    for year in range(2016, 2021):
        year_coverage, year_candidates, year_industry_candidates = audit_year(
            year, metadata, names, industries)
        coverage.extend(year_coverage)
        candidates.extend(year_candidates)
        industry_candidates.extend(year_industry_candidates)
    coverage = pd.DataFrame(coverage)
    candidates = pd.DataFrame(candidates)
    industry_candidates = pd.DataFrame(industry_candidates)
    if not industry_candidates.empty:
        industry_dates = industries.assign(
            _start=pd.to_datetime(industries.in_date, format='%Y%m%d', errors='coerce'),
            _end=pd.to_datetime(industries.out_date, format='%Y%m%d', errors='coerce'))

        def classify_gap(row):
            date = pd.Timestamp(row.signal_date)
            history = industry_dates.loc[industry_dates.ts_code.eq(row.ts_code)]
            active = history.loc[history._start.le(date) &
                                 (history._end.isna() | history._end.gt(date))]
            if active.l1_code.nunique() > 1:
                return 'overlap'
            if history._start.gt(date).all():
                return 'before_first'
            if (history._end.notna() & history._end.le(date)).all():
                return 'after_last'
            return 'between_intervals'

        industry_candidates['gap_type'] = industry_candidates.apply(classify_gap, axis=1)
    destination = ROOT / 'output' / 'universe_history_audit'
    destination.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(destination / 'weekly_coverage.csv', index=False)
    candidates.to_csv(destination / 'missing_name_top40.csv', index=False)
    industry_candidates.to_csv(destination / 'missing_industry_top40.csv', index=False)
    sources = {name: hashlib.sha256((audit / name).read_bytes()).hexdigest()
               for name in ('universe.csv', 'name_history.csv', 'industry_history.csv')}
    summary = []
    for year, frame in coverage.groupby('year'):
        summary.append(dict(
            year=int(year), signal_dates=len(frame),
            mean_name_coverage=float((frame.known_name / frame.age_eligible).mean()),
            minimum_name_coverage=float((frame.known_name / frame.age_eligible).min()),
            mean_industry_coverage=float((frame.known_industry / frame.age_eligible).mean()),
            minimum_industry_coverage=float((frame.known_industry / frame.age_eligible).min()),
            mean_active_st_pt=float(frame.active_st_pt.mean()),
            mean_old_historical_eligible=float(frame.old_final_historical_eligible.mean()),
            mean_revised_historical_eligible=float(frame.revised_historical_eligible.mean()),
            mean_old_factor_liquidity_eligible=float(frame.old_factor_liquidity_eligible.mean()),
            mean_revised_factor_liquidity_eligible=float(frame.revised_factor_liquidity_eligible.mean()),
            missing_name_factor_liquid_occurrences=int(frame.missing_name_factor_liquid.sum()),
            missing_name_top40_occurrences=int(frame.missing_name_unconstrained_top40.sum()),
            distinct_missing_name_top40=int(candidates.loc[candidates.year.eq(year), 'ts_code'].nunique()),
            missing_industry_top40_occurrences=int(
                frame.missing_industry_unconstrained_top40.sum()),
            distinct_missing_industry_top40=int(industry_candidates.loc[
                industry_candidates.year.eq(year), 'ts_code'].nunique())))
    result = dict(
        scope='All evaluation-year weekly signal dates; top40 is an unconstrained materiality screen, not a counterfactual portfolio',
        source_sha256=sources,
        industry_top40_gap_types=industry_candidates.gap_type.value_counts().to_dict(),
        distinct_missing_industry_top40=int(industry_candidates.ts_code.nunique()),
        years=summary)
    (destination / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
