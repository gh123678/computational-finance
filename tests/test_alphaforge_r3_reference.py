"""Independent small paths exercise the approved reference-return boundary."""
import numpy as np
import pandas as pd
import pytest

from scripts.alphaforge_r3_reference import compute_reference_windows, weekly_reference_labels


CODE = '000001.SZ'


def sample(n=32):
    calendar = pd.bdate_range('2018-07-02', periods=n)
    closes = 20 * 1.01 ** np.arange(n)
    group = pd.DataFrame(dict(trade_date=calendar, ts_code=CODE, close=closes,
                              pre_close=np.r_[19., closes[:-1]], open=closes * .997))
    group['close_text'] = group.close.map(str)
    group['pre_close_text'] = group.pre_close.map(str)
    return calendar, group


def event(day, known, verified=True, identifier='E', conflict=False):
    return dict(code=CODE, event_date=day, known_date=known,
                timing_verified=verified, event_id=identifier, conflict=conflict)


def schedule(calendar, start=22, end=27):
    return pd.DataFrame(dict(signal_date=[calendar[start - 1]],
                             execution_date=[calendar[start]],
                             next_execution=[calendar[end] if end is not None else pd.NaT]))


def benchmark(calendar):
    return pd.Series(100 * 1.002 ** np.arange(len(calendar)), index=calendar)


def test_twenty_one_points_twenty_bridges_and_original_factor_definitions():
    calendar, group = sample()
    group.loc[0, 'pre_close_text'] = None
    result = compute_reference_windows(group, calendar, calendar[:21])
    assert len(result) == 21 and result.iloc[:20].reason.eq('warmup_21').all()
    row = result.iloc[20]
    assert row.reference_valid and row.bridge_count == row.valid_bridge_count == 20
    assert row.window_start == calendar[0] and row.window_end == calendar[20]
    assert row.valid_quote_count_21 == 21 and row.K_start == row.K_end == 1
    prices = group.close.to_numpy()[:21]
    assert row.momentum20 == prices[-1] / prices[0] - 1
    assert row.reversal5 == -(prices[-1] / prices[-6] - 1)
    assert row.lowvol20 == -np.std(prices[1:] / prices[:-1] - 1, ddof=1)


def test_known_cash_reference_change_uses_raw_observed_reference_not_theory():
    calendar, group = sample()
    group.loc[10, 'pre_close_text'] = str(group.close.iloc[9] - .2001741)
    events = [event(calendar[10], calendar[9])]
    row = compute_reference_windows(group, calendar, calendar[[20]], events).iloc[0]
    k, prices = 1., [float(group.close_text.iloc[0])]
    for index in range(1, 21):
        k = np.float64(np.float64(k * float(group.close_text.iloc[index - 1])) /
                       float(group.pre_close_text.iloc[index]))
        prices.append(np.float64(float(group.close_text.iloc[index]) * k))
    prices = np.array(prices)
    assert row.reference_valid and row.reference_change_count == row.known_action_count == 1
    assert row.K_end == k and row.P_end == prices[-1]
    assert row.momentum20 == prices[-1] / prices[0] - 1
    assert row.reversal5 == -(prices[-1] / prices[-6] - 1)
    assert row.lowvol20 == -np.std(prices[1:] / prices[:-1] - 1, ddof=1)


def test_decimal_reference_matching_precedes_float_rounding():
    calendar, group = sample()
    group.loc[19, 'close_text'] = '20.00000000000000000001'
    group.loc[20, 'pre_close_text'] = '20.00000000000000000002'
    assert float(group.close_text.iloc[19]) == float(group.pre_close_text.iloc[20])
    row = compute_reference_windows(group, calendar, calendar[[20]]).iloc[0]
    assert not row.reference_valid and row.reason == 'unexplained_reference_change'
    group.loc[19, 'close_text'] = '2.0000E+1'
    group.loc[20, 'pre_close_text'] = '20.00'
    assert compute_reference_windows(group, calendar, calendar[[20]]).iloc[0].reference_valid


