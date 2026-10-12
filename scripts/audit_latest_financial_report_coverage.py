"""Offline scope audit: latest report evidence, never financial consumption."""
from pathlib import Path
from collections import Counter
import json
import pandas as pd
import announcement_financial_audit as audit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/latest_financial_report_coverage_20261012_r1'
RECORDS = ROOT / 'output/announcement_financial_audit_20261007/fina_indicator_records.csv'
SIGNALS = audit.SOURCE / 'common_samples.csv'
CONTENT = ROOT / 'output/financial_field_visual_review_20261012_r1'


def publication_states(keys):
    """Retain newest report period; an older report's later publication cannot replace it."""
    states = []
    for code, group in keys.groupby('ts_code', sort=True):
        latest_period = ''
        for ann, batch in group.groupby('ann_date', sort=True):
            period = batch.end_date.max()
            if period < latest_period:
                continue
            latest_period = period
            row = batch.loc[batch.end_date.eq(period)].iloc[0].to_dict()
            states.append(row)
    return pd.DataFrame(states, columns=keys.columns)


def align_states(signals, states):
    # Signals are verified open sessions. Strict date inequality gives the
    # same candidate boundary as next-open-day visibility at those sessions.
    left = signals.copy()
    right = states.copy()
    left['signal_date'] = pd.to_datetime(left.trade_date, format='%Y-%m-%d')
    right['publication_date'] = pd.to_datetime(right.ann_date, format='%Y%m%d')
    result = pd.merge_asof(left.sort_values(['signal_date', 'ts_code']),
        right.sort_values(['publication_date', 'ts_code']), by='ts_code',
        left_on='signal_date', right_on='publication_date', direction='backward',
        allow_exact_matches=False)
    result['usable_in_verified_history'] = False
    result['selected_financial_value'] = None
    result['verified_publication_day'] = None
    return result


