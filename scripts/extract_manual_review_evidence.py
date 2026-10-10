"""Targeted evidence extraction for the 32-key manual acceptance review.

For each unresolved acceptance-checklist key, locate the summary-accounting-data
pages of each candidate PDF (text-layer hints: 主要会计数据 / 扣非+营业收入;
fallbacks: any 扣非 page, then the front matter), OCR them into the shared cache,
and dump the rows that carry the 扣除非经常性损益 label together with their
numeric tokens, so a human can read the current/prior-period columns directly.

Evidence only: never sets usable_in_verified_history; frozen artifacts untouched.
Outputs: output/announcement_financial_audit_20261007/manual_review_20261010/
"""
import json
import re
import sys
from pathlib import Path

import fitz
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import screen_profit_dedt_candidates as scr
from build_acceptance_checklist import candidate_documents

AUDIT = audit.OUT
OCR_CACHE = AUDIT / 'ocr_adjudication_20261009' / 'ocr_cache'
REVIEW = AUDIT / 'case_review_20261009'
OUT = AUDIT / 'manual_review_20261010'

LABEL = re.compile(r'扣除非经常性损益|扣除非经\s*$|扣除非\s*$')
SUMMARY = re.compile(r'主要会计数据|主要财务指标|会计数据和财务指标摘要')
NUM = re.compile(r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+\.\d+')
ZOOM = 2.5
MAX_SUMMARY_PAGES = 8
MAX_FALLBACK_LABEL_PAGES = 8
MAX_FRONT_PAGES = 10

_ocr = None


def ocr_engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def ocr_page(pdf_path, pno, page):
    cache = OCR_CACHE / f'{pdf_path.stem}_p{pno + 1}.txt'
    if cache.exists():
        return cache.read_text(encoding='utf-8')
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    result, _ = ocr_engine()(img)
    text = '' if not result else '\n'.join(
        r[1] for r in sorted(result, key=lambda r: (round(r[0][0][1] / 20), r[0][0][0])))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding='utf-8')
    return text


def pick_pages(pdf):
    texts = [pdf[i].get_text() or '' for i in range(pdf.page_count)]
    summary = [i for i, t in enumerate(texts) if SUMMARY.search(t)]
    if summary:
        return summary[:MAX_SUMMARY_PAGES]
    label = [i for i, t in enumerate(texts) if LABEL.search(t)]
    if label:
        return label[:MAX_FALLBACK_LABEL_PAGES]
    return list(range(min(MAX_FRONT_PAGES, pdf.page_count)))


def rows_with_label(text):
    """Return (line_index, line, joined_row) for each 扣非-bearing line."""
    lines = text.split('\n')
    out = []
    for i, line in enumerate(lines):
        if not LABEL.search(line):
            continue
        row = [line]
        for j in range(i + 1, min(i + 8, len(lines))):
            nxt = lines[j]
            # stop only at a clear new row label: >=4 CJK chars, no number,
            # and not the tail of a wrapped label line (e.g. 常性损益的净利润（元）)
            if re.search(r'[\u4e00-\u9fff]{4,}', nxt) and not NUM.search(nxt):
                if '损益' in nxt and len(nxt) <= 20:
                    row.append(nxt)
                    continue
                break
            row.append(nxt)
        out.append((i, line, ' | '.join(row)))
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    checklist = pd.read_csv(REVIEW / 'acceptance_checklist.csv', dtype=str, encoding='utf-8-sig')
    for _, key in checklist.iterrows():
        ts_code, ann_date, end_date = key['ts_code'], key['ann_date'], key['end_date']
        if only and f'{ts_code}_{ann_date}_{end_date}' not in only:
            continue
        val0, val1 = float(key['val_flag0']), float(key['val_flag1'])
        docs, seen = [], set()
        for d in candidate_documents(ts_code, ann_date):
            name = Path(d['pdf']).name
            if d['pdf_exists'] and name not in seen:
                seen.add(name)
                docs.append(d)
        bundle = dict(ts_code=ts_code, ann_date=ann_date, end_date=end_date,
                      val_flag0=val0, val_flag1=val1,
                      nearest_original_value=key.get('nearest_original_value'),
                      nearest_original_doc=key.get('nearest_original_doc'),
                      final_status=key['final_status'], documents=[])
        for d in docs:
            pdf_path = Path(d['pdf'])
            try:
                pdf = fitz.open(pdf_path)
            except Exception as exc:
                bundle['documents'].append(dict(title=d['title'], error=str(exc)))
                continue
            entry = dict(title=d['title'], round=d['round'], pdf=pdf_path.name, pages=[])
            with pdf:
                for pno in pick_pages(pdf):
                    try:
                        text = ocr_page(pdf_path, pno, pdf[pno])
                    except Exception as exc:
                        entry['pages'].append(dict(page=pno + 1, error=str(exc)))
                        continue
                    hits = rows_with_label(text)
                    unit_hint = None
                    m = re.search(r'单位[：:]?\s*(?:人民币)?(百万元|千元|万元|元)', text)
                    if m:
                        unit_hint = m.group(1)
                    entry['pages'].append(dict(
                        page=pno + 1, unit_hint=unit_hint, n_chars=len(text),
                        rows=[dict(line=i, text=line, row=row) for i, line, row in hits],
                        page_text=text[:4000]))
            bundle['documents'].append(entry)
        path = OUT / f'{ts_code}_{ann_date}_{end_date}.json'
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding='utf-8')
        n_pages = sum(len(e.get('pages', [])) for e in bundle['documents'])
        n_rows = sum(len(p.get('rows', [])) for e in bundle['documents'] for p in e.get('pages', []))
        print(f"{ts_code} {end_date}: {len(docs)} docs, {n_pages} pages, {n_rows} labelled rows",
              flush=True)


if __name__ == '__main__':
    main()
