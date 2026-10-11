"""Retrieve only already indexed corrections for the 20 flagged keys.

Uses the existing bounded official-PDF collector. Checkpoint every document;
never interprets number matches as field/version approval.
"""
import json
import sys
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_remaining_financial_evidence as collector
import announcement_financial_audit as audit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/financial_review_repair_20261011_r1/corrections'


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / 'documents').mkdir(exist_ok=True)
    collector.OUT = OUT
    rows = json.loads((OUT.parent / 'remaining_23_review.json').read_text(encoding='utf-8'))
    files = list((ROOT / 'output').rglob('*.pdf'))
    records = []
    for r in rows:
        for c in r['corrections']:
            identifier = Path(c['url']).stem
            saved = OUT / f"{r['ts_code']}_{r['end_date']}_{identifier}.json"
            if saved.exists():
                records.append(json.loads(saved.read_text(encoding='utf-8')))
                continue
            cached = next((p for p in files if p.stem.endswith(identifier)), None)
            if cached:
                doc = dict(status='existing_pdf_cache', file=str(cached.relative_to(ROOT)), sha256=audit.sha(cached))
                path = cached
            else:
                item = dict(adjunctUrl=c['url'], announcementTitle=c['title'], announcementId=identifier)
                doc = collector.download(item, r['ts_code'], c['day'])
                path = OUT / doc['file']
                time.sleep(1.3)
            rec = dict(ts_code=r['ts_code'], end_date=r['end_date'], correction=c,
                       document=doc, usable_in_verified_history=False, snippets=[])
            if path.exists() and doc['status'] in ('existing_pdf_cache', 'downloaded_readable_candidate_only'):
                with fitz.open(path) as pdf:
                    for i, page in enumerate(pdf):
                        text = page.get_text()
                        if i < 15 and ('非经常性损益' in text or '更正' in text or '修订' in text):
                            rec['snippets'].append(dict(page=i + 1, text=text))
            audit.write_json(saved, rec)
            records.append(rec)
            audit.write_json(OUT / 'progress.json', dict(records=len(records), documents=records,
                                                       usable_in_verified_history=False))
            print(r['ts_code'], r['end_date'], identifier, doc['status'], flush=True)
    audit.write_json(OUT / 'progress.json', dict(records=len(records), documents=records,
                                               access_pass_finished=True, usable_in_verified_history=False))


if __name__ == '__main__':
    main()
