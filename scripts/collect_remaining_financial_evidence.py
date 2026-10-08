"""Collect public document candidates for the entire approved review queue.

This does not approve numeric fields, original versions or historical usability.
It preserves input hashes, cached responses, attempt failures and bounded downloads.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import fitz

OUT = audit.OUT / 'remaining_evidence_r1'
QUEUE = audit.OUT / 'original_document_check_queue.csv'
ENDPOINT = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
WINDOW = ('20130101', '20201231')
MAX_PDF_BYTES = 20 * 1024 * 1024
TOTAL_PDF_BUDGET = 4 * 1024 ** 3
ALIASES = {'000004.SZ': '国农科技'}


def load_queue(path=QUEUE):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    active, outside = [], []
    for row in rows:
        day = row['ann_date']
        (active if len(day) == 8 and day.isdigit() and WINDOW[0] <= day <= WINDOW[1]
         else outside).append(row)
    groups = {}
    for row in active:
        groups.setdefault((row['ts_code'], row['ann_date']), []).append(row)
    return active, outside, groups


def event(kind, **details):
    with (OUT / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(dict(at=audit.now(), kind=kind, **details), ensure_ascii=False)+'\n')


def run_curl(arguments, timeout, context):
    """Keep each unsuccessful attempt, including failures followed by success."""
    for attempt in range(1, 3):
        try:
            result = subprocess.run(['curl.exe', '-4', '--connect-timeout', '10',
                '--fail', '--silent', '--show-error', *arguments], capture_output=True, timeout=timeout)
            if result.returncode == 0:
                return True
            error = result.stderr.decode('utf-8', errors='replace').strip()
            event('transport_failure', context=context, attempt=attempt, exit_code=result.returncode, error=error)
        except subprocess.TimeoutExpired:
            event('transport_failure', context=context, attempt=attempt, error='subprocess timeout')
        time.sleep(1.3)
    return False


def query(code, day, keyword):
    date = datetime.strptime(day, '%Y%m%d').strftime('%Y-%m-%d')
    key = hashlib.sha256(keyword.encode('utf-8')).hexdigest()[:12]
    all_items, pages = [], []
    for page in range(1, 6):
        params = dict(pageNum=str(page), pageSize='30', tabName='fulltext',
            column='szse' if code.endswith('.SZ') else 'sse', isHLtitle='false',
            searchkey=keyword, seDate=f'{date}~{date}')
        path = OUT / 'responses' / f'{code}_{day}_{key}_{page}.json'
        # Reuse original code-keyword responses, never edit them.
        old = audit.OUT / 'fixed_sample_indices/responses' / f'{code}_{day}_{page}.json'
        if not path.exists() and keyword == code[:6] and old.exists():
            shutil.copy2(old, path)
        if not path.exists():
            temp = path.with_suffix('.partial')
            arguments = ['--max-time', '40', ENDPOINT, '--header', 'User-Agent: Mozilla/5.0',
                '--header', 'Referer: https://www.cninfo.com.cn/', '--output', str(temp)]
            for name, value in params.items():
                arguments += ['--data-urlencode', f'{name}={value}']
            if not run_curl(arguments, 50, dict(code=code, day=day, query=params)):
                return dict(status='query_failed', pages=pages, items=all_items, request=params)
            try:
                obj = json.loads(temp.read_text(encoding='utf-8'))
                if not isinstance(obj, dict) or 'announcements' not in obj:
                    raise ValueError('missing announcements schema')
                temp.replace(path)
            except (ValueError, UnicodeError) as exc:
                event('index_schema_failure', code=code, day=day, error=str(exc))
                return dict(status='query_schema_failed', pages=pages, items=all_items, request=params)
        obj = json.loads(path.read_text(encoding='utf-8'))
        items = obj.get('announcements') or []
        if not isinstance(items, list):
            return dict(status='query_schema_failed', pages=pages, items=all_items)
        all_items.extend(items)
        pages.append(dict(file=str(path.relative_to(OUT)), sha256=audit.sha(path), request=params,
            total_announcement=obj.get('totalAnnouncement'), has_more=bool(obj.get('hasMore'))))
        if not obj.get('hasMore', False):
            return dict(status='query_completed_current_index_only', pages=pages, items=all_items)
        time.sleep(1.3)
    return dict(status='query_page_bound_hit', pages=pages, items=all_items)


def matched_items(items, code, day):
    """Do not accept a parent company, wrong publication day or another issuer."""
    result = []
    for item in items:
        if item.get('secCode') != code[:6]:
            continue
        try:
            local_day = datetime.fromtimestamp(item['announcementTime']/1000, timezone.utc).astimezone(
                timezone(timedelta(hours=8))).strftime('%Y%m%d')
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if local_day == day:
            result.append(item)
    return result


def candidate_items(items, periods):
    """Identify possible financial documents only, not their definitive type/version."""
    years = {period[:4] for period in periods}
    positive = re.compile('业绩预告|业绩快报|年度报告|年年度报告|半年度报告|季度报告|审计报告|招股|财务报表')
    negative = re.compile('内部控制|内控|董事|监事|保荐|律师|摘要|社会责任|可持续|薪酬')
    candidates = []
    for item in items:
        title = re.sub('<[^>]+>', '', item.get('announcementTitle', ''))
        if not positive.search(title) or negative.search(title):
            continue
        named_years = set(re.findall(r'20\d{2}', title))
        if named_years and not (named_years & years):
            continue
        candidates.append(item)
    return sorted(candidates, key=lambda item: ('更正' not in item.get('announcementTitle', ''),
        '修正' not in item.get('announcementTitle', ''), item.get('announcementId', '')))


def safe_url(item, day):
    adjunct = item.get('adjunctUrl', '')
    date = datetime.strptime(day, '%Y%m%d').strftime('%Y-%m-%d')
    if not re.fullmatch(r'finalpage/'+date+r'/[0-9]+\.[Pp][Dd][Ff]', adjunct):
        raise ValueError('Unexpected public document URL/path; preserve metadata only')
    url = 'https://static.cninfo.com.cn/' + adjunct
    assert urlparse(url).hostname == 'static.cninfo.com.cn'
    return url


def download(item, code, day):
    try:
        url = safe_url(item, day)
    except ValueError as exc:
        return dict(status='document_url_unaccepted', error=str(exc))
    identifier = Path(urlparse(url).path).stem
    path = OUT / 'documents' / f'{code}_{day}_{identifier}.pdf'
    metadata = dict(url=url, title=item.get('announcementTitle'), file=str(path.relative_to(OUT)),
        announcement_id=item.get('announcementId'), usable_in_verified_history=False)
    if not path.exists():
        if sum(p.stat().st_size for p in (OUT/'documents').glob('*')) >= TOTAL_PDF_BUDGET:
            return dict(**metadata, status='document_storage_budget_reached')
        if shutil.disk_usage(OUT).free < 6 * 1024 ** 3:
            return dict(**metadata, status='document_free_space_floor_reached')
        temp = path.with_suffix('.partial')
        args = ['--max-time', '55', '--max-filesize', str(MAX_PDF_BYTES), url, '--output', str(temp)]
        if not run_curl(args, 65, dict(code=code, day=day, url=url)):
            return dict(**metadata, status='document_transport_failed')
        try:
            with fitz.open(temp) as pdf:
                if not pdf.is_pdf or pdf.page_count == 0:
                    raise ValueError('Not a nonempty PDF')
            temp.replace(path)
        except Exception as exc:
            event('pdf_validation_failure', code=code, day=day, url=url, error=str(exc))
            return dict(**metadata, status='document_invalid_pdf', error=str(exc))
    try:
        with fitz.open(path) as pdf:
            page_count = pdf.page_count
            # A searchable candidate artifact only; never a field or timing approval.
            text_path = path.with_suffix('.txt')
            if not text_path.exists():
                text_path.write_text('\n'.join(f'\n[PDF PAGE {i+1}]\n'+page.get_text()
                    for i, page in enumerate(pdf)), encoding='utf-8')
        return dict(**metadata, status='downloaded_readable_candidate_only', bytes=path.stat().st_size,
            pages=page_count, sha256=audit.sha(path), text_file=str(text_path.relative_to(OUT)),
            text_sha256=audit.sha(text_path), retrieved_file_time_utc=datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc).isoformat())
    except Exception as exc:
        return dict(**metadata, status='document_extraction_failed', error=str(exc))


def collect(code, day, rows, current_name):
    queries = [query(code, day, code[:6])]
    items = matched_items(queries[0]['items'], code, day)
    candidates = candidate_items(items, [r['end_date'] for r in rows])
    keyword = ALIASES.get(code, current_name)
    if not candidates and keyword and keyword != code[:6]:
        time.sleep(1.3)
        queries.append(query(code, day, keyword))
        items.extend(matched_items(queries[-1]['items'], code, day))
        candidates = candidate_items(items, [r['end_date'] for r in rows])
    unique = {item['adjunctUrl']: item for item in candidates}
    candidates = list(unique.values())
    documents = [download(item, code, day) for item in candidates[:4]]
    if any(d['status'] == 'downloaded_readable_candidate_only' for d in documents):
        state = 'document_candidates_downloaded_only'
    elif candidates:
        state = 'document_candidates_download_failed'
    elif items:
        state = 'issuer_index_matches_no_target_document_identified'
    elif all(q['status'] == 'query_completed_current_index_only' for q in queries):
        state = 'successful_index_queries_no_exact_issuer_day_match'
    else:
        state = 'query_incomplete_or_failed'
    return dict(ts_code=code, ann_date=day, status=state, queries=queries,
        candidate_count=len(candidates), selected_document_limit=4, unselected_candidates=candidates[4:],
        documents=documents, row_keys=[dict(api=r['api'], row_sha256=r['row_sha256'],
            end_date=r['end_date']) for r in rows], usable_in_verified_history=False,
        limitation='Current indexes and downloaded candidates do not prove original release/version or field agreement.')


def summarize(active, outside, groups, results, final=False):
    counts = {}
    for result in results:
        counts[result['status']] = counts.get(result['status'], 0)+1
    status = dict(at=audit.now(), pid=os.getpid(), state='completed_candidate_access_only' if final else 'running',
        active_queue_rows=len(active), excluded_window_rows=len(outside), total_keys=len(groups),
        completed_keys=len(results), status_counts=counts,
        downloaded_documents=sum(d['status']=='downloaded_readable_candidate_only'
            for r in results for d in r.get('documents', [])),
        verified_original_version_rows=0, limitation='Access pass only; manual financial/version/timing audit remains outstanding.')
    audit.write_json(OUT/'status.json', status)
    if final:
        by_key = {(r['ts_code'], r['ann_date']): r for r in results}
        checked = set()
        with (audit.OUT/'evidence/field_checks.csv').open(encoding='utf-8-sig', newline='') as stream:
            checked = {r['row_sha256'] for r in csv.DictReader(stream)}
        with (OUT/'row_access_coverage.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            names = ['api','ts_code','ann_date','end_date','row_sha256','access_status',
                'document_candidate_count','some_numeric_fields_manually_checked','usable_in_verified_history']
            writer = csv.DictWriter(stream, fieldnames=names); writer.writeheader()
            for row in active:
                result = by_key[(row['ts_code'], row['ann_date'])]
                writer.writerow(dict(**{k:row[k] for k in names[:5]}, access_status=result['status'],
                    document_candidate_count=result['candidate_count'],
                    some_numeric_fields_manually_checked=row['row_sha256'] in checked,
                    usable_in_verified_history=False))
    return status


def main():
    audit.initialize(); audit.verify_old()
    for name in ['responses','results','documents','source_snapshot']:
        (OUT/name).mkdir(parents=True, exist_ok=True)
    active, outside, groups = load_queue()
    protocol = dict(queue_sha256=audit.sha(QUEUE), source_sha256=audit.sha(Path(__file__)),
        design_sha256=audit.sha(audit.SPEC), window=list(WINDOW), active_rows=len(active),
        excluded_rows=len(outside), keys=len(groups), interval_seconds=1.3,
        max_index_pages=5, max_documents_per_key=4, max_pdf_bytes=MAX_PDF_BYTES,
        total_pdf_budget=TOTAL_PDF_BUDGET, aliases=ALIASES)
    target = OUT/'protocol.json'
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8')) != protocol:
            raise RuntimeError('Frozen input/source mismatch; use a separate revision')
    else:
        audit.write_json(target, protocol)
        shutil.copy2(QUEUE, OUT/'source_snapshot/original_document_check_queue.csv')
        shutil.copy2(__file__, OUT/'source_snapshot'/Path(__file__).name)
    lock = OUT/'collection.lock'
    fd = os.open(lock, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    try:
        with (audit.ROOT/'data/audit/universe.csv').open(encoding='utf-8-sig', newline='') as stream:
            names = {r['ts_code']:re.sub(r'^(\*?ST)', '', r['name']).removesuffix('退') for r in csv.DictReader(stream)}
        # Fixed samples first, then all remaining groups in deterministic order.
        with (audit.OUT/'fixed_original_samples.csv').open(encoding='utf-8-sig', newline='') as stream:
            fixed = {(r['ts_code'],r['ann_date']) for r in csv.DictReader(stream)}
        results = []
        ordered = sorted(groups, key=lambda key: (key not in fixed, *key))
        for code, day in ordered:
            path = OUT/'results'/f'{code}_{day}.json'
            if path.exists():
                result = json.loads(path.read_text(encoding='utf-8'))
            else:
                try:
                    result = collect(code, day, groups[(code,day)], names.get(code,''))
                except Exception as exc:
                    event('key_failure', code=code, day=day, error=str(exc))
                    result = dict(ts_code=code,ann_date=day,status='key_failed',error=str(exc),
                        candidate_count=0,documents=[],usable_in_verified_history=False)
                audit.write_json(path, result)
                time.sleep(1.3)
            results.append(result)
            summarize(active,outside,groups,results)
            print(f'{len(results)}/{len(groups)} {code} {day}: {result["status"]}',flush=True)
        if audit.sha(QUEUE) != protocol['queue_sha256']:
            raise RuntimeError('Input queue changed during collection')
        audit.verify_old()
        print(json.dumps(summarize(active,outside,groups,results,True)),flush=True)
    finally:
        lock.unlink()


if __name__ == '__main__':
    main()