@pytest.mark.parametrize('value', [None, '', 'NaN', 'Infinity', '0', '-2', 'not a price'])
def test_invalid_reference_text_is_not_filled_from_float_or_future(value):
    calendar, group = sample()
    group.loc[12, 'pre_close_text'] = value
    row = compute_reference_windows(group, calendar, calendar[[20]]).iloc[0]
    assert not row.reference_valid and row.reason == 'unknown_reference'
    assert pd.isna(row.momentum20) and row.unknown_reference_count == 1


def test_missing_calendar_quote_is_not_compressed_or_key_deleted():
    calendar, group = sample()
    result = compute_reference_windows(group.drop(index=10), calendar, calendar[[20, 21]])
    assert len(result) == 2 and not result.reference_valid.any()
    assert result.reason.eq('missing_quote').all() and result.valid_quote_count_21.eq(20).all()
    assert result.bridge_count.eq(20).all() and result.unknown_reference_count.eq(2).all()


@pytest.mark.parametrize('known,verified', [(None, True), ('2018-12-31', True),
                                           ('2018-07-02', False), ('2018-07-02', 'False')])
def test_unknown_or_late_event_does_not_explain_break_or_reject_continuity(known, verified):
    calendar, group = sample()
    events = [event(calendar[10], known, verified)]
    continuous = compute_reference_windows(group, calendar, calendar[[20]], events).iloc[0]
    assert continuous.reference_valid and continuous.event_timing_unverified_count == 1
    group.loc[10, 'pre_close_text'] = '10'
    broken = compute_reference_windows(group, calendar, calendar[[20]], events).iloc[0]
    assert not broken.reference_valid and broken.reason == 'unexplained_reference_change'
    assert broken.known_action_count == 0


def test_formation_uses_formation_cutoff_but_does_not_read_future_recovery_or_A():
    calendar, group = sample()
    signals = calendar[[20, 21]]
    expected = compute_reference_windows(group, calendar, signals)
    changed = group.copy()
    changed.loc[22:, ['close_text', 'pre_close_text']] = '999'
    changed.loc[22:, 'open'] = 999.
    changed['adj_factor'] = np.nan
    changed['D_label'] = 1e100
    changed['R_week'] = -1e100
    actual = compute_reference_windows(changed, calendar, signals,
                                       [event(calendar[25], calendar[0])])
    pd.testing.assert_frame_equal(expected, actual)
    late = compute_reference_windows(group, calendar, signals,
                                    [event(calendar[10], calendar[25], conflict=True)])
    assert late.reference_valid.all()
    for column in ['reference_valid', 'reason', 'momentum20', 'reversal5', 'lowvol20', 'K_end']:
        pd.testing.assert_series_equal(expected[column], late[column])
    assert late.event_timing_unverified_count.eq(1).all()
    truncated = compute_reference_windows(group.iloc[:22], calendar[:22], signals)
    pd.testing.assert_frame_equal(expected, truncated)


def test_closed_day_event_literal_interval_and_first_point_boundary():
    calendar, group = sample()
    saturday = pd.Timestamp('2018-07-07')
    assert calendar[4] < saturday < calendar[5]
    group.loc[5, 'pre_close_text'] = '12'
    events = [event(calendar[0], calendar[0], identifier='outside', conflict=True),
              event(saturday, '2018-07-06', identifier='inside')]
    row = compute_reference_windows(group, calendar, calendar[[20]], events).iloc[0]
    assert row.reference_valid and row.known_action_count == 1


def test_known_conflicts_only_block_when_known_and_multiple_actions_are_not_conflicts():
    calendar, group = sample()
    multiple = [event(calendar[6], calendar[5], identifier='a'),
                event(calendar[6], calendar[5], identifier='b')]
    row = compute_reference_windows(group, calendar, calendar[[20]], multiple).iloc[0]
    assert row.reference_valid and row.known_action_count == 2
    multiple[0]['conflict'] = True
    row = compute_reference_windows(group, calendar, calendar[[20]], multiple).iloc[0]
    assert not row.reference_valid and row.reason == 'known_action_conflict'
    assert row.known_conflict_count == 1


def test_constant_reference_path_is_valid_zero_factor_tie():
    calendar, group = sample()
    group['close_text'] = group['pre_close_text'] = '12'
    row = compute_reference_windows(group, calendar, calendar[[20]]).iloc[0]
    assert row.reference_valid
    assert row.momentum20 == row.reversal5 == row.lowvol20 == 0


