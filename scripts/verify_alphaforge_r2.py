"""Independent raw-text, event-timing and account audit for the approved r2.

No r2 feature/event constructor is imported.  The immutable r1 verifier's
diagnostic, target and ledger checks are reused with explicit output paths.
"""
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import argparse
import csv
import json
import math
from pathlib import Path
import re
import traceback

import numpy as np
import pandas as pd

import verify_alphaforge_case as prior
from quant_research.backtest import Config, summarize
from quant_research.corporate_corrections import correct_actions, correct_adjustments
from quant_research.factors import FACTORS, weekly_schedule
from quant_research.rights import verified_rights

ROOT, DATA, OLD = prior.ROOT, prior.DATA, prior.OLD
OUT = ROOT/'output/alphaforge_case_2018_2020_r2'
R1 = ROOT/'output/alphaforge_case_2018_2020_r1'
PATHS, PRIMARY = prior.PATHS, prior.PRIMARY
read_json, sha = prior.read_json, prior.sha
COUNTS = ('reference_change_count', 'unknown_reference_count', 'known_action_count',
          'event_timing_unverified_count', 'adj_factor_change_count')
MATH_FIELDS = ('case_factor', 'case_signal', 'case_rho', 'case_nlvar', 'case_nrvar')
EVENT_COLUMNS = ('code', 'event_date', 'known_date', 'timing_verified', 'kind',
                 'source', 'known_date_field', 'timing_reason')


def persist(name, value, out=OUT):
    prior.persist(name, value, Path(out))


def boolean(value, missing=False):
    """Explicit CSV Boolean parser; 'False' must never become truthy."""
    if value is None or pd.isna(value) or value == '':
        if missing:
            return None
        raise AssertionError('Missing Boolean flag')
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    assert str(value) in ('True', 'False', 'true', 'false', '1', '0'), repr(value)
    return str(value) in ('True', 'true', '1')


def day(value):
    """Date-level cached fields only; do not guess numeric epochs or URL dates."""
    if value is None or pd.isna(value) or str(value) == '':
        return pd.NaT
    text = str(value)
    if re.fullmatch(r'\d{8}', text):
        return pd.to_datetime(text, format='%Y%m%d', errors='coerce')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return pd.to_datetime(text, format='%Y-%m-%d', errors='coerce')
    return pd.NaT


def positive_decimal(value):
    if value is None or pd.isna(value):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


