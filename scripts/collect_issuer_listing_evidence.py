"""Round-4 collection for the 67 no-candidate update_flag conflict keys via the
cninfo issuer-listing API (stock=code,orgId) instead of fulltext search.

Why: the round-1/round-3 fulltext searchkey approach found no issuer match for
these pairs even at +/-5 days. The issuer-listing API is authoritative per
issuer and also covers delisted companies (e.g. 002781 奇信退).

Method per (ts_code, ann_date) pair:
1. Resolve orgId via POST /new/information/topSearch/query (cached per code).
2. Query /new/hisAnnouncement/query with stock=code,orgId over
   ann_date +/-5 days (single range request per pair, up to 5 pages).
3. Accept items whose announcementTime local day falls inside the window;
   record each item's index day and deviation from the vendor ann_date.
4. Candidate filter and download rules identical to round 1
   (collect_remaining_financial_evidence.candidate_items / download).

Outputs: output/announcement_financial_audit_20261007/issuer_listing_evidence_20261009/
Evidence only; usable_in_verified_history is never set; frozen artifacts untouched.
"""
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import collect_remaining_financial_evidence as r1

AUDIT_OUT = audit.OUT
OUT = AUDIT_OUT / 'issuer_listing_evidence_20261009'
KEYS_CSV = AUDIT_OUT / 'case_review_20261009' / 'update_flag_conflict_all204.csv'
ENDPOINT = r1.ENDPOINT
TOPSEARCH = 'https://www.cninfo.com.cn/new/information/topSearch/query'
WINDOW_DAYS = 5
MAX_DOCS_PER_PAIR = 4

r1.OUT = OUT  # redirect downloads/events/response cache of round-1 helpers


def load_groups():
    ck = pd.read_csv(KEYS_CSV, dtype=str, encoding='utf-8-sig')
    u = ck[ck['final_status'] == 'no_candidate_document_unverified']
    groups = {}
    for (code, day), grp in u.groupby(['ts_code', 'ann_date']):
        groups[(code, day)] = [dict(end_date=e) for e in grp['end_date']]
    return groups


def resolve_org(code):
    """POST topSearch; cache the raw response; return orgId for exact code."""
    path = OUT / 'responses' / f'org_{code}.json'
    if not path.exists():
        temp = path.with_suffix('.partial')
        args = ['--max-time', '40', TOPSEARCH, '--header', 'User-Agent: Mozilla/5.0',
                '--header', 'Referer: https://www.cninfo.com.cn/',
                '--output', str(temp),
                '--data-urlencode', f'keyWord={code[:6]}', '--data-urlencode', 'maxNum=10']
        if not r1.run_curl(args, 50, dict(code=code, api='topSearch')):
            return None, 'org_query_failed'
        try:
            obj = json.loads(temp.read_text(encoding='utf-8'))
            if not isinstance(obj, list):
                raise ValueError('topSearch schema not a list')
            temp.replace(path)
        except (ValueError, UnicodeError) as exc:
            r1.event('org_schema_failure', code=code, error=str(exc))
            return None, 'org_schema_failed'
        time.sleep(1.3)
    obj = json.loads(path.read_text(encoding='utf-8'))
    for item in obj:
        if item.get('code') == code[:6] and item.get('orgId'):
            return item['orgId'], 'org_resolved'
    return None, 'org_not_found_for_code'


def query_issuer_window(code, org_id, day):
    base = datetime.strptime(day, '%Y%m%d')
    start = (base - timedelta(days=WINDOW_DAYS)).strftime('%Y-%m-%d')
    end = (base + timedelta(days=WINDOW_DAYS)).strftime('%Y-%m-%d')
    all_items, pages = [], []
    for page in range(1, 6):
        path = OUT / 'responses' / f'{code}_{day}_issuer_{page}.json'
        if not path.exists():
            args = ['--max-time', '40', ENDPOINT, '--header', 'User-Agent: Mozilla/5.0',
                    '--header', 'Referer: https://www.cninfo.com.cn/', '--output',
                    str(path.with_suffix('.partial'))]
            params = dict(pageNum=str(page), pageSize='30', tabName='fulltext',
                column='szse' if code.endswith('.SZ') else 'sse', isHLtitle='false',
                stock=f'{code[:6]},{org_id}', seDate=f'{start}~{end}')
            for name, value in params.items():
                args += ['--data-urlencode', f'{name}={value}']
            temp = path.with_suffix('.partial')
            if not r1.run_curl(args, 50, dict(code=code, day=day, query=params)):
                return dict(status='query_failed', pages=pages, items=all_items)
            try:
                obj = json.loads(temp.read_text(encoding='utf-8'))
                if not isinstance(obj, dict) or 'announcements' not in obj:
                    raise ValueError('missing announcements schema')
                temp.replace(path)
            except (ValueError, UnicodeError) as exc:
                r1.event('index_schema_failure', code=code, day=day, error=str(exc))
                return dict(status='query_schema_failed', pages=pages, items=all_items)
            time.sleep(1.3)
        obj = json.loads(path.read_text(encoding='utf-8'))
        items = obj.get('announcements') or []
        all_items.extend(items)
        pages.append(dict(file=str(path.relative_to(OUT)), sha256=audit.sha(path),
            total_announcement=obj.get('totalAnnouncement'), has_more=bool(obj.get('hasMore'))))
        if not obj.get('hasMore', False):
            break
    return dict(status='query_completed_current_index_only', pages=pages, items=all_items)


