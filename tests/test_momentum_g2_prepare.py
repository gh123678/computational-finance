import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from momentum_g2_events import EventBook
from momentum_g2_prepare import PreparationError, historical_pool, prepare


def inputs(ncodes=1, periods=300):
    cal = pd.bdate_range('2016-01-04', periods=periods)
    frames = []
    codes = [f'{i:06d}.SZ' for i in range(1, ncodes + 1)]
    for code in codes:
        close = 10 + np.arange(periods) / 100
        frame = pd.DataFrame(dict(ts_code=code, trade_date=cal, open=close,
            high=close, low=close, close=close, vol=100000., amount=20000.))
        frame['close_text'] = [f'{v:.2f}' for v in close]
        frame['pre_close_text'] = ['999'] + [f'{v:.2f}' for v in close[:-1]]
        frame['pre_close'] = frame.pre_close_text.astype(float)
        frames.append(frame)
    bars = pd.concat(frames, ignore_index=True)
    schedule = pd.DataFrame(dict(signal_date=[cal[273]], execution_date=[cal[274]]))
    universe = pd.DataFrame(dict(ts_code=codes, list_date='20100101', delist_date=None))
    names = pd.DataFrame(columns=['ts_code', 'name', 'start_date', 'end_date', 'ann_date'])
    industries = pd.DataFrame(dict(ts_code=codes, l1_code='801010.SI', in_date='20100101', out_date=None))
    return bars, cal, schedule, universe, names, industries


def run(data, book=None, minimum_pool=1):
    return prepare(*data, book or EventBook(data[1]), minimum_pool=minimum_pool)


def test_exact_274_points_252_intervals_skip_21_and_first_reference_not_consumed():
    data = inputs()
    result = run(data)
    assert result['feature_rows'].iloc[0].momentum == pytest.approx(12.52 / 10 - 1)
    assert len(result['daily_bridge_audit']) == 273
    assert result['daily_bridge_audit'].bridge_left.min() == data[1][0]
    assert result['feature_rows'].iloc[0].adv20_cny == 20_000_000
    changed = data[0].copy()
    changed.loc[changed.index[-26:], ['open', 'high', 'low', 'close']] *= 2
    # Late 21 intervals must still validate, so change lexical references too.
    changed['close_text'] = changed.close.map(lambda x: f'{x:.2f}')
    changed['pre_close_text'] = changed.close_text.shift(1).fillna('999')
    # i-21=252 is unchanged; indices 274+ are outside the only formation.
    changed.loc[253:, ['open','high','low','close']] = data[0].loc[253:, ['open','high','low','close']].to_numpy() * 2
    changed['close_text'] = changed.close.map(lambda x: f'{x:.2f}')
    changed['pre_close_text'] = changed.close_text.shift(1).fillna('999')
    assert run((changed, *data[1:]))['feature_rows'].iloc[0].momentum == pytest.approx(result['feature_rows'].iloc[0].momentum)


def test_all_six_fields_required_and_no_sparse_adv():
    data = inputs()
    bars = data[0].copy(); bars.loc[270, 'amount'] = np.nan
    with pytest.raises(PreparationError) as error:
        run((bars, *data[1:]))
    assert error.value.partial['exclusions'].iloc[0].reason == 'missing_or_invalid_six_field_274_point_window'
    bars = data[0].drop(index=100)
    with pytest.raises(PreparationError):
        run((bars, *data[1:]))


def test_gross_cash_and_stock_theoretical_g_are_not_price_return():
    data = inputs()
    bars, cal = data[:2]
    bars = bars.copy()
    prices = np.where(np.arange(len(cal)) < 100, 10., 7.5)
    for field in ('open', 'high', 'low', 'close'):
        bars[field] = prices
    bars['close_text'] = [str(x) for x in prices]
    bars['pre_close_text'] = ['999'] + [str(x) for x in prices[:-1]]
    bars.loc[100, 'pre_close_text'] = '7.50'
    book = EventBook(cal, [dict(code='000001.SZ', event_id='dist',
        source_available_date=cal[90], record=cal[99], ex=cal[100],
        cash_pay=cal[105], stock_pay=cal[110], cash_per_share='1',
        stock_per_share='.2', taxable_bonus_per_share='.1', cash_div='.8')])
    result = run((bars, *data[1:]), book)
    assert result['feature_rows'].iloc[0].momentum == pytest.approx(0.)
    row = result['daily_bridge_audit'].loc[lambda f: f.bridge_right.eq(cal[100])].iloc[0]
    assert row.D == '1' and row.s == '0.2' and row.economic_factor == 1.


def test_future_announcement_not_used_for_past_filter_but_consumed_late_terms_stop():
    data = inputs(periods=330)
    cal = data[1]
    future = dict(code='000001.SZ', event_id='future-right', kind='unsupported',
        source_available_date=cal[280], ex=cal[290], record=cal[289])
    a = run(data)
    b = run(data, EventBook(cal, [future]))
    pd.testing.assert_frame_equal(a['feature_rows'], b['feature_rows'])
    late = dict(code='000001.SZ', event_id='late-cash', kind='ordinary',
        source_available_date=cal[101], ex=cal[100], record=cal[99], cash_pay=cal[100],
        cash_per_share='.001', stock_per_share='0', taxable_bonus_per_share='0')
    with pytest.raises(PreparationError) as error:
        run(data, EventBook(cal, [late]))
    assert error.value.reason == 'consumed_bridge_requires_later_or_unavailable_terms'