def check_fingerprints(protocol):
    """Verify r1 plus its three predecessors, rather than weakening r1's guard."""
    for name, expected in protocol['inputs'].items():
        assert sha(ROOT/name) == expected, 'Input changed: '+name
    for name, expected in protocol['external_inputs'].items():
        assert sha(Path(name)) == expected, 'External input changed: '+name
    assert {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')} == protocol['source_sha256']
    market = read_json(DATA/'manifest.json')['files_sha256']
    assert {'daily.csv', 'adj_factor.csv', 'calendar.csv', 'benchmark.csv', 'stk_limit.csv',
            'suspend_d.csv', 'dividend.csv'}.issubset(market)
    for name, expected in market.items():
        assert sha(DATA/name) == expected, 'Market manifest mismatch: '+name
    expected_paths = {str(Path('output')/name/'output_sha256.json')
                      for name in (*prior.PRIOR_DIRECTORIES, R1.name)}
    manifests = protocol['prior_artifact_manifests']
    assert {str(Path(name)) for name in manifests} == expected_paths
    counts = {}
    for name, expected in manifests.items():
        manifest = ROOT/name
        assert sha(manifest) == expected, 'Prior manifest changed: '+name
        entries = read_json(manifest)
        for item, digest in entries.items():
            assert sha(manifest.parent/item) == digest, 'Prior artifact changed: '+item
        counts[manifest.parent.name] = len(entries)
    return counts


def verify_events(events, raw_dividends, calendar, raw_versions=None, corrections=None, rights=None, codes=None):
    """Rebuild event semantics from frozen dividend rows and existing rights.

    Reuse only the old, frozen corporate corrections.  No new event-builder is
    called, and neither proposal ann_date nor a source URL supplies known_date.
    Duplicate cached versions are compared as a multiset, not deduplicated.
    """
    assert set(EVENT_COLUMNS).union({'event_id'}).issubset(events)
    assert events.event_id.notna().all() and not events.event_id.astype(str).str.strip().eq('').any()
    assert not events.event_id.duplicated().any()
    if raw_versions is not None:
        left, right = raw_versions.fillna('').astype(str), raw_dividends.fillna('').astype(str)
        pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True))
    corrected, expected_corrections = correct_actions(raw_dividends.copy())
    if corrections is not None:
        assert corrections == expected_corrections, 'Event correction ledger changed'
    expected = []
    first, last = pd.DatetimeIndex(calendar).min(), pd.DatetimeIndex(calendar).max()

    def in_scope(code, effective):
        return (codes is None or code in codes) and first <= effective <= last

    amounts = ('cash_div', 'cash_div_tax', 'stk_div', 'stk_bo_rate', 'stk_co_rate')
    for row in corrected.to_dict('records'):
        if row['div_proc'] != '实施':
            continue
        values = {}
        for name in amounts:
            raw = row.get(name)
            value = 0. if raw is None or pd.isna(raw) or raw == '' else float(raw)
            assert math.isfinite(value) and value >= 0, (row['ts_code'], name)
            values[name] = value
        cash = any(values[name] > 0 for name in amounts[:2])
        stock = any(values[name] > 0 for name in amounts[2:])
        if not cash and not stock:
            continue
        effective, known = day(row['ex_date']), day(row.get('imp_ann_date'))
        assert pd.notna(effective), 'Invalid implemented effective date'
        if not in_scope(row['ts_code'], effective):
            continue
        raw_known = row.get('imp_ann_date')
        if raw_known is None or pd.isna(raw_known):
            reason = 'missing_imp_ann_date'
        elif pd.isna(known):
            reason = 'invalid_imp_ann_date'
        elif known > effective:
            reason = 'imp_ann_date_after_event_date'
        else:
            reason = 'valid_cached_implementation_day_not_after_event'
        expected.append(dict(code=row['ts_code'], event_date=effective, known_date=known,
                             timing_verified=pd.notna(known) and known <= effective,
                             kind='cash_and_stock' if cash and stock else 'cash' if cash else 'stock',
                             source='dividend_frame_after_existing_correct_actions',
                             known_date_field='imp_ann_date', timing_reason=reason))
    for issue in verified_rights() if rights is None else rights:
        if not in_scope(issue.code, pd.Timestamp(issue.ex)):
            continue
        expected.append(dict(code=issue.code, event_date=pd.Timestamp(issue.ex), known_date=pd.NaT,
                             timing_verified=False, kind='rights', source=issue.source,
                             known_date_field='none_verified', timing_reason='public_announcement_day_not_verified'))

    def signature(row):
        result = []
        for name in EVENT_COLUMNS:
            value = row[name]
            if name in ('event_date', 'known_date'):
                parsed = day(value) if not isinstance(value, pd.Timestamp) else value
                value = None if pd.isna(parsed) else parsed.strftime('%Y-%m-%d')
            elif name == 'timing_verified':
                value = boolean(value)
            result.append(value)
        return tuple(result)

    observed = Counter(signature(row) for row in events.to_dict('records'))
    wanted = Counter(signature(row) for row in expected)
    assert observed == wanted, ('Event semantics differ', observed-wanted, wanted-observed)
    verified = events.timing_verified.map(boolean)
    return dict(event_rows=len(events), dividend_rows=sum(e['kind'] != 'rights' for e in expected),
                rights_rows=sum(e['kind'] == 'rights' for e in expected),
                timing_verified_rows=int(verified.sum()), timing_unverified_rows=int((~verified).sum()),
                original_version_identity_certified=False, intraday_publication_time_certified=False,
                known_day_source='Only cached imp_ann_date; no proposal/URL date fallback')


