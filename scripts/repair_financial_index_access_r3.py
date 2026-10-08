"""Finite second access pass, sequenced after r1, using observed issuer IDs."""
import csv
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_remaining_financial_evidence as c
import announcement_financial_audit as audit

FIRST = c.OUT
OUT = audit.OUT / 'remaining_evidence_r2_fixed_r1'


def issuer_ids(results):
    ids = {}
    for result in results:
        code = result['ts_code']
        for query in result.get('queries', []):
            for item in query.get('items', []):
                value = item.get('orgId', '')
                if item.get('secCode') == code[:6] and re.fullmatch(r'[A-Za-z0-9]+', value):
                    ids.setdefault(code, set()).add(value)
    return {code: next(iter(values)) for code, values in ids.items() if len(values) == 1}


def candidates(items, periods):
    extra = [i for i in items if re.search('业绩预增|业绩预减|业绩预亏|业绩预盈', i.get('announcementTitle', ''))]
    found = {i['announcementId']: i for i in c.candidate_items(items, periods) + extra
             if not re.search('持续督导|督导报告', i.get('announcementTitle', ''))}
    return sorted(found.values(), key=lambda i: i['announcementId'])


def stock_query(code, day, org):
    date = datetime.strptime(day, '%Y%m%d').strftime('%Y-%m-%d')
    pages, items = [], []
    for page in range(1, 6):
        params = dict(pageNum=str(page), pageSize='30', tabName='fulltext',
            column='szse' if code.endswith('.SZ') else 'sse', stock=f'{code[:6]},{org}',
            searchkey='', isHLtitle='false', seDate=f'{date}~{date}')
        path = OUT / 'responses' / f'{code}_{day}_{page}.json'
        if not path.exists():
            temp = path.with_suffix('.partial')
            args = ['--max-time', '40', c.ENDPOINT, '--header', 'User-Agent: Mozilla/5.0',
                    '--header', 'Referer: https://www.cninfo.com.cn/', '--output', str(temp)]
            for name, value in params.items(): args += ['--data-urlencode', f'{name}={value}']
            if not c.run_curl(args, 50, dict(code=code, day=day, request=params)):
                return dict(status='stock_query_failed', pages=pages, items=items)
            try:
                obj = json.loads(temp.read_text(encoding='utf-8'))
                if not isinstance(obj.get('announcements'), (list, type(None))) or 'announcements' not in obj:
                    raise ValueError('Invalid announcements schema')
                temp.replace(path)
            except (ValueError, UnicodeError) as exc:
                c.event('index_schema_failure', code=code, day=day, error=str(exc))
                return dict(status='stock_query_schema_failed', pages=pages, items=items)
        obj = json.loads(path.read_text(encoding='utf-8'))
        pages.append(dict(file=str(path.relative_to(OUT)), sha256=audit.sha(path), request=params,
                          has_more=bool(obj.get('hasMore')), total=obj.get('totalAnnouncement')))
        items.extend(obj.get('announcements') or [])
        if not obj.get('hasMore'):
            return dict(status='stock_query_complete_current_index_only', pages=pages, items=items)
        time.sleep(1.3)
    return dict(status='stock_query_page_limit', pages=pages, items=items)


