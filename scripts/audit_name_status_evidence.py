"""Audit retrospective risk-interval exits; does not alter trading results.

An expired ST interval without a known ordinary-name successor is an evidence
gap, not proof that the stock was ST. Only registered development years are read.
"""
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.universe import historical_universe


def main():
    source = ROOT / 'data' / 'audit'
    destination = ROOT / 'output' / 'name_status_evidence_audit'
    destination.mkdir(parents=True, exist_ok=True)
    names = pd.read_csv(source / 'name_history.csv', dtype=str)
    metadata = pd.read_csv(source / 'universe.csv', dtype=str)
    industries = pd.read_csv(source / 'industry_history.csv', dtype=str)
    risk = names.name.str.contains('ST|^PT', case=False, na=False)
    rows, selections, years = [], [], []
    input_hashes = {}
    for year in range(2016, 2021):
        folder = ROOT / 'output' / f'development_{year}'
        coverage = pd.read_csv(folder / 'coverage.csv', dtype=str)
        cal = pd.read_csv(ROOT / 'data' / f'development_{year}' / 'calendar.csv', dtype=str)
        calendar = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq('1'), 'cal_date'])).sort_values()
        targets = []
        for target_path in sorted(folder.glob('*/historical_targets.csv')):
            table = pd.read_csv(target_path, dtype={'ts_code': str})
            table['strategy'] = target_path.parent.name
            table['signal_date'] = pd.to_datetime(table.signal_date).dt.strftime('%Y%m%d')
            targets.append(table[['strategy', 'signal_date', 'ts_code']])
            input_hashes[str(target_path.relative_to(ROOT))] = hashlib.sha256(target_path.read_bytes()).hexdigest()
        targets = pd.concat(targets, ignore_index=True)
        # Keep the same evaluation-year schedule as the research run.
        eval_coverage = coverage.loc[pd.to_datetime(coverage.execution_date).dt.year.eq(year)]
        dates = pd.to_datetime(eval_coverage.signal_date).sort_values().unique()
        year_rows = []
        for date in dates:
            stamp = pd.Timestamp(date).strftime('%Y%m%d')
            known = names.loc[names.start_date.le(stamp) & names.ann_date.notna() & names.ann_date.le(stamp)]
            known_risk = known.loc[risk.reindex(known.index)]
            active_risk_codes = set(known_risk.loc[
                known_risk.end_date.isna() | known_risk.end_date.ge(stamp), 'ts_code'])
            latest_risk = known_risk.sort_values(['start_date', 'ann_date']).drop_duplicates('ts_code', keep='last')
            expired = latest_risk.loc[latest_risk.end_date.notna() & latest_risk.end_date.lt(stamp)]
            ordinary = known.loc[~risk.reindex(known.index)]
            latest_ordinary = ordinary.groupby('ts_code').start_date.max()
            # A successor must start after the risk period, and be known by date.
            evidence_gap = expired.loc[
                expired.ts_code.map(latest_ordinary).fillna('').le(expired.end_date) &
                ~expired.ts_code.isin(active_risk_codes)]
            available = historical_universe(date, metadata, names, industries, calendar)
            evidence_gap = evidence_gap.loc[evidence_gap.ts_code.isin(available.ts_code)]
            codes = set(evidence_gap.ts_code)
            day_targets = targets.loc[targets.signal_date.eq(stamp)]
            exposed = day_targets.loc[day_targets.ts_code.isin(codes)]
            for record in evidence_gap.itertuples(index=False):
                rows.append(dict(year=year, signal_date=stamp, ts_code=record.ts_code,
                                 last_risk_name=record.name, risk_start=record.start_date,
                                 risk_end=record.end_date, risk_ann_date=record.ann_date))
            for record in exposed.itertuples(index=False):
                selections.append(dict(year=year, signal_date=stamp, strategy=record.strategy,
                                       ts_code=record.ts_code))
            year_rows.append(dict(signal_date=stamp, admitted_with_exit_evidence_gap=len(codes),
                                  target_occurrences=len(exposed),
                                  combined_target_occurrences=int(exposed.strategy.eq('combined').sum())))
        frame = pd.DataFrame(year_rows)
        years.append(dict(year=year, signal_dates=len(frame),
                          evidence_gap_stock_weeks=int(frame.admitted_with_exit_evidence_gap.sum()),
                          maximum_gap_codes_per_week=int(frame.admitted_with_exit_evidence_gap.max()),
                          target_occurrences=int(frame.target_occurrences.sum()),
                          combined_target_occurrences=int(frame.combined_target_occurrences.sum())))
    pd.DataFrame(rows, columns=['year', 'signal_date', 'ts_code', 'last_risk_name',
                               'risk_start', 'risk_end', 'risk_ann_date']).to_csv(
        destination / 'expired_risk_without_known_successor.csv', index=False)
    selected = pd.DataFrame(selections, columns=['year', 'signal_date', 'strategy', 'ts_code'])
    selected.to_csv(destination / 'affected_targets.csv', index=False)
    result = dict(
        scope='Development 2016-2020 only; diagnostic evidence gaps, not verified ST classifications',
        late_risk_announcements=int((names.loc[risk, 'ann_date'] > names.loc[risk, 'start_date']).sum()),
        missing_risk_announcements=int(names.loc[risk, 'ann_date'].isna().sum()),
        duplicate_name_rows=int(names.duplicated().sum()),
        years=years,
        source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (source / 'universe.csv', source / 'name_history.csv', source / 'industry_history.csv')},
        target_sha256=input_hashes,
    )
    (destination / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'target_sha256'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