def event_index(events):
    result = defaultdict(list)
    for row in events.to_dict('records'):
        effective = day(row['event_date']) if not isinstance(row['event_date'], pd.Timestamp) else row['event_date']
        known = day(row['known_date']) if not isinstance(row['known_date'], pd.Timestamp) else row['known_date']
        assert pd.notna(effective)
        result[(row['code'], effective)].append(dict(event_id=str(row['event_id']), event_date=effective, known_date=known,
                                                     timing_verified=boolean(row['timing_verified'])))
    for values in result.values():
        values.sort(key=lambda item:item['event_id'])
    return result


def independent_window(code, dates, quotes, events=None):
    """Ten raw observations; independently derive nine reference/action tests.

    quotes is a ten-row frame, including missing rows, with close/pre_close raw
    text and vol/adj_factor.  This function never uses a return label.
    """
    dates = pd.DatetimeIndex(dates)
    assert len(dates) == len(quotes) == 10 and not dates.has_duplicates
    assert dates.is_monotonic_increasing
    formation, start = dates[-1], dates[0]
    numeric = np.array([[float(v) if v is not None and not pd.isna(v) and str(v) != '' else np.nan
                         for v in quotes[name]] for name in ('close', 'vol', 'adj_factor')], dtype=float).T
    valid = np.isfinite(numeric).all(axis=1) & (numeric > 0).all(axis=1)
    result = dict(window_start=start, window_end=formation, case_valid=False,
                  reason='valid', volume_scale=100., valid_quote_count_10=int(valid.sum()),
                  **{name:0 for name in COUNTS}, **{name:np.nan for name in MATH_FIELDS}, case_guard=None)
    transitions = []
    for position in range(1, 10):
        previous_text = quotes.iloc[position-1]['close']
        current_text = quotes.iloc[position]['pre_close']
        left, right = positive_decimal(previous_text), positive_decimal(current_text)
        reference = 'unknown_reference' if left is None or right is None else 'continuous' if left == right else 'raw_reference_change'
        result['unknown_reference_count'] += reference == 'unknown_reference'
        result['reference_change_count'] += reference == 'raw_reference_change'
        a, b = numeric[position-1, 2], numeric[position, 2]
        changed = bool(math.isfinite(a) and math.isfinite(b) and a != b)
        result['adj_factor_change_count'] += changed
        # Partition the literal calendar interval (start, formation] into nine
        # open-to-open transitions, preserving an event's original date.
        matches = []
        if events is not None:
            effective = dates[position-1] + pd.Timedelta(days=1)
            while effective <= dates[position]:
                matches.extend(events.get((code, effective), []))
                effective += pd.Timedelta(days=1)
            matches.sort(key=lambda item:item['event_id'])
        known = [row for row in matches if row['timing_verified'] and pd.notna(row['known_date']) and row['known_date'] <= formation]
        ids = [row['event_id'] for row in matches]
        known_ids = [row['event_id'] for row in known]
        unverified_ids = [identifier for identifier in ids if identifier not in known_ids]
        result['known_action_count'] += len(known_ids)
        result['event_timing_unverified_count'] += len(unverified_ids)
        transitions.append(dict(signal_date=formation, ts_code=code, window_start=start, window_end=formation,
                                previous_date=dates[position-1], current_date=dates[position],
                                previous_close_text=previous_text, current_pre_close_text=current_text,
                                reference_status=reference, adj_factor_changed=changed, matched_event_ids=ids,
                                known_action_ids=known_ids, unverified_event_ids=unverified_ids,
                                event_known_dates={row['event_id']:None if pd.isna(row['known_date']) else row['known_date'].strftime('%Y-%m-%d') for row in matches},
                                event_effective_dates={row['event_id']:row['event_date'].strftime('%Y-%m-%d') for row in matches},
                                known_action_count=len(known_ids), event_timing_unverified_count=len(unverified_ids),
                                isolated_factor_change_no_observed_reference_break=changed and reference == 'continuous' and not known_ids))
    result['isolated_factor_change_no_observed_reference_break'] = bool(result['adj_factor_change_count'] and not (
        result['unknown_reference_count'] or result['reference_change_count'] or result['known_action_count']))
    if result['unknown_reference_count']:
        result['reason'] = 'unknown_reference'
    elif result['reference_change_count']:
        result['reason'] = 'raw_reference_change'
    elif result['known_action_count']:
        result['reason'] = 'known_action'
    elif result['valid_quote_count_10'] != 10:
        result['reason'] = 'invalid_quote'
    else:
        values = prior.scalar_formula(numeric[:,0], numeric[:,1])
        if all(math.isfinite(values[name]) for name in MATH_FIELDS):
            result.update(values, case_valid=True)
        else:
            result['reason'] = 'nonfinite_factor'
            result['case_guard'] = values['case_guard']
    return result, transitions


