import pandas as pd
import pytest
from quant_research.corporate_corrections import correct_actions, correct_adjustments, correct_limit_code_aliases


def record():
    return dict(ts_code='002260.SZ', ex_date='20200925', div_proc='实施',
                record_date='20200924', imp_ann_date='20200919', stk_div='1.1',
                stk_co_rate='1.1', cash_div=None, cash_div_tax=None, stk_bo_rate=None)


def test_shenhua_special_dividend_is_not_counted_twice():
    from quant_research.accounting import normalize_actions
    row = dict(ts_code='601088.SH', ex_date='20170710', record_date='20170707',
               pay_date='20170710', div_proc='实施', stk_div='0', stk_bo_rate=None)
    raw = pd.DataFrame([dict(row, cash_div_tax='2.51'), dict(row, cash_div_tax='2.97')])
    corrected, audit = correct_actions(raw)
    assert normalize_actions(corrected, {'601088.SH'})[0].cash_per_share == 2.97
    assert len(raw) == 2 and len(audit) == 1
    with pytest.raises(ValueError, match='Shenhua'):
        correct_actions(raw.iloc[:1])


def test_non_shareholder_distribution_is_logged_and_other_events_preserved():
    original = pd.DataFrame([record(), dict(record(), ex_date='20200926')])
    result, audit = correct_actions(original)
    assert result.ex_date.tolist() == ['20200926']
    assert len(original) == 2
    assert len(audit) == 1 and audit[0]['original']['stk_div'] == '1.1'
    assert audit[0]['source'].startswith('https://static.cninfo.com.cn/')


def test_correction_refuses_changed_cash_distribution():
    with pytest.raises(ValueError, match='no longer matches'):
        correct_actions(pd.DataFrame([dict(record(), cash_div_tax='0.2')]))


def test_lutianhua_restructuring_shares_are_not_credited_to_shareholders():
    row = dict(ts_code='000912.SZ', ex_date='20180730', div_proc='实施',
               record_date='20180727', imp_ann_date='20180724', stk_div='1.6803419',
               stk_co_rate='1.6803419', cash_div=None, cash_div_tax=None, stk_bo_rate=None)
    result, audit = correct_actions(pd.DataFrame([row]))
    assert result.empty
    assert audit[0]['ts_code'] == '000912.SZ'
    assert audit[0]['source'].endswith('1205254635.PDF')


def test_chuanhua_restructuring_shares_are_not_credited_to_shareholders():
    row = dict(ts_code='000155.SZ', ex_date='20161214', div_proc='实施',
               record_date='20161213', imp_ann_date='20161210', stk_div='1.7021276',
               stk_co_rate='1.7021276', cash_div=None, cash_div_tax=None, stk_bo_rate=None)
    result, audit = correct_actions(pd.DataFrame([row]))
    assert result.empty
    assert audit[0]['ts_code'] == '000155.SZ'
    assert audit[0]['source'].endswith('1202736702.PDF')


def test_longping_transient_adjustment_revision_is_repaired():
    dates = pd.to_datetime(['2018-08-15', '2018-08-23', '2018-08-24', '2018-08-27', '2018-08-28'])
    frame = pd.DataFrame({'ts_code': ['000998.SZ'] * 5, 'trade_date': dates,
                          'adj_factor': [11.1070, 10.8142, 10.8142, 10.8142, 11.1070]})
    corrected, audit = correct_adjustments(frame)
    assert corrected.adj_factor.tolist() == [11.1070] * 5
    assert audit[0]['action'] == 'replace_transient_vendor_adjustment_factor'


def test_longping_correction_ignores_nonoverlapping_dataset():
    frame = pd.DataFrame({'ts_code': ['000998.SZ'],
                          'trade_date': pd.to_datetime(['2017-08-23']),
                          'adj_factor': [10.]})
    corrected, audit = correct_adjustments(frame)
    pd.testing.assert_frame_equal(corrected, frame)
    assert audit == []


def test_historical_price_limits_follow_verified_code_change():
    frame = pd.DataFrame({'ts_code': ['000043.SZ', '001914.SZ'],
                          'trade_date': pd.to_datetime(['2018-01-02', '2019-12-16']),
                          'up_limit': [10., 20.], 'down_limit': [8., 16.]})
    corrected, audit = correct_limit_code_aliases(frame)
    alias = corrected[(corrected.ts_code == '001914.SZ') &
                      (corrected.trade_date == pd.Timestamp('2018-01-02'))]
    assert alias[['up_limit', 'down_limit']].iloc[0].tolist() == [10., 8.]
    assert audit[0]['corrected_rows'] == 1
