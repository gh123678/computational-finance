"""Known identities, epsilon behavior, units and past-only data boundaries."""
import numpy as np
import pandas as pd
import pytest

from scripts.alphaforge_case_factor import compute_asset, formula_10


def sample(n=24):
    calendar = pd.bdate_range('2020-01-02', periods=n)
    close = np.array([10, 11, 10, 13, 12, 14, 14, 15, 13, 17,
                      18, 15, 19, 17, 22, 20, 21, 22, 19, 25,
                      24, 22, 27, 28], dtype=float)[:n]
    frame = pd.DataFrame({'trade_date': calendar, 'ts_code': '000001.SZ',
                          'close': close, 'vol': 100 + np.arange(n) ** 2,
                          'adj_factor': 1.})
    return calendar, frame


def test_known_positive_negative_and_constant():
    x = np.arange(1., 11.)
    positive = formula_10(x, 2 * x + 50)
    negative = formula_10(x, 50 - 2 * x)
    assert positive['rho'] == pytest.approx(1)
    assert positive['factor'] == pytest.approx(np.log(2))
    assert positive['signal'] == pytest.approx(-np.log(2))
    assert negative['rho'] == pytest.approx(-1)
    assert negative['factor'] == pytest.approx(-np.log(2))
    assert not positive['guard']
    for left, right in ((np.ones(10), x), (x, np.ones(10)), (np.ones(10), np.ones(10))):
        constant = formula_10(left, right)
        assert constant['guard']
        assert constant['rho'] == constant['factor'] == constant['signal'] == 0


def test_epsilon_branch_is_covariance_sum_without_clipping_or_default_correlation():
    centered = np.arange(10.) - 4.5
    left = 10 + 1e-5 * centered
    right = 1e9 + 1e8 * centered
    value = formula_10(left, right)
    expected_covariance = sum((left - left.mean()) * (right - right.mean()))
    assert value['nlvar'] < 1e-6
    assert value['guard']
    assert value['rho'] == pytest.approx(expected_covariance)
    assert value['rho'] > 1  # Guarded source operator is not always a correlation.
    assert value['factor'] == pytest.approx(np.log1p(expected_covariance))


def test_above_epsilon_is_the_ordinary_centered_correlation():
    x = np.arange(10.) - 4.5
    left = 10 + 2e-4 * x
    right = np.array([5, 6, 8, 7, 11, 9, 13, 12, 10, 15.])
    result = formula_10(left, right)
    assert result['nlvar'] > 1e-6
    assert not result['guard']
    assert result['rho'] == pytest.approx(np.corrcoef(left, right)[0, 1])


def test_only_ten_finite_points_and_explicit_float_precision():
    for count in (9, 11):
        with pytest.raises(ValueError, match='Exactly 10'):
            formula_10(np.arange(count), np.arange(count))
    bad = np.arange(10.)
    bad[-1] = np.nan
    with pytest.raises(ValueError, match='finite'):
        formula_10(bad, np.arange(10.))
    with pytest.raises(ValueError, match='float32 or float64'):
        formula_10(np.arange(10.), np.arange(10.), dtype=np.int64)
    value = formula_10(np.arange(10.), np.arange(10.), dtype=np.float32)
    assert value['rho'] == pytest.approx(1)


def test_exact_ten_sessions_includes_formation_day_and_uses_price_levels():
    calendar, frame = sample()
    result = compute_asset(frame, calendar, calendar)
    assert result.loc[:8, 'case_valid'].eq(False).all()
    assert result.loc[:8, 'reason'].eq('warmup_10').all()
    first = result.iloc[9]
    expected = formula_10(frame.close.iloc[:10], frame.vol.iloc[:10] * 100)
    assert first.case_valid
    assert first.window_start == calendar[0]
    assert first.window_end == calendar[9]
    assert first.rho == pytest.approx(expected['rho'])
    changed = frame.copy()
    changed.loc[9, 'close'] = 3
    assert compute_asset(changed, calendar, calendar).iloc[9].rho != pytest.approx(first.rho)
    # A returns-based correlation requires 11 closes and is a different factor.
    returns = frame.close.iloc[:11].pct_change(fill_method=None).iloc[1:]
    wrong = formula_10(returns, frame.vol.iloc[1:11] * 100)['rho']
    assert result.iloc[10].rho != pytest.approx(wrong)


