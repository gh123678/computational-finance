"""r2 reference/action changes only; the frozen r1 formula remains unchanged."""
import json

import numpy as np
import pandas as pd
import pytest

from scripts.alphaforge_case_factor import compute_asset as r1_asset, formula_10
from scripts.alphaforge_case_r2_features import compute_asset


def sample(n=24):
    calendar = pd.bdate_range('2018-08-01', periods=n)
    close = 10 + np.arange(n) * .2 + np.sin(np.arange(n))
    frame = pd.DataFrame({'trade_date': calendar, 'ts_code': '000001.SZ',
                          'close': close, 'pre_close': np.r_[10., close[:-1]],
                          'vol': 100 + np.arange(n) ** 2, 'adj_factor': 1.})
    return calendar, frame


def event(date, known_date, verified=True, event_id='e1', code='000001.SZ'):
    return dict(code=code, event_date=date, known_date=known_date,
                timing_verified=verified, event_id=event_id)


def test_ten_points_nine_transitions_and_first_day_boundary():
    calendar, frame = sample()
    frame.loc[0, 'pre_close'] = 1.  # Outside the first full window's 9 transitions.
    features, transitions = compute_asset(frame, calendar, calendar[:10])
    assert features.iloc[:9].reason.eq('warmup_10').all()
    assert features.iloc[9].case_valid
    assert len(transitions) == 9
    assert transitions.previous_date.iloc[0] == calendar[0]
    assert transitions.current_date.iloc[-1] == calendar[9]
    expected = formula_10(frame.close.iloc[:10], frame.vol.iloc[:10] * 100)
    assert features.iloc[9].factor == pytest.approx(expected['factor'])
    assert features.iloc[9].signal == -features.iloc[9].factor


def test_reference_change_excludes_only_windows_spanning_that_transition():
    calendar, frame = sample()
    frame.loc[10, 'pre_close'] -= .1
    features, transitions = compute_asset(frame, calendar, calendar[9:21])
    assert features.loc[features.trade_date.between(calendar[10], calendar[18]), 'reason'].eq('raw_reference_change').all()
    assert features.loc[features.trade_date.eq(calendar[19]), 'case_valid'].all()
    assert len(transitions) == len(features) * 9


def test_decimal_source_text_overrides_float_rounding_and_scientific_notation_is_exact():
    calendar, frame = sample()
    frame['close_text'] = frame.close.astype(str)
    frame['pre_close_text'] = frame.pre_close.astype(str)
    frame.loc[8, 'close_text'] = '10.00000000000000000001'
    frame.loc[9, 'pre_close_text'] = '10.00000000000000000002'
    # Both collapse to the same binary float, but the source Decimal values differ.
    assert float(frame.loc[8, 'close_text']) == float(frame.loc[9, 'pre_close_text'])
    features, transitions = compute_asset(frame, calendar, calendar[[9]])
    assert features.iloc[0].reason == 'raw_reference_change'
    last = transitions.iloc[-1]
    assert last.previous_close_text == '10.00000000000000000001'
    assert last.current_pre_close_text == '10.00000000000000000002'
    frame.loc[8, 'close_text'] = '1.00E+1'
    frame.loc[9, 'pre_close_text'] = '10.000'
    features, _ = compute_asset(frame, calendar, calendar[[9]])
    assert features.iloc[0].case_valid


@pytest.mark.parametrize('value', [None, '', 'NaN', 'Infinity', '0', '-1', 'not-a-number'])
def test_unknown_source_reference_is_not_filled_from_numeric_column(value):
    calendar, frame = sample()
    frame['pre_close_text'] = frame.pre_close.astype(str)
    frame.loc[9, 'pre_close_text'] = value
    features, _ = compute_asset(frame, calendar, calendar[[9]])
    assert features.iloc[0].reason == 'unknown_reference'
    assert features.iloc[0].unknown_reference_count == 1
    assert pd.isna(features.iloc[0].factor)


