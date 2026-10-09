"""Version-chain republication search for the 6 still-unresolved true-difference
update_flag conflict keys.

Correction-keyword searches (correction_evidence_20261009/_r2) found no
financial-report corrections for these keys. Some republished reports keep the
plain title, so this pass queries the cninfo index in ~6-month slices (to avoid
the 300-item page cap) from the vendor ann_date forward 24 months, matching the
plain period report title (e.g. "2019年年度报告", "2020年第三季度报告"),
excluding documents already collected in earlier rounds, then screens both
update_flag API values with the unchanged extraction rules.

Outputs: output/announcement_financial_audit_20261007/version_chain_evidence_20261009/
Evidence only; usable_in_verified_history is never set.
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
from collect_and_screen_corrections_r2 import query_range, issuer_name  # noqa: F401
import collect_and_screen_corrections_r2 as cr2
import collect_remaining_financial_evidence as r1
import screen_profit_dedt_candidates as scr

AUDIT_OUT = audit.OUT
OUT = AUDIT_OUT / 'version_chain_evidence_20261009'
KEYS_CSV = AUDIT_OUT / 'case_review_20261009' / 'update_flag_conflict_all204.csv'
SLICE_DAYS = 180
FORWARD_DAYS = 730
MAX_DOCS_PER_KEY = 8
NEGATIVE = re.compile(r'问询|回复|说明会|审核|函|意见|核查|摘要|正文$|正文（|英文|H股')

cr2.OUT = OUT  # query_range caches responses under OUT
r1.OUT = OUT   # downloads/events under OUT

PERIOD_TITLE = {
    '1231': lambda y: re.compile(rf'{y}年(?:年度|年)报告'),
    '0930': lambda y: re.compile(rf'{y}年第三季度报告'),
    '0630': lambda y: re.compile(rf'{y}年(?:半年度|中期)报告'),
    '0331': lambda y: re.compile(rf'{y}年第一季度报告'),
}

PRIOR_DIRS = ['remaining_evidence_r1', 'remaining_evidence_r2_fixed_r1',
              'update_flag_conflict_evidence_20261009',
              'correction_evidence_20261009', 'correction_evidence_20261009_r2']


def load_keys():
    ck = pd.read_csv(KEYS_CSV, dtype=str, encoding='utf-8-sig')
    u = ck[ck['final_status'] == 'unresolved_true_difference']
    u = u[~((u['ts_code'] == '000676.SZ') & (u['end_date'] == '20201231'))]  # resolved
    assert len(u) == 6, f'expected 6 unresolved keys, got {len(u)}'
    return [dict(ts_code=r['ts_code'], ann_date=r['ann_date'], end_date=r['end_date'],
                 val_flag0=r['val_flag0'], val_flag1=r['val_flag1'])
            for _, r in u.iterrows()]


def prior_urls():
    seen = set()
    for name in PRIOR_DIRS:
        results = AUDIT_OUT / name / 'results'
        if not results.is_dir():
            continue
        for f in results.glob('*.json'):
            try:
                result = json.loads(f.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                continue
            for doc in result.get('documents', []):
                if doc.get('url'):
                    seen.add(doc['url'])
    return seen


def collect_key(key, seen_urls):
    code, day, end = key['ts_code'], key['ann_date'], key['end_date']
    year, mmdd = end[:4], end[4:]
    title_re = PERIOD_TITLE[mmdd](year)
    base = datetime.strptime(day, '%Y%m%d')
    items, queries = [], []
    for offset in range(0, FORWARD_DAYS, SLICE_DAYS):
        s = (base + timedelta(days=offset)).strftime('%Y%m%d')
        e = (base + timedelta(days=min(offset + SLICE_DAYS, FORWARD_DAYS))).strftime('%Y%m%d')
        q = query_range(code, s, e, code[:6])
        queries.append(dict(range=f'{s}-{e}', status=q['status'], pages=len(q['pages']),
                            items=len(q['items'])))
        items.extend(q['items'])
        time.sleep(1.3)
    cands = []
    for item in items:
        if item.get('secCode') != code[:6]:
            continue
        title = re.sub('<[^>]+>', '', item.get('announcementTitle', ''))
        if not title_re.search(title) or NEGATIVE.search(title):
            continue
        adjunct = item.get('adjunctUrl', '')
        url = 'https://static.cninfo.com.cn/' + adjunct
        if url in seen_urls:
            continue
        cands.append(item)
    unique = {item['adjunctUrl']: item for item in cands}
    cands = sorted(unique.values(), key=lambda i: i.get('announcementId', ''))
    documents = []
    for item in cands[:MAX_DOCS_PER_KEY]:
        m = re.search(r'finalpage/(\d{4}-\d{2}-\d{2})/', item.get('adjunctUrl', ''))
        if not m:
            continue
        index_day = m.group(1).replace('-', '')
        doc = r1.download(item, code, index_day)
        doc['index_day'] = index_day
        documents.append(doc)
        time.sleep(1.3)
    state = ('document_candidates_downloaded_only'
             if any(d.get('status') == 'downloaded_readable_candidate_only' for d in documents)
             else 'no_new_version_document')
    return dict(**key, status=state, queries=queries,
        version_candidate_count=len(cands), documents=documents,
        unselected_candidates=[dict(title=c.get('announcementTitle'), url=c.get('adjunctUrl'))
                               for c in cands[MAX_DOCS_PER_KEY:]],
        usable_in_verified_history=False,
        limitation='Plain-title republication candidates only; no version-chain approval.')


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
        for flag in ['0', '1']:
            api_value = float(key[f'val_flag{flag}'])
            status, matched, nearest = 'not_found_in_candidate_text', None, None
            if doc_period and doc_period != key['end_date']:
                status = 'not_compared_period_mismatch'
            elif valued:
                found = None
                for c in valued:
                    for pos, v in enumerate(c['values_cny'], 1):
                        if v is not None and abs(v - api_value) < 0.5:
                            found = (c, pos, v)
                            break
                    if found:
                        break
                best = min(valued, key=lambda c: min(
                    abs(v - api_value) for v in c['values_cny'] if v is not None))
                nearest = min((v for v in best['values_cny'] if v is not None),
                              key=lambda v: abs(v - api_value))
                if found:
                    matched = found[2]
                    status = ('value_matches_republication_document'
                              if found[1] == 1 and found[0]['strong_context']
                              else 'value_matches_needs_manual_confirm')
                else:
                    status = 'value_differs_from_republication_document'
            elif cands:
                status = 'unit_unconfirmed_in_candidate_text'
            rows.append(dict(ts_code=key['ts_code'], ann_date=key['ann_date'],
                end_date=key['end_date'], update_flag=flag, api_value=api_value,
                matched_value=matched, nearest_candidate_value=nearest, status=status,
                document_title=doc.get('title'), index_day=doc.get('index_day'),
                pdf_sha256=doc.get('sha256'), source_url=doc.get('url'),
                document_period=doc_period, period_source=period_source,
                usable_in_verified_history=False))
    return rows


def main():
    for name in ['responses', 'documents', 'results', 'source_snapshot']:
        (OUT / name).mkdir(parents=True, exist_ok=True)
    keys = load_keys()
    import shutil
    protocol = dict(script=Path(__file__).name, script_sha256=audit.sha(Path(__file__)),
        keys_csv_sha256=audit.sha(KEYS_CSV), forward_days=FORWARD_DAYS,
        slice_days=SLICE_DAYS, max_docs_per_key=MAX_DOCS_PER_KEY,
        rules='Extraction/comparison rules imported unchanged from screen_profit_dedt_candidates.py',
        note='Plain-title republication search for 6 unresolved keys; evidence only.')
    target = OUT / 'protocol.json'
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8')) != protocol:
            raise RuntimeError('Protocol mismatch; use a separate revision')
    else:
        target.write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')
        shutil.copy2(__file__, OUT / 'source_snapshot' / Path(__file__).name)
    seen = prior_urls()
    screen_rows = []
    for i, key in enumerate(keys, 1):
        path = OUT / 'results' / f"{key['ts_code']}_{key['ann_date']}_{key['end_date']}.json"
        if path.exists():
            result = json.loads(path.read_text(encoding='utf-8'))
        else:
            result = collect_key(key, seen)
            audit.write_json(path, result)
        screen_rows.extend(screen(key, result))
        print(f"{i}/{len(keys)} {key['ts_code']} {key['ann_date']}/{key['end_date']}: "
              f"{result['status']} (candidates={result['version_candidate_count']})", flush=True)
    frame = pd.DataFrame(screen_rows)
    frame.to_csv(OUT / 'republication_screen.csv', index=False, encoding='utf-8-sig')
    summary = dict(keys=len(keys),
        keys_with_new_docs=sum(1 for k in keys if any(
            d.get('status') == 'downloaded_readable_candidate_only'
            for d in json.loads((OUT / 'results' / f"{k['ts_code']}_{k['ann_date']}_{k['end_date']}.json")
                .read_text(encoding='utf-8')).get('documents', []))),
        status_counts=frame.status.value_counts().to_dict() if len(frame) else {},
        usable_in_verified_history_rows=0,
        limitation='Machine screen of republication documents; manual confirmation required.')
    (OUT / 'republication_screen_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
