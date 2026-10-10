# -*- coding: utf-8 -*-
"""清单外修订键逐键核验（签报 §4.2 / 工作清单配套，首轮 A 批试点）。

每键流程：orgId 解析 → 发行人列表 ±5 天检索 → 候选过滤 → 下载候选 PDF
（沿用 r1/r4 采集助手与缓存）→ 全文检索 flag0/flag1 数值（元/万元两种格式）
→ 判定 flag0_found / flag1_found / both / neither，逐键 JSON 留档。

纪律：usable_in_verified_history 永不置位；不改冻结 CSV；产物只进本目录。

用法：python scripts/verify_off_checklist_key.py 000547.SZ 20201231 [更多 键...]
不带参数时处理 A 批中尚未核验的前 2 键。
"""
import csv
import json
import sys
import time
from pathlib import Path

import fitz  # noqa: F401  (r1 依赖，保持环境一致)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import collect_remaining_financial_evidence as r1
import collect_issuer_listing_evidence as r4

WORKLIST = audit.OUT / '..' / 'off_checklist_revision_worklist_20261010' / 'worklist.csv'
WORKLIST = Path(__file__).resolve().parent.parent / 'output' / 'off_checklist_revision_worklist_20261010' / 'worklist.csv'
OUT = WORKLIST.parent / 'verification_round'
RESULTS = OUT / 'results'
DOCS = OUT / 'documents'

MAX_DOCS = 4


def fmt_variants(value):
    v = float(value)
    outs = set()
    for x in (v,):
        outs.add(f"{x:,.2f}")
        outs.add(f"{x:.2f}")
    w = v / 10000.0
    outs.add(f"{w:,.2f}")
    outs.add(f"{w:.2f}")
    # 负号兼容（减号/全角）
    extra = set()
    for s in outs:
        extra.add(s.replace('-', '−'))
        extra.add(s.replace('-', '–'))
    return outs | extra


def search_pdf(path, targets):
    """返回 {target_label: [(page, snippet), ...]}"""
    hits = {k: [] for k in targets}
    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001
        return hits, f'open_failed: {exc}'
    for pno in range(doc.page_count):
        text = doc.load_page(pno).get_text() or ''
        compact = text.replace(',', '').replace(' ', '').replace('\u3000', '')
        for label, variants in targets.items():
            for s in variants:
                key = s.replace(',', '').replace(' ', '')
                if key and key in compact:
                    i = compact.index(key)
                    hits[label].append((pno + 1, compact[max(0, i - 30):i + len(key) + 30]))
                    break
    doc.close()
    return hits, 'ok'


def verify_one(code, end_date):
    wl = { (r['ts_code'], r['end_date']): r for r in
           csv.DictReader(WORKLIST.open(encoding='utf-8-sig')) }
    row = wl.get((code, end_date))
    if row is None:
        raise SystemExit(f'{code} {end_date} not in worklist')
    day = row['ann_date']
    org_id, org_status = r4.resolve_org(code)
    rec = dict(ts_code=code, end_date=end_date, ann_date=day,
               val_flag0=row['val_flag0'], val_flag1=row['val_flag1'],
               batch=row['batch'], org_id=org_id, org_status=org_status,
               usable_in_verified_history=False, documents=[], verdict=None,
               note='证据仅证明候选文本中数值命中，不构成时点可用批准')
    if not org_id:
        rec['verdict'] = 'org_unresolved'
        return rec
    q = r4.query_issuer_window(code, org_id, day)
    items = []
    base = __import__('datetime').datetime.strptime(day, '%Y%m%d')
    for item in q['items']:
        d = r4.local_day(item)
        if d is None:
            continue
        dev = (__import__('datetime').datetime.strptime(d, '%Y%m%d') - base).days
        if abs(dev) <= r4.WINDOW_DAYS:
            item['_index_day'] = d
            item['_deviation'] = dev
            items.append(item)
    candidates = r1.candidate_items(items, [end_date])
    candidates = list({c['adjunctUrl']: c for c in candidates}.values())
    rec['window_items'] = len(items)
    rec['candidate_count'] = len(candidates)
    targets = {'flag0': fmt_variants(row['val_flag0']),
               'flag1': fmt_variants(row['val_flag1'])}
    found = {'flag0': [], 'flag1': []}
    for item in candidates[:MAX_DOCS]:
        doc = r1.download(item, code, item['_index_day'])
        time.sleep(1.3)
        entry = dict(title=item.get('announcementTitle'),
                     index_day=item['_index_day'],
                     deviation=item['_deviation'],
                     status=doc.get('status'), file=doc.get('file'))
        if doc.get('status') == 'downloaded_readable_candidate_only' and doc.get('file'):
            p = r1.OUT / doc['file']
            hits, st = search_pdf(p, targets)
            entry['text_status'] = st
            entry['hits'] = {k: v[:4] for k, v in hits.items()}
            for k in found:
                for pg, snip in hits[k]:
                    found[k].append(dict(doc=item.get('announcementTitle'),
                                         page=pg, snippet=snip))
        rec['documents'].append(entry)
    f0, f1 = bool(found['flag0']), bool(found['flag1'])
    rec['verdict'] = ('both_flags_found' if f0 and f1 else
                      'flag0_found' if f0 else
                      'flag1_found' if f1 else
                      'neither_found' if candidates else 'no_candidates')
    rec['flag0_hit_count'] = len(found['flag0'])
    rec['flag1_hit_count'] = len(found['flag1'])
    rec['flag0_hits'] = found['flag0'][:6]
    return rec


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    r1.OUT = OUT  # 下载与事件重定向到本目录
    (OUT / 'documents').mkdir(exist_ok=True)
    args = sys.argv[1:]
    if args:
        pairs = [(args[i], args[i + 1]) for i in range(0, len(args), 2)]
    else:
        done = {p.stem for p in RESULTS.glob('*.json')}
        wl = list(csv.DictReader(WORKLIST.open(encoding='utf-8-sig')))
        todo = [r for r in wl if r['batch'] == 'A_window_mismatch'
                and f"{r['ts_code']}_{r['end_date']}" not in done]
        pairs = [(r['ts_code'], r['end_date']) for r in todo[:2]]
    if not pairs:
        print('no keys to process')
        return
    for code, end_date in pairs:
        rec = verify_one(code, end_date)
        target = RESULTS / f'{code}_{end_date}.json'
        audit.write_json(target, rec)
        print(code, end_date, rec['verdict'],
              f"candidates={rec.get('candidate_count')}",
              f"f0hits={rec.get('flag0_hit_count')}",
              f"f1hits={rec.get('flag1_hit_count')}")


if __name__ == '__main__':
    main()