def check_transition(expected, observed):
    assert set(expected).issubset(observed), 'Incomplete reference-transition columns'
    for name, value in expected.items():
        found = observed[name]
        if isinstance(value, pd.Timestamp):
            assert pd.Timestamp(found) == value, (name, found, value)
        elif name.endswith('_text'):
            original = '' if value is None or pd.isna(value) else str(value)
            assert found == original, (name, found, original)
        elif isinstance(value, bool):
            assert boolean(found) == value, (name, found, value)
        elif isinstance(value, (list, dict)):
            assert json.loads(found) == value, (name, found, value)
        elif isinstance(value, int):
            assert int(found) == value, (name, found, value)
        else:
            assert found == value, (name, found, value)


def verify_formation(common, base, calendar, raw_bars, events, coverage, r1_features,
                     transition_rows=None, minimum_pool=200):
    """Audit every base formation, independent of all labels and r2 production.

    transition_rows is an optional csv.DictReader/iterator in canonical
    (ts_code, signal_date, current_date) order.  It is consumed once, bounded
    to nine records per complete formation window rather than loaded at once.
    """
    key = ['trade_date', 'ts_code']
    for frame in (base, common, coverage, r1_features):
        assert not frame.duplicated(key).any()
    base_keys = set(base[key].itertuples(index=False, name=None))
    assert base_keys == set(coverage[key].itertuples(index=False, name=None))
    calendar = pd.DatetimeIndex(calendar)
    assert calendar.is_monotonic_increasing and not calendar.has_duplicates
    positions = {date:i for i, date in enumerate(calendar)}
    saved = coverage.set_index(key)
    common_saved = common.set_index(key)
    original_r1 = r1_features.set_index(key)
    assert set(original_r1.index) == base_keys
    by_code = {code:frame for code, frame in raw_bars.groupby('ts_code', sort=False)}
    actions = event_index(events)
    expected_keys = set()
    maximum = {name:0. for name in MATH_FIELDS}
    checked = valid_count = guards = transition_count = intersection = 0
    reasons = Counter()
    for code, formed in base.groupby('ts_code', sort=True):
        assert code in by_code
        quoted = by_code[code]
        assert not quoted.trade_date.duplicated().any()
        q = quoted.set_index('trade_date').reindex(calendar)
        for date in sorted(formed.trade_date):
            position = positions[date]
            assert position >= 9, 'Frozen common200 unexpectedly has a short history'
            expected, transitions = independent_window(code, calendar[position-9:position+1], q.iloc[position-9:position+1], actions)
            row_key = (date, code)
            row = saved.loc[row_key]
            for name in ('case_valid', 'isolated_factor_change_no_observed_reference_break'):
                assert boolean(row[name]) == expected[name], (row_key, name)
            for name in ('reason', 'valid_quote_count_10', 'volume_scale', *COUNTS):
                assert row[name] == expected[name], (row_key, name, row[name], expected[name])
            assert pd.Timestamp(row.window_start) == expected['window_start']
            assert pd.Timestamp(row.window_end) == date
            assert boolean(row.case_guard, missing=True) == expected['case_guard'], (row_key, 'case_guard')
            for transition in transitions:
                if transition_rows is not None:
                    try:
                        observed = next(transition_rows)
                    except StopIteration as error:
                        raise AssertionError('Missing reference transition: '+str(row_key)) from error
                    check_transition(transition, observed)
                transition_count += 1
            reasons[expected['reason']] += 1
            checked += 1
            if expected['case_valid']:
                expected_keys.add(row_key)
                valid_count += 1
                guards += int(expected['case_guard'])
                assert row_key in common_saved.index, ('Eligible formation omitted', row_key)
                common_row = common_saved.loc[row_key]
                for name in MATH_FIELDS:
                    value = expected[name]
                    for observed_value in (row[name], common_row[name]):
                        error = abs(float(observed_value)-value)
                        maximum[name] = max(maximum[name], error)
                        assert math.isclose(float(observed_value), value, rel_tol=2e-12 if name in ('case_nlvar','case_nrvar') else 0,
                                            abs_tol=1e-10), (row_key, name, observed_value, value)
                old = original_r1.loc[row_key]
                if boolean(old.case_valid):
                    for name in ('case_factor', 'case_signal', 'case_rho'):
                        assert math.isclose(float(row[name]), float(old[name]), rel_tol=0, abs_tol=1e-12), (row_key, 'r1 intersection '+name)
                    intersection += 1
            else:
                assert all(pd.isna(row[name]) for name in MATH_FIELDS), ('Excluded formula must remain missing', row_key)
    if transition_rows is not None:
        assert next(transition_rows, None) is None, 'Extra saved reference-transition rows'
    assert set(common_saved.index) == expected_keys, 'Past-only formation pool differs'
    # Labels and inherited factors are checked only after eligibility was
    # derived without them; they are pass-through values, never a pool mask.
    original = base.set_index(key)
    for name in ('industry', 'D_label', 'D_valid', 'D_end', 'reference_end', *FACTORS):
        if name in base:
            pd.testing.assert_series_equal(common_saved[name], original.loc[common_saved.index, name], check_names=False)
    sizes = common.groupby('trade_date').size().reindex(sorted(base.trade_date.unique()), fill_value=0)
    assert sizes.ge(minimum_pool).all(), 'Fewer than required formed assets on a scheduled date'
    return dict(original_formation_rows=checked, feature_rows_checked=valid_count,
                excluded_rows=checked-valid_count, maximum_absolute_error=maximum,
                maximum_factor_error=maximum['case_factor'], source_epsilon_guard_rows=guards,
                smallest_cross_section=int(sizes.min()), formation_dates=len(sizes),
                reference_transition_rows_checked=transition_count, internal_transitions_per_window=9,
                r1_common_valid_intersection_rows=intersection, r1_intersection_formula_unchanged=True,
                reasons=dict(reasons), future_label_used_for_formation=False,
                unknown_event_timing_does_not_change_eligibility=True,
                adjustment_factor_change_alone_does_not_exclude=True)


