"""Recover fixed official PDF candidates without changing historical approval."""
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pandas as pd
import announcement_financial_audit as audit
import audit_publication_time as timing
import collect_remaining_financial_evidence as collector

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / 'output/publication_time_audit_20261011_r1'
OUT = ROOT / 'output/publication_pdf_recovery_20261011_r2'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify(manifest):
    changed = [p for p, digest in manifest.items() if not (ROOT / p).is_file()
               or audit.sha(ROOT / p) != digest]
    if changed:
        raise RuntimeError(f'Frozen evidence changed: {changed[:5]}')


def summarize(queue, records, inputs, final=False):
    by_key = {(r['ts_code'], r['target_review_period'], r['announcement_id']): r for r in records}
    calendar = timing.calendar_map(pd.read_csv(
        ROOT / 'data/continuous_2016_2025_dividend_r1/calendar.csv', dtype={'cal_date': str}))
    supplemental = read(PREVIOUS / 'events.json')
    recovered = 0
    for event in supplemental:
        key = (event['ts_code'], event['target_review_period'], event['announcement_id'])
        rec = by_key.get(key)
        if not rec or rec['document']['status'] != 'downloaded_readable_candidate_only':
            continue
        doc = rec['document']
        path = OUT / doc['file']
        if audit.sha(path) != doc['sha256']:
            raise RuntimeError('Recovered PDF fingerprint changed')
        day, state = timing.next_session(rec['current_index_day'], calendar)
        event['source_observations'].append(dict(
            ts_code=key[0], target_review_period=key[1], announcement_id=key[2],
            reported_index_day=rec['current_index_day'], title=rec['title'],
            pdf=str(path.relative_to(ROOT)), pdf_sha256=doc['sha256'],
            source_metadata=str((OUT / rec['record_file']).relative_to(ROOT)),
            collection_status=doc['status'], scope='recovered_current_content_candidate_only'))
        event['blockers'] = [b for b in event['blockers'] if b != 'pdf_missing']
        if event['identity_status'] == 'current_index_identity_date_matches':
            event['candidate_available_day'], event['date_status'] = day, state
        recovered += 1
    assert all(e['usable_in_verified_history'] is False and e['verified_publication_day'] is None
               and e['selected_financial_value'] is None for e in supplemental)
    if final:
        verify(inputs)
    frozen = audit.verify_old() if final else None
    status = dict(at=audit.now(), pid=os.getpid(), state='completed' if final else 'running',
        queued_events=len(queue), completed_events=len(records), recovered_pdf_events=recovered,
        remaining_missing_pdf_events=sum('pdf_missing' in e['blockers'] for e in supplemental),
        status_counts=dict(Counter(r['document']['status'] for r in records)),
        candidate_next_session_events=sum(e['candidate_available_day'] is not None for e in supplemental),
        approved_historical_events=0, frozen_input_files_checked=len(inputs),
        preserved_experiment_files=frozen, new_features=0, new_models=0, new_backtests=0)
    audit.write_json(OUT / 'status.json', status)
    audit.write_json(OUT / 'supplemental_events.json', supplemental)
    audit.write_json(OUT / 'unresolved_queue.json', [q for q in queue if
        (q['ts_code'], q['target_review_period'], q['announcement_id']) not in by_key or
        by_key[(q['ts_code'], q['target_review_period'], q['announcement_id'])]['document']['status']
        != 'downloaded_readable_candidate_only'])
    report = f'''# 缺失公告PDF补齐（2026-10-11）

固定上轮63事件清单，逐一访问已保存官方链接；旧报告、账本、失败记录及实验结果不修改。

本轮状态：{status['state']}；处理{len(records)}/{len(queue)}，补回可读PDF {recovered}个，剩余缺失{status['remaining_missing_pdf_events']}个。补充账本候选可用日事件{status['candidate_next_session_events']}；历史可用批准仍0。下载状态：{json.dumps(status['status_counts'], ensure_ascii=False)}。

下载器沿用既有官方PDF路径校验、55秒请求上限、两次尝试、128MB单文件上限（仅本修订）、4GB总存储上限及6GB空闲空间底线；每个事件断点保存。网络失败见events.jsonl，失败的.partial不删除，旧失败证据保留。下载成功只证明当前能读取这些字节，不证明历史首发内容身份、完整版本链或财务字段正确。

补充账本见supplemental_events.json；逐文档URL、抓取时间、页数、PDF与文本指纹见results。PDF可打开不代表扫描件文字已完整提取。报告期仍是核验目标期，不推断附件实际报告期。所有财务值和verified_publication_day保持空，usable_in_verified_history保持False。后续仍需历史公开/内容身份、完整版本链及后续报告覆盖证据。

冻结输入{len(inputs)}文件已校验一致；原实验指纹校验：{json.dumps(frozen, ensure_ascii=False)}。未训练、未回测、未调整策略，未接入券商。
'''
    (OUT / 'report.md').write_text(report, encoding='utf-8')
    return status


