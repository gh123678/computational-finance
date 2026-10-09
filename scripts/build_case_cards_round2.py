# -*- coding: utf-8 -*-
"""第二轮：为剩余差异案例抽取全部扣非出现位置与追溯/更正上下文，供逐案定性。"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / 'output' / 'announcement_financial_audit_20261007'
SCREEN = AUDIT / 'auto_screen_20261008'
OUT = AUDIT / 'case_review_20261009'

DIRS = [AUDIT / 'remaining_evidence_r1' / 'documents',
        AUDIT / 'remaining_evidence_r2_fixed_r1' / 'documents']
LABEL = re.compile(r'扣除非经常性损益(?:后)?的?(?:归属于(?:上市公司|母公司)?(?:公司)?(?:普通股)?股东的?)?净利润')
NUM = r'(-?[0-9][0-9,]*\.?[0-9]*)'


def load(pdf):
    for d in DIRS:
        p = d / pdf.replace('.pdf', '.txt')
        if p.exists():
            return re.sub(r'\s+', '', p.read_text(encoding='utf-8'))
    return ''


def fmt(v):
    return f'{v:,.2f}'


def main():
    rl = pd.read_csv(SCREEN / 'profit_dedt_screen_row_level.csv', encoding='utf-8')
    flags = pd.read_csv(OUT / 'case_flags.csv', encoding='utf-8-sig')
    done = flags[flags.api_value_found_in_best == True]
    done_keys = set(zip(done.ts_code, done.ann_date, done.end_date))
    diffs = rl[rl.status == 'value_differs_from_dated_original']

    cards = []
    seen = set()
    for _, row in diffs.iterrows():
        key = (row.ts_code, row.ann_date, row.end_date)
        if key in done_keys or key in seen:
            continue
        seen.add(key)
        flat = load(row.pdf_file)
        L = [f"=== {row.ts_code} ann={row.ann_date} end={row.end_date} | {row.document_title} | {row.pdf_file}",
             f"API={fmt(row.api_value)} 提取={fmt(row.original_value)}"]
        if not flat:
            L.append('  文本缺失')
            cards.append('\n'.join(L))
            continue
        for m in list(LABEL.finditer(flat))[:4]:
            seg = flat[m.start():m.start() + 90]
            nums = re.findall(NUM, seg)
            L.append(f"  标签后数值: {' / '.join(nums[:4])} | 前文: ...{flat[max(0, m.start() - 45):m.start()]}")
        for kw in ['追溯', '重述', '更正', '取消', '会计政策变更', '同一控制', '差错']:
            i = flat.find(kw)
            if i >= 0:
                L.append(f"  [{kw}] ...{flat[max(0, i - 30):i + 50]}...")
        cards.append('\n'.join(L))

    (OUT / 'case_cards_round2.txt').write_text('\n\n'.join(cards), encoding='utf-8')
    print(f'cards={len(cards)} written to case_cards_round2.txt')


if __name__ == '__main__':
    main()
