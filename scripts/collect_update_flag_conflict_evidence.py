"""Round-3 candidate collection for the 100 unscreened update_flag conflict keys.

Gap analysis (2026-10-09): 58 (ts_code, ann_date) pairs were never attempted
because the original collector window ended 20201231 (2020 annual reports were
announced in 2021); 40 pairs were attempted but yielded no usable candidate
(exact-day index mismatch or unresolved issuer id in repair rounds); 9 pairs
already have downloaded documents in remaining_evidence_r2_fixed_r1 and are
skipped here (the round-3 screen reads them directly).

Behaviour differences vs round 1, documented honestly:
- No window restriction: 2021 announcement dates are queried.
- If the vendor ann_date has no exact issuer-day match, the cninfo index is
  queried day by day out to +/-5 calendar days. Every accepted item records
  its own index publication day and the deviation from the vendor ann_date.
  These remain candidates only: usable_in_verified_history is never set.

Outputs go to output/announcement_financial_audit_20261007/update_flag_conflict_evidence_20261009/
and never touch frozen artifacts. Resume-safe: existing result files are kept.
"""
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import collect_remaining_financial_evidence as r1

AUDIT_OUT = audit.OUT
OUT = AUDIT_OUT / 'update_flag_conflict_evidence_20261009'
KEYS_CSV = AUDIT_OUT / 'case_review_20261009' / 'update_flag_conflict_out_of_queue.csv'
UNIVERSE = audit.ROOT / 'data' / 'audit' / 'universe.csv'
R2_RESULTS = AUDIT_OUT / 'remaining_evidence_r2_fixed_r1' / 'results'
MAX_DEVIATION_DAYS = 5

r1.OUT = OUT  # redirect downloads, events and responses to the round-3 directory


def vendor_pairs():
    keys = pd.read_csv(KEYS_CSV, dtype=str, encoding='utf-8-sig')
    records = pd.read_csv(AUDIT_OUT / 'fina_indicator_records.csv', dtype=str, encoding='utf-8')
    key_set = set(zip(keys['ts_code'], keys['ann_date'], keys['end_date']))
    mask = [(t, a, e) in key_set for t, a, e in
            zip(records['ts_code'], records['ann_date'], records['end_date'])]
    rows = records[mask]
    groups = {}
    for (code, day), grp in rows.groupby(['ts_code', 'ann_date']):
        groups[(code, day)] = [dict(api=r['api'], row_sha256=r['row_sha256'],
                                    end_date=r['end_date']) for _, r in grp.iterrows()]
    return groups


def r2_already_documented(groups):
    skip = set()
    for code, day in groups:
        path = R2_RESULTS / f'{code}_{day}.json'
        if not path.exists():
            continue
        result = json.loads(path.read_text(encoding='utf-8'))
        if any(d.get('status') == 'downloaded_readable_candidate_only'
               for d in result.get('documents', [])):
            skip.add((code, day))
    return skip


def collect_pair(code, vendor_day, rows, current_name):
    """Query the vendor day first, then widen day by day out to +/-5 days."""
    queries, items = [], []
    deviations = [0]
    for step in range(1, MAX_DEVIATION_DAYS + 1):
        deviations += [-step, step]
    base = datetime.strptime(vendor_day, '%Y%m%d')
    for dev in deviations:
        qday = (base + timedelta(days=dev)).strftime('%Y%m%d')
        queries.append(dict(day=qday, deviation_days=dev,
                            **{k: v for k, v in r1.query(code, qday, code[:6]).items()}))
        new_items = r1.matched_items(queries[-1]['items'], code, qday)
        for item in new_items:
            item['_index_day'] = qday
        items.extend(new_items)
        if items:
            break
        keyword = r1.ALIASES.get(code, current_name)
        if dev == 0 and keyword and keyword != code[:6]:
            time.sleep(1.3)
            alias_query = r1.query(code, qday, keyword)
            queries.append(dict(day=qday, deviation_days=dev, keyword=keyword, **alias_query))
            alias_items = r1.matched_items(alias_query['items'], code, qday)
            for item in alias_items:
                item['_index_day'] = qday
            items.extend(alias_items)
        if items:
            break
        time.sleep(1.3)
    candidates = r1.candidate_items(items, [r['end_date'] for r in rows])
    unique = {item['adjunctUrl']: item for item in candidates}
    candidates = list(unique.values())
    documents = []
    for item in candidates[:4]:
        doc = r1.download(item, code, item['_index_day'])
        doc['index_day'] = item['_index_day']
        doc['vendor_ann_date'] = vendor_day
        doc['ann_date_deviation_days'] = int(
            (datetime.strptime(item['_index_day'], '%Y%m%d') - base).days)
        documents.append(doc)
    if any(d['status'] == 'downloaded_readable_candidate_only' for d in documents):
        state = 'document_candidates_downloaded_only'
    elif candidates:
        state = 'document_candidates_download_failed'
    elif items:
        state = 'issuer_index_matches_no_target_document_identified'
    else:
        state = 'successful_index_queries_no_issuer_match_within_window'
    return dict(ts_code=code, ann_date=vendor_day, status=state, queries=queries,
        candidate_count=len(candidates), selected_document_limit=4,
        unselected_candidates=candidates[4:], documents=documents,
        row_keys=rows, usable_in_verified_history=False,
        limitation=('Candidates collected with up to +/-5 day index widening around the '
                    'vendor ann_date; they do not prove original release, version chain '
                    'or field agreement.'))