def read_raw_bars(codes, calendar):
    """Consume original close/pre_close CSV text, not reconstructed float text."""
    quote_fields = ['ts_code', 'trade_date', 'close', 'pre_close', 'vol']
    dates = set(pd.DatetimeIndex(calendar).strftime('%Y%m%d'))
    pieces = []
    for chunk in pd.read_csv(DATA/'daily.csv', dtype=str, keep_default_na=False,
                             usecols=quote_fields, chunksize=250_000):
        picked = chunk.loc[chunk.ts_code.isin(codes) & chunk.trade_date.isin(dates)]
        if len(picked):
            pieces.append(picked)
    raw = pd.concat(pieces, ignore_index=True)
    factors = []
    for chunk in pd.read_csv(DATA/'adj_factor.csv', dtype=str, keep_default_na=False,
                             usecols=['ts_code', 'trade_date', 'adj_factor'], chunksize=250_000):
        picked = chunk.loc[chunk.ts_code.isin(codes) & chunk.trade_date.isin(dates)]
        if len(picked):
            factors.append(picked)
    raw = raw.merge(pd.concat(factors, ignore_index=True), on=['ts_code','trade_date'], how='left', validate='one_to_one')
    raw['trade_date'] = pd.to_datetime(raw.trade_date, format='%Y%m%d')
    raw['adj_factor'] = pd.to_numeric(raw.adj_factor.replace('', np.nan), errors='raise')
    raw, _ = correct_adjustments(raw)
    return raw