def main():
    for name in ['responses', 'results', 'documents', 'source_snapshot']:
        (OUT / name).mkdir(parents=True, exist_ok=True)
    lock = OUT / 'collection.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    try:
        active, outside, groups = c.load_queue()
        protocol = dict(queue_sha256=audit.sha(c.QUEUE), source_sha256=audit.sha(Path(__file__)),
            shared_collector_sha256=audit.sha(Path(c.__file__)), design_sha256=audit.sha(audit.SPEC),
            window=c.WINDOW, max_index_pages=5, max_documents=4,
            rule='Only failed/missing/incomplete/nonfinancial r1 candidate keys; observed unambiguous official orgId only')
        protocol = json.loads(json.dumps(protocol))
        file = OUT / 'protocol.json'
        if file.exists():
            if json.loads(file.read_text(encoding='utf-8')) != protocol:
                raise RuntimeError('Frozen repair protocol changed')
        else:
            audit.write_json(file, protocol)
            for path in [c.QUEUE, Path(__file__), Path(c.__file__)]:
                shutil.copy2(path, OUT / 'source_snapshot' / path.name)
        started = time.monotonic()
        while (FIRST / 'collection.lock').exists():
            audit.write_json(OUT / 'status.json', dict(at=audit.now(), pid=os.getpid(),
                state='waiting_for_first_pass', verified_original_version_rows=0))
            if time.monotonic() - started > 10800:
                raise RuntimeError('First pass not finished within bounded three-hour wait')
            time.sleep(30)
        first = [json.loads(p.read_text(encoding='utf-8')) for p in (FIRST / 'results').glob('*.json')]
        if len(first) != len(groups):
            raise RuntimeError('First pass exited incomplete; do not silently launch another collector')
        if audit.sha(c.QUEUE) != protocol['queue_sha256']:
            raise RuntimeError('Queue changed')
        ids = issuer_ids(first)
        audit.write_json(OUT / 'observed_issuer_ids.json', ids)
        targets = [r for r in first if r['status'] != 'document_candidates_downloaded_only'
            or r.get('unselected_candidates')
            or any(d.get('status') != 'downloaded_readable_candidate_only'
                   or '持续督导' in d.get('title', '') for d in r.get('documents', []))]
        c.OUT = OUT
        results = []
        for original in sorted(targets, key=lambda r: (r['ts_code'], r['ann_date'])):
            code, day = original['ts_code'], original['ann_date']
            path = OUT / 'results' / f'{code}_{day}.json'
            if path.exists():
                result = json.loads(path.read_text(encoding='utf-8'))
            else:
                result = dict(ts_code=code, ann_date=day, first_pass_status=original['status'],
                    first_pass_result_sha256=audit.sha(FIRST / 'results' / path.name),
                    usable_in_verified_history=False, documents=[])
                if code not in ids:
                    result['status'] = 'unresolved_no_unambiguous_official_issuer_id'
                else:
                    query = stock_query(code, day, ids[code]); result['query'] = query
                    matched = c.matched_items(query['items'], code, day)
                    selected = candidates(matched, {r['end_date'] for r in groups[(code, day)]})
                    result['candidate_count'] = len(selected)
                    result['unselected_candidates'] = selected[4:]
                    for item in selected[:4]:
                        result['documents'].append(c.download(item, code, day)); time.sleep(1.3)
                    result['status'] = ('candidate_documents_accessed_only' if selected else
                        'no_financial_candidate_identified' if matched else 'no_exact_issuer_day_match')
                    if query['status'] != 'stock_query_complete_current_index_only':
                        result['status'] = query['status']
                audit.write_json(path, result)
                time.sleep(1.3)
            results.append(result)
            audit.write_json(OUT / 'status.json', dict(at=audit.now(), pid=os.getpid(), state='running',
                completed_keys=len(results), total_repair_keys=len(targets), verified_original_version_rows=0))
            print(f'{len(results)}/{len(targets)} {code} {day}: {result["status"]}', flush=True)
        audit.verify_old()
        if audit.sha(c.QUEUE) != protocol['queue_sha256']:
            raise RuntimeError('Queue changed')
        states = {}
        for result in results: states[result['status']] = states.get(result['status'], 0) + 1
        audit.write_json(OUT / 'status.json', dict(at=audit.now(), pid=os.getpid(),
            state='completed_access_repair_only', completed_keys=len(results), total_repair_keys=len(targets),
            counts=states, verified_original_version_rows=0, old_results_hashes_checked=True))
        (audit.OUT / 'index-access-repair-report.md').write_text(
            '# 公告检索修正轮\n\n' + f'已处理{len(results)}组。分类：{json.dumps(states, ensure_ascii=False)}。\n\n'
            + '首轮结果完整保留；本轮使用已观察官方主体标识，未猜测旧代码。候选文件取得不等于财务字段或原版本链通过。历史可用审批仍为0，不能据此开始财务风险过滤回测。\n'
            + '原结果哈希检查通过；逐组结果及访问失败见remaining_evidence_r2。原文人工核验、日期差异、身份映射及版本恢复仍需逐项解决。\n', encoding='utf-8')
    except Exception as exc:
        audit.write_json(OUT / 'status.json', dict(at=audit.now(), pid=os.getpid(), state='failed',
            error=str(exc), verified_original_version_rows=0))
        raise
    finally:
        lock.unlink()


if __name__ == '__main__':
    main()