def test_missing_calendar_quote_does_not_compress_or_fill_window():
    calendar, frame = sample()
    features, transitions = compute_asset(frame.drop(index=8), calendar, calendar[[9]])
    assert features.iloc[0].reason == 'unknown_reference'
    assert features.iloc[0].valid_quote_count_10 == 9
    assert features.iloc[0].unknown_reference_count == 2
    assert len(transitions) == 9


def test_known_action_on_first_window_day_is_outside_but_internal_last_day_is_included():
    calendar, frame = sample()
    events = [event(calendar[0], calendar[0], event_id='before'),
              event(calendar[9], calendar[9], event_id='internal')]
    features, transitions = compute_asset(frame, calendar, calendar[[9]], events)
    assert features.iloc[0].reason == 'known_action'
    assert features.iloc[0].known_action_count == 1
    assert json.loads(transitions.iloc[-1].known_action_ids) == ['internal']
    assert all('before' not in json.loads(value) for value in transitions.matched_event_ids)


@pytest.mark.parametrize('verified,known', [(True, None), (True, '2030-01-01'),
                                         (False, '2018-08-01'), ('False', '2018-08-01'),
                                         (None, '2018-08-01')])
def test_unverified_or_late_action_is_counted_without_changing_eligibility(verified, known):
    calendar, frame = sample()
    original, _ = compute_asset(frame, calendar, calendar[[9]])
    features, transitions = compute_asset(frame, calendar, calendar[[9]],
                                          [event(calendar[7], known, verified)])
    assert features.iloc[0].case_valid
    assert features.iloc[0].factor == original.iloc[0].factor
    assert features.iloc[0].known_action_count == 0
    assert features.iloc[0].event_timing_unverified_count == 1
    matched = transitions.loc[transitions.current_date.eq(calendar[7])].iloc[0]
    assert json.loads(matched.unverified_event_ids) == ['e1']
    assert json.loads(matched.known_action_ids) == []


def test_action_becomes_known_by_formation_not_necessarily_on_effective_day():
    calendar, frame = sample()
    features, _ = compute_asset(frame, calendar, calendar[[9]],
                                [event(calendar[7], calendar[9], 'True')])
    assert features.iloc[0].reason == 'known_action'
    assert features.iloc[0].known_action_count == 1


def test_nontrading_effective_date_inside_window_is_not_silently_omitted_or_moved():
    calendar, frame = sample()
    saturday = pd.Timestamp('2018-08-04')
    features, transitions = compute_asset(frame, calendar, calendar[[9]],
                                          [event(saturday, '2018-08-03')])
    assert features.iloc[0].reason == 'known_action'
    matched = transitions.loc[transitions.known_action_count.eq(1)].iloc[0]
    assert matched.previous_date == pd.Timestamp('2018-08-03')
    assert matched.current_date == pd.Timestamp('2018-08-06')
    assert json.loads(matched.event_effective_dates) == {'e1': '2018-08-04'}


def test_multiple_actions_count_event_ids_and_other_assets_are_ignored():
    calendar, frame = sample()
    events = [event(calendar[7], calendar[8], event_id='a'),
              event(calendar[7], calendar[8], event_id='b'),
              event(calendar[7], calendar[8], event_id='x', code='600000.SH')]
    features, transitions = compute_asset(frame, calendar, calendar[[9]], events)
    assert features.iloc[0].known_action_count == 2
    matched = transitions.loc[transitions.current_date.eq(calendar[7])].iloc[0]
    assert json.loads(matched.known_action_ids) == ['a', 'b']


def test_isolated_factor_changes_are_reported_without_adjusting_price_or_volume():
    calendar, frame = sample()
    original, _ = compute_asset(frame, calendar, calendar[[9]])
    frame.loc[7:, 'adj_factor'] = 1.000000001
    changed, transitions = compute_asset(frame, calendar, calendar[[9]])
    assert changed.iloc[0].case_valid
    assert changed.iloc[0].adj_factor_change_count == 1
    assert changed.iloc[0].isolated_factor_change_no_observed_reference_break
    assert changed.iloc[0].factor == original.iloc[0].factor
    assert transitions.adj_factor_changed.sum() == 1


