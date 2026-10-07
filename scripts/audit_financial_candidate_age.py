"""Publication-age coverage only; never selects financial values or grants approval."""
import json
from pathlib import Path
import sys
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit


def candidate_age(signals, records, units):
    signals = signals[['trade_date', 'ts_code']].copy()
    signals['trade_date'] = pd.to_datetime(signals.trade_date)
    records = records.copy()
    records['candidate_available_date'] = pd.to_datetime(records.candidate_available_date, errors='coerce')
    records['ann_date_parsed'] = pd.to_datetime(records.ann_date, format='%Y%m%d', errors='coerce')
    records = records.loc[records.candidate_available_date.notna()]
    keys = ['ts_code', 'ann_date', 'end_date']
    records['same_date_content_conflict'] = records.groupby(keys).content_sha256.transform('nunique').gt(1)
    # Group whole publication batches: no tie-breaking between competing numeric versions.
    latest = records.groupby(['ts_code', 'candidate_available_date']).agg(
        latest_candidate_ann_date=('ann_date_parsed', 'max'),
        oldest_ann_date_in_batch=('ann_date_parsed', 'min'),
        candidate_batch_rows=('row_sha256', 'count'),
        candidate_batch_content_versions=('content_sha256', 'nunique'),
        candidate_batch_has_content_conflict=('same_date_content_conflict', 'any')).reset_index()
    if latest.empty:
        joined = signals.copy()
        for field in latest.columns:
            if field != 'ts_code': joined[field] = pd.NaT if 'date' in field else None
    else:
        joined = pd.merge_asof(signals.sort_values(['trade_date', 'ts_code']),
            latest.sort_values(['candidate_available_date', 'ts_code']),
            left_on='trade_date', right_on='candidate_available_date', by='ts_code', direction='backward')
    joined['download_unit_status'] = joined.ts_code.map(units.set_index('ts_code').status)
    has = joined.candidate_available_date.notna()
    joined['coverage_status'] = 'successful_query_no_prior_candidate'
    joined.loc[joined.download_unit_status.eq('success_empty'), 'coverage_status'] = 'successful_empty_query'
    joined.loc[joined.download_unit_status.isna() | joined.download_unit_status.eq('not_completed'), 'coverage_status'] = 'download_not_completed'
    joined.loc[has, 'coverage_status'] = 'unverified_api_candidate'
    joined['latest_candidate_ann_age_calendar_days'] = (joined.trade_date - joined.latest_candidate_ann_date).dt.days
    joined['candidate_available_age_calendar_days'] = (joined.trade_date - joined.candidate_available_date).dt.days
    joined['usable_in_verified_history'] = False
    return joined.sort_values(['trade_date', 'ts_code'])


def main():
    protocol = audit.initialize()
    old = audit.verify_old()
    out = audit.OUT
    inputs = [out/'analysis_status.json', out/'stock_api_coverage.csv', audit.SOURCE/'common_samples.csv']
    inputs += [out/f'{api}_records.csv' for api in audit.APIS]
    input_sha = {str(p.relative_to(audit.ROOT)): audit.sha(p) for p in inputs}
    signal = pd.read_csv(audit.SOURCE/'common_samples.csv', usecols=['trade_date','ts_code'], dtype={'ts_code':str})
    units = pd.read_csv(out/'stock_api_coverage.csv', dtype={'ts_code':str})
    summaries = []
    filename = out/'signal_candidate_age.csv.gz'
    # One pass writes a compressed detail table; input CSVs are a fixed analysis snapshot.
    import gzip
    with gzip.open(filename, 'wt', encoding='utf-8', newline='') as stream:
        for index, api in enumerate(audit.APIS):
            records = pd.read_csv(out/f'{api}_records.csv', dtype=str, usecols=[
                'ts_code','ann_date','end_date','candidate_available_date','row_sha256','content_sha256'])
            joined = candidate_age(signal, records, units.loc[units.api.eq(api)])
            has = joined.candidate_available_date.notna()
            assert joined.loc[has, 'candidate_available_date'].le(joined.loc[has, 'trade_date']).all()
            assert joined.loc[has, 'latest_candidate_ann_date'].lt(joined.loc[has, 'candidate_available_date']).all()
            assert not joined.usable_in_verified_history.any()
            assert not joined.loc[has, 'download_unit_status'].eq('not_completed').any()
            joined.insert(0, 'api', api)
            joined.to_csv(stream, index=False, header=index == 0)
            for year, g in joined.groupby(joined.trade_date.dt.year):
                age = g.latest_candidate_ann_age_calendar_days.dropna()
                summaries.append(dict(api=api, year=int(year), stock_signal_rows=len(g),
                    unverified_candidate_rows=int(g.candidate_available_date.notna().sum()),
                    download_not_completed_rows=int(g.coverage_status.eq('download_not_completed').sum()),
                    successful_empty_query_rows=int(g.coverage_status.eq('successful_empty_query').sum()),
                    no_prior_candidate_rows=int(g.coverage_status.eq('successful_query_no_prior_candidate').sum()),
                    latest_batch_content_conflict_rows=int(g.candidate_batch_has_content_conflict.eq(True).sum()),
                    ann_age_median_calendar_days=None if age.empty else float(age.median()),
                    ann_age_p90_calendar_days=None if age.empty else float(age.quantile(.9)),
                    ann_age_max_calendar_days=None if age.empty else int(age.max()), verified_original_version_rows=0))
    # Detect concurrent refresh; never silently mix two analysis snapshots.
    assert all(audit.sha(audit.ROOT/p) == value for p,value in input_sha.items()), 'Analysis inputs changed during age calculation'
    pd.DataFrame(summaries).to_csv(out/'signal_candidate_age_summary.csv', index=False)
    summary = pd.DataFrame(summaries)
    assert (summary.unverified_candidate_rows + summary.download_not_completed_rows +
            summary.successful_empty_query_rows + summary.no_prior_candidate_rows).eq(summary.stock_signal_rows).all()
    audit.write_json(out/'candidate_age_verification.json', dict(at=audit.now(),
        rows=int(summary.stock_signal_rows.sum()), candidate_rows=int(summary.unverified_candidate_rows.sum()),
        future_candidate_rows=0, same_day_ann_used_rows=0, verified_rows=0,
        summary_reconciles=True, detail_sha256=audit.sha(filename)))
    incomplete = bool(units.status.eq('not_completed').any())
    audit.write_json(out/'candidate_age_status.json', dict(at=audit.now(), state='partial_api_age_coverage_only' if incomplete else 'api_age_coverage_only',
        input_sha256=input_sha, source_sha256=audit.sha(Path(__file__)), output_sha256=audit.sha(filename),
        old_artifacts=old, rows=sum(s['stock_signal_rows'] for s in summaries),
        download_complete_in_snapshot=not incomplete,
        limitation='No age threshold, numeric version selection, risk filtering, or historical approval.'))
    print(json.dumps({'rows':sum(s['stock_signal_rows'] for s in summaries), 'summary_groups':len(summaries), 'download_complete_in_snapshot':not incomplete}))


if __name__ == '__main__':
    main()
