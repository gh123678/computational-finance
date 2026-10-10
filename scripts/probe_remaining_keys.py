"""Probe remaining unresolved keys: locate income-statement and non-recurring
detail pages in bundle PDFs via text layer, print context lines.

Usage: python scripts/probe_remaining_keys.py <ts_code> <end_date> [max_pages]
"""
import json
import re
import sys
from pathlib import Path

import fitz

BASE = Path(__file__).resolve().parent.parent / 'output' / 'announcement_financial_audit_20261007'


def find_bundle(ts_code, end_date):
    for sub in ('manual_review_20261010',):
        p = BASE / sub / f'{ts_code}_*_{end_date}.json'
        hits = list(BASE.glob(f'{sub}/{ts_code}_*_{end_date}.json'))
        if hits:
            return json.loads(hits[0].read_text(encoding='utf-8'))
    return None


def doc_dirs():
    dirs = []
    for sub in sorted(BASE.glob('remaining_evidence*')):
        d = sub / 'documents'
        if d.is_dir():
            dirs.append(d)
    for sub in sorted(BASE.glob('ocr_adjudication*')):
        d = sub / 'documents'
        if d.is_dir():
            dirs.append(d)
    ev = BASE / 'evidence'
    if ev.is_dir():
        dirs.append(ev)
    return dirs


def find_pdf(name):
    for d in doc_dirs():
        p = d / name
        if p.exists():
            return p
    return None


KW_IS = ['合并利润表', '归属于母公司股东的净利润', '归属于母公司所有者的净利润']
KW_NR = ['非经常性损益明细表', '非经常性损益项目', '补充资料', '扣除非经常性损益']


def probe_pdf(path, max_pages=None, pages_want=None):
    doc = fitz.open(path)
    n = len(doc)
    out = {'n_pages': n, 'is_hits': [], 'nr_hits': []}
    rng = pages_want if pages_want else range(n)
    for i in rng:
        if i >= n:
            continue
        text = doc[i].get_text() or ''
        if not text.strip():
            continue
        for kw in KW_IS:
            if kw in text:
                out['is_hits'].append(i)
                break
        for kw in KW_NR:
            if kw in text:
                out['nr_hits'].append(i)
                break
    doc.close()
    return out


def context_lines(path, page, patterns, ctx=6):
    doc = fitz.open(path)
    if page >= len(doc):
        doc.close()
        return ''
    lines = (doc[page].get_text() or '').split('\n')
    doc.close()
    keep = set()
    for idx, ln in enumerate(lines):
        if any(p in ln for p in patterns):
            for j in range(max(0, idx - ctx), min(len(lines), idx + ctx + 1)):
                keep.add(j)
    return '\n'.join(lines[i] for i in sorted(keep))


def main():
    ts_code, end_date = sys.argv[1], sys.argv[2]
    b = find_bundle(ts_code, end_date)
    if not b:
        print('no bundle')
        return
    print(f"== {ts_code} {end_date} flag0={b['val_flag0']} flag1={b['val_flag1']}")
    for d in b['documents']:
        name = d.get('pdf')
        title = d.get('title')
        p = find_pdf(name) if name else None
        if not p:
            print(f"-- {title} | {name} | PDF NOT FOUND")
            continue
        info = probe_pdf(p)
        print(f"-- {title} | {name} | pages={info['n_pages']} is_hits={info['is_hits'][:10]} nr_hits={info['nr_hits'][:10]}")


if __name__ == '__main__':
    main()
