"""Round 2 (relaxed): correction-version collection + screening for the 6 still
unresolved true-difference update_flag conflict keys (000676.SZ was resolved in
round 1 by the updated 2020 annual report).

Relaxed vs round 1: title must contain 更正/修订/更新/补充/取消 but need not
contain 报告 (catches 前期会计差错更正的公告 etc.); year filter applies only
when a year is named in the title; company-name keyword fallback added.

Outputs: output/announcement_financial_audit_20261007/correction_evidence_20261009_r2/
Evidence only; usable_in_verified_history is never set; frozen artifacts untouched.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import collect_remaining_financial_evidence as r1
import screen_profit_dedt_candidates as scr

AUDIT_OUT = audit.OUT
OUT = AUDIT_OUT / 'correction_evidence_20261009_r2'
KEYS_CSV = AUDIT_OUT / 'case_review_20261009' / 'update_flag_conflict_all204.csv'
ENDPOINT = r1.ENDPOINT
FORWARD_DAYS = 548  # ~18 months
MAX_DOCS_PER_KEY = 8
CORRECTION = re.compile(r'更正|修订|更新|补充|取消')

r1.OUT = OUT  # redirect downloads/events/response cache of the round-1 helpers


def load_keys():
    ck = pd.read_csv(KEYS_CSV, dtype=str, encoding='utf-8-sig')
    u = ck[ck['final_status'] == 'unresolved_true_difference']
    # 000676.SZ 20201231 was resolved in round 1 (updated 2020 annual report
    # published 2022-04-28 matches the flag=0 value exactly).
    u = u[~((u['ts_code'] == '000676.SZ') & (u['end_date'] == '20201231'))]
    assert len(u) == 6, f'expected 6 unresolved keys, got {len(u)}'
    return [dict(ts_code=r['ts_code'], ann_date=r['ann_date'], end_date=r['end_date'],
                 val_flag0=r['val_flag0'], val_flag1=r['val_flag1'])
            for _, r in u.iterrows()]


def issuer_name(code):
    import csv
    universe = audit.ROOT / 'data' / 'audit' / 'universe.csv'
    with universe.open(encoding='utf-8-sig', newline='') as stream:
        for r in csv.DictReader(stream):
            if r['ts_code'] == code:
                return re.sub(r'^(\*?ST)', '', r['name']).removesuffix('退')
    return ''


def query_range(code, start_day, end_day, keyword):
    import hashlib
    key = hashlib.sha256(keyword.encode('utf-8')).hexdigest()[:12]
    all_items, pages = [], []
    for page in range(1, 11):
        path = OUT / 'responses' / f'{code}_{start_day}_{end_day}_{key}_{page}.json'
        if not path.exists():
            params = dict(pageNum=str(page), pageSize='30', tabName='fulltext',
                column='szse' if code.endswith('.SZ') else 'sse', isHLtitle='false',
                searchkey=keyword,
                seDate=f'{datetime.strptime(start_day, "%Y%m%d"):%Y-%m-%d}~'
                       f'{datetime.strptime(end_day, "%Y%m%d"):%Y-%m-%d}')
            temp = path.with_suffix('.partial')
            args = ['--max-time', '40', ENDPOINT, '--header', 'User-Agent: Mozilla/5.0',
                    '--header', 'Referer: https://www.cninfo.com.cn/', '--output', str(temp)]
            for name, value in params.items():
                args += ['--data-urlencode', f'{name}={value}']
            if not r1.run_curl(args, 50, dict(code=code, range=f'{start_day}-{end_day}', query=params)):
                return dict(status='query_failed', pages=pages, items=all_items)
            try:
                obj = json.loads(temp.read_text(encoding='utf-8'))
                if not isinstance(obj, dict) or 'announcements' not in obj:
                    raise ValueError('missing announcements schema')
                temp.replace(path)
            except (ValueError, UnicodeError) as exc:
                r1.event('index_schema_failure', code=code, error=str(exc))
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


def correction_candidates(items, code, year):
    out = []
    for item in items:
        if item.get('secCode') != code[:6]:
            continue
        title = re.sub('<[^>]+>', '', item.get('announcementTitle', ''))
        if not CORRECTION.search(title):
            continue
        named = set(re.findall(r'20\d{2}', title))
        if named and year not in named:
            continue
        out.append(item)
    return out


def collect_key(key):
    code, day, end = key['ts_code'], key['ann_date'], key['end_date']
    start = day
    stop = (datetime.strptime(day, '%Y%m%d') + timedelta(days=FORWARD_DAYS)).strftime('%Y%m%d')
    q = query_range(code, start, stop, code[:6])
    cands = correction_candidates(q['items'], code, end[:4])
    queries = [dict(keyword=code[:6], status=q['status'], pages=len(q['pages']))]
    if not cands:
        name = issuer_name(code)
        if name:
            time.sleep(1.3)
            q2 = query_range(code, start, stop, name)
            queries.append(dict(keyword=name, status=q2['status'], pages=len(q2['pages'])))
            cands = correction_candidates(q2['items'], code, end[:4])
    unique = {item['adjunctUrl']: item for item in cands}
    cands = sorted(unique.values(), key=lambda i: i.get('announcementId', ''))
    documents = []
    for item in cands[:MAX_DOCS_PER_KEY]:
        m = re.search(r'finalpage/(\d{4}-\d{2}-\d{2})/', item.get('adjunctUrl', ''))
        if not m:
            documents.append(dict(status='document_url_unaccepted',
                                  title=item.get('announcementTitle')))
            continue
        index_day = m.group(1).replace('-', '')
        doc = r1.download(item, code, index_day)
        doc['index_day'] = index_day
        documents.append(doc)
        time.sleep(1.3)
    state = ('document_candidates_downloaded_only'
             if any(d.get('status') == 'downloaded_readable_candidate_only' for d in documents)
             else 'no_correction_document_downloaded')
    return dict(**key, status=state, queries=queries,
        correction_candidate_count=len(cands), documents=documents,
        unselected_candidates=cands[MAX_DOCS_PER_KEY:],
        usable_in_verified_history=False,
        limitation='Correction-version candidates only; no field or version-chain approval.')


def screen(key, result):
    rows = []
    for doc in result.get('documents', []):
        if doc.get('status') != 'downloaded_readable_candidate_only':
            continue
        text_path = OUT / doc['text_file']
        if not text_path.is_file():
            continue
        doc_period, period_source = scr.document_period(doc.get('title'))
        text = text_path.read_text(encoding='utf-8', errors='replace')
        cands = scr.extract_candidates(text)
        valued = [c for c in cands if any(v is not None for v in c['values_cny'])]
        period_ok = (not doc_period) or doc_period == key['end_date']
        for flag in ['0', '1']:
            api_value = float(key[f'val_flag{flag}'])
            status, matched = 'not_compared_period_mismatch', None
            if period_ok:
                found = None
                for c in valued:
                    for pos, v in enumerate(c['values_cny'], 1):
                        if v is not None and abs(v - api_value) < 0.5:
                            found = (c, pos, v)
                            break
                    if found:
                        break
                if found:
                    matched = found[2]
                    status = ('value_matches_correction_document'
                              if found[1] == 1 and found[0]['strong_context']
                              else 'value_matches_needs_manual_confirm')
                elif valued:
                    status = 'value_differs_from_correction_document'
                elif cands:
                    status = 'unit_unconfirmed_in_candidate_text'
                else:
                    status = 'not_found_in_candidate_text'
            nearest = None
            if valued:
                best = min(valued, key=lambda c: min(
                    abs(v - api_value) for v in c['values_cny'] if v is not None))
                nearest = min((v for v in best['values_cny'] if v is not None),
                              key=lambda v: abs(v - api_value))
            rows.append(dict(ts_code=key['ts_code'], ann_date=key['ann_date'],
                end_date=key['end_date'], update_flag=flag, api_value=api_value,
                matched_value=matched, nearest_candidate_value=nearest,
                status=status, document_title=doc.get('title'), index_day=doc.get('index_day'),
                pdf_sha256=doc.get('sha256'), source_url=doc.get('url'),
                document_period=doc_period, period_source=period_source,
                usable_in_verified_history=False))
    return rows


def main():
    for name in ['responses', 'documents', 'results', 'source_snapshot']:
        (OUT / name).mkdir(parents=True, exist_ok=True)
    keys = load_keys()
    import shutil
    protocol_target = OUT / 'protocol.json'
    protocol = dict(script=Path(__file__).name, script_sha256=audit.sha(Path(__file__)),
        keys_csv_sha256=audit.sha(KEYS_CSV), forward_days=FORWARD_DAYS,
        max_docs_per_key=MAX_DOCS_PER_KEY,
        rules='Extraction/comparison rules imported unchanged from screen_profit_dedt_candidates.py',
        note='Correction-version search for 7 unresolved true-difference keys; evidence only.')
    if protocol_target.exists():
        if json.loads(protocol_target.read_text(encoding='utf-8')) != protocol:
            raise RuntimeError('Protocol mismatch; use a separate revision')
    else:
        protocol_target.write_text(json.dumps(protocol, ensure_ascii=False, indent=2),
                                   encoding='utf-8')
        shutil.copy2(__file__, OUT / 'source_snapshot' / Path(__file__).name)
    screen_rows = []
    for i, key in enumerate(keys, 1):
        path = OUT / 'results' / f"{key['ts_code']}_{key['ann_date']}_{key['end_date']}.json"
        if path.exists():
            result = json.loads(path.read_text(encoding='utf-8'))
        else:
            result = collect_key(key)
            audit.write_json(path, result)
        screen_rows.extend(screen(key, result))
        print(f"{i}/{len(keys)} {key['ts_code']} {key['ann_date']}/{key['end_date']}: {result['status']} "
              f"(candidates={result['correction_candidate_count']})", flush=True)
    frame = pd.DataFrame(screen_rows)
    frame.to_csv(OUT / 'correction_screen.csv', index=False, encoding='utf-8-sig')
    summary = dict(keys=len(keys),
        keys_with_correction_docs=int(sum(1 for k in keys
            if any(d.get('status') == 'downloaded_readable_candidate_only'
                   for d in json.loads((OUT / 'results' / f"{k['ts_code']}_{k['ann_date']}_{k['end_date']}.json")
                       .read_text(encoding='utf-8')).get('documents', [])))),
        status_counts=frame.status.value_counts().to_dict() if len(frame) else {},
        usable_in_verified_history_rows=0,
        limitation='Machine screen of correction documents; manual confirmation required.')
    (OUT / 'correction_screen_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