def local_day(item):
    try:
        return datetime.fromtimestamp(item['announcementTime'] / 1000, timezone.utc).astimezone(
            timezone(timedelta(hours=8))).strftime('%Y%m%d')
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def collect_pair(code, day, rows):
    org_id, org_status = resolve_org(code)
    if not org_id:
        return dict(ts_code=code, ann_date=day, status=org_status, queries=[],
            candidate_count=0, documents=[], row_keys=rows,
            usable_in_verified_history=False)
    q = query_issuer_window(code, org_id, day)
    base = datetime.strptime(day, '%Y%m%d')
    items = []
    for item in q['items']:
        d = local_day(item)
        if d is None:
            continue
        dev = (datetime.strptime(d, '%Y%m%d') - base).days
        if abs(dev) <= WINDOW_DAYS:
            item['_index_day'] = d
            item['_deviation'] = dev
            items.append(item)
    candidates = r1.candidate_items(items, [r['end_date'] for r in rows])
    unique = {item['adjunctUrl']: item for item in candidates}
    candidates = list(unique.values())
    documents = []
    for item in candidates[:MAX_DOCS_PER_PAIR]:
        doc = r1.download(item, code, item['_index_day'])
        doc['index_day'] = item['_index_day']
        doc['vendor_ann_date'] = day
        doc['ann_date_deviation_days'] = item['_deviation']
        documents.append(doc)
        time.sleep(1.3)
    if any(d['status'] == 'downloaded_readable_candidate_only' for d in documents):
        state = 'document_candidates_downloaded_only'
    elif candidates:
        state = 'document_candidates_download_failed'
    elif items:
        state = 'issuer_index_matches_no_target_document_identified'
    else:
        state = 'issuer_listing_empty_within_window'
    return dict(ts_code=code, ann_date=day, status=state,
        org_id=org_id, org_status=org_status,
        queries=[dict(status=q['status'], pages=len(q['pages']), items=len(q['items']))],
        window_items=len(items), candidate_count=len(candidates),
        selected_document_limit=MAX_DOCS_PER_PAIR,
        unselected_candidates=[dict(title=c.get('announcementTitle'),
                                    url=c.get('adjunctUrl')) for c in candidates[MAX_DOCS_PER_PAIR:]],
        documents=documents, row_keys=rows, usable_in_verified_history=False,
        limitation=('Issuer-listing candidates within +/-5 days of the vendor ann_date; '
                    'they do not prove original release, version chain or field agreement.'))


def main():
    for name in ['responses', 'results', 'documents', 'source_snapshot']:
        (OUT / name).mkdir(parents=True, exist_ok=True)
    groups = load_groups()
    import shutil
    protocol = dict(script=Path(__file__).name, script_sha256=audit.sha(Path(__file__)),
        keys_csv_sha256=audit.sha(KEYS_CSV), window_days=WINDOW_DAYS,
        max_documents_per_pair=MAX_DOCS_PER_PAIR, interval_seconds=1.3,
        max_pdf_bytes=r1.MAX_PDF_BYTES, total_pdf_budget=r1.TOTAL_PDF_BUDGET,
        note=('Round-4 issuer-listing collection for 67 no-candidate conflict keys; '
              'orgId resolved via topSearch; +/-5 day window around vendor ann_date.'))
    target = OUT / 'protocol.json'
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8')) != protocol:
            raise RuntimeError('Protocol mismatch; use a separate revision')
    else:
        audit.write_json(target, protocol)
        shutil.copy2(KEYS_CSV, OUT / 'source_snapshot' / KEYS_CSV.name)
        shutil.copy2(__file__, OUT / 'source_snapshot' / Path(__file__).name)
    pairs = sorted(groups)
    results = []
    for i, (code, day) in enumerate(pairs, 1):
        path = OUT / 'results' / f'{code}_{day}.json'
        if path.exists():
            result = json.loads(path.read_text(encoding='utf-8'))
        else:
            try:
                result = collect_pair(code, day, groups[(code, day)])
            except Exception as exc:
                r1.event('key_failure', code=code, day=day, error=str(exc))
                result = dict(ts_code=code, ann_date=day, status='key_failed',
                    error=str(exc), candidate_count=0, documents=[],
                    row_keys=groups[(code, day)], usable_in_verified_history=False)
            audit.write_json(path, result)
        results.append(result)
        print(f"{i}/{len(pairs)} {code} {day}: {result['status']}", flush=True)
    counts = {}
    for r in results:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    status = dict(at=audit.now(), pid=os.getpid(), state='completed_candidate_access_only',
        attempted_pairs=len(pairs), status_counts=counts,
        downloaded_documents=sum(d['status'] == 'downloaded_readable_candidate_only'
            for r in results for d in r.get('documents', [])),
        verified_original_version_rows=0,
        limitation='Access pass only; manual financial/version/timing audit remains outstanding.')
    audit.write_json(OUT / 'status.json', status)
    print(json.dumps(status['status_counts'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
