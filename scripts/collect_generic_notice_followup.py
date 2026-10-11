"""Collect six already indexed notices and retry one recorded original PDF.

Separate evidence folder; previous outputs and all strategy inputs stay untouched.
Reuses the bounded official-PDF collector, and checkpoints after each document.
"""
import json
from pathlib import Path

import announcement_financial_audit as audit
import collect_remaining_financial_evidence as collector

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / 'output/cross_period_review_20261011_r1'
OUT = ROOT / 'output/generic_notice_followup_20261011_r1'


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / 'documents').mkdir(exist_ok=True)
    collector.OUT = OUT
    manifest = OUT / 'previous_sha256.json'
    if not manifest.exists():
        audit.write_json(manifest, {str(p.relative_to(ROOT)): audit.sha(p)
            for p in PREVIOUS.rglob('*') if p.is_file()})
    source = json.loads((PREVIOUS / 'remaining_generic_notice_review.json').read_text(encoding='utf-8'))
    tasks = [(r['ts_code'], r['end_date'], n) for r in source for n in r['notices']]
    tasks.append(('600343.SH', '20191231', dict(title='非经营性资金占用专项说明原版',
        day='20200428', url='finalpage/2020-04-28/1207646993.PDF')))
    cached = list((ROOT / 'output').rglob('*.pdf'))
    records = []
    for code, period, notice in tasks:
        identifier = Path(notice['url']).stem
        saved = OUT / f'{code}_{period}_{identifier}.json'
        if saved.exists():
            records.append(json.loads(saved.read_text(encoding='utf-8')))
            continue
        path = next((p for p in cached if p.stem.endswith(identifier)), None)
        if path:
            document = dict(status='existing_pdf_cache', file=str(path.relative_to(ROOT)),
                sha256=audit.sha(path))
        else:
            document = collector.download(dict(adjunctUrl=notice['url'],
                announcementTitle=notice['title'], announcementId=identifier), code, notice['day'])
        record = dict(ts_code=code, end_date=period, notice=notice, document=document,
            usable_in_verified_history=False)
        audit.write_json(saved, record)
        records.append(record)
        audit.write_json(OUT / 'collection_progress.json', dict(records=records, finished=False))
        print(code, period, identifier, document['status'], flush=True)
    audit.write_json(OUT / 'collection_progress.json', dict(records=records, finished=True))


if __name__ == '__main__':
    main()
