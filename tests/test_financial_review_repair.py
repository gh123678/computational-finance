import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import repair_financial_review as repair
import verify_off_checklist_key as verify


def test_latest_slice_keeps_one_stock_and_ignores_late_older_period():
    frame = pd.DataFrame([
        ['A', '20200601', '20181231', '20190301', 10],
        ['A', '20200601', '20191231', '20200401', 20],
        ['A', '20200601', '20181231', '20200501', 11],
        ['B', '20200601', '20191231', '20200501', 30],
    ], columns=['ts_code', 'trade_date', 'end_date', 'ann_date', 'consumption_value'])
    result = repair.latest_slice_observations(frame)
    assert result.consumption_value.tolist() == [20, 30]
    assert len(result) == 2
    with pytest.raises(ValueError, match='undisclosed'):
        repair.latest_slice_observations(frame.assign(ann_date='20200601'))
    with pytest.raises(ValueError, match='conflicting'):
        repair.latest_slice_observations(pd.concat([frame, frame.iloc[[0]].assign(consumption_value=99)]))


def test_correction_explanation_is_not_silently_excluded():
    query = dict(items=[dict(announcementTitle='2020年年度报告更正说明公告')],
                 complete=True, failure=None, pages=1, total=1)
    result = verify.assess_version_query(query)
    assert result['status'] == 'later_correction_found'
    assert len(result['corrections']) == 1
    assert result['full_version_chain_verified'] is False
    query['complete'] = False
    query['failure'] = 'request_failed'
    assert verify.assess_version_query(query)['status'] == 'query_incomplete'


def test_pdf_numeric_match_does_not_find_smaller_value_inside_larger_number(tmp_path):
    import fitz
    path = tmp_path / 'numbers.pdf'
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 40), '15,977,616.02\n-160,235.75\n3,185,985.75')
    doc.save(path)
    doc.close()
    hits, status = verify.search_pdf(path, {'positive': {'16.02', '160235.75'},
                                           'negative': {'-160235.75'},
                                           'exact': {'3185985.75'}})
    assert status == 'ok'
    assert not hits['positive']
    assert hits['negative'] and hits['exact']


@pytest.mark.parametrize('title', ['补充更正公告', '前期会计差错更正公告', '更正公告'])
def test_generic_financial_correction_requires_content_review(title):
    query = dict(items=[dict(announcementTitle=title)], complete=True,
                 failure=None, pages=1, total=1)
    result = verify.assess_version_query(query)
    assert result['status'] == 'ambiguous_correction_notice_requires_review'
    assert len(result['ambiguous_corrections']) == 1
    assert result['full_version_chain_verified'] is False


@pytest.mark.parametrize('response', [None, {}, {'announcements': []},
    dict(announcements=[], hasMore='false', totalAnnouncement=0),
    dict(announcements=[], hasMore=True, totalAnnouncement=10),
    dict(announcements=[], hasMore=False, totalAnnouncement=True)])
def test_invalid_response_cannot_be_clear(response):
    assert verify.validate_post_response(response)


def test_cached_missing_page_and_count_mismatch(tmp_path):
    rec = dict(ts_code='A', ann_date='20200401')
    path = tmp_path / 'A_20200401_post_1.json'
    assert repair.cached_query(rec, tmp_path)['failure'] == 'missing_cached_page'
    path.write_text(json.dumps(dict(announcements=[], hasMore=False, totalAnnouncement=1)))
    assert repair.cached_query(rec, tmp_path)['failure'] == 'total_count_mismatch'
    path.write_text(json.dumps(dict(announcements=None, hasMore=False, totalAnnouncement=0)))
    assert repair.cached_query(rec, tmp_path)['complete'] is True


def test_online_failure_is_not_success(monkeypatch, tmp_path):
    monkeypatch.setattr(verify, 'OUT', tmp_path)
    monkeypatch.setattr(verify.r1, 'run_curl', lambda *a: False)
    query = verify.query_post_window('A', 'org', '20200401')
    assert query['failure'] == 'request_failed'
    assert not query['complete']


def test_pagination_cap_is_incomplete(tmp_path, monkeypatch):
    rec = dict(ts_code='A', ann_date='20200401')
    for page in range(1, 6):
        (tmp_path / f'A_20200401_post_{page}.json').write_text(json.dumps(dict(
            announcements=[dict(announcementId=str(page))], hasMore=True, totalAnnouncement=10)))
    assert repair.cached_query(rec, tmp_path)['failure'] == 'pagination_limit_reached'
    monkeypatch.setattr(verify, 'OUT', tmp_path.parent)
    (tmp_path.parent / 'responses').mkdir(exist_ok=True)
    for p in tmp_path.glob('*.json'):
        (tmp_path.parent / 'responses' / p.name).write_bytes(p.read_bytes())
    assert verify.query_post_window('A', 'org', '20200401')['failure'] == 'pagination_limit_reached'
