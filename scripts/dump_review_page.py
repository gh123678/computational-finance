"""Dump full page text from a manual-review bundle for eyeball adjudication.

Usage: python scripts/dump_review_page.py <ts_code> <end_date> [doc_substr] [page]
Without doc_substr/page: list documents and pages in the bundle.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / 'output' / 'announcement_financial_audit_20261007' / 'manual_review_20261010'


def main():
    ts_code, end_date = sys.argv[1], sys.argv[2]
    doc_sub = sys.argv[3] if len(sys.argv) > 3 else None
    page_want = int(sys.argv[4]) if len(sys.argv) > 4 else None
    paths = list(BASE.glob(f'{ts_code}_*_{end_date}.json'))
    if not paths:
        print('no bundle for', ts_code, end_date)
        return
    b = json.loads(paths[0].read_text(encoding='utf-8'))
    print(f"== {b['ts_code']} {b['end_date']} flag0={b['val_flag0']} flag1={b['val_flag1']} "
          f"nearest={b.get('nearest_original_value')} ({b.get('nearest_original_doc')})")
    for d in b['documents']:
        pages = d.get('pages', [])
        print(f"-- doc: {d.get('title')} | round={d.get('round')} | pdf={d.get('pdf')} | pages={len(pages)}")
        if doc_sub and doc_sub not in (d.get('title') or ''):
            continue
        for p in pages:
            if page_want and p.get('page') != page_want:
                continue
            if 'error' in p:
                print(f"   p{p['page']} ERROR {p['error']}")
                continue
            print(f"   ===== p{p['page']} unit_hint={p.get('unit_hint')} chars={p.get('n_chars')}")
            print(p.get('page_text', ''))


if __name__ == '__main__':
    main()
