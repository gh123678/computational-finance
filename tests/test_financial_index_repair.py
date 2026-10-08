import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import repair_financial_index_access as repair


def test_issuer_mapping_requires_matching_code_and_unambiguous_observed_id():
    def result(code, items):
        return dict(ts_code=code, queries=[dict(items=items)])
    records = [
        result('000595.SZ', [dict(secCode='000595', orgId='gssz0000595'),
                              dict(secCode='000001', orgId='wrongCompany')]),
        result('000595.SZ', [dict(secCode='000595', orgId='gssz0000595')]),
        result('000002.SZ', [dict(secCode='000002', orgId='one'),
                              dict(secCode='000002', orgId='two')]),
        result('000003.SZ', [dict(secCode='000003', orgId='../unsafe')]),
    ]
    assert repair.issuer_ids(records) == {'000595.SZ': 'gssz0000595'}


def test_candidate_titles_rescue_preincrease_but_exclude_supervision():
    items = [dict(announcementId='1', announcementTitle='2013年第一季度业绩预增公告'),
             dict(announcementId='2', announcementTitle='2013年持续督导年度报告'),
             dict(announcementId='3', announcementTitle='2013年年度报告'),
             dict(announcementId='4', announcementTitle='2013年年度报告摘要')]
    assert [i['announcementId'] for i in repair.candidates(items, {'20130331'})] == ['1', '3']


def test_corrected_query_keeps_day_and_uses_explicit_issuer(monkeypatch, tmp_path):
    import json
    monkeypatch.setattr(repair, 'OUT', tmp_path)
    (tmp_path / 'responses').mkdir()
    captured = []
    def curl(arguments, timeout, context):
        captured.append(context['request'])
        Path(arguments[arguments.index('--output') + 1]).write_text(
            json.dumps(dict(announcements=[], hasMore=False, totalAnnouncement=0)), encoding='utf-8')
        return True
    monkeypatch.setattr(repair.c, 'run_curl', curl)
    result = repair.stock_query('000595.SZ', '20190430', 'gssz0000595')
    assert captured[0]['stock'] == '000595,gssz0000595'
    assert captured[0]['searchkey'] == ''
    assert captured[0]['seDate'] == '2019-04-30~2019-04-30'
    assert result['status'] == 'stock_query_complete_current_index_only'
