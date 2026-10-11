"""Read-only validation and access coverage; no financial field extraction."""
from collections import Counter
import json
from pathlib import Path
import re

import announcement_financial_audit as audit
import recover_large_publication_pdfs as recovery

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/publication_pdf_recovery_20261011_r2'


def main():
    status = recovery.read(OUT / 'status.json')
    if status['state'] != 'completed' or status['completed_events'] != 63:
        raise RuntimeError('Fixed access pass must finish before final validation')
    recovery.verify(recovery.read(OUT / 'input_sha256.json'))
    prior = recovery.read(ROOT / 'output/financial_review_repair_20261011_r1/input_sha256.json')
    recovery.verify(prior)
    frozen = audit.verify_old()
    protocol = recovery.read(OUT / 'protocol.json')
    for name, digest in protocol['source_sha256'].items():
        assert audit.sha(ROOT / 'scripts' / name) == digest
        assert audit.sha(OUT / 'source_snapshot' / name) == digest
    records = [recovery.read(p) for p in sorted((OUT / 'results').glob('*.json'))]
    coverage = []
    for rec in records:
        doc = rec['document']
        headers = rec['response_headers']
        assert audit.sha(OUT / headers['file']) == headers['sha256']
        row = dict(ts_code=rec['ts_code'], target_review_period=rec['target_review_period'],
            announcement_id=rec['announcement_id'], access_status=doc['status'],
            usable_in_verified_history=False, financial_field_verified=False)
        if doc['status'] == 'downloaded_readable_candidate_only':
            assert audit.sha(OUT / doc['file']) == doc['sha256']
            assert audit.sha(OUT / doc['text_file']) == doc['text_sha256']
            text = (OUT / doc['text_file']).read_text(encoding='utf-8')
            pages = re.split(r'\[PDF PAGE \d+\]', text)[1:]
            assert len(pages) == doc['pages']
            nonempty = sum(bool(p.strip()) for p in pages)
            head = (OUT / headers['file']).read_text(encoding='utf-8', errors='replace')
            lengths = re.findall(r'^Content-Length:\s*(\d+)', head, flags=re.I | re.M)
            declared = int(lengths[-1]) if lengths else None
            row.update(bytes=doc['bytes'], pdf_pages=doc['pages'], text_bearing_pages=nonempty,
                textless_pages=doc['pages']-nonempty, all_pages_textless=nonempty == 0,
                text_extraction_complete_not_certified=True,
                current_head_content_length=declared,
                head_size_matches_download=declared == doc['bytes'] if declared is not None else None)
        coverage.append(row)
    events = recovery.read(OUT / 'supplemental_events.json')
    assert len(events) == 464
    assert all(e['usable_in_verified_history'] is False and e['verified_publication_day'] is None
        and e['selected_financial_value'] is None for e in events)
    keys = sorted({(e['ts_code'], e['target_review_period']) for e in events})
    per_key = []
    for code, period in keys:
        own = [e for e in events if (e['ts_code'], e['target_review_period']) == (code, period)]
        per_key.append(dict(ts_code=code, target_review_period=period, event_count=len(own),
            missing_pdf_events=sum('pdf_missing' in e['blockers'] for e in own),
            candidate_days=sorted({e['candidate_available_day'] for e in own if e['candidate_available_day']}),
            historical_release_status='unverified', complete_version_chain_status='unverified',
            usable_in_verified_history=False))
    tests = (OUT / 'tests.log').read_text(encoding='utf-8-sig', errors='replace')
    assert re.search(r'165 passed, 6 warnings', tests)
    readable = [r for r in coverage if r['access_status'] == 'downloaded_readable_candidate_only']
    result = dict(fixed_queue_events=63, access_status_counts=dict(Counter(r['access_status'] for r in coverage)),
        recovered_pdf_events=len(readable), total_download_bytes=sum(r['bytes'] for r in readable),
        max_pdf_bytes=max((r['bytes'] for r in readable), default=0),
        files_above_original_20mb=sum(r['bytes'] > 20*1024**2 for r in readable),
        fully_textless_pdf_events=sum(r['all_pages_textless'] for r in readable),
        partially_textless_pdf_events=sum(0 < r['text_bearing_pages'] < r['pdf_pages'] for r in readable),
        head_size_mismatches=sum(r['head_size_matches_download'] is False for r in readable),
        ledger_events=len(events), ledger_keys=len(keys),
        remaining_missing_pdf_events=sum('pdf_missing' in e['blockers'] for e in events),
        historical_approvals=0, tests_passed=165, existing_warnings=6,
        original_audit_files_preserved=len(prior), preserved_experiment_files=frozen,
        frozen_input_files_checked=status['frozen_input_files_checked'],
        first_cover_visual_check=dict(ts_code='000595.SZ', period='20201231',
            announcement_id='1209777426', observed_issuer='宝塔实业股份有限公司',
            observed_report='审计报告2020年度', historical_identity_approved=False),
        new_features=0, new_models=0, new_backtests=0)
    audit.write_json(OUT / 'document_access_coverage.json', coverage)
    audit.write_json(OUT / 'per_key_timing_gaps.json', per_key)
    audit.write_json(OUT / 'verification.json', result)
    (OUT / 'events.jsonl').touch(exist_ok=True)
    with (OUT / 'report.md').open('a', encoding='utf-8') as stream:
        stream.write(f'''\n## 最终核验

{len(readable)}/63事件补回；文件合计{result['total_download_bytes']/1024**3:.3f}GB，最大{result['max_pdf_bytes']/1024**2:.2f}MB。其中{result['files_above_original_20mb']}份超过旧20MB上限，说明旧“transport_failed”不能一律理解为网站或网络不可达。旧失败日志和首次重试失败完整保留。

补回文件中{result['fully_textless_pdf_events']}份完全无文字层，{result['partially_textless_pdf_events']}份部分页无文字层。文字层存在也未认证表格、符号、单位提取正确。逐文档状况见document_access_coverage.json；这些未知值不得填为0或“无风险”。宝塔实业2020年度审计报告封面已只读视觉核验，113页全部无文字层；封面相符不构成历史内容身份认证。

补充账本保留464事件、166键，PDF剩余缺口{result['remaining_missing_pdf_events']}；候选日期不是已核实历史日期，历史批准仍0。HTTP头的Last-Modified、IsLatest等只描述当前服务器状态，不能替代历史首次发布证据。完整修订链和后续报告覆盖仍未核验。

失败日志保留逐次curl错误、时间和下载字节信息。既有下载器复用同一.partial路径，中间失败字节可能被下一次尝试覆盖；不把.partial视为完整的逐次响应字节归档。旧r1文件已单独冻结。

165项测试通过（6项既有警告）；冻结输入{status['frozen_input_files_checked']}文件、旧{len(prior)}审计产物及960实验文件指纹一致。请求头大小与实际文件不符{result['head_size_mismatches']}份。采集已结束；未启动后台任务。下一步处理扫描件的定向字段证据及历史版本/发布时间认证，不能直接消费这些文件训练策略。
''')
    snapshot = OUT / 'source_snapshot'
    for path in [Path(__file__), Path(audit.__file__), ROOT / 'tests/test_publication_pdf_recovery.py']:
        (snapshot / path.name).write_bytes(path.read_bytes())
    audit.write_json(OUT / 'artifact_sha256.json', {str(p.relative_to(OUT)): audit.sha(p)
        for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'artifact_sha256.json'})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
