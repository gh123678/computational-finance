"""Exercise the real shared matcher through the repair's complete entry point."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import repair_financial_index_access_r3 as repair
import pytest


@pytest.mark.parametrize('item_code,stamp,expected', [
    ('000595', 1556553600000, 'no_financial_candidate_identified'),
    ('000001', 1556553600000, 'no_exact_issuer_day_match'),
    ('000595', 1556640000000, 'no_exact_issuer_day_match'),
])
def test_full_entry_point_uses_real_shared_matcher(monkeypatch, tmp_path, item_code, stamp, expected):
    first = tmp_path / 'first'
    (first / 'results').mkdir(parents=True)
    code, day = '000595.SZ', '20190430'
    original = dict(ts_code=code, ann_date=day, status='successful_index_queries_no_exact_issuer_day_match',
                    queries=[dict(items=[dict(secCode=code[:6], orgId='gssz0000595')])])
    original_path = first / 'results' / f'{code}_{day}.json'
    original_path.write_text(json.dumps(original), encoding='utf-8')
    original_bytes = original_path.read_bytes()
    out = tmp_path / 'fixed'
    monkeypatch.setattr(repair, 'FIRST', first)
    monkeypatch.setattr(repair, 'OUT', out)
    monkeypatch.setattr(repair.audit, 'OUT', tmp_path)
    queue = tmp_path / 'queue.csv'; queue.write_text('fixture', encoding='utf-8')
    spec = tmp_path / 'spec.md'; spec.write_text('approved fixture', encoding='utf-8')
    monkeypatch.setattr(repair.c, 'QUEUE', queue)
    monkeypatch.setattr(repair.c, 'OUT', first)
    monkeypatch.setattr(repair.audit, 'SPEC', spec)
    monkeypatch.setattr(repair.audit, 'verify_old', lambda: None)
    rows = [dict(ts_code=code, ann_date=day, end_date='20190331')]
    monkeypatch.setattr(repair.c, 'load_queue', lambda: (rows, [], {(code, day): rows}))
    monkeypatch.setattr(repair.time, 'sleep', lambda _: None)
    monkeypatch.setattr(repair, 'stock_query', lambda *_: dict(
        status='stock_query_complete_current_index_only', pages=[], items=[dict(
            secCode=item_code, announcementTime=stamp, announcementId='123',
            announcementTitle='关于召开股东大会的公告')]))
    repair.main()
    result = json.loads((out / 'results' / original_path.name).read_text(encoding='utf-8'))
    assert result['status'] == expected
    assert result['usable_in_verified_history'] is False
    assert original_path.read_bytes() == original_bytes
    assert not (out / 'collection.lock').exists()
    final = json.loads((out / 'status.json').read_text(encoding='utf-8'))
    assert final['state'] == 'completed_access_repair_only'
    assert final['completed_keys'] == 1
    assert final['verified_original_version_rows'] == 0
