"""Deep-dive OCR for audit-report-only and other unresolved keys.

Targets the 每股收益/净资产收益率 calculation section and the 非经常性损益
明细表 deep in audit reports, plus any page whose text layer mentions 扣非.
For each page, dump rows carrying the 扣非 label with their numeric tokens.

Evidence only: never sets usable_in_verified_history.
Appends results into manual_review_20261010/deep_dive_<key>.json (new files).
"""
import json
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_manual_review_evidence import ocr_page, rows_with_label
from build_acceptance_checklist import candidate_documents

AUDIT = Path(__file__).resolve().parent.parent / 'output' / 'announcement_financial_audit_20261007'
OUT = AUDIT / 'manual_review_20261010'
PAT = re.compile(r'扣除非经常性损益|非经常性损益|加权平均净资产收益率|基本每股收益')
MAX_PAGES_PER_DOC = 14


def main():
    only = sys.argv[1:]
    checklist = (OUT / '..' / 'case_review_20261009' / 'acceptance_checklist.csv').resolve()
    import pandas as pd
    cl = pd.read_csv(checklist, dtype=str, encoding='utf-8-sig')
    for _, key in cl.iterrows():
        tag = f"{key['ts_code']}_{key['ann_date']}_{key['end_date']}"
        if only and tag not in only:
            continue
        docs, seen = [], set()
        for d in candidate_documents(key['ts_code'], key['ann_date']):
            name = Path(d['pdf']).name
            if d['pdf_exists'] and name not in seen:
                seen.add(name)
                docs.append(d)
        bundle = dict(ts_code=key['ts_code'], ann_date=key['ann_date'],
                      end_date=key['end_date'], val_flag0=float(key['val_flag0']),
                      val_flag1=float(key['val_flag1']), documents=[])
        for d in docs:
            pdf_path = Path(d['pdf'])
            try:
                pdf = fitz.open(pdf_path)
            except Exception as exc:
                bundle['documents'].append(dict(title=d['title'], error=str(exc)))
                continue
            entry = dict(title=d['title'], pdf=pdf_path.name, pages=[])
            with pdf:
                hit_pages = [i for i in range(pdf.page_count)
                             if PAT.search(pdf[i].get_text() or '')]
                for pno in hit_pages[:MAX_PAGES_PER_DOC]:
                    try:
                        text = ocr_page(pdf_path, pno, pdf[pno])
                    except Exception as exc:
                        entry['pages'].append(dict(page=pno + 1, error=str(exc)))
                        continue
                    hits = rows_with_label(text)
                    if hits:
                        entry['pages'].append(dict(
                            page=pno + 1,
                            rows=[dict(line=i, text=line, row=row) for i, line, row in hits]))
            bundle['documents'].append(entry)
        (OUT / f'deep_dive_{tag}.json').write_text(
            json.dumps(bundle, ensure_ascii=False, indent=1), encoding='utf-8')
        n_pages = sum(len(e.get('pages', [])) for e in bundle['documents'])
        n_rows = sum(len(p.get('rows', [])) for e in bundle['documents'] for p in e.get('pages', []))
        print(f"{tag}: {len(docs)} docs, {n_pages} hit pages, {n_rows} rows", flush=True)


if __name__ == '__main__':
    main()