def test_labels_use_open_anchors_and_only_u_to_v_internal_bridges():
    calendar, group = sample()
    plans = schedule(calendar)
    group.loc[22, 'pre_close_text'] = None
    events = [event(calendar[22], calendar[21], conflict=True)]
    row = weekly_reference_labels(group, calendar, plans, benchmark(calendar), events).iloc[0]
    expected = group.open.iloc[27] / group.open.iloc[22] - 1 - (
        benchmark(calendar).iloc[27] / benchmark(calendar).iloc[22] - 1)
    assert row.R_valid and row.R_week == expected and row.bridge_count == 5
    assert row.K_start == row.K_end == 1 and row.known_action_count == 0
    assert row.R_end == calendar[27]


def test_label_event_cutoff_is_each_bridge_rear_date_not_formation_or_v():
    calendar, group = sample()
    plans = schedule(calendar)
    group.loc[24, 'pre_close_text'] = '10'
    known_after_formation = [event(calendar[24], calendar[23])]
    valid = weekly_reference_labels(group, calendar, plans, benchmark(calendar), known_after_formation).iloc[0]
    assert valid.R_valid and valid.known_action_count == 1
    known_after_bridge = [event(calendar[24], calendar[25])]
    invalid = weekly_reference_labels(group, calendar, plans, benchmark(calendar), known_after_bridge).iloc[0]
    assert not invalid.R_valid and invalid.R_reason == 'unexplained_reference_change'
    assert invalid.event_timing_unverified_count == 1
    same_day = [event(calendar[24], calendar[24])]
    assert weekly_reference_labels(group, calendar, plans, benchmark(calendar), same_day).iloc[0].R_valid


def test_rights_with_unverified_timing_never_becomes_a_known_label_explanation():
    calendar, group = sample()
    plans = schedule(calendar)
    rights = [dict(event(calendar[24], None, False), kind='rights')]
    continuous = weekly_reference_labels(group, calendar, plans, benchmark(calendar), rights).iloc[0]
    assert continuous.R_valid and continuous.known_action_count == 0
    assert continuous.event_timing_unverified_count == 1
    group.loc[24, 'pre_close_text'] = '10'
    assert not weekly_reference_labels(group, calendar, plans, benchmark(calendar), rights).iloc[0].R_valid


def test_missing_internal_quote_label_is_invalid_and_cannot_change_formation():
    calendar, group = sample()
    plans = schedule(calendar)
    before = compute_reference_windows(group, calendar, calendar[[21]])
    labels = weekly_reference_labels(group.drop(index=24), calendar, plans, benchmark(calendar))
    assert len(labels) == 1 and not labels.iloc[0].R_valid
    assert labels.iloc[0].R_reason == 'missing_quote' and pd.isna(labels.iloc[0].R_week)
    after = compute_reference_windows(group.drop(index=24), calendar, calendar[[21]])
    pd.testing.assert_frame_equal(before, after)


@pytest.mark.parametrize('kind', ['stock', 'benchmark', 'last'])
def test_endpoint_and_last_period_failures_keep_label_rows(kind):
    calendar, group = sample()
    plans, index = schedule(calendar), benchmark(calendar)
    if kind == 'stock':
        group.loc[27, 'open'] = 0
        reason = 'stock_endpoint'
    elif kind == 'benchmark':
        index.iloc[27] = np.nan
        reason = 'benchmark_endpoint'
    else:
        plans['next_execution'] = pd.NaT
        reason = 'missing_next_execution'
    row = weekly_reference_labels(group, calendar, plans, index).iloc[0]
    assert not row.R_valid and row.R_reason == reason and pd.isna(row.R_week)


def test_future_quote_event_and_benchmark_perturbations_leave_earlier_label_unchanged():
    calendar, group = sample()
    plans, index = schedule(calendar), benchmark(calendar)
    expected = weekly_reference_labels(group, calendar, plans, index)
    changed, different = group.copy(), index.copy()
    changed.loc[28:, ['close_text', 'pre_close_text']] = '1'
    changed.loc[28:, 'open'] = 1.
    different.iloc[28:] *= 100
    actual = weekly_reference_labels(changed, calendar, plans, different,
                                     [event(calendar[30], calendar[0], conflict=True)])
    pd.testing.assert_frame_equal(expected, actual)


