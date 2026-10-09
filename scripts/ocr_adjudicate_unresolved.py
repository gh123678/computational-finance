"""OCR-assisted adjudication for the 36 unresolved update_flag conflict keys.

For each key, pick the period-matching candidate PDFs (annual/quarterly report
preferred), locate pages whose text layer mentions 扣除非经常性损益 (plus the
first 15 pages for scanned documents without a text layer), render at high
resolution, OCR with rapidocr-onnxruntime, and look for the 扣非净利润 figure
near the label. OCR text boxes keep table columns separate, which fixes the
PDF text-layer column-merge problem behind most extraction failures.

Adjudication (evidence-level, never sets usable_in_verified_history):
- flag0_ocr_match / flag1_ocr_match / both_ocr_match: exact match within 0.5
  CNY after unit conversion, only when the other flag does not match;
- ocr_value_found_no_flag_match: a 扣非 value was read but matches neither
  flag (carried to manual review with the value);
- ocr_no_value: nothing readable; stays manual.

Outputs: output/announcement_financial_audit_20261007/ocr_adjudication_20261009/
Resume-safe: per-key JSON results are kept.
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
OUT = AUDIT / 'ocr_adjudication_20261009'
REVIEW = AUDIT / 'case_review_20261009'
UNRESOLVED = {'unresolved_true_difference', 'screened_r1_extraction_not_found',
              'screened_r3_extraction_not_found', 'screened_r4_extraction_not_found'}
LABEL = re.compile(r'扣除非经常性损益')
UNIT_NEAR = re.compile(r'单位[：:]?\s*(?:人民币)?(百万元|千元|万元|元)')
NUM = re.compile(r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+\.\d+')
UNIT_MULT = {'元': 1.0, '千元': 1e3, '万元': 1e4, '百万元': 1e6}
SCAN_PAGES = 15
ZOOM = 2.5
HEADLINE = re.compile(r'归属于上市公司股东的扣除非经常性损益的?净利润')
NOISE = re.compile(r'每股收益|净资产收益率|收益率|%\s*$|孰低|稀释')

_ocr = None


def ocr_engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def load_keys():
    ck = pd.read_csv(REVIEW / 'update_flag_conflict_all204.csv', dtype=str, encoding='utf-8-sig')
    u = ck[ck['final_status'].isin(UNRESOLVED)]
    assert len(u) == 36
    return [dict(ts_code=r['ts_code'], ann_date=r['ann_date'], end_date=r['end_date'],
                 val_flag0=float(r['val_flag0']), val_flag1=float(r['val_flag1']),
                 final_status=r['final_status']) for _, r in u.iterrows()]


def pick_pdfs(key):
    docs = [d for d in candidate_documents(key['ts_code'], key['ann_date'])
            if d['pdf_exists']]
    good, rest, other = [], [], []
    for d in docs:
        period, _ = scr.document_period(d.get('title'))
        title = d.get('title') or ''
        if period == key['end_date'] and ('报告' in title) and '审计' not in title \
                and '专项' not in title and '关联' not in title:
            (rest if ('摘要' in title or '正文' in title) else good).append(d)
        elif period == key['end_date']:
            rest.append(d)
        else:
            # e.g. audit reports without a parseable period, or IPO prospectuses
            # that carry the historical years (002781 keys)
            other.append(d)
    return (good + rest + other)[:3]


def ocr_page(pdf_path, pno, page):
    cache = OUT / 'ocr_cache' / f'{pdf_path.stem}_p{pno + 1}.txt'
    if cache.exists():
        return cache.read_text(encoding='utf-8')
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    result, _ = ocr_engine()(img)
    if not result:
        text = ''
    else:
        lines = sorted(result, key=lambda r: (round(r[0][0][1] / 20), r[0][0][0]))
        text = '\n'.join(r[1] for r in lines)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding='utf-8')
    return text


def find_values(text):
    """Headline 扣非净利润 rows only; skip EPS/ROE narrative sections."""
    found = []
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if not LABEL.search(line):
            continue
        if NOISE.search(line) or '每股' in line or '率' in line:
            continue
        # same line + following lines until a new label-like row appears
        row = [line]
        for j in range(i + 1, min(i + 6, len(lines))):
            nxt = lines[j]
            if re.search(r'[\u4e00-\u9fff]{4,}', nxt) and not NUM.search(nxt):
                break
            row.append(nxt)
        window = '\n'.join(row)
        unit = None
        for m in UNIT_NEAR.finditer('\n'.join(lines[:i + 3])):
            unit = m.group(1)
        headline = bool(HEADLINE.search(line))
        for n in NUM.finditer(window):
            raw = float(n.group().replace(',', ''))
            found.append((raw, unit, window[:200], headline))
    return found


def adjudicate_key(key):
    result = dict(key, pages_ocr=0, observations=[], adjudication='ocr_no_value',
                  ocr_value=None, ocr_doc=None, usable_in_verified_history=False)
    observations = []
    for doc in pick_pdfs(key):
        pdf_path = Path(doc['pdf'])
        try:
            pdf = fitz.open(pdf_path)
        except Exception as exc:
            observations.append(dict(doc=doc['title'], error=str(exc)))
            continue
        with pdf:
            hit_pages = [i for i in range(pdf.page_count)
                         if LABEL.search(pdf[i].get_text() or '')]
            if not hit_pages:
                hit_pages = list(range(min(SCAN_PAGES, pdf.page_count)))
            for pno in hit_pages[:6]:
                text = ocr_page(pdf_path, pno, pdf[pno])
                result['pages_ocr'] += 1
                for value, unit, ctx, headline in find_values(text):
                    units = [(unit, UNIT_MULT[unit])] if unit else list(UNIT_MULT.items())
                    for mult_name, mult in units:
                        cny = value * mult
                        observations.append(dict(doc=doc['title'], page=pno + 1,
                            raw=value, unit_assumed=mult_name, value_cny=cny,
                            headline=headline, context=ctx))
    # decide: headline observations outrank narrative ones
    v0, v1 = key['val_flag0'], key['val_flag1']
    obs_sorted = sorted(observations, key=lambda o: not o.get('headline'))
    m0 = [o for o in obs_sorted if abs(o['value_cny'] - v0) < 0.5]
    m1 = [o for o in obs_sorted if abs(o['value_cny'] - v1) < 0.5]
    if m0 and not m1:
        result.update(adjudication='flag0_ocr_match', ocr_value=v0, ocr_doc=m0[0]['doc'])
    elif m1 and not m0:
        result.update(adjudication='flag1_ocr_match', ocr_value=v1, ocr_doc=m1[0]['doc'])
    elif m0 and m1:
        result.update(adjudication='both_ocr_match', ocr_doc=m0[0]['doc'])
    elif obs_sorted:
        head = [o for o in obs_sorted if o.get('headline')] or obs_sorted
        best = min(head, key=lambda o: min(abs(o['value_cny'] - v0), abs(o['value_cny'] - v1)))
        result.update(adjudication='ocr_value_found_no_flag_match',
                      ocr_value=best['value_cny'], ocr_doc=best['doc'])
    result['observations'] = obs_sorted[:40]
    return result


def main():
    (OUT / 'results').mkdir(parents=True, exist_ok=True)
    keys = load_keys()
    results = []
    for i, key in enumerate(keys, 1):
        path = OUT / 'results' / f"{key['ts_code']}_{key['ann_date']}_{key['end_date']}.json"
        if path.exists():
            result = json.loads(path.read_text(encoding='utf-8'))
        else:
            try:
                result = adjudicate_key(key)
            except Exception as exc:
                result = dict(key, adjudication='ocr_key_failed', error=str(exc),
                              observations=[], usable_in_verified_history=False)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        results.append(result)
        print(f"{i}/36 {key['ts_code']} {key['end_date']}: {result['adjudication']} "
              f"(pages={result.get('pages_ocr')})", flush=True)
    frame = pd.DataFrame([{k: v for k, v in r.items() if k != 'observations'} for r in results])
    frame.to_csv(OUT / 'ocr_adjudication.csv', index=False, encoding='utf-8-sig')
    summary = dict(keys=36,
        adjudication_counts=frame['adjudication'].value_counts().to_dict(),
        pages_ocr_total=int(frame['pages_ocr'].fillna(0).sum()),
        usable_in_verified_history_rows=0,
        limitation='OCR evidence only; matches still require human confirmation of the page image.')
    (OUT / 'ocr_adjudication_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