def test_r1_r2_common_valid_inputs_have_identical_formula_values():
    calendar, frame = sample()
    old = r1_asset(frame, calendar, calendar)
    new, _ = compute_asset(frame, calendar, calendar)
    columns = ['rho', 'factor', 'signal', 'nlvar', 'nrvar', 'guard']
    pd.testing.assert_frame_equal(old.loc[old.case_valid, columns], new.loc[new.case_valid, columns])


def test_future_quotes_future_effective_events_and_labels_do_not_change_past():
    calendar, frame = sample()
    signals = calendar[:16]
    expected, transitions = compute_asset(frame, calendar, signals)
    changed = frame.copy()
    changed.loc[16:, ['close', 'pre_close', 'vol', 'adj_factor']] *= 10
    changed['D_label'] = 999
    changed['D_valid'] = False
    actual, actual_transitions = compute_asset(changed, calendar, signals,
                                                [event(calendar[16], calendar[0])])
    pd.testing.assert_frame_equal(expected, actual)
    pd.testing.assert_frame_equal(transitions, actual_transitions)
    truncated, truncated_transitions = compute_asset(frame.iloc[:16], calendar[:16], signals)
    pd.testing.assert_frame_equal(expected, truncated)
    pd.testing.assert_frame_equal(transitions, truncated_transitions)


def test_constant_formula_guard_keeps_valid_zero_ties():
    calendar, frame = sample()
    frame['close'] = frame['pre_close'] = 12.
    features, _ = compute_asset(frame, calendar, calendar[9:])
    assert features.case_valid.all()
    assert features.guard.all()
    assert features.factor.eq(0).all()
    assert features.signal.eq(0).all()


def test_microvariance_guard_and_share_units_reuse_original_rule_without_clipping():
    calendar, frame = sample()
    frame['close'] = 10 + 1e-5 * (np.arange(len(frame)) - 4.5)
    frame['pre_close'] = np.r_[10., frame.close.iloc[:-1]]
    frame['vol'] = 1e7 + 1e6 * np.arange(len(frame))
    features, _ = compute_asset(frame, calendar, calendar[[9]])
    row = features.iloc[0]
    expected = formula_10(frame.close.iloc[:10], frame.vol.iloc[:10] * 100)
    assert row.case_valid and row.guard and row.rho > 1
    assert row.factor == expected['factor']
    assert row.volume_scale == 100


def test_bad_volume_still_invalidates_ten_point_math_input():
    calendar, frame = sample()
    frame.loc[9, 'vol'] = 0
    features, _ = compute_asset(frame, calendar, calendar[[9]])
    assert features.iloc[0].reason == 'invalid_quote'
    assert features.iloc[0].valid_quote_count_10 == 9


def test_invalid_event_boolean_and_effective_date_fail_closed():
    calendar, frame = sample()
    with pytest.raises(ValueError, match='timing_verified'):
        compute_asset(frame, calendar, calendar[[9]], [event(calendar[7], calendar[8], 'maybe')])
    with pytest.raises(ValueError, match='effective date'):
        compute_asset(frame, calendar, calendar[[9]], [event(None, calendar[8])])


def test_integer_quote_dates_and_empty_signal_output_schema():
    calendar, frame = sample()
    frame['trade_date'] = frame.trade_date.dt.strftime('%Y%m%d').astype(int)
    features, transitions = compute_asset(frame, calendar, calendar[[9]])
    assert features.iloc[0].case_valid and len(transitions) == 9
    empty, no_transitions = compute_asset(frame, calendar, [])
    assert empty.empty and no_transitions.empty
    assert {'case_valid', 'guard', 'event_timing_unverified_count'}.issubset(empty.columns)