def main():
    for name in ['responses', 'results', 'documents', 'source_snapshot']:
        (OUT / name).mkdir(parents=True, exist_ok=True)
    groups = vendor_pairs()
    skip = r2_already_documented(groups)
    todo = sorted(set(groups) - skip)
    protocol = dict(keys_csv_sha256=audit.sha(KEYS_CSV),
        source_sha256=audit.sha(Path(__file__)), total_pairs=len(groups),
        skipped_r2_documented_pairs=len(skip), attempted_pairs=len(todo),
        max_deviation_days=MAX_DEVIATION_DAYS, interval_seconds=1.3,
        max_documents_per_pair=4, max_pdf_bytes=r1.MAX_PDF_BYTES,
        total_pdf_budget=r1.TOTAL_PDF_BUDGET, aliases=r1.ALIASES,
        note=('Round-3 gap closure for update_flag conflict keys. 2021 ann_dates '
              'included; +/-5 day index widening recorded per document.'))
    target = OUT / 'protocol.json'
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8')) != protocol:
            raise RuntimeError('Protocol mismatch; use a separate revision')
    else:
        audit.write_json(target, protocol)
        import shutil
        shutil.copy2(KEYS_CSV, OUT / 'source_snapshot' / KEYS_CSV.name)
        shutil.copy2(__file__, OUT / 'source_snapshot' / Path(__file__).name)
    with UNIVERSE.open(encoding='utf-8-sig', newline='') as stream:
        names = {r['ts_code']: re.sub(r'^(\*?ST)', '', r['name']).removesuffix('退')
                 for r in csv.DictReader(stream)}
    results = []
    for i, (code, day) in enumerate(todo, 1):
        path = OUT / 'results' / f'{code}_{day}.json'
        if path.exists():
            result = json.loads(path.read_text(encoding='utf-8'))
        else:
            try:
                result = collect_pair(code, day, groups[(code, day)], names.get(code, ''))
            except Exception as exc:
                r1.event('key_failure', code=code, day=day, error=str(exc))
                result = dict(ts_code=code, ann_date=day, status='key_failed',
                    error=str(exc), candidate_count=0, documents=[],
                    row_keys=groups[(code, day)], usable_in_verified_history=False)
            audit.write_json(path, result)
            time.sleep(1.3)
        results.append(result)
        print(f"{i}/{len(todo)} {code} {day}: {result['status']}", flush=True)
    counts = {}
    for r in results:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    status = dict(at=audit.now(), pid=os.getpid(),
        state='completed_candidate_access_only', attempted_pairs=len(todo),
        status_counts=counts,
        downloaded_documents=sum(d['status'] == 'downloaded_readable_candidate_only'
            for r in results for d in r.get('documents', [])),
        skipped_r2_documented_pairs=sorted(list(skip)),
        verified_original_version_rows=0,
        limitation='Access pass only; manual financial/version/timing audit remains outstanding.')
    audit.write_json(OUT / 'status.json', status)
    print(json.dumps(status['status_counts'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
