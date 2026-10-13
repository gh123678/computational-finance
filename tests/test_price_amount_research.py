import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from price_amount_features import FEATURES, compute_asset
from price_amount_model import training_samples, fit_scales, transform


def market(n=450):
    dates = pd.bdate_range('20160101', periods=n)
    price = 10 * np.exp(np.arange(n) * .001 + np.sin(np.arange(n)) * .02)
    bars = pd.DataFrame(dict(trade_date=dates, open=price, high=price*1.02,
                            low=price*.98, close=price, adj_factor=1., vol=1e5,
                            amount=1000 + np.arange(n) ** 1.2))
    return dates, bars


def training():
    rng = np.random.default_rng(123)
    dates = pd.date_range('20160101', periods=53, freq='7D')
    frame = pd.DataFrame(rng.normal(size=(53*200, 8)), columns=FEATURES)
    frame['trade_date'] = np.repeat(dates, 200)
    frame['ts_code'] = np.tile([f'C{i}' for i in range(200)], 53)
    frame['D_end'] = frame.trade_date + pd.Timedelta(days=2)
    frame['reference_end'] = frame.trade_date + pd.Timedelta(days=4)
    frame['feature_valid'] = True
    frame['D_valid'] = True
    frame['D_label'] = frame.price_20 * .002
    return frame, dates[-1] + pd.Timedelta(days=7)


def test_feature_direction_amount_units_and_future_invariance():
    dates, bars = market()
    before, _ = compute_asset(bars, dates, dates)
    changed = bars.copy()
    changed.loc[changed.trade_date > dates[300], ['open','high','low','close','amount']] *= 10
    after, _ = compute_asset(changed, dates, dates)
    pd.testing.assert_frame_equal(before.loc[:300, FEATURES], after.loc[:300, FEATURES])
    assert not before.loc[198, 'feature_valid'] and before.loc[199, 'feature_valid']
    assert before.loc[220, 'price_20'] == pytest.approx(bars.close.iloc[201:221].mean()/bars.close.iloc[220]-1)
    assert before.loc[220, 'current_amount_cny'] == pytest.approx(bars.amount.iloc[220]*1000)
    assert before.loc[220, 'amount_20'] == pytest.approx(bars.amount.iloc[201:221].mean()/bars.amount.iloc[220]-1)


@pytest.mark.parametrize('fault', ['missing', 'zero', 'infinite'])
def test_invalid_quote_blocks_full200_window(fault):
    dates, bars = market()
    if fault == 'missing':
        bars = bars.drop(index=220)
    else:
        bars.loc[220, 'amount'] = 0 if fault == 'zero' else np.inf
    result, _ = compute_asset(bars, dates, dates)
    assert not result.loc[220:419, 'feature_valid'].any()
    assert result.loc[420, 'feature_valid']


def test_unknown_event_quarantine_includes199_following_sessions():
    dates, bars = market()
    result, _ = compute_asset(bars, dates, dates, [dates[220]])
    assert result.loc[219, 'feature_valid']
    assert not result.loc[220:419, 'feature_valid'].any()
    assert result.loc[420, 'feature_valid']


def test_strict_dual_maturity_and_latest52_equal_date_weights():
    frame, fit = training()
    result, audit = training_samples(frame, fit)
    assert result.trade_date.nunique() == 52
    assert frame.trade_date.min() not in set(result.trade_date)
    assert audit['total_weight'] == pytest.approx(52)
    assert np.allclose(result.groupby('trade_date').sample_weight.sum(), 1)
    last = frame.trade_date.max()
    frame.loc[frame.trade_date.eq(last), 'reference_end'] = fit
    result, _ = training_samples(frame, fit)
    assert last not in set(result.trade_date)
    frame.loc[frame.trade_date.eq(last-pd.Timedelta(days=7)), 'D_end'] = fit
    with pytest.raises(ValueError, match='Need52'):
        training_samples(frame, fit)


def test_under200_and_duplicate_keys_stop_without_relaxation():
    frame, fit = training()
    frame = frame.loc[frame.trade_date.ne(frame.trade_date.min())].copy()
    with pytest.raises(ValueError, match='Need52'):
        training_samples(frame.iloc[1:], fit)
    with pytest.raises(ValueError, match='Duplicate'):
        training_samples(pd.concat([frame, frame.iloc[:1]]), fit)


def test_future_rows_do_not_change_train_scales_and_prediction_matrix():
    frame, fit = training()
    future = frame.iloc[:200].copy()
    future['trade_date'] = fit-pd.Timedelta(days=1)
    future['D_end'] = fit
    future['reference_end'] = fit+pd.Timedelta(days=20)
    full = pd.concat([frame, future], ignore_index=True)
    before, _ = training_samples(full, fit)
    full.loc[full.trade_date.eq(fit-pd.Timedelta(days=1)), FEATURES+['D_label']] *= 10000
    after, _ = training_samples(full, fit)
    pd.testing.assert_frame_equal(before, after)
    scales = fit_scales(before)
    assert scales == fit_scales(after)
    z = transform(before, scales)
    weights = before.sample_weight
    np.testing.assert_allclose(np.average(z, axis=0, weights=weights), 0, atol=1e-12)
    np.testing.assert_allclose(np.average(z*z, axis=0, weights=weights), 1, atol=1e-12)
    before.loc[:, 'price_20'] = 1.
    with pytest.raises(ValueError, match='variance'):
        fit_scales(before)