def test_label_closed_day_event_maps_to_literal_bridge_without_moving_effective_day():
    calendar, group = sample()
    # u=Friday, internal next point=Monday; the action retains Saturday's date.
    plans = schedule(calendar, start=19, end=24)
    saturday = calendar[19] + pd.Timedelta(days=1)
    assert calendar[19].dayofweek == 4 and calendar[19] < saturday < calendar[20]
    group.loc[20, 'pre_close_text'] = '10'
    row = weekly_reference_labels(group, calendar, plans, benchmark(calendar),
                                   [event(saturday, calendar[19])]).iloc[0]
    assert row.R_valid and row.reference_change_count == row.known_action_count == 1


def test_later_announcement_cannot_change_earlier_label_value_or_explain_earlier_break():
    calendar, group = sample()
    plans = schedule(calendar)
    expected = weekly_reference_labels(group, calendar, plans, benchmark(calendar))
    events = [event(calendar[24], calendar[28], conflict=True)]
    later = weekly_reference_labels(group, calendar, plans, benchmark(calendar), events)
    for column in ['R_valid', 'R_week', 'R_reason', 'K_end', 'stock_reference_return']:
        pd.testing.assert_series_equal(expected[column], later[column])
    assert later.iloc[0].event_timing_unverified_count == 1
    group.loc[24, 'pre_close_text'] = '10'
    broken = weekly_reference_labels(group, calendar, plans, benchmark(calendar), events).iloc[0]
    assert not broken.R_valid and broken.R_reason == 'unexplained_reference_change'


def test_source_open_missingness_is_authoritative_and_missing_v_close_is_not_hidden():
    calendar, group = sample()
    plans = schedule(calendar)
    group['open_text'] = group.open.map(str)
    group.loc[27, 'open_text'] = None
    row = weekly_reference_labels(group, calendar, plans, benchmark(calendar)).iloc[0]
    assert not row.R_valid and row.R_reason == 'stock_endpoint'
    group.loc[27, 'open_text'] = str(group.open.iloc[27])
    group.loc[27, 'close_text'] = None
    row = weekly_reference_labels(group, calendar, plans, benchmark(calendar)).iloc[0]
    assert not row.R_valid and row.R_reason == 'invalid_close'


def test_reference_values_ignore_numeric_shadow_prices_and_all_other_unrequested_fields():
    calendar, group = sample()
    expected = compute_reference_windows(group, calendar, calendar[[20]])
    group['close'] = -999
    group['pre_close'] = -999
    group['high'] = group['low'] = group['vol'] = group['amount'] = group['adj_factor'] = np.nan
    pd.testing.assert_frame_equal(expected, compute_reference_windows(group, calendar, calendar[[20]]))


def test_float64_nonfinite_path_fails_closed_without_dropping_key():
    calendar, group = sample()
    group.loc[10, 'pre_close_text'] = '1e-320'
    row = compute_reference_windows(group, calendar, calendar[[20]],
                                     [event(calendar[10], calendar[9])]).iloc[0]
    assert not row.reference_valid and row.reason == 'nonfinite_reference_index'
    assert pd.isna(row.momentum20)


def test_schema_empty_signals_source_dates_and_structural_errors():
    calendar, group = sample()
    group['trade_date'] = group.trade_date.dt.strftime('%Y%m%d').astype(int)
    assert compute_reference_windows(group, calendar, calendar[[20]]).iloc[0].reference_valid
    assert {'reference_valid', 'momentum20', 'reason'}.issubset(
        compute_reference_windows(group, calendar, []).columns)
    with pytest.raises(ValueError, match='Raw CSV price text'):
        compute_reference_windows(group.drop(columns='close_text'), calendar, calendar[[20]])
    with pytest.raises(ValueError, match='Duplicate asset'):
        compute_reference_windows(pd.concat([group, group.iloc[:1]]), calendar, calendar[[20]])
    with pytest.raises(ValueError, match='sorted and unique'):
        compute_reference_windows(group, calendar, calendar[[21, 20]])
    duplicate = [event(calendar[10], calendar[9]), event(calendar[11], calendar[9])]
    with pytest.raises(ValueError, match='Duplicate event_id'):
        compute_reference_windows(group, calendar, calendar[[20]], duplicate)