def test_visible_mismatch_is_exclusion_even_if_later_event_explains_it():
    data = inputs(periods=330); cal = data[1]
    bars = data[0].copy(); bars.loc[100, 'pre_close_text'] = '10.98'
    late = dict(code='000001.SZ', event_id='late-cash', source_available_date=cal[101],
        ex=cal[100], record=cal[99], cash_pay=cal[100], stock_pay=None,
        cash_per_share='.01', stock_per_share='0', taxable_bonus_per_share='0')
    with pytest.raises(PreparationError) as error:
        run((bars, *data[1:]), EventBook(cal, [late]))
    assert error.value.reason == 'common_pool_below_test_minimum'
    assert error.value.partial['exclusions'].iloc[0].reason == 'pre_close_display_mismatch'


def test_later_conflicting_small_amount_cannot_hide_in_equal_display_cents():
    data = inputs(periods=330); cal = data[1]
    base = dict(code='000001.SZ', event_id='same-cash', kind='ordinary',
        source_available_date=cal[90], ex=cal[100], record=cal[99], cash_pay=cal[100],
        cash_per_share='.001', stock_per_share='0', taxable_bonus_per_share='0', version=1)
    later = dict(base, source_available_date=cal[101], cash_per_share='.002', version=2)
    with pytest.raises(PreparationError) as error:
        run(data, EventBook(cal, [base, later]))
    assert error.value.reason == 'consumed_bridge_requires_later_or_unavailable_terms'


def test_known_future_unsupported_is_normal_formation_exclusion():
    data = inputs(periods=330); cal = data[1]
    event = dict(code='000001.SZ', event_id='active-right', kind='unsupported',
        source_available_date=cal[260], ex=cal[290], record=cal[289])
    with pytest.raises(PreparationError) as error:
        run(data, EventBook(cal, [event]))
    assert error.value.partial['exclusions'].iloc[0].reason == 'known_unsupported_or_conflicting_action'


def test_vendor_factor_is_never_an_input_and_true_reference_mismatch_excludes():
    data = inputs(); bars = data[0].copy()
    bars['adj_factor'] = np.where(np.arange(len(bars)) < 100, -999., np.inf)
    pd.testing.assert_frame_equal(run(data)['feature_rows'], run((bars, *data[1:]))['feature_rows'])
    bars.loc[100, 'pre_close_text'] = '1'
    with pytest.raises(PreparationError) as error:
        run((bars, *data[1:]))
    assert error.value.partial['exclusions'].iloc[0].reason == 'pre_close_display_mismatch'


def test_all_periods_have_200_gate_and_shared_windows_not_duplicated():
    data = inputs(ncodes=200, periods=310)
    schedule = pd.DataFrame(dict(signal_date=[data[1][273], data[1][278]], execution_date=[data[1][274], data[1][279]]))
    result = run((data[0], data[1], schedule, *data[3:]), minimum_pool=200)
    assert result['coverage'].common_pool.tolist() == [200, 200]
    assert len(result['daily_bridge_audit']) == 200 * 278
    with pytest.raises(PreparationError) as error:
        run(inputs(ncodes=199), minimum_pool=200)
    assert error.value.reason == 'common_pool_below_200'


def test_historical_missing_ordinary_name_ok_st_publication_strict_and_industry_unique():
    data = inputs(ncodes=2); cal = data[1]; date = cal[273]
    names = pd.DataFrame([dict(ts_code='000001.SZ', name='*ST甲', start_date=cal[200], end_date=None, ann_date=date)])
    pool = historical_pool(date, data[3], names, data[5], cal)
    assert len(pool) == 2
    names['ann_date'] = cal[272]
    assert historical_pool(date, data[3], names, data[5], cal).ts_code.tolist() == ['000002.SZ']
    industries = pd.concat([data[5], pd.DataFrame([dict(ts_code='000002.SZ', l1_code='other', in_date='20100101', out_date=None)])])
    assert historical_pool(date, data[3], names, industries, cal).empty


def test_duplicate_identity_hard_stops_and_one_lot_guard():
    data = inputs()
    duplicated = pd.concat([data[0], data[0].iloc[[100]]])
    with pytest.raises(PreparationError, match='duplicate_raw_quote_identity'):
        run((duplicated, *data[1:]))
    bars = data[0].copy()
    for f in ('open', 'high', 'low', 'close'):
        bars[f] = 490.01
    bars['close_text'] = bars['pre_close_text'] = '490.01'
    with pytest.raises(PreparationError) as error:
        run((bars, *data[1:]))
    assert error.value.partial['exclusions'].iloc[0].reason == 'formation_one_lot_exceeds_49000'


def test_progress_budget_guard_keeps_completed_pool_and_bridges():
    data = inputs()
    def budget_stop(row):
        raise RuntimeError('synthetic budget exhausted')
    with pytest.raises(PreparationError) as error:
        prepare(*data, EventBook(data[1]), progress=budget_stop, minimum_pool=1)
    assert error.value.reason == 'preparation_progress_guard_stop'
    assert len(error.value.partial['coverage']) == 1
    assert len(error.value.partial['feature_rows']) == 1
    assert len(error.value.partial['daily_bridge_audit']) == 273
