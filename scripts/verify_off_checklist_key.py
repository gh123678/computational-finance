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


POST_WINDOW_DAYS = 60
CORRECTION_RE = None  # compiled below (avoid re module at import time cost)


def query_post_window(code, org_id, day):
    """ann_date 之后 POST_WINDOW_DAYS 天内的发行人公告列表（版本链检查用）。"""
    from datetime import datetime as _dt, timedelta as _td
    base = _dt.strptime(day, '%Y%m%d')
    start = (base + _td(days=1)).strftime('%Y-%m-%d')
    end = (base + _td(days=POST_WINDOW_DAYS)).strftime('%Y-%m-%d')
    resp_dir = OUT / 'responses'
    resp_dir.mkdir(parents=True, exist_ok=True)
    all_items = []
    for page in range(1, 6):
        path = resp_dir / f'{code}_{day}_post_{page}.json'
        if not path.exists():
            args = ['--max-time', '40', r4.ENDPOINT, '--header', 'User-Agent: Mozilla/5.0',
                    '--header', 'Referer: https://www.cninfo.com.cn/', '--output',
                    str(path.with_suffix('.partial'))]
            params = dict(pageNum=str(page), pageSize='30', tabName='fulltext',
                          column='szse' if code.endswith('.SZ') else 'sse',
                          isHLtitle='false', stock=f'{code[:6]},{org_id}',
                          seDate=f'{start}~{end}')
            for name, value in params.items():
                args += ['--data-urlencode', f'{name}={value}']
            if not r1.run_curl(args, 50, dict(code=code, day=day, query='post_window')):
                break
            try:
                obj = json.loads(path.with_suffix('.partial').read_text(encoding='utf-8'))
                if not isinstance(obj, dict) or 'announcements' not in obj:
                    break
                path.with_suffix('.partial').replace(path)
            except (ValueError, UnicodeError):
                break
            time.sleep(1.3)
        obj = json.loads(path.read_text(encoding='utf-8'))
        items = obj.get('announcements') or []
        all_items.extend(items)
        if not obj.get('hasMore', False):
            break
    return all_items


def version_chain_check(code, org_id, day):
    """检索 ann_date 后更正/更新后/修订/取消类公告；返回状态与命中清单。

    版本链判定只认**定期报告/审计报告类**更正（上市公告书等无关公告单独列示，
    如资产收购"（更新后）"不算年报版本链变更）。
    """
    import re
    pat = re.compile('更正|更新后|修订|取消')
    neg = re.compile('问询|回复|补充|意见|提示|说明')
    report_pat = re.compile('年度报告|年年度报告|半年度报告|季度报告|审计报告')
    hits, unrelated = [], []
    for item in query_post_window(code, org_id, day):
        title = re.sub('<[^>]+>', '', item.get('announcementTitle', ''))
        if not (pat.search(title) and not neg.search(title)):
            continue
        d = r4.local_day(item)
        entry = dict(title=title, day=d, url=item.get('adjunctUrl'))
        (hits if report_pat.search(title) else unrelated).append(entry)
    status = 'clear_no_later_correction' if not hits else 'later_correction_found'
    return dict(status=status, checked_range_days=POST_WINDOW_DAYS,
                corrections=hits[:10], unrelated_corrections=unrelated[:10])


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
    if org_id:
        vc = version_chain_check(code, org_id, day)
        rec['version_chain'] = vc
        rec['final_status'] = ('verified_flag0_clear' if f0 and not f1
                               and vc['status'] == 'clear_no_later_correction'
                               else 'verified_flag0_but_version_chain_flagged' if f0 and not f1
                               else 'needs_manual_review')
    else:
        rec['final_status'] = 'org_unresolved'
    return rec


def write_progress():
    rows = []
    for p in sorted(RESULTS.glob('*.json')):
        r = json.loads(p.read_text(encoding='utf-8'))
        rows.append(dict(ts_code=r['ts_code'], end_date=r['end_date'], batch=r.get('batch'),
                         verdict=r.get('verdict'), final_status=r.get('final_status'),
                         version_chain=(r.get('version_chain') or {}).get('status'),
                         corrections=len((r.get('version_chain') or {}).get('corrections') or []),
                         candidates=r.get('candidate_count')))
    if rows:
        with (OUT / 'adjudication_progress.csv').open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return len(rows)


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    r1.OUT = OUT  # 下载与事件重定向到本目录
    (OUT / 'documents').mkdir(exist_ok=True)
    args = sys.argv[1:]
    next_n = 2
    if args and args[0] == '--next':
        next_n = int(args[1])
        args = args[2:]
    if args:
        pairs = [(args[i], args[i + 1]) for i in range(0, len(args), 2)]
    else:
        done = {p.stem for p in RESULTS.glob('*.json')}
        wl = list(csv.DictReader(WORKLIST.open(encoding='utf-8-sig')))
        # worklist.csv 已按批次排序（A→B→C），续跑全部剩余键
        todo = [r for r in wl if f"{r['ts_code']}_{r['end_date']}" not in done]
        pairs = [(r['ts_code'], r['end_date']) for r in todo[:next_n]]
    if not pairs:
        print('no keys to process')
        return
    for code, end_date in pairs:
        rec = verify_one(code, end_date)
        target = RESULTS / f'{code}_{end_date}.json'
        audit.write_json(target, rec)
        vc = (rec.get('version_chain') or {}).get('status', '-')
        print(code, end_date, rec.get('final_status'), rec['verdict'],
              f"candidates={rec.get('candidate_count')}",
              f"f0hits={rec.get('flag0_hit_count')}",
              f"f1hits={rec.get('flag1_hit_count')}", f"vc={vc}")
    print(f"progress: {write_progress()}/166 keys have results")


if __name__ == '__main__':
    main()