def main():
    for name in ('documents', 'results', 'source_snapshot'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    collector.OUT = OUT
    collector.MAX_PDF_BYTES = 128 * 1024 ** 2
    manifest_path = OUT / 'input_sha256.json'
    inputs = read(PREVIOUS / 'input_sha256.json')
    inputs.update({str(p.relative_to(ROOT)): audit.sha(p) for p in PREVIOUS.rglob('*') if p.is_file()})
    inputs.update({str(p.relative_to(ROOT)): audit.sha(p) for p in
        (ROOT / 'output/publication_pdf_recovery_20261011_r1').rglob('*') if p.is_file()})
    if manifest_path.exists():
        inputs = read(manifest_path)
    else:
        audit.write_json(manifest_path, inputs)
    verify(inputs)
    audit.verify_old()
    queue = read(PREVIOUS / 'missing_pdf_queue.json')
    sources = [Path(__file__), Path(collector.__file__), Path(timing.__file__)]
    protocol = dict(queue_sha256=audit.sha(PREVIOUS / 'missing_pdf_queue.json'),
        source_sha256={p.name: audit.sha(p) for p in sources},
        expected_events=63, max_pdf_bytes=collector.MAX_PDF_BYTES,
        total_pdf_budget=collector.TOTAL_PDF_BUDGET, request_max_seconds=55,
        max_attempts=2, usable_in_verified_history=False)
    if len(queue) != 63:
        raise RuntimeError('Fixed queue length changed')
    protocol_path = OUT / 'protocol.json'
    if protocol_path.exists() and read(protocol_path) != protocol:
        raise RuntimeError('Protocol changed; use a separate revision')
    if not protocol_path.exists():
        audit.write_json(protocol_path, protocol)
        for path in sources:
            shutil.copy2(path, OUT / 'source_snapshot' / path.name)
    lock = OUT / 'collection.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    records = []
    try:
        for q in queue:
            name = f"results/{q['ts_code']}_{q['target_review_period']}_{q['announcement_id']}.json"
            path = OUT / name
            if path.exists():
                rec = read(path)
            else:
                if len(q['indexed_urls']) != 1:
                    raise RuntimeError('Ambiguous current indexed URL')
                item = dict(adjunctUrl=q['indexed_urls'][0], announcementId=q['announcement_id'])
                url = collector.safe_url(item, q['current_index_day'])
                header_file = OUT / 'results' / (path.stem + '.headers.txt')
                head = subprocess.run(['curl.exe', '-4', '--head', '--fail', '--silent',
                    '--show-error', '--connect-timeout', '10', '--max-time', '20', url],
                    capture_output=True, timeout=25)
                header_file.write_bytes(head.stdout)
                header_evidence = dict(file=str(header_file.relative_to(OUT)),
                    sha256=audit.sha(header_file), exit_code=head.returncode,
                    error=head.stderr.decode('utf-8', errors='replace'), retrieved_at=audit.now(),
                    limitation='Current server headers are not historical first-publication proof')
                doc = collector.download(dict(adjunctUrl=q['indexed_urls'][0],
                    announcementId=q['announcement_id'], announcementTitle=q['title']),
                    q['ts_code'], q['current_index_day'])
                rec = dict(**q, document=doc, record_file=name, response_headers=header_evidence)
                audit.write_json(path, rec)
                time.sleep(1.3)
            records.append(rec)
            summarize(queue, records, inputs)
            print(q['ts_code'], q['announcement_id'], rec['document']['status'], flush=True)
        print(json.dumps(summarize(queue, records, inputs, final=True), ensure_ascii=False), flush=True)
    except Exception as exc:
        collector.event('recovery_run_failed', error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
