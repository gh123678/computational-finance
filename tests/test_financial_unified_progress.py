import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from report_financial_access_repair_progress import load_results


@pytest.mark.parametrize('code,day,approved', [
    ('000001.SZ','20210101',False),
    ('000001.SZ','20200101',True),
    ('000001.SZ','20200101','False'),
])
def test_unified_report_rejects_outside_scope_or_history_approval(tmp_path, code, day, approved):
    (tmp_path / 'results').mkdir()
    (tmp_path / 'results/case.json').write_text(json.dumps(dict(ts_code=code,ann_date=day,
        usable_in_verified_history=approved)),encoding='utf-8')
    with pytest.raises(RuntimeError):
        load_results(tmp_path,{('000001.SZ','20200101'):[]})


def test_candidate_access_remains_unapproved_in_unified_report(tmp_path):
    (tmp_path / 'results').mkdir()
    row=dict(ts_code='000001.SZ',ann_date='20200101',usable_in_verified_history=False,
             status='candidate_documents_accessed_only')
    (tmp_path / 'results/case.json').write_text(json.dumps(row),encoding='utf-8')
    assert load_results(tmp_path,{('000001.SZ','20200101'):[]})[('000001.SZ','20200101')]==row
