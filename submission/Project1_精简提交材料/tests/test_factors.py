import numpy as np
import pandas as pd
import pytest
from quant_research.factors import compute_factors, rank_scores, select_targets, select_buffered_targets, weekly_schedule, FACTORS


def bars(n=45):
    calendar = pd.bdate_range('2020-01-01', periods=n)
    frame = pd.DataFrame({'trade_date': calendar.strftime('%Y%m%d'), 'ts_code': 'A',
                          'close': 10 * 1.01 ** np.arange(n), 'adj_factor': 1., 'amount': 30000.})
    return calendar, frame


def test_known_compound_returns_and_units():
    cal, frame = bars()
    result = compute_factors(frame, cal).iloc[-1]
    assert result.momentum20 == pytest.approx(1.01 ** 20 - 1)
    assert result.reversal5 == pytest.approx(-(1.01 ** 5 - 1))
    assert result.lowvol20 == pytest.approx(0, abs=1e-12)
    assert result.adv20_cny == 30_000_000


def test_future_mutation_cannot_change_past():
    cal, frame = bars()
    original = compute_factors(frame, cal)
    changed = frame.copy()
    changed.loc[30:, 'close'] *= 7
    changed.loc[30:, 'adj_factor'] *= 3
    pd.testing.assert_frame_equal(original.iloc[:30], compute_factors(changed, cal).iloc[:30])


def test_missing_session_invalidates_windows():
    cal, frame = bars()
    result = compute_factors(frame.drop(index=25), cal)
    assert result.loc[30, FACTORS].isna().all()
    assert pd.isna(result.loc[44, 'lowvol20'])


def test_split_does_not_create_artificial_loss():
    cal, frame = bars()
    frame.loc[25:, 'close'] /= 2
    frame.loc[25:, 'adj_factor'] *= 2
    result = compute_factors(frame, cal)
    assert result.iloc[30].momentum20 == pytest.approx(1.01 ** 20 - 1)


def test_reject_duplicates():
    cal, frame = bars()
    with pytest.raises(ValueError, match='Duplicate'):
        compute_factors(pd.concat([frame, frame.iloc[:1]]), cal)


def test_missing_factors_not_zero_and_ties_stable():
    frame = pd.DataFrame({'trade_date': ['2020-01-01'] * 3, 'ts_code': ['B', 'A', 'C'],
                          'industry': ['bank'] * 3, **{f: [1., 1., np.nan] for f in FACTORS}})
    ranked = rank_scores(frame)
    targets = select_targets(ranked, count=2, industry_cap=1)
    assert targets.ts_code.tolist() == ['A', 'B']
    assert targets.target_weight.sum() == pytest.approx(.98)


def test_industry_cap_leaves_cash():
    frame = pd.DataFrame({'trade_date': ['2020-01-01'] * 20, 'ts_code': [str(i) for i in range(20)],
                          'industry': ['bank'] * 20, 'score': np.arange(20)})
    targets = select_targets(frame)
    assert len(targets) == 5
    assert targets.target_weight.sum() == pytest.approx(.245)


def test_rank_buffer_retains_prior_names_and_respects_industry_cap():
    frame = pd.DataFrame({'trade_date': ['2020-01-01'] * 8,
                          'ts_code': list('ABCDEFGH'),
                          'industry': ['x', 'x', 'y', 'y', 'z', 'z', 'w', 'w'],
                          'score': [8, 7, 6, 5, 4, 3, 2, 1]})
    result = select_buffered_targets(frame, previous_codes=['D', 'F'], count=4,
                                     exit_rank=6, cash_buffer=0, industry_cap=.5)
    assert result.ts_code.tolist() == ['D', 'F', 'A', 'B']
    assert result.groupby('industry').target_weight.sum().max() <= .5


def test_rank_buffer_drops_prior_name_outside_exit_rank():
    frame = pd.DataFrame({'trade_date': ['2020-01-01'] * 5,
                          'ts_code': list('ABCDE'), 'industry': list('abcde'),
                          'score': [5, 4, 3, 2, 1]})
    result = select_buffered_targets(frame, previous_codes=['E'], count=2,
                                     exit_rank=4, cash_buffer=0, industry_cap=1)
    assert result.ts_code.tolist() == ['A', 'B']


def test_holiday_delays_execution_not_signal():
    cal = pd.DatetimeIndex(['2023-12-28', '2023-12-29', '2024-01-02', '2024-01-03'])
    result = weekly_schedule(cal)
    assert len(result) == 1
    assert result.iloc[0].signal_date == pd.Timestamp('2023-12-29')
    assert result.iloc[0].execution_date == pd.Timestamp('2024-01-02')