def test_raw_close_is_not_silently_adjusted_and_vol_is_shares():
    calendar, frame = sample()
    centered = np.arange(24.) - 4.5
    # This very small raw-volume variance crosses epsilon only after *100.
    frame['vol'] = 10 + 1e-5 * centered
    frame['adj_factor'] = 500.
    row = compute_asset(frame, calendar, calendar[[9]]).iloc[0]
    expected = formula_10(frame.close.iloc[:10], frame.vol.iloc[:10] * 100)
    unconverted = formula_10(frame.close.iloc[:10], frame.vol.iloc[:10])
    assert row.case_valid and not row.guard
    assert unconverted['guard']
    assert row.volume_scale == 100
    assert row.nlvar == pytest.approx(expected['nlvar'])
    assert row.nrvar == pytest.approx(expected['nrvar'])
    assert row.rho == pytest.approx(expected['rho'])


def test_missing_session_invalidates_without_compressing_calendar():
    calendar, frame = sample()
    result = compute_asset(frame.drop(index=10), calendar, calendar)
    assert result.loc[10:19, 'case_valid'].eq(False).all()
    assert result.loc[10:19, 'reason'].eq('missing_quote').all()
    assert result.loc[10:19, 'factor'].isna().all()
    assert result.loc[20, 'case_valid']


@pytest.mark.parametrize('field,value', [('close', 0), ('vol', 0), ('adj_factor', -1), ('close', np.inf)])
def test_invalid_quote_excluded_by_formation_information(field, value):
    calendar, frame = sample()
    frame.loc[10, field] = value
    result = compute_asset(frame, calendar, calendar)
    assert result.loc[10:19, 'reason'].eq('invalid_quote').all()
    assert result.loc[10:19, 'factor'].isna().all()
    assert result.loc[20, 'case_valid']


def test_any_adjustment_change_excludes_exactly_the_windows_containing_both_levels():
    calendar, frame = sample()
    frame.loc[10:, 'adj_factor'] = 1.000000001
    result = compute_asset(frame, calendar, calendar)
    assert result.loc[10:18, 'reason'].eq('adjustment_factor_change').all()
    assert result.loc[19, 'case_valid']  # Window [10,19] contains one factor level.
    assert result.loc[19, 'window_start'] == calendar[10]


def test_future_mutation_extension_and_future_labels_cannot_change_past():
    calendar, frame = sample()
    original = compute_asset(frame, calendar, calendar[:16])
    changed = frame.copy()
    changed.loc[16:, ['close', 'vol', 'adj_factor']] *= 17
    changed['D_valid'] = False
    changed['D_label'] = np.arange(len(frame)) * 1000
    pd.testing.assert_frame_equal(original, compute_asset(changed, calendar, calendar[:16]))
    truncated = compute_asset(frame.iloc[:16], calendar[:16], calendar[:16])
    pd.testing.assert_frame_equal(original, truncated)


def test_constant_windows_are_valid_formation_ties():
    calendar, frame = sample()
    frame['close'] = 12.
    result = compute_asset(frame, calendar, calendar[9:])
    assert result.case_valid.all()
    assert result.guard.all()
    assert result.factor.eq(0).all()


def test_rejects_ambiguous_asset_and_dates():
    calendar, frame = sample()
    with pytest.raises(ValueError, match='duplicate'):
        compute_asset(pd.concat([frame, frame.iloc[:1]]), calendar, calendar)
    mixed = frame.copy()
    mixed.loc[0, 'ts_code'] = '000002.SZ'
    with pytest.raises(ValueError, match='one asset'):
        compute_asset(mixed, calendar, calendar)
    with pytest.raises(ValueError, match='Signal outside calendar'):
        compute_asset(frame, calendar, calendar.append(pd.DatetimeIndex(['2030-01-01'])))


def test_yyyymmdd_integer_inputs_have_the_same_dates():
    calendar, frame = sample()
    expected = compute_asset(frame, calendar, calendar)
    frame['trade_date'] = frame.trade_date.dt.strftime('%Y%m%d').astype(int)
    pd.testing.assert_frame_equal(expected, compute_asset(frame, calendar, calendar))
