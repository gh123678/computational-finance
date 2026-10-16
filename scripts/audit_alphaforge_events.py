"""Read-only price/event cross-check after the frozen AlphaForge coverage stop.

This sidecar never reads labels or strategy returns, computes an IC, changes an
adjustment factor or relaxes a filter. No cache match means unknown, not proof
that a corporate action did not happen.
"""
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import platform
import shutil
import sys
import traceback

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.corporate_corrections import correct_actions
from quant_research.rights import verified_rights
from run_retention_development import sha
from verify_alphaforge_case import check_fingerprints, read_json

OUT = Path('D:/QuantResearchEvidence/alphaforge_event_crosscheck_20261016_r1')
R1 = ROOT / 'output/alphaforge_case_2018_2020_r1'
ANNUAL = ROOT / 'data/development_2018'
FROZEN = ROOT / 'data/continuous_2016_2025_dividend_r1'
START, END = '20180801', '20180910'
NAMED_CODES = ('000011.SZ', '000545.SZ', '000998.SZ', '000002.SZ')


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def decimal(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def positive(value):
    return value is not None and value > 0


def verify_r1(expected_manifest_hash=None):
    manifest_path = R1 / 'output_sha256.json'
    if expected_manifest_hash is not None:
        assert sha(manifest_path) == expected_manifest_hash, 'r1 manifest changed'
    entries = read_json(manifest_path)
    assert len(entries) == 63, 'Expected the frozen 63-artifact r1 manifest'
    for name, expected in entries.items():
        assert sha(R1 / name) == expected, 'r1 artifact changed: ' + name
    old = check_fingerprints(read_json(R1 / 'frozen_protocol.json'))
    return dict(r1_artifacts=len(entries), prior_artifacts=old,
                r1_manifest_sha256=sha(manifest_path))


def read_subset(path, fields, codes, begin, end):
    parts = []
    for chunk in pd.read_csv(path, usecols=fields, dtype=str, chunksize=150000):
        parts.append(chunk.loc[chunk.ts_code.isin(codes) & chunk.trade_date.between(begin, end)].copy())
    frame = pd.concat(parts, ignore_index=True)
    assert not frame.duplicated(['ts_code', 'trade_date']).any(), str(path)
    return frame


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    shutil.copy2(Path(__file__), OUT / Path(__file__).name)
    print('Verify frozen r1 and prior result fingerprints', flush=True)
    before = verify_r1()
    tracked = [Path(__file__), R1 / 'output_sha256.json', R1 / 'frozen_protocol.json',
               R1 / 'preparation_audit.json', R1 / 'feature_coverage.csv',
               ANNUAL / 'manifest.json', ANNUAL / 'daily.csv', ANNUAL / 'adj_factor.csv',
               ANNUAL / 'calendar.csv', FROZEN / 'dividend.csv', FROZEN / 'calendar.csv',
               ROOT / 'quant_research/corporate_corrections.py', ROOT / 'quant_research/rights.py',
               ROOT / 'scripts/verify_alphaforge_case.py', ROOT / 'scripts/run_retention_development.py']
    input_hashes = {str(path): sha(path) for path in tracked}
    annual_manifest = read_json(ANNUAL / 'manifest.json')['files_sha256']
    for name in ('daily.csv', 'adj_factor.csv', 'calendar.csv'):
        assert sha(ANNUAL / name) == annual_manifest[name], 'Annual cache changed: ' + name
    failed = read_json(R1 / 'preparation_audit.json')['failures']
    failed_days = {row['signal_date'].replace('-', '') for row in failed}
    assert len(failed_days) == 4
    # Deliberately exclude factor values, labels and label-validity columns.
    selection = pd.read_csv(R1 / 'feature_coverage.csv', usecols=['trade_date', 'ts_code'], dtype=str)
    selection['trade_date'] = selection.trade_date.str.replace('-', '', regex=False)
    selection = selection.loc[selection.trade_date.isin(failed_days)].copy()
    assert not selection.duplicated(['trade_date', 'ts_code']).any()
    for row in failed:
        assert int(selection.trade_date.eq(row['signal_date'].replace('-', '')).sum()) == row['original_rows']
    cohort = set(selection.ts_code)
    codes = cohort | set(NAMED_CODES)
    code_table = selection.groupby('ts_code').trade_date.agg(lambda values: '|'.join(sorted(values))).rename('failed_formation_dates').reset_index()
    code_table['scope'] = 'union_of_four_failed_original_pools'
    code_table.to_csv(OUT / 'cohort_codes.csv', index=False)
    selection.to_csv(OUT / 'selected_original_pool_rows.csv', index=False)
    cal = pd.read_csv(FROZEN / 'calendar.csv', usecols=['cal_date', 'is_open'], dtype=str)
    opened = sorted(cal.loc[cal.is_open.eq('1'), 'cal_date'])
    dates = [day for day in opened if START <= day <= END]
    assert dates
    first = opened.index(dates[0])
    assert first > 0
    previous_days = {day: opened[opened.index(day) - 1] for day in dates}
    begin = previous_days[dates[0]]
    annual_cal = pd.read_csv(ANNUAL / 'calendar.csv', usecols=['cal_date', 'is_open'], dtype=str)
    annual_days = set(annual_cal.loc[annual_cal.is_open.eq('1') & annual_cal.cal_date.between(begin, END), 'cal_date'])
    assert annual_days == set([begin] + dates), 'Annual and frozen open calendars differ'
    daily = read_subset(ANNUAL / 'daily.csv', ['ts_code', 'trade_date', 'close', 'pre_close'], codes, begin, END)
    factors = read_subset(ANNUAL / 'adj_factor.csv', ['ts_code', 'trade_date', 'adj_factor'], codes, begin, END)
    daily.to_csv(OUT / 'annual_daily_selected_price_fields.csv', index=False)
    factors.to_csv(OUT / 'annual_adj_factor_selected.csv', index=False)
    quotes = {(row.ts_code, row.trade_date): row for row in daily.itertuples(index=False)}
    adjustment = {(row.ts_code, row.trade_date): row.adj_factor for row in factors.itertuples(index=False)}
    raw_dividend = pd.read_csv(FROZEN / 'dividend.csv', dtype=str)
    corrected_dividend, action_corrections = correct_actions(raw_dividend)
    def local_dividend(frame):
        return frame.loc[frame.ts_code.isin(codes) & frame.div_proc.eq('实施') & frame.ex_date.between(START, END)].copy()
    raw = local_dividend(raw_dividend)
    corrected = local_dividend(corrected_dividend)
    raw.to_csv(OUT / 'dividend_implemented_raw_rows.csv', index=False)
    corrected.to_csv(OUT / 'dividend_implemented_after_existing_corrections.csv', index=False)
    raw_groups = {key: frame for key, frame in raw.groupby(['ts_code', 'ex_date'])}
    corrected_groups = {key: frame for key, frame in corrected.groupby(['ts_code', 'ex_date'])}
    rights_rows = [dict(ts_code=item.code, record_date=item.record.strftime('%Y%m%d'),
                        ex_date=item.ex.strftime('%Y%m%d'), source=item.source,
                        subscription_price=item.price, ratio=item.ratio,
                        list_date=item.list_date.strftime('%Y%m%d') if item.list_date is not None else None)
                   for item in verified_rights()
                   if item.code in codes and START <= item.ex.strftime('%Y%m%d') <= END]
    pd.DataFrame(rights_rows, columns=['ts_code', 'record_date', 'ex_date', 'source',
                                      'subscription_price', 'ratio', 'list_date']).to_csv(OUT / 'verified_rights_rows.csv', index=False)
    rights = {(row['ts_code'], row['ex_date']): row for row in rights_rows}
    rows = []
    for code in sorted(codes):
        for day in dates:
            previous = previous_days[day]
            p, current = quotes.get((code, previous)), quotes.get((code, day))
            a, b = adjustment.get((code, previous)), adjustment.get((code, day))
            prior_close_raw = p.close if p is not None else None
            current_pre_close_raw = current.pre_close if current is not None else None
            old_close, new_pre_close = decimal(prior_close_raw), decimal(current_pre_close_raw)
            old_factor, new_factor = decimal(a), decimal(b)
            complete_quotes = p is not None and current is not None
            complete_factors = a is not None and b is not None
            valid_prices = positive(old_close) and positive(new_pre_close)
            valid_factors = positive(old_factor) and positive(new_factor)
            continuity = old_close == new_pre_close if valid_prices else None
            changed = old_factor != new_factor if valid_factors else None
            key = (code, day)
            raw_count = len(raw_groups[key]) if key in raw_groups else 0
            corrected_count = len(corrected_groups[key]) if key in corrected_groups else 0
            matched_rights = key in rights
            any_match = raw_count > 0 or matched_rights
            if not complete_quotes or not complete_factors:
                classification = 'missing_adjacent_quote_or_factor'
            elif not valid_prices or not valid_factors:
                classification = 'invalid_adjacent_price_or_factor'
            elif not changed:
                classification = 'factor_unchanged'
            else:
                classification = ('factor_changed_' + ('raw_continuous_' if continuity else 'raw_discontinuous_')
                                  + ('cached_event_match' if any_match else 'no_cached_event_match_unknown'))
            rows.append(dict(scope='failed_pool_union' if code in cohort else 'extra_named_case_only',
                             ts_code=code, trade_date=day, previous_open_date=previous,
                             previous_quote_present=p is not None, current_quote_present=current is not None,
                             previous_factor_present=a is not None, current_factor_present=b is not None,
                             previous_close_raw=prior_close_raw, current_pre_close_raw=current_pre_close_raw,
                             current_close_raw=current.close if current is not None else None,
                             previous_adj_factor_raw=a, current_adj_factor_raw=b,
                             adj_factor_changed_exact=changed, raw_close_pre_close_equal_exact=continuity,
                             raw_pre_close_difference=str(new_pre_close - old_close) if valid_prices else None,
                             adj_factor_ratio=str(new_factor / old_factor) if valid_factors else None,
                             relative_adj_factor_change=str(new_factor / old_factor - 1) if valid_factors else None,
                             implemented_dividend_raw_row_count=raw_count,
                             implemented_dividend_after_existing_corrections_row_count=corrected_count,
                             verified_rights_match=matched_rights,
                             event_match_status=('dividend_and_rights' if raw_count and matched_rights else
                                                 'dividend_raw_cache' if raw_count else
                                                 'verified_rights_cache' if matched_rights else 'no_cached_event_match_unknown'),
                             classification=classification))
    all_rows = pd.DataFrame(rows)
    main_rows = all_rows.loc[all_rows.scope.eq('failed_pool_union')].copy()
    changed_rows = main_rows.loc[main_rows.adj_factor_changed_exact.eq(True)].copy()
    named = all_rows.loc[all_rows.ts_code.isin(NAMED_CODES)].copy()
    requested_dates = all_rows.loc[all_rows.trade_date.isin(['20180816', '20180828'])].copy()
    main_rows.to_csv(OUT / 'all_adjacent_open_day_checks.csv', index=False)
    changed_rows.to_csv(OUT / 'exact_adj_factor_changes.csv', index=False)
    named.to_csv(OUT / 'named_case_checks.csv', index=False)
    requested_dates.to_csv(OUT / 'aug16_aug28_checks.csv', index=False)
    by_date = main_rows.groupby(['trade_date', 'classification']).size().unstack(fill_value=0).reset_index()
    by_date.to_csv(OUT / 'classification_by_date.csv', index=False)
    by_event = changed_rows.groupby(['event_match_status', 'raw_close_pre_close_equal_exact']).size().reset_index(name='rows')
    by_event.to_csv(OUT / 'changed_event_continuity_counts.csv', index=False)
    after = verify_r1(before['r1_manifest_sha256'])
    hashes_after = {str(path): sha(path) for path in tracked}
    assert input_hashes == hashes_after and before == after, 'Frozen evidence changed during cross-check'
    focus = named.loc[(named.trade_date.isin(['20180815', '20180816', '20180827', '20180828'])) |
                      (named.ts_code.eq('000002.SZ') & named.trade_date.eq('20180823'))].copy()
    focus.to_csv(OUT / 'named_focus_dates.csv', index=False)
    output_hashes = {path.relative_to(OUT).as_posix(): sha(path) for path in OUT.iterdir() if path.is_file()}
    result = dict(status='completed', recorded_at=pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),
                  scope='Adjacent-open-day raw-price continuity and cached-event cross-check; no correction or general repair certification',
                  start=START, end=END, previous_open_date_for_start=begin,
                  failed_formation_dates=sorted(failed_days), failed_pool_union_codes=len(cohort),
                  extra_named_codes_outside_pool=sorted(set(NAMED_CODES) - cohort),
                  open_dates=len(dates), primary_adjacent_checks=len(main_rows),
                  exact_adj_factor_changes=len(changed_rows),
                  primary_classifications=main_rows.classification.value_counts().to_dict(),
                  changed_classifications=changed_rows.classification.value_counts().to_dict(),
                  named_case_classifications=named.groupby('ts_code').classification.value_counts().to_dict(),
                  raw_implemented_dividend_rows=len(raw), corrected_implemented_dividend_rows=len(corrected),
                  verified_rights_rows=len(rights_rows), existing_action_corrections=action_corrections,
                  original_r1_and_old_results_before=before, original_r1_and_old_results_after=after,
                  source_sha256_before=input_hashes, source_sha256_after=hashes_after,
                  output_sha256=output_hashes, source_script_sha256=sha(Path(__file__)),
                  versions=dict(python=platform.python_version(), pandas=pd.__version__),
                  raw_price_comparison='Decimal numeric equality of previous adjacent open-session close and current pre_close; source strings retained',
                  labels_read=False, strategy_returns_read=False, strategy_accounts_started=0,
                  filter_changed=False, minimum_pool_changed=False, data_changed=False,
                  limitations=['A missing cached event is unknown, not proof of no action.',
                               'Exact price continuity does not prove a factor change is erroneous.',
                               'Current cached event records do not establish historical-version availability.',
                               'Named diagnostic cases outside the original pool are never counted in the primary cohort.',
                               'Earlier analyses of 2020 are not evidence about 2018 events.'])
    # JSON object keys cannot be pandas MultiIndex tuples.
    result['named_case_classifications'] = {code: frame.classification.value_counts().to_dict()
                                             for code, frame in named.groupby('ts_code')}
    save('crosscheck.json', result)
    save('input_sha256.json', input_hashes)
    manifest = {path.relative_to(OUT).as_posix(): sha(path) for path in OUT.iterdir() if path.is_file()}
    save('output_sha256.json', manifest)
    print(json.dumps(dict(status='completed', cohort_codes=len(cohort), adjacent_checks=len(main_rows),
                          exact_changes=len(changed_rows), classes=changed_rows.classification.value_counts().to_dict(),
                          extra_named_codes=sorted(set(NAMED_CODES) - cohort)), ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    try:
        main()
    except Exception:
        if OUT.is_dir():
            (OUT / ('failure_' + pd.Timestamp.now().strftime('%Y%m%dT%H%M%S') + '.txt')).write_text(
                traceback.format_exc(), encoding='utf-8')
        raise
