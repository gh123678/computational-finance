import csv
from datetime import datetime, timezone, timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import collect_remaining_financial_evidence as evidence


def test_scope_preserves_outside_rows_without_requesting_them(tmp_path):
    path=tmp_path/'queue.csv'
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['ts_code','ann_date']);writer.writeheader()
        writer.writerows([dict(ts_code='000001.SZ',ann_date=d) for d in ['20130308','20201231','20210308','bad']])
    active,outside,groups=evidence.load_queue(path)
    assert len(active)==2 and len(outside)==2
    assert all('20130101'<=day<='20201231' for _,day in groups)


def test_parent_and_wrong_day_are_not_issuer_publication_evidence():
    epoch=datetime(2013,3,8,tzinfo=timezone(timedelta(hours=8))).timestamp()*1000
    rows=[dict(secCode=code,announcementTime=stamp) for code,stamp in
        [('000001',epoch),('601318',epoch),('000001',epoch+86400000)]]
    assert evidence.matched_items(rows,'000001.SZ','20130308')==rows[:1]


def test_candidate_selection_does_not_download_legal_reports_or_other_years():
    rows=[dict(announcementTitle=t,announcementId=str(i)) for i,t in enumerate(
        ['2019年年度报告','2019年年度报告摘要','2019年内部控制审计报告','2021年年度报告','2019年度业绩预告修正公告'])]
    candidates=evidence.candidate_items(rows,['20191231'])
    assert {r['announcementTitle'] for r in candidates}=={'2019年年度报告','2019年度业绩预告修正公告'}


def test_untrusted_url_cannot_escape_public_host_or_filename():
    import pytest
    assert evidence.safe_url(dict(adjunctUrl='finalpage/2020-01-18/1207263441.PDF'),'20200118').startswith('https://static.cninfo.com.cn/')
    for path in ['https://evil.example/a.pdf','finalpage/2020-01-18/../a.pdf','finalpage/2021-01-18/1.PDF']:
        with pytest.raises(ValueError):evidence.safe_url(dict(adjunctUrl=path),'20200118')
