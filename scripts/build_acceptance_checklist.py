"""Build the manual-check acceptance checklist for the 36 still-unresolved
update_flag conflict keys (11 true differences + 25 extraction failures).

For each key the checklist carries: both API values, the screening round that
produced the current status, every downloaded candidate document (absolute
path) with its extracted nearest original value, and a concrete manual action.
This is the acceptance gate before any fundamental factor may consume
profit_dedt.

Outputs (case_review_20261009/):
- acceptance_checklist.csv  machine-readable, one row per key
- fundamental-factor-acceptance-checklist.md  human checklist
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'output' / 'announcement_financial_audit_20261007'
REVIEW = AUDIT / 'case_review_20261009'

ROUNDS = {
    'r1': AUDIT / 'auto_screen_20261008' / 'profit_dedt_screen_row_level.csv',
    'r3': AUDIT / 'auto_screen_20261009_conflict_keys' / 'profit_dedt_screen.csv',
    'r4': AUDIT / 'auto_screen_20261009_issuer_listing' / 'profit_dedt_screen.csv',
}
RESULT_DIRS = [
    AUDIT / 'remaining_evidence_r1' / 'results',
    AUDIT / 'remaining_evidence_r2_fixed_r1' / 'results',
    AUDIT / 'update_flag_conflict_evidence_20261009' / 'results',
    AUDIT / 'issuer_listing_evidence_20261009' / 'results',
    AUDIT / 'correction_evidence_20261009' / 'results',
    AUDIT / 'correction_evidence_20261009_r2' / 'results',
    AUDIT / 'version_chain_evidence_20261009' / 'results',
]
UNRESOLVED = {'unresolved_true_difference', 'screened_r1_extraction_not_found',
              'screened_r3_extraction_not_found', 'screened_r4_extraction_not_found'}
ACTION = {
    'unresolved_true_difference': ('人工核对：对照候选年报/季报 PDF 原文表格（含图像表格 OCR），'
        '确认扣非净利润真实值并判定 flag=0/flag=1 哪行为原文值、差异是否源于数据商口径'),
    'screened_r1_extraction_not_found': ('人工核对：机器未在候选文本中定位到该数值；'
        '打开候选 PDF 人工查找"扣除非经常性损益"条目（可能在图像表格或非常规排版中）'),
    'screened_r3_extraction_not_found': ('人工核对：机器未在候选文本中定位到该数值；'
        '打开候选 PDF 人工查找"扣除非经常性损益"条目（可能在图像表格或非常规排版中）'),
    'screened_r4_extraction_not_found': ('人工核对：机器未在候选文本中定位到该数值；'
        '打开候选 PDF 人工查找"扣除非经常性损益"条目（可能在图像表格或非常规排版中）'),
}


def candidate_documents(ts_code, ann_date):
    docs = []
    for results in RESULT_DIRS:
        path = results / f'{ts_code}_{ann_date}.json'
        if not path.exists():
            continue
        try:
            result = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError):
            continue
        base = path.parent.parent
        for doc in result.get('documents', []):
            if doc.get('status') != 'downloaded_readable_candidate_only':
                continue
            pdf = base / doc['file']
            docs.append(dict(title=doc.get('title'), url=doc.get('url'),
                pdf=str(pdf), pdf_exists=pdf.is_file(),
                round=base.name, index_day=doc.get('index_day')))
    # also correction round results keyed with end_date in filename
    for results in RESULT_DIRS:
        for path in results.glob(f'{ts_code}_{ann_date}_*.json'):
            try:
                result = json.loads(path.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                continue
            base = path.parent.parent
            for doc in result.get('documents', []):
                if doc.get('status') != 'downloaded_readable_candidate_only':
                    continue
                pdf = base / doc['file']
                entry = dict(title=doc.get('title'), url=doc.get('url'),
                    pdf=str(pdf), pdf_exists=pdf.is_file(),
                    round=base.name, index_day=doc.get('index_day'))
                if entry not in docs:
                    docs.append(entry)
    return docs


def screen_observations(ts_code, ann_date, end_date):
    obs = []
    for name, csv_path in ROUNDS.items():
        if not csv_path.is_file():
            continue
        frame = pd.read_csv(csv_path, dtype=str, encoding='utf-8-sig')
        sub = frame[(frame['ts_code'] == ts_code) & (frame['ann_date'] == ann_date)
                    & (frame['end_date'] == end_date)]
        for _, r in sub.iterrows():
            obs.append(dict(round=name, status=r['status'], update_flag=r.get('update_flag'),
                api_value=r.get('api_value'), original_value=r.get('original_value'),
                document_title=r.get('document_title')))
    return obs


def main() -> None:
    ck = pd.read_csv(REVIEW / 'update_flag_conflict_all204.csv', dtype=str, encoding='utf-8-sig')
    u = ck[ck['final_status'].isin(UNRESOLVED)]
    assert len(u) == 32, f'expected 32 unresolved keys, got {len(u)}'
    rows = []
    for _, r in u.iterrows():
        ts, ad, ed = r['ts_code'], r['ann_date'], r['end_date']
        docs = candidate_documents(ts, ad)
        obs = screen_observations(ts, ad, ed)
        nearest, nearest_doc = None, None
        for o in obs:
            if o['status'] == 'value_differs_from_dated_original' and o['original_value']:
                try:
                    cand = float(o['original_value'])
                except ValueError:
                    continue
                ref = min(float(r['val_flag0']), float(r['val_flag1']),
                          key=lambda v: abs(v - cand))
                if nearest is None or abs(cand - ref) < abs(nearest - ref):
                    nearest, nearest_doc = cand, o['document_title']
        doc_list = ' | '.join(f"{d['title']} ({Path(d['pdf']).name})" for d in docs)
        rows.append(dict(ts_code=ts, ann_date=ad, end_date=ed,
            final_status=r['final_status'], val_flag0=r['val_flag0'], val_flag1=r['val_flag1'],
            rel_diff_pct=r['rel_diff_pct'], n_candidate_docs=len(docs),
            candidate_docs=doc_list,
            nearest_original_value=nearest, nearest_original_doc=nearest_doc,
            manual_action=ACTION[r['final_status']]))
    frame = pd.DataFrame(rows).sort_values(['final_status', 'ts_code', 'end_date'])
    frame.to_csv(REVIEW / 'acceptance_checklist.csv', index=False, encoding='utf-8-sig')

    lines = ['# 基本面因子启用前验收清单：36 个未决冲突键人工核对', '',
        '日期：2026-10-09', '',
        '来源：`update_flag_conflict_all204.csv` 中 `final_status` 为真差异未决（11 键）或提取失败（25 键）的全部键。'
        '在以下 36 键全部完成人工核对并定性之前，任何基本面因子不得消费 `profit_dedt`；'
        '已确认的 162 个修订模式键只能使用 flag=0 口径且需版本链与单位核验（000676/601989 两例）。', '',
        '机器可读版本：`acceptance_checklist.csv`（含每键候选 PDF 文件名、最近原文值）。', '']
    for status, title in [('unresolved_true_difference', 'A. 真差异未决（11 键）'),
                          ('screened_r1_extraction_not_found', 'B. 提取失败·第一轮（18 键）'),
                          ('screened_r3_extraction_not_found', 'C. 提取失败·第三轮（2 键）'),
                          ('screened_r4_extraction_not_found', 'D. 提取失败·第四轮（5 键）')]:
        sub = frame[frame['final_status'] == status]
        if not len(sub):
            continue
        lines.append(f'## {title}')
        lines.append('')
        for i, (_, r) in enumerate(sub.iterrows(), 1):
            v0, v1 = float(r['val_flag0']), float(r['val_flag1'])
            lines.append(f"### {i}. {r['ts_code']} {r['end_date']}（ann_date {r['ann_date']}）")
            lines.append('')
            lines.append(f'- API 双版本：flag=0 = {v0:,.2f}；flag=1 = {v1:,.2f}'
                         f'（相对差 {float(r["rel_diff_pct"]):.2f}%）')
            if r['nearest_original_value'] == r['nearest_original_value']:
                lines.append(f"- 机器提取的最近原文值：{float(r['nearest_original_value']):,.2f}"
                             f"（{r['nearest_original_doc']}）")
            else:
                lines.append('- 机器未能提取任何原文值')
            if r['candidate_docs']:
                lines.append(f"- 候选文档（{r['n_candidate_docs']} 份，位于对应轮次 documents/ 目录）："
                             f"{r['candidate_docs']}")
            else:
                lines.append('- 无已下载候选文档：需先人工检索原文')
            lines.append(f"- 处置：{r['manual_action']}")
            lines.append('- [ ] 人工核对完成，结论：____')
            lines.append('')
    lines += ['## 验收标准', '',
        '1. 每键给出唯一结论：flag=0 为原文值 / flag=1 为原文值 / 两值皆错（写明真实值与出处页码）。',
        '2. 结论须附原文证据（PDF 页码 + 截图或文本摘录），存入 `evidence/` 并登记行哈希。',
        '3. 36 键全部定性后，重跑 `finalize_update_flag_conflict_status.py` 并更新本清单状态。',
        '4. 在此之前，`usable_in_verified_history` 维持 False，时点核验批准维持 0。', '']
    (REVIEW / 'fundamental-factor-acceptance-checklist.md').write_text(
        '\n'.join(lines), encoding='utf-8')
    print(frame.groupby('final_status').size().to_string())
    print('docs coverage:', (frame['n_candidate_docs'] > 0).sum(), '/', len(frame))


if __name__ == '__main__':
    main()
