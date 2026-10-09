# -*- coding: utf-8 -*-
"""为 122 条扣非净利润真差异候选生成逐案核查证据卡。

纪律：只读既有证据目录与第一轮初筛输出；新证据写入
output/announcement_financial_audit_20261007/case_review_20261009/，
不改冻结输出、队列文件或 usable_in_verified_history。
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / 'output' / 'announcement_financial_audit_20261007'
SCREEN = AUDIT / 'auto_screen_20261008'
OUT = AUDIT / 'case_review_20261009'
OUT.mkdir(parents=True, exist_ok=True)

EVIDENCE_DIRS = [AUDIT / 'remaining_evidence_r1' / 'documents',
                 AUDIT / 'remaining_evidence_r2_fixed_r1' / 'documents']

VERSION_MARK = re.compile(r'取消|更正|修订|补充|英文|摘要')
RESTATE_MARK = re.compile(r'追溯调整|追溯重述|重述|会计政策变更|同一控制下|差错更正')


def find_text(pdf_file):
    name = pdf_file.replace('.pdf', '.txt')
    for d in EVIDENCE_DIRS:
        p = d / name
        if p.exists():
            return p
    return None


def num_variants(v):
    """生成数值在原文中的常见排版形式（千分位两位小数、无逗号、整数）。"""
    if pd.isna(v):
        return []
    forms = {f'{v:,.2f}', f'{v:.2f}'}
    if abs(v - round(v)) < 0.005:
        forms.add(f'{v:,.0f}')
        forms.add(str(int(round(v))))
    return [f for f in forms if f not in ('0', '0.00')]


def main():
    rl = pd.read_csv(SCREEN / 'profit_dedt_screen_row_level.csv', encoding='utf-8')
    doc = pd.read_csv(SCREEN / 'profit_dedt_screen.csv', encoding='utf-8')
    diffs = rl[rl['status'] == 'value_differs_from_dated_original'].copy()

    cards, flags = [], []
    for _, row in diffs.iterrows():
        rid = row.row_sha256
        checks = doc[doc.row_sha256 == rid]
        cand_files = list(dict.fromkeys(checks.pdf_file.dropna()))
        api_v, orig_v = row.api_value, row.original_value
        abs_diff = abs(api_v - orig_v)
        pct = abs_diff / abs(orig_v) * 100 if orig_v else float('inf')

        card = [
            f"=== {row.ts_code} ann={row.ann_date} end={row.end_date} ===",
            f"API={api_v:,.2f}  原文提取={orig_v:,.2f}  差={abs_diff:,.2f} ({pct:.2f}%)",
            f"首选文档: {row.pdf_file} | {row.document_title} | 候选数={row.candidate_count}",
        ]
        f = dict(row_sha256=rid, ts_code=row.ts_code, ann_date=row.ann_date,
                 end_date=row.end_date, api_value=api_v, original_value=orig_v,
                 abs_diff=abs_diff, pct_diff=pct, candidate_count=row.candidate_count,
                 best_title=row.document_title,
                 title_version_mark=bool(VERSION_MARK.search(str(row.document_title))))

        api_hits, other_matches, restate, versions = 0, [], False, []
        for pf in cand_files:
            p = find_text(pf)
            title = checks[checks.pdf_file == pf].document_title.iloc[0]
            if p is None:
                card.append(f"  [候选] {pf} | {title} | 文本缺失")
                continue
            flat = re.sub(r'\s+', '', p.read_text(encoding='utf-8'))
            hit_api = any(form in flat for form in num_variants(api_v))
            hit_orig = any(form in flat for form in num_variants(orig_v))
            api_hits += int(hit_api)
            if RESTATE_MARK.search(flat):
                restate = True
            if VERSION_MARK.search(str(title)):
                versions.append(str(title))
            # 该候选中扣非标签后的数值
            m = re.search(r'扣除非经常性损益的净利润(?:（[^）]*）)?[^0-9\-]{0,12}(-?[0-9][0-9,]*\.?[0-9]*)', flat)
            cand_val = m.group(1) if m else '未定位'
            mark = []
            if hit_api:
                mark.append('含API值')
            if hit_orig:
                mark.append('含提取值')
            card.append(f"  [候选] {pf} | {title} | 扣非后数值={cand_val} | {'/'.join(mark) or '两值均未命中'}")
            if hit_api and pf != row.pdf_file:
                other_matches.append(pf)

        f.update(api_value_found_in_best=bool(any(
            form in re.sub(r'\s+', '', find_text(row.pdf_file).read_text(encoding='utf-8'))
            for form in num_variants(api_v))) if find_text(row.pdf_file) else None,
            api_value_docs=api_hits,
            other_candidate_matches_api=';'.join(other_matches),
            restate_keywords=restate,
            version_titles=';'.join(versions))
        flags.append(f)
        cards.append('\n'.join(card))

    fdf = pd.DataFrame(flags)
    fdf.to_csv(OUT / 'case_flags.csv', index=False, encoding='utf-8-sig')
    (OUT / 'case_cards.txt').write_text('\n\n'.join(cards), encoding='utf-8')
    summary = dict(
        cases=len(fdf),
        title_version_mark=int(fdf.title_version_mark.sum()),
        api_value_found_in_best_doc=int(fdf.api_value_found_in_best.fillna(False).sum()),
        api_value_in_any_candidate=int((fdf.api_value_docs > 0).sum()),
        other_candidate_matches_api=int((fdf.other_candidate_matches_api != '').sum()),
        restate_keywords=int(fdf.restate_keywords.sum()),
    )
    (OUT / 'case_flags_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
