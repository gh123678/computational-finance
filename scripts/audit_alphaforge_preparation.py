"""Audit a stopped preparation using past quote fields only, without accounts.

The coverage CSV is deliberately read with an explicit column allowlist that
does not contain labels, label-validity flags, benchmark prices or returns.
No completed-account or minimum-pool assertion is required to check arithmetic.
"""
from pathlib import Path
import math
import traceback

import numpy as np
import pandas as pd

from verify_alphaforge_case import (ROOT, DATA, OLD, OUT, check_fingerprints,
                                    read_json, scalar_formula, persist)
from run_retention_development import read_subset, sha
from quant_research.corporate_corrections import correct_adjustments
from quant_research.factors import weekly_schedule


FIELDS = ['trade_date', 'ts_code', 'window_start', 'window_end', 'case_valid',
          'reason', 'valid_quote_count_10', 'volume_scale', 'case_rho',
          'case_factor', 'case_signal', 'case_nlvar', 'case_nrvar', 'case_guard']
MATH_FIELDS = ('case_rho', 'case_factor', 'case_signal', 'case_nlvar', 'case_nrvar')


def flag(value):
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if str(value).lower() in ('true', '1'):
        return True
    if str(value).lower() in ('false', '0'):
        return False
    raise AssertionError('Unrecognized non-null Boolean')


def classify_window(values, present, position):
    """Separate scalar qualification, keeping the frozen exclusion priority."""
    if position < 9:
        return dict(valid=False, reason='warmup_10', count=0, result=None)
    window = values[position - 9:position + 1]
    seen = present[position - 9:position + 1]
    valid_quotes = np.isfinite(window).all(axis=1) & (window > 0).all(axis=1)
    count = int(valid_quotes.sum())
    if not seen.all():
        return dict(valid=False, reason='missing_quote', count=count, result=None)
    if not valid_quotes.all():
        return dict(valid=False, reason='invalid_quote', count=count, result=None)
    if not (window[:, 2] == window[0, 2]).all():
        return dict(valid=False, reason='adjustment_factor_change', count=count, result=None)
    result = scalar_formula(window[:, 0], window[:, 1])
    if not all(math.isfinite(result[name]) for name in MATH_FIELDS):
        return dict(valid=False, reason='nonfinite_factor', count=count, result=None)
    return dict(valid=True, reason='valid', count=count, result=result)