def main():
    if OUT.exists():
        raise RuntimeError('Existing snapshot: inspect it; do not overwrite')
    OUT.mkdir()
    inputs = [RECORDS, SIGNALS, CONTENT/'field_ledger_current_content_checkpoint07.json',
        CONTENT/'artifact_sha256.json', ROOT/'data/continuous_2016_2025_dividend_r1/calendar.csv',
        Path(__file__)]
    before = {str(p.relative_to(ROOT)): audit.sha(p) for p in inputs}
    old = audit.verify_old()
    for rel, digest in json.loads((CONTENT/'artifact_sha256.json').read_text(encoding='utf-8')).items():
        if audit.sha(CONTENT/rel) != digest:
            raise ValueError('Frozen content review artifact changed: '+rel)
    raw = pd.read_csv(RECORDS, dtype=str, keep_default_na=False)
    signals = pd.read_csv(SIGNALS, dtype=str, usecols=['ts_code', 'trade_date'])
    if signals.duplicated(['ts_code', 'trade_date']).any():
        raise ValueError('Duplicate signal key')
    calendar = pd.read_csv(inputs[4], dtype=str)
    opened = set(calendar.loc[calendar.is_open.eq('1'), 'cal_date'])
    if not set(signals.trade_date.str.replace('-', '', regex=False)) <= opened:
        raise ValueError('Signal outside verified open calendar')
    for col in ['ann_date', 'end_date']:
        pd.to_datetime(raw[col], format='%Y%m%d', errors='raise')
    # Preserve all raw rows. Only the approved announcement window is inspected.
    candidate = raw.loc[raw.ann_date.between('20130101', '20201231')].copy()
    invalid_order = candidate.end_date.gt(candidate.ann_date)
    candidate.loc[invalid_order].to_csv(OUT/'invalid_report_date_order.csv', index=False)
    candidate = candidate.loc[~invalid_order].copy()
    candidate['profit_present'] = candidate.profit_dedt.ne('')
    candidate['profit_numeric'] = pd.to_numeric(candidate.profit_dedt, errors='coerce')
    bad_numeric = candidate.profit_present & candidate.profit_numeric.isna()
    if bad_numeric.any():
        raise ValueError('Non-numeric nonempty profit_dedt')
    keys = candidate.groupby(['ts_code', 'ann_date', 'end_date'], sort=True).agg(
        version_rows=('row_sha256', 'size'),
        nonempty_profit_rows=('profit_present', 'sum'),
        distinct_profit_values=('profit_numeric', 'nunique'),
        distinct_content_versions=('content_sha256', 'nunique')).reset_index()
    evidence = json.loads((CONTENT/'field_ledger_current_content_checkpoint07.json').read_text(encoding='utf-8'))
    reviewed = {(r['ts_code'], r['vendor_ann_date'], r['target_review_period']):r for r in evidence}
    keys['has_166_key_content_record'] = [tuple(x) in reviewed for x in keys[['ts_code','ann_date','end_date']].itertuples(index=False, name=None)]
    keys['same_day_profit_conflict'] = keys.distinct_profit_values.gt(1)
    keys['profit_missing_all_versions'] = keys.nonempty_profit_rows.eq(0)
    keys['partly_missing_profit_versions'] = keys.nonempty_profit_rows.lt(keys.version_rows) & keys.nonempty_profit_rows.gt(0)
    states = publication_states(keys)
    joined = align_states(signals, states)
    # Diagnostic comparator: newest publication batch alone can point to an old period.
    naive_states = keys.sort_values(['ts_code','ann_date','end_date']).drop_duplicates(['ts_code','ann_date'], keep='last')
    naive = align_states(signals, naive_states)[['ts_code','trade_date','end_date']].rename(columns={'end_date':'latest_publication_only_period'})
    joined = joined.merge(naive, on=['ts_code','trade_date'], validate='one_to_one')
    joined['older_report_would_shadow_latest_period'] = joined.end_date.notna() & joined.latest_publication_only_period.notna() & joined.end_date.gt(joined.latest_publication_only_period)
    joined['year'] = joined.signal_date.dt.year
    joined['report_age_calendar_days'] = (joined.signal_date-pd.to_datetime(joined.end_date, format='%Y%m%d', errors='coerce')).dt.days
    joined['coverage_status'] = 'no_prior_api_candidate'
    present = joined.end_date.notna()
    joined.loc[present, 'coverage_status'] = 'latest_report_api_candidate_only'
    joined.loc[present & joined.profit_missing_all_versions.eq(True), 'coverage_status'] = 'latest_report_profit_missing'
    joined.loc[present & joined.same_day_profit_conflict.eq(True), 'coverage_status'] = 'latest_report_profit_version_conflict'
    summaries = []
    for year,g in joined.groupby('year'):
        summaries.append(dict(year=int(year),signal_stock_rows=len(g),api_candidate_rows=int(g.end_date.notna().sum()),
            scoped_166_key_record_rows=int(g.has_166_key_content_record.eq(True).sum()),
            latest_profit_conflict_rows=int(g.same_day_profit_conflict.eq(True).sum()),
            latest_profit_missing_rows=int(g.profit_missing_all_versions.eq(True).sum()),
            older_report_shadow_rows=int(g.older_report_would_shadow_latest_period.sum()),
            verified_history_rows=0,status_counts=dict(Counter(g.coverage_status))))
    joined.drop(columns=['signal_date','publication_date']).to_csv(OUT/'signal_latest_report_evidence.csv.gz', index=False, compression='gzip')
    keys.to_csv(OUT/'dated_report_key_inventory.csv.gz', index=False, compression='gzip')
    states.to_csv(OUT/'latest_report_publication_states.csv.gz', index=False, compression='gzip')
    audit.write_json(OUT/'yearly_summary.json', summaries)
    summary = dict(raw_rows=len(raw),raw_codes=raw.ts_code.nunique(),raw_dated_keys=len(raw[['ts_code','ann_date','end_date']].drop_duplicates()),
        in_window_rows=len(candidate),excluded_invalid_date_order_rows=int(invalid_order.sum()),
        in_window_dated_keys=len(keys),signal_stock_rows=len(signals),signal_dates=signals.trade_date.nunique(),
        scoped_166_key_record_signal_rows=int(joined.has_166_key_content_record.eq(True).sum()),
        latest_profit_conflict_signal_rows=int(joined.same_day_profit_conflict.eq(True).sum()),
        latest_profit_missing_signal_rows=int(joined.profit_missing_all_versions.eq(True).sum()),
        older_report_shadow_signal_rows=int(joined.older_report_would_shadow_latest_period.sum()),
        historical_approvals=0,new_models=0,new_backtests=0,
        limitation='166-key content-record link is not full content verification or historical approval; versions retained, no values selected')
    assert not joined.usable_in_verified_history.any() and joined.selected_financial_value.isna().all()
    for path,digest in before.items():
        if audit.sha(ROOT/path)!=digest:raise ValueError('Input changed during audit: '+path)
    audit.write_json(OUT/'summary.json', summary)
    audit.write_json(OUT/'input_sha256.json', before)
    audit.write_json(OUT/'verification.json',dict(inputs_unchanged=True,old_experiments=old,history_gates_closed=True))
    print(json.dumps(summary, ensure_ascii=False))


if __name__=='__main__':
    main()
