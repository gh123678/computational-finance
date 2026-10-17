"""Small runner integration checks; no preparation, outputs or real accounts."""
import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.alphaforge_case_r2_features import compute_asset as frozen_r2_features


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('run_alphaforge_r3')


@pytest.mark.parametrize('scenario', ['normal', 'constant', 'microvariance'])
def test_primary_formula_is_bit_identical_to_frozen_r2_vector_path(runner, scenario):
    calendar = pd.bdate_range('2019-01-02', periods=43)
    rng = np.random.default_rng(718)
    close = 10 + rng.lognormal(0, .7, len(calendar))
    volume = 1e6 + rng.lognormal(2, 1, len(calendar)) * 1e5
    if scenario == 'constant':
        close[:] = 12.
    elif scenario == 'microvariance':
        close = 12. + np.arange(len(calendar)) * 1e-6
    group = pd.DataFrame(dict(trade_date=calendar, ts_code='000001.SZ',
        close=close, pre_close=np.r_[close[0], close[:-1]], vol=volume,
        amount=rng.uniform(1e3, 1e7, len(calendar)), adj_factor=11.267))
    group['close_text'] = group.close.map(str)
    group['pre_close_text'] = group.pre_close.map(str)
    dates = list(calendar[[9, 13, 20, 29, 42]])
    expected, _ = frozen_r2_features(group, calendar, dates)
    # A is unavailable to the new main formula; real amount occupies the third
    # array column while the frozen reduction path keeps its original strides.
    current = group.drop(columns='adj_factor')
    current['D_label'] = np.nan
    current['R_week'] = np.inf
    actual = runner.primary_formula(current, calendar, dates)
    pd.testing.assert_series_equal(actual.trade_date, expected.trade_date)
    for column in ('rho', 'factor', 'signal', 'nlvar', 'nrvar'):
        assert np.array_equal(actual['case_' + column].to_numpy(), expected[column].to_numpy())
    assert np.array_equal(actual.case_guard.to_numpy(dtype=bool), expected.guard.to_numpy(dtype=bool))
    assert actual.case_signal.eq(-actual.case_factor).all()


def test_raw_loader_retains_exact_csv_text_and_frozen_r2_numeric_parsing(runner, monkeypatch, tmp_path):
    path = tmp_path / 'daily.csv'
    path.write_text(
        'ts_code,trade_date,open,high,low,close,pre_close,vol,amount\n'
        '000001.SZ,20190102,10.01,11,9,10.000000000000001,9.999999999999999,100.7,1234.5678901234567\n'
        '000001.SZ,20190103,10.02,11,9,1.0000000000000001E+1,10.000000000000001,101.3,1234567.000000001\n'
        '000001.SZ,20190104,10.03,11,9,10.000,1.0000000000000001E+1,102.1,1.23456789012345E+6\n'
        '000002.SZ,20190102,99,99,99,99,99,999,999\n', encoding='utf-8')
    calendar = pd.DatetimeIndex(['2019-01-02', '2019-01-03', '2019-01-04'])
    codes = {'000001.SZ'}
    monkeypatch.setattr(runner, 'DATA', tmp_path)
    monkeypatch.setattr(runner.r2, 'DATA', tmp_path)
    adjustment = pd.DataFrame(dict(ts_code='000001.SZ', trade_date=calendar, adj_factor=11.267))
    calls = []

    def frozen_adjustments(name, requested):
        calls.append((name, requested))
        return adjustment.copy()

    monkeypatch.setattr(runner.r2, 'read_subset', frozen_adjustments)
    original, corrections = runner.r2.read_quotes(codes, calendar)
    current = runner.load_raw(codes)
    assert not corrections and calls == [('adj_factor', codes)]
    columns = [column for column in original if column != 'adj_factor']
    pd.testing.assert_frame_equal(current[columns], original[columns], check_exact=True)
    assert current.close_text.tolist() == [
        '10.000000000000001', '1.0000000000000001E+1', '10.000']
    assert current.pre_close_text.tolist() == [
        '9.999999999999999', '10.000000000000001', '1.0000000000000001E+1']
    assert set(current.ts_code) == codes and 'adj_factor' not in current


def test_primary_formula_rejects_missing_quote_in_a_fixed_window(runner):
    calendar = pd.bdate_range('2019-01-02', periods=10)
    group = pd.DataFrame(dict(trade_date=calendar, close=10., vol=100., amount=500.))
    with pytest.raises(RuntimeError, match='Fixed primary window missing'):
        runner.primary_formula(group.drop(index=4), calendar, [calendar[-1]])