def verify_pool_comparison(coverage, r1_features, observed):
    key = ['trade_date', 'ts_code']
    expected = coverage[[*key, 'case_valid', 'case_factor', 'reason']].merge(
        r1_features[[*key, 'case_valid', 'case_factor']], on=key, validate='one_to_one',
        suffixes=('_r2', '_r1'))
    assert not observed.duplicated(key).any()
    left, right = expected.set_index(key).sort_index(), observed.set_index(key).sort_index()
    assert left.index.equals(right.index)
    for name in ('case_valid_r1', 'case_valid_r2'):
        assert left[name].map(boolean).equals(right[name].map(boolean))
    assert left.reason.equals(right.reason)
    for name in ('case_factor_r1', 'case_factor_r2'):
        np.testing.assert_allclose(left[name], right[name], rtol=0, atol=1e-12, equal_nan=True)
    both = left.case_valid_r1.map(boolean) & left.case_valid_r2.map(boolean)
    np.testing.assert_allclose(left.loc[both, 'case_factor_r1'], left.loc[both, 'case_factor_r2'],
                               rtol=0, atol=1e-12)
    old, new = left.case_valid_r1.map(boolean), left.case_valid_r2.map(boolean)
    return dict(rows=len(left), old_valid=int(old.sum()), new_valid=int(new.sum()),
                common_valid=int(both.sum()), newly_valid=int((~old & new).sum()),
                no_longer_valid=int((old & ~new).sum()), comparison_independently_verified=True)


def schedule_and_calendar():
    full = pd.read_csv(DATA/'calendar.csv', dtype={'cal_date':str})
    full = pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    calendar = full[(full >= '2015-11-01') & (full <= '2020-12-31')]
    schedule = weekly_schedule(full[full >= '2015-11-01'])
    schedule = schedule.loc[schedule.execution_date.between('2018-01-01','2020-12-31')].reset_index(drop=True)
    assert len(schedule) == 154
    return calendar, schedule