def main(out=OUT):
    out = Path(out)
    if (out / 'preparation_audit.json').exists():
        raise RuntimeError('Existing preparation audit; inspect rather than overwrite')
    protocol = read_json(out / 'frozen_protocol.json')
    counts_before = check_fingerprints(protocol)
    failure = read_json(out / 'last_failure.json')
    assert failure['stage'] == 'prepare' and (out / failure['failure']).is_file()
    absent = ['common_samples.csv', 'factor_ic.csv', 'factor_groups.csv',
              'experiment_protocol.json', 'experiment_stage.json', 'summary.json']
    assert all(not (out / name).exists() for name in absent), 'Preparation progressed past the stop gate'
    assert all(not (out / f'{path}_{cost}bp').exists()
               for path in protocol['paths'] for cost in protocol['costs'])
    tracked = [out / 'frozen_protocol.json', out / 'feature_coverage.csv',
               out / 'schedule.csv', out / 'last_failure.json', out / failure['failure'],
               Path(__file__), ROOT / 'scripts/verify_alphaforge_case.py']
    before = {str(path): sha(path) for path in tracked}
    cal = pd.read_csv(DATA / 'calendar.csv', dtype={'cal_date': str})
    full = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1), 'cal_date'])).sort_values()
    calendar = full[(full >= '2015-11-01') & (full <= '2020-12-31')]
    schedule = weekly_schedule(full[full >= '2015-11-01'])
    schedule = schedule.loc[schedule.execution_date.between('2018-01-01', '2020-12-31')].reset_index(drop=True)
    observed_schedule = pd.read_csv(out / 'schedule.csv', parse_dates=['signal_date', 'execution_date'])
    pd.testing.assert_frame_equal(observed_schedule, schedule)
    base = pd.read_csv(OLD / 'common_samples.csv', usecols=['trade_date', 'ts_code'], parse_dates=['trade_date'])
    base = base.loc[base.trade_date.isin(schedule.signal_date)].copy()
    coverage = pd.read_csv(out / 'feature_coverage.csv', usecols=FIELDS,
                           parse_dates=['trade_date', 'window_start', 'window_end'],
                           float_precision='round_trip')
    keys = ['trade_date', 'ts_code']
    assert coverage[keys].equals(base[keys].reset_index(drop=True))
    assert not coverage.duplicated(keys).any()
    assert coverage.volume_scale.eq(100.).all()
    codes = set(base.ts_code)
    bars = read_subset('daily', codes, columns=['trade_date', 'ts_code', 'close', 'vol']).merge(
        read_subset('adj_factor', codes, columns=['trade_date', 'ts_code', 'adj_factor']),
        on=['trade_date', 'ts_code'], validate='one_to_one')
    bars = bars.loc[bars.trade_date.isin(calendar)].copy()
    bars, corrections = correct_adjustments(bars)
    grouped = {code: frame for code, frame in coverage.groupby('ts_code')}
    assert set(grouped) == set(bars.ts_code)
    checked = valid_rows = guarded_rows = 0
    errors = {name: 0. for name in MATH_FIELDS}
    for i, (code, quotes) in enumerate(bars.groupby('ts_code', sort=True)):
        assert not quotes.trade_date.duplicated().any()
        present = calendar.isin(quotes.trade_date)
        values = quotes.set_index('trade_date').reindex(calendar)[['close', 'vol', 'adj_factor']].to_numpy(dtype=float)
        for row in grouped[code].itertuples(index=False):
            position = calendar.get_loc(row.trade_date)
            expected = classify_window(values, present, position)
            assert flag(row.case_valid) == expected['valid'], (code, row.trade_date, 'validity')
            assert row.reason == expected['reason'], (code, row.trade_date, 'reason')
            assert row.valid_quote_count_10 == expected['count']
            assert row.window_end == row.trade_date
            if position >= 9:
                assert row.window_start == calendar[position - 9]
            else:
                assert pd.isna(row.window_start)
            if expected['valid']:
                result = expected['result']
                assert flag(row.case_guard) == result['case_guard']
                for name in MATH_FIELDS:
                    observed, calculated = float(getattr(row, name)), result[name]
                    errors[name] = max(errors[name], abs(observed - calculated))
                    assert math.isclose(observed, calculated, rel_tol=2e-12 if name.endswith('var') else 0,
                                        abs_tol=1e-10), (code, row.trade_date, name)
                valid_rows += 1
                guarded_rows += int(result['case_guard'])
            else:
                assert pd.isna(row.case_guard)
                assert all(pd.isna(getattr(row, name)) for name in MATH_FIELDS)
            checked += 1
        if (i + 1) % 500 == 0:
            print('Independent failed-preparation audit assets', i + 1, 'rows', checked, flush=True)
    assert checked == len(coverage)
    by_date = coverage.groupby('trade_date').agg(original_rows=('ts_code', 'size'),
                                                retained_rows=('case_valid', 'sum')).reset_index()
    by_date['excluded_rows'] = by_date.original_rows - by_date.retained_rows
    by_date['retained_fraction'] = by_date.retained_rows / by_date.original_rows
    reasons = pd.crosstab(coverage.trade_date, coverage.reason).add_prefix('reason_').reset_index()
    by_date = by_date.merge(reasons, on='trade_date', validate='one_to_one').merge(
        schedule, left_on='trade_date', right_on='signal_date', validate='one_to_one')
    by_date['minimum_formed_requirement'] = protocol['minimum_formed_per_date']
    by_date['coverage_gate_passed'] = by_date.retained_rows.ge(protocol['minimum_formed_per_date'])
    failures = by_date.loc[~by_date.coverage_gate_passed].copy()
    counts_after = check_fingerprints(protocol)
    assert counts_after == counts_before
    after = {str(path): sha(path) for path in tracked}
    assert after == before, 'Frozen/preparation evidence changed during the audit'
    by_date.to_csv(out / 'coverage_by_date.csv', index=False)
    result = dict(status='passed', scope='Mathematical and past-only coverage audit of stopped preparation; no account or performance evaluation',
                  original_formation_rows=len(coverage), independently_checked_rows=checked,
                  valid_formula_rows=valid_rows, excluded_rows=checked - valid_rows,
                  epsilon_guard_rows=guarded_rows, maximum_absolute_error=errors,
                  reasons=coverage.reason.value_counts().to_dict(), formation_dates=len(by_date),
                  minimum_retained_rows=int(by_date.retained_rows.min()), failed_dates=len(failures),
                  failures=[dict(signal_date=row.signal_date.strftime('%Y-%m-%d'),
                                 execution_date=row.execution_date.strftime('%Y-%m-%d'),
                                 original_rows=int(row.original_rows), retained_rows=int(row.retained_rows),
                                 excluded_rows=int(row.excluded_rows)) for row in failures.itertuples(index=False)],
                  coverage_gate_passed=bool(by_date.coverage_gate_passed.all()),
                  minimum_pool_requirement_not_relaxed=True, accounts_started=0,
                  ic_calculated=False, performance_evaluated=False, future_label_fields_consumed=False,
                  input_columns_read=FIELDS, market_columns_read=['trade_date', 'ts_code', 'close', 'vol', 'adj_factor'],
                  original_preparation_failure=failure, old_artifacts=counts_after,
                  adjustment_corrections=corrections, audit_source_sha256=sha(Path(__file__)),
                  independent_scalar_source_sha256=sha(ROOT / 'scripts/verify_alphaforge_case.py'),
                  frozen_and_evidence_sha256_before=before, frozen_and_evidence_sha256_after=after,
                  coverage_by_date_sha256=sha(out / 'coverage_by_date.csv'))
    persist('preparation_audit.json', result, out)
    print(dict(status='passed', checked=checked, valid=valid_rows, failed_dates=len(failures), accounts_started=0), flush=True)
    return result


if __name__ == '__main__':
    try:
        main()
    except Exception:
        name = 'preparation_audit_failure_' + pd.Timestamp.now().strftime('%Y%m%dT%H%M%S') + '.txt'
        (OUT / name).write_text(traceback.format_exc(), encoding='utf-8')
        raise
