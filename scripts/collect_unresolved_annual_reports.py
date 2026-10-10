"""Targeted re-collection of annual-report full texts for the 4 unresolved
acceptance keys (2026-10-10, second pass).

Findings from the first pass:
- 002581.SZ 2017/2018 annual reports on the original index days are titled
  '（已取消）' — both originals were cancelled and republished later.
- 002872.SZ / 002602.SZ day fulltext queries return no issuer items; use the
  issuer-listing route (stock=code,orgId) with +/-5 day windows.

This pass:
1. Downloads the cancelled 002581 originals (they ARE the values disclosed at
   flag=0 time).
2. Sweeps issuer windows to find the republished 002581 reports and the
   002872 / 002602 annual reports + audit reports.
Outputs to output/announcement_financial_audit_20261007/manual_review_20261010/.
Never touches frozen artifacts; usable_in_verified_history is never set.
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import collect_remaining_financial_evidence as r1
import collect_issuer_listing_evidence as il

OUT = audit.OUT / 'manual_review_20261010'
r1.OUT = OUT
il.OUT = OUT

CANCELLED = re.compile(r'^(\S*?：)?20\d{2}年年度报告（已取消）$')
ANNUAL = re.compile(r'^(\S*?：)?20\d{2}年年度报告$')
AUDIT = re.compile(r'^(\S*?：)?20\d{2}年年度审计报告$')


def have(item, code, day):
    ident = Path(item['adjunctUrl']).stem
    for d in audit.OUT.glob('*/documents'):
        if (d / f'{code}_{day}_{ident}.pdf').exists():
            return True
    return False


def fetch(item, code):
    day = il.local_day(item)
    title = re.sub('<[^>]+>', '', item.get('announcementTitle', ''))
    if have(item, code, day):
        print(f'   SKIP have: {title}')
        return
    meta = r1.download(item, code, day)
    print(f'   {meta.get("status")}: {title} -> {meta.get("file")}')
    time.sleep(1.3)


def sweep_windows(code, centers, patterns):
    org_id, status = il.resolve_org(code)
    print(f'== {code} orgId={org_id} ({status})')
    if not org_id:
        return
    seen = set()
    for center in centers:
        res = il.query_issuer_window(code, org_id, center)
        for item in res.get('items') or []:
            title = re.sub('<[^>]+>', '', item.get('announcementTitle', ''))
            if item.get('secCode') != code[:6]:
                continue
            if not any(p.match(title) for p in patterns):
                continue
            key = item.get('announcementId')
            if key in seen:
                continue
            seen.add(key)
            fetch(item, code)


def main():
    (OUT / 'documents').mkdir(parents=True, exist_ok=True)
    (OUT / 'responses').mkdir(parents=True, exist_ok=True)

    # 1. Cancelled 002581 originals from the cached day queries.
    for code, day in [('002581.SZ', '20180428'), ('002581.SZ', '20190425')]:
        res = r1.query(code, day, code[:6])
        for item in r1.matched_items(res.get('items') or [], code, day):
            title = re.sub('<[^>]+>', '', item.get('announcementTitle', ''))
            if CANCELLED.match(title):
                fetch(item, code)

    # 2. Republished 002581 reports + 002872/002602 annual/audit reports.
    sweep_windows('002581.SZ',
                  ['20180508', '20180518', '20180528', '20180607', '20180617',
                   '20180627', '20190508', '20190518', '20190528', '20190607',
                   '20190617', '20190627'],
                  [ANNUAL, AUDIT])
    sweep_windows('002872.SZ',
                  ['20190416', '20190426', '20190506', '20190516'],
                  [ANNUAL, AUDIT])
    sweep_windows('002602.SZ',
                  ['20210420', '20210430', '20210510', '20210520'],
                  [ANNUAL, AUDIT])


if __name__ == '__main__':
    main()