def verify_preparation(out=OUT, persist_result=True):
    out = Path(out)
    protocol = read_json(out/'frozen_protocol.json')
    counts = check_fingerprints(protocol)
    assert read_json(out/'preparation_status.json')['state'] == 'completed'
    for name, expected in read_json(out/'preparation_sha256.json').items():
        assert sha(out/name) == expected, 'Prepared artifact changed: '+name
    calendar, schedule = schedule_and_calendar()
    saved_schedule = pd.read_csv(out/'schedule.csv', parse_dates=['signal_date','execution_date'])
    pd.testing.assert_frame_equal(saved_schedule, schedule)
    base = pd.read_csv(OLD/'common_samples.csv', parse_dates=['trade_date','D_end','reference_end'], float_precision='round_trip')
    base = base.loc[base.trade_date.isin(schedule.signal_date)].copy()
    common = pd.read_csv(out/'common_samples.csv', parse_dates=['trade_date','D_end','reference_end'], float_precision='round_trip')
    coverage = pd.read_csv(out/'feature_coverage.csv', parse_dates=['trade_date','window_start','window_end'], float_precision='round_trip')
    r1_features = pd.read_csv(R1/'feature_coverage.csv', usecols=['trade_date','ts_code','case_valid','case_factor','case_signal','case_rho'],
                               parse_dates=['trade_date'], float_precision='round_trip')
    assert set(common.trade_date) == set(schedule.signal_date)
    events = pd.read_csv(out/'events.csv', dtype=str, keep_default_na=False)
    raw_versions = pd.read_csv(out/'raw_event_versions.csv', dtype=str, keep_default_na=False)
    dividends = pd.read_csv(DATA/'dividend.csv', dtype=str)
    corrections = read_json(out/'event_corrections.json')
    event_audit = verify_events(events, dividends, calendar, raw_versions, corrections, codes=set(base.ts_code))
    raw = read_raw_bars(set(base.ts_code), calendar)
    print('Independent r2 raw-text ten-point verification', len(base), flush=True)
    with (out/'reference_transitions.csv').open(encoding='utf-8', newline='') as stream:
        formation = verify_formation(common, base, calendar, raw, events, coverage, r1_features, csv.DictReader(stream))
    comparison = pd.read_csv(out/'r1_pool_comparison.csv', parse_dates=['trade_date'], float_precision='round_trip')
    pool_audit = verify_pool_comparison(coverage, r1_features, comparison)
    assert check_fingerprints(protocol) == counts
    result = dict(status='passed', engineering_preparation_verified=True, **formation,
                  event_timing=event_audit, pool_comparison=pool_audit, old_artifacts=counts, accounts_started_by_verifier=0,
                  formula_imported_from_r2_production=False, raw_reference_source='Frozen daily.csv original text parsed with Decimal',
                  broker_connected=False, r1_modified=False, verifier_sha256=sha(Path(__file__)))
    if persist_result:
        target = out/'preparation_audit.json'
        if target.exists():
            raise RuntimeError('Existing r2 preparation audit; inspect rather than overwrite')
        persist(target.name, result, out)
    return result


