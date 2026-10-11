import pandas as pd
import pytest

from audit_publication_time import calendar_map, next_session, visible_candidate_events, current_index_items


def calendar(start, flags):
    return calendar_map(pd.DataFrame(dict(cal_date=pd.date_range(start, periods=len(flags)).strftime('%Y%m%d'), is_open=flags)))


def test_friday_and_weekend_release_wait_for_monday():
    days = calendar('2020-01-03', [1, 0, 0, 1, 1])
    assert next_session('20200103', days)[0] == '20200106'
    assert next_session('20200104', days)[0] == '20200106'
    assert next_session('20200106', days)[0] == '20200107'


def test_long_holiday_does_not_use_next_calendar_day():
    days = calendar('2020-09-30', [1, *([0] * 8), 1])
    assert next_session('20200930', days)[0] == '20201009'


@pytest.mark.parametrize('day', ['20200230', '2020-01-03', None, ''])
def test_invalid_publication_day_is_unknown(day):
    assert next_session(day, calendar('2020-01-03', [1, 1])) == (None, 'invalid_publication_day')


def test_calendar_gaps_and_conflicts_are_not_skipped():
    with pytest.raises(ValueError, match='gap'):
        calendar_map(pd.DataFrame([dict(cal_date='20200103', is_open=1), dict(cal_date='20200106', is_open=1)]))
    with pytest.raises(ValueError, match='conflicting'):
        calendar_map(pd.DataFrame([dict(cal_date='20200103', is_open=1), dict(cal_date='20200103', is_open=0)]))


def test_out_of_calendar_not_assigned_to_first_or_last_session():
    days = calendar('2020-01-03', [1, 0, 0, 1])
    assert next_session('20191231', days)[0] is None
    assert next_session('20200106', days) == (None, 'next_session_not_covered')


def test_later_revision_cannot_rewrite_earlier_diagnostic_exposure():
    original = dict(candidate_available_day='20200106', value=10, usable_in_verified_history=False)
    revised = dict(candidate_available_day='20200508', value=-10, vendor_ann_date='20200103', usable_in_verified_history=False)
    assert visible_candidate_events([original, revised], '20200301') == [original]
    assert visible_candidate_events([original, revised], '20200507') == [original]
    assert visible_candidate_events([original, revised], '20200508') == [original, revised]
    assert not any(e['usable_in_verified_history'] for e in [original, revised])


def test_same_day_versions_preserved_without_automatic_value_selection():
    rows = [dict(candidate_available_day='20200106', value=1), dict(candidate_available_day='20200106', value=2), dict(candidate_available_day=None, value=3)]
    assert visible_candidate_events(rows, '20200103') == []
    assert visible_candidate_events(rows, '20200106') == rows[:2]


@pytest.mark.parametrize('response', [[dict(orgId='X')], {}, None,
    dict(announcements=None), dict(announcements=[None])])
def test_non_announcement_cache_cannot_be_used_as_publication_evidence(response):
    with pytest.raises(ValueError):
        current_index_items(response)
