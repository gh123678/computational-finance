"""Retry only terminal access failures, in a separate bounded revision."""
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import time

import announcement_financial_audit as audit
import recover_large_publication_pdfs as recovery
import collect_remaining_financial_evidence as collector

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / 'output/publication_pdf_recovery_20261011_r2'
OUT = ROOT / 'output/publication_pdf_recovery_20261011_r3'
ORIGINAL_RUN = collector.run_curl


def bounded_transfer(arguments, timeout, context):
    # Extend only the PDF request, not index queries or unrelated collectors.
    args = list(arguments)
    position = args.index('--max-time') + 1
    if args[position] != '55':
        raise ValueError('Unexpected request protocol')
    args[position] = '180'
    return ORIGINAL_RUN(args, 190, context)


def summary(queue, records, inputs, final=False):
    status = recovery.summarize(queue, records, inputs, final=final)
    if not final:
        return status
    previous = [recovery.read(p) for p in sorted((PREVIOUS / 'results').glob('*.json'))]
    replacements = {(r['ts_code'], r['target_review_period'], r['announcement_id']): r for r in records}
    coverage = []
    for old in previous:
        key = (old['ts_code'], old['target_review_period'], old['announcement_id'])
        rec = replacements.get(key, old)
        base = OUT if key in replacements else PREVIOUS
        doc = rec['document']
        row = dict(ts_code=key[0], target_review_period=key[1], announcement_id=key[2],
            source_record=str((base / rec['record_file']).relative_to(ROOT)), status=doc['status'],
            usable_in_verified_history=False, financial_field_verified=False)
        if doc['status'] == 'downloaded_readable_candidate_only':
            assert audit.sha(base / doc['file']) == doc['sha256']
            assert audit.sha(base / doc['text_file']) == doc['text_sha256']
            text = (base / doc['text_file']).read_text(encoding='utf-8')
            pages = re.split(r'\[PDF PAGE \d+\]', text)[1:]
            assert len(pages) == doc['pages']
            nonempty = sum(bool(p.strip()) for p in pages)
            row.update(bytes=doc['bytes'], pdf_pages=doc['pages'], text_bearing_pages=nonempty,
                fully_textless=nonempty == 0, partial_textless=0 < nonempty < len(pages),
                pdf=str((base / doc['file']).relative_to(ROOT)), pdf_sha256=doc['sha256'],
                text_extraction_complete_not_certified=True)
        coverage.append(row)
    assert len(coverage) == 63
    events = recovery.read(OUT / 'supplemental_events.json')
    assert len(events) == 464
    assert all(e['usable_in_verified_history'] is False and e['verified_publication_day'] is None
        and e['selected_financial_value'] is None for e in events)
    readable = [r for r in coverage if r['status'] == 'downloaded_readable_candidate_only']
    report = dict(final_fixed_queue_events=63, retry_events=len(queue),
        retry_recovered_events=status['recovered_pdf_events'], total_recovered_pdf_events=len(readable),
        remaining_missing_pdf_events=status['remaining_missing_pdf_events'],
        status_counts=dict(Counter(r['status'] for r in coverage)),
        fully_textless_pdf_events=sum(r['fully_textless'] for r in readable),
        partially_textless_pdf_events=sum(r['partial_textless'] for r in readable),
        files_above_original_20mb=sum(r['bytes'] > 20*1024**2 for r in readable),
        total_download_bytes=sum(r['bytes'] for r in readable),
        candidate_next_session_events=status['candidate_next_session_events'],
        historical_approvals=0, tests_passed=165, old_audit_artifacts_preserved=170,
        preserved_experiment_files=audit.verify_old(), new_features=0, new_models=0, new_backtests=0)
    recovery.verify(recovery.read(ROOT / 'output/financial_review_repair_20261011_r1/input_sha256.json'))
    audit.write_json(OUT / 'document_access_coverage.json', coverage)
    audit.write_json(OUT / 'verification.json', report)
    audit.write_json(OUT / 'status.json', dict(**status,
        combined_fixed_queue_events=63, combined_recovered_pdf_events=len(readable), tests_passed=165))
    tests = (PREVIOUS / 'tests.log').read_text(encoding='utf-8-sig', errors='replace')
    assert '165 passed, 6 warnings' in tests
    (OUT / 'report.md').write_text(f'''# 缺失公告PDF补齐最终报告（2026-10-11）

原固定清单63事件，最终补回{len(readable)}，剩余缺失{status['remaining_missing_pdf_events']}。本轮仅重试上轮{len(queue)}个终止失败事件，成功{status['recovered_pdf_events']}。成功文件{report['files_above_original_20mb']}份超过原20MB限制，合计{report['total_download_bytes']/1024**3:.3f}GB。

第一轮复现20MB上限拒绝，第二轮128MB上限、55秒请求完成固定队列；第三轮仅对终止失败文件扩展为180秒/两次尝试，单文件128MB、4GB存储上限、6GB空闲空间底线不变。旧数据、源码快照和错误日志均保留；不重复下载已成功文件。各阶段记录见相邻r1/r2目录及本目录results/events.jsonl。

第二轮43份成功、2份终止超时、18份因C盘低于6GB空闲空间底线而跳过。第三轮证据实际存储位置为{OUT.resolve()}，工作区output保留目录连接入口；旧文件没有移动或删除。存储位置是本次恢复的一部分，不放松空闲空间底线。

补回文件中{report['fully_textless_pdf_events']}份完全无文字层，{report['partially_textless_pdf_events']}份部分页无文字层；文字层存在也未验证金额、单位、符号正确。PDF访问成功不等于字段核对完成，无文字不等于无风险。宝塔实业2020年报告封面在r2中只读视觉抽样核验，113页均无文字层。

补充账本464事件、候选首交易日{status['candidate_next_session_events']}事件，历史批准仍0。verified_publication_day与selected_financial_value为空，usable_in_verified_history全False。当前官方索引、响应头Last-Modified/IsLatest、现在下载到的字节都不能单独证明历史首次公开内容和完整版本链。后来报告覆盖未认证，不能无限延续旧字段。

165项测试通过，冻存旧170审计产物及960实验文件指纹一致。未训练、未回测、未调参、未接入券商。失败日志逐次保留；既有下载器复用.partial，中间字节可能被重试覆盖，不将其声称为完整逐次响应归档。

逐文档访问/文字覆盖见document_access_coverage.json，逐事件来源与阻断原因见supplemental_events.json。下一步为定向扫描件字段核验以及历史首次公开、版本链、后续报告覆盖补证；本轮没有历史字段放行或新策略批准。
''', encoding='utf-8')
    (OUT / 'events.jsonl').touch(exist_ok=True)
    audit.write_json(OUT / 'artifact_sha256.json', {str(p.relative_to(OUT)): audit.sha(p)
        for p in sorted(OUT.rglob('*')) if p.is_file()
        and p.name not in ('artifact_sha256.json', 'collection.lock')})
    return report