def main(out=OUT):
    out = Path(out)
    assert read_json(out/'experiment_stage.json')['state'] == 'completed'
    if (out/'verification.json').exists():
        raise RuntimeError('Existing verification; inspect rather than overwrite')
    formation = verify_preparation(out, persist_result=False)
    protocol = read_json(out/'frozen_protocol.json')
    experiment = read_json(out/'experiment_protocol.json')
    assert sha(ROOT/'scripts/run_alphaforge_r2.py') == experiment['runner_sha256']
    assert sha(out/'simulation_adapter_block.py.txt') == experiment['adapter_sha256']
    summary = read_json(out/'summary.json')
    expected_labels = {f'{path}_{cost}bp' for path in PATHS for cost in (0,10,30)}
    statuses = summary['experiment_statuses']
    assert len(statuses) == 6 and {item['strategy'] for item in statuses} == expected_labels
    assert all(item['status'] == 'completed' for item in statuses)
    assert len(summary['experiments']) == 6 and {item['strategy'] for item in summary['experiments']} == expected_labels
    calendar, schedule = schedule_and_calendar()
    common = pd.read_csv(out/'common_samples.csv', parse_dates=['trade_date','D_end','reference_end'], float_precision='round_trip')
    ic = prior.verify_diagnostics(common, schedule, out)
    prior.verify_targets(common, schedule, out)
    checks, annual, boundaries, operations = [], [], [], []
    expected_calendar = calendar[calendar >= '2017-10-01']
    for item in summary['experiments']:
        folder = out/item['strategy']
        assert sha(folder/'historical_targets.csv') == sha(out/f'targets_{item["path"]}.csv')
        cost = int(item['strategy'].rsplit('_',1)[1][:-2])
        assert item['config'] == asdict(Config(slippage_bps=cost, zero_trading_costs=cost == 0))
        nav = pd.read_csv(folder/'nav.csv', parse_dates=['date'], float_precision='round_trip')
        orders = pd.read_csv(folder/'orders.csv', parse_dates=['date'], float_precision='round_trip')
        events = pd.read_csv(folder/'corporate_events.csv', parse_dates=['date'], float_precision='round_trip')
        holdings = pd.read_csv(folder/'holdings.csv', parse_dates=['date'], float_precision='round_trip')
        assert pd.DatetimeIndex(nav.date).equals(expected_calendar)
        assert nav.loc[nav.date.eq(pd.Timestamp('2017-12-29')),'equity'].iloc[0] == 1_000_000
        assert orders.date.isin(schedule.execution_date).all()
        if cost == 0:
            assert orders[['fee','slippage_cost']].eq(0).all().all()
        record, edges = prior.reconstruct_account(nav, orders, events, holdings)
        assert len(edges) == 2
        checks.append(dict(strategy=item['strategy'], **record))
        operations.append(dict(strategy=item['strategy'], **prior.summarize_operations(nav, orders)))
        boundaries.extend(dict(strategy=item['strategy'], **edge) for edge in edges)
        calculated = summarize(nav, orders, schedule.execution_date.iloc[0], pd.Timestamp('2018-01-01'))
        for name, value in calculated.items():
            if isinstance(value, (float,int)):
                assert np.isclose(value,item[name],rtol=0,atol=1e-6), (item['strategy'],name)
        assert abs(float(orders.fee.sum())-item['total_fees']) < 1e-6
        assert abs(float(orders.slippage_cost.sum())-item['total_slippage']) < 1e-6
        previous_equity = 1_000_000.
        for year, group in nav.loc[nav.date >= '2018-01-01'].groupby(nav.date.dt.year):
            ending = float(group.equity.iloc[-1])
            annual.append(dict(strategy=item['strategy'],year=int(year),start_equity=previous_equity,
                               end_equity=ending,return_value=ending/previous_equity-1))
            previous_equity = ending
    assert len(checks) == 6 and len(boundaries) == 12
    annual = pd.DataFrame(annual)
    stats = pd.DataFrame(summary['experiments']).set_index('strategy')
    gates, mean_ic, yearly_ic = prior.strategy_gates(stats,annual,ic,schedule)
    assert check_fingerprints(protocol) == formation['old_artifacts']
    annual.to_csv(out/'annual_returns.csv',index=False)
    pd.DataFrame(operations).to_csv(out/'account_operations.csv',index=False)
    stats.reset_index().drop(columns=['config']).to_csv(out/'comparison.csv',index=False)
    pd.DataFrame(boundaries).to_csv(out/'year_boundary_audit.csv',index=False)
    persist('flow_reconstruction_audit.json',dict(status='passed',checks=checks,year_boundaries=len(boundaries)),out)
    result = dict(formation, engineering_verification_passed=True, accounts=checks, year_boundaries=len(boundaries),
                  mean_rankIC=mean_ic,yearly_rankIC={int(k):float(v) for k,v in yearly_ic.items()},
                  gates=gates,research_gates_passed=all(gates.values()),summary_sha256=sha(out/'summary.json'),
                  scope='Retrospective raw-input r2 mapping revision; not a repaired r1 or independent holdout.')
    persist('verification.json',result,out)
    print(json.dumps(dict(engineering='passed',research_gates_passed=all(gates.values()),gates=gates),ensure_ascii=False),flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['preparation', 'final'], default='final')
    args = parser.parse_args()
    try:
        verify_preparation() if args.stage == 'preparation' else main()
    except Exception:
        failure = OUT/f'verification_failure_{args.stage}_{pd.Timestamp.now():%Y%m%dT%H%M%S}.txt'
        failure.write_text(traceback.format_exc(),encoding='utf-8')
        raise
