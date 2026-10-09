# -*- coding: utf-8 -*-
"""补充裁决：为 122 行差异候选标注 update_flag 与"原文值是否在队列同键行中可得"。

根因：fina_indicator 原始返回对同一 (ts_code, ann_date, end_date) 同时给出
update_flag=0（原始披露值）与 update_flag=1（修订值）两行，队列全部保留。
77 个差异键的 flag=0 同键行与原文精确一致——差异行是修订值，非数据错误。
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / 'output' / 'announcement_financial_audit_20261007'
OUT = AUDIT / 'case_review_20261009'


def main():
    rl = pd.read_csv(AUDIT / 'auto_screen_20261008' / 'profit_dedt_screen_row_level.csv',
                     encoding='utf-8')
    fr = pd.read_csv(AUDIT / 'fina_indicator_records.csv', encoding='utf-8')
    adj = pd.read_csv(OUT / 'case_adjudication.csv', encoding='utf-8-sig')

    flag = fr.set_index('row_sha256').update_flag
    adj['update_flag'] = adj.row_sha256.map(flag)

    match = rl[rl.status == 'value_matches_dated_original']
    match_keys = set(zip(match.ts_code, match.ann_date, match.end_date))
    # 提取假象键：差异行本身的 API 值经人工核实与原文一致
    artifact_keys = set(zip(adj[adj.adjudication == 'extraction_artifact_match'].ts_code,
                            adj[adj.adjudication == 'extraction_artifact_match'].ann_date,
                            adj[adj.adjudication == 'extraction_artifact_match'].end_date))
    # 队列冲突键的姊妹行（16,324,568.32）经核实与原文一致
    sibling_verified = {('603559.SH', 20200425, 20191231)}

    def refined(r):
        key = (r.ts_code, r.ann_date, r.end_date)
        if r.adjudication == 'extraction_artifact_match':
            return 'cleared_extraction_artifact'
        if key in match_keys or key in sibling_verified:
            return 'revision_row_original_available_in_queue'
        if r.adjudication == 'version_chain_superseded':
            return 'unresolved_version_chain'
        return 'unresolved_true_difference'

    adj['original_value_in_queue'] = [
        (r.ts_code, r.ann_date, r.end_date) in match_keys
        or (r.ts_code, r.ann_date, r.end_date) in artifact_keys
        or (r.ts_code, r.ann_date, r.end_date) in sibling_verified
        for r in adj.itertuples()]
    adj['refined_category'] = [refined(r) for r in adj.itertuples()]
    adj.to_csv(OUT / 'case_adjudication.csv', index=False, encoding='utf-8-sig')

    summ = adj.refined_category.value_counts().to_dict()
    uniq = adj.drop_duplicates(['ts_code', 'ann_date', 'end_date'])
    result = dict(rows=len(adj), refined_rows=summ,
                  unique_keys=len(uniq),
                  refined_keys=uniq.refined_category.value_counts().to_dict(),
                  flag_crosstab={str(k): v for k, v in
                                 adj.groupby(['refined_category', 'update_flag']).size().items()})
    (OUT / 'adjudication_summary.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=1))

    # 全数据集规模：update_flag 冲突键
    dup = fr[fr.duplicated(['ts_code', 'ann_date', 'end_date'], keep=False)]
    ck = dup.groupby(['ts_code', 'ann_date', 'end_date']).profit_dedt.nunique()
    conflicts = int((ck > 1).sum())
    queued_keys = set(zip(rl.ts_code, rl.ann_date, rl.end_date))
    in_queue = int(sum(1 for k in ck[ck > 1].index if k in queued_keys))
    print(f'full-dataset conflicting keys: {conflicts}, in screened queue: {in_queue}')


if __name__ == '__main__':
    main()