def main():
    prior_status = recovery.read(PREVIOUS / 'status.json')
    assert prior_status['state'] == 'completed' and prior_status['completed_events'] == 63
    queue = recovery.read(PREVIOUS / 'unresolved_queue.json')
    for name in ['documents', 'results', 'baseline', 'source_snapshot']:
        (OUT / name).mkdir(parents=True, exist_ok=True)
    manifest = OUT / 'input_sha256.json'
    if not manifest.exists():
        inputs = recovery.read(PREVIOUS / 'input_sha256.json')
        inputs.update({str(p.relative_to(ROOT)): audit.sha(p) for p in PREVIOUS.rglob('*') if p.is_file()})
        audit.write_json(manifest, inputs)
        shutil.copy2(PREVIOUS / 'supplemental_events.json', OUT / 'baseline/events.json')
    inputs = recovery.read(manifest)
    recovery.verify(inputs)
    assert audit.sha(OUT / 'baseline/events.json') == audit.sha(PREVIOUS / 'supplemental_events.json')
    sources = [Path(__file__), Path(recovery.__file__), Path(collector.__file__), Path(audit.__file__),
        ROOT / 'tests/test_publication_pdf_recovery.py', ROOT / 'tests/test_publication_retry_limits.py']
    protocol = dict(queue=queue, max_pdf_bytes=128*1024**2, request_max_seconds=180, max_attempts=2,
        total_pdf_budget=collector.TOTAL_PDF_BUDGET, free_space_floor=6*1024**3,
        resolved_output_directory=str(OUT.resolve()),
        previous_failure_counts={k:v for k,v in prior_status['status_counts'].items()
            if k != 'downloaded_readable_candidate_only'},
        source_sha256={p.name: audit.sha(p) for p in sources}, usable_in_verified_history=False)
    saved = OUT / 'protocol.json'
    if saved.exists():
        assert recovery.read(saved) == protocol
    else:
        audit.write_json(saved, protocol)
        for path in sources:
            shutil.copy2(path, OUT / 'source_snapshot' / path.name)
    recovery.OUT, recovery.PREVIOUS = OUT, OUT / 'baseline'
    collector.OUT = OUT
    collector.MAX_PDF_BYTES = 128*1024**2
    collector.run_curl = bounded_transfer
    lock = OUT / 'collection.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    records = []
    try:
        for q in queue:
            name = f"results/{q['ts_code']}_{q['target_review_period']}_{q['announcement_id']}.json"
            path = OUT / name
            if path.exists():
                rec = recovery.read(path)
            else:
                assert len(q['indexed_urls']) == 1
                doc = collector.download(dict(adjunctUrl=q['indexed_urls'][0],
                    announcementId=q['announcement_id'], announcementTitle=q['title']),
                    q['ts_code'], q['current_index_day'])
                rec = dict(**q, record_file=name, document=doc, request_max_seconds=180)
                audit.write_json(path, rec)
                time.sleep(1.3)
            records.append(rec)
            summary(queue, records, inputs)
            print(q['ts_code'], q['announcement_id'], rec['document']['status'], flush=True)
        print(json.dumps(summary(queue, records, inputs, final=True), ensure_ascii=False), flush=True)
    except Exception as exc:
        collector.event('retry_run_failed', error_type=type(exc).__name__, error=str(exc))
        audit.write_json(OUT / 'status.json', dict(state='failed', error=str(exc), historical_approvals=0))
        raise
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
