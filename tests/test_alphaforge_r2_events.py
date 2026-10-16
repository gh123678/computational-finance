from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alphaforge_r2_events import COLUMNS, build_events


def dividend(**updates):
    row = dict(ts_code='000001.SZ', div_proc='实施', ex_date='20180823',
               imp_ann_date='20180820', ann_date='20180301', end_date='20171231',
               cash_div='0.1', cash_div_tax='0.1', stk_div='0', stk_bo_rate='0', stk_co_rate='0',
               record_date='20180822', pay_date='20180823', div_listdate=np.nan)
    row.update(updates)
    return row


def test_implementation_day_is_used_instead_of_earlier_proposal():
    events = build_events(pd.DataFrame([dividend()]), rights=[])
    assert list(events) == COLUMNS
    row = events.iloc[0]
    assert row.known_date == pd.Timestamp('2018-08-20')
    assert row.event_date == pd.Timestamp('2018-08-23') and row.timing_verified
    assert row.known_date_field == 'imp_ann_date'
    assert str(events.known_date.dtype) == str(events.event_date.dtype) == 'datetime64[ns]'


@pytest.mark.parametrize('value,reason', [(None, 'missing_imp_ann_date'),
                                         (np.nan, 'missing_imp_ann_date'),
                                         ('', 'invalid_imp_ann_date'),
                                         ('20180230', 'invalid_imp_ann_date'),
                                         ('2018082', 'invalid_imp_ann_date'),
                                         ('20180824', 'imp_ann_date_after_event_date')])
def test_unknown_invalid_and_late_implementation_do_not_fall_back_to_ann(value, reason):
    row = build_events(pd.DataFrame([dividend(imp_ann_date=value)]), rights=[]).iloc[0]
    assert not row.timing_verified and row.timing_reason == reason
    if reason != 'imp_ann_date_after_event_date':
        assert pd.isna(row.known_date)
    else:
        assert row.known_date == pd.Timestamp('2018-08-24')


def test_same_day_known_date_is_valid_only_at_day_precision():
    row = build_events(pd.DataFrame([dividend(imp_ann_date='20180823')]), rights=[]).iloc[0]
    assert row.timing_verified


def test_future_proposal_day_does_not_change_frozen_timing_or_identity():
    first = build_events(pd.DataFrame([dividend(ann_date='20180301')]), rights=[])
    second = build_events(pd.DataFrame([dividend(ann_date='20260101')]), rights=[])
    pd.testing.assert_frame_equal(first, second)


def test_cash_stock_mixed_and_zero_actions_have_distinct_meaning():
    records = [dividend(), dividend(cash_div=0, cash_div_tax=0, stk_div=.2),
               dividend(stk_div=.1), dividend(cash_div=0, cash_div_tax=0),
               dividend(div_proc='预案')]
    events = build_events(pd.DataFrame(records), rights=[])
    assert list(events.kind) == ['cash', 'stock', 'cash_and_stock']


def test_identical_and_different_versions_are_retained_without_latest_selection():
    records = [dividend(), dividend(), dividend(imp_ann_date='20180824')]
    events = build_events(pd.DataFrame(records, index=[1, 1, 1]), rights=[])
    assert len(events) == 3 and events.event_id.nunique() == 3
    assert events.timing_verified.tolist() == [True, True, False]


@pytest.mark.parametrize('updates', [dict(ts_code='A'), dict(ts_code='000001'),
                                      dict(ex_date='20180230'), dict(ex_date=None),
                                      dict(cash_div_tax='garbage'), dict(cash_div_tax=-.1),
                                      dict(cash_div_tax=float('inf'))])
def test_invalid_action_identity_or_amount_is_an_error(updates):
    with pytest.raises(ValueError):
        build_events(pd.DataFrame([dividend(**updates)]), rights=[])


def test_source_url_does_not_certify_rights_publication_day():
    rights = SimpleNamespace(code='000001.SZ', record=pd.Timestamp('2018-08-20'),
                             ex=pd.Timestamp('2018-08-23'),
                             source='https://example.test/2018-08-01/disclosure.pdf')
    events = build_events(pd.DataFrame(), rights=[rights])
    assert len(events) == 1
    row = events.iloc[0]
    assert row.kind == 'rights' and not row.timing_verified
    assert pd.isna(row.known_date) and row.known_date_field == 'none_verified'


def test_existing_non_shareholder_distribution_correction_is_applied():
    row = dividend(ts_code='000912.SZ', ex_date='20180730', record_date='20180727',
                   imp_ann_date='20180724', cash_div=0, cash_div_tax=0,
                   stk_div=1.6803419, stk_co_rate=1.6803419, stk_bo_rate=0)
    assert build_events(pd.DataFrame([row]), rights=[]).empty


def test_empty_output_keeps_date_and_boolean_types():
    events = build_events(pd.DataFrame(), rights=[])
    assert events.empty and list(events) == COLUMNS
    assert str(events.event_date.dtype) == str(events.known_date.dtype) == 'datetime64[ns]'
    assert events.timing_verified.dtype == bool


def test_input_frame_is_not_modified():
    frame = pd.DataFrame([dividend()])
    expected = frame.copy(deep=True)
    build_events(frame, rights=[])
    pd.testing.assert_frame_equal(frame, expected)
