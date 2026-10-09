"""Merge round-1 adjudication, round-1/round-3 screens into the final per-key
status for all 204 update_flag conflict keys (distinct keys, priority order):

1. case_adjudication.csv refined_category (revision > version_chain > true_diff > artifact)
2. round-1 row-level screen status for screened-but-unadjudicated keys
3. round-3 key classification (flag0 match => revision row; else unresolved)
4. remainder: no candidate document after round-3 collection

Rewrites case_review_20261009/update_flag_conflict_all204.csv with a final_status column.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'output' / 'announcement_financial_audit_20261007'
REVIEW = AUDIT / 'case_review_20261009'

R3_CLASS = {
    'flag0_matches_revision_pattern': 'revision_row_original_available_in_queue',
    'unresolved_true_difference': 'unresolved_true_difference',
    'unresolved_extraction_not_found': 'screened_r3_extraction_not_found',
}


def main() -> None:
    ck = pd.read_csv(REVIEW / 'update_flag_conflict_all204.csv', dtype=str, encoding='utf-8-sig')
    ck = ck[[c for c in ck.columns if c != 'final_status']].drop_duplicates(
        subset=['ts_code', 'ann_date', 'end_date'])
    status = {(r['ts_code'], r['ann_date'], r['end_date']): None for _, r in ck.iterrows()}

    adj = pd.read_csv(REVIEW / 'case_adjudication.csv', dtype=str, encoding='utf-8')
    adj['key'] = list(zip(adj['ts_code'], adj['ann_date'], adj['end_date']))
    for cat in ['revision_row_original_available_in_queue', 'unresolved_version_chain',
                'unresolved_true_difference', 'cleared_extraction_artifact']:
        for k in set(adj.loc[adj['refined_category'] == cat, 'key']):
            if k in status and status[k] is None:
                status[k] = cat

    rl = pd.read_csv(AUDIT / 'auto_screen_20261008' / 'profit_dedt_screen_row_level.csv',
                     dtype=str, encoding='utf-8')
    rl['key'] = list(zip(rl['ts_code'], rl['ann_date'], rl['end_date']))
    for k, sts in rl.groupby('key')['status'].apply(lambda s: set(s)).items():
        if k in status and status[k] is None:
            status[k] = ('screened_r1_extraction_not_found'
                         if sts == {'not_found_in_candidate_text'}
                         else 'screened_r1_period_mismatch')

    kc = pd.read_csv(AUDIT / 'auto_screen_20261009_conflict_keys' / 'key_classification.csv',
                     dtype=str, encoding='utf-8-sig')
    for _, r in kc.iterrows():
        k = (r['ts_code'], r['ann_date'], r['end_date'])
        if k in status:
            status[k] = R3_CLASS[r['classification']]

    # Round 4: issuer-listing documents for the 67 no-candidate keys
    kc4 = pd.read_csv(AUDIT / 'auto_screen_20261009_issuer_listing' / 'key_classification.csv',
                      dtype=str, encoding='utf-8-sig')
    for _, r in kc4.iterrows():
        k = (r['ts_code'], r['ann_date'], r['end_date'])
        if k in status and status[k] is None:
            status[k] = R3_CLASS[r['classification']].replace('_r3_', '_r4_')

    for k in status:
        if status[k] is None:
            status[k] = 'no_candidate_document_unverified'

    # 000676.SZ 20201231 resolved by correction_evidence_20261009: the updated
    # 2020 annual report (更新后, published 2022-04-28) matches the flag=0 value
    # exactly. NOTE: flag=0 here carries the post-ann_date updated value
    # (vendor backfill), not the cancelled original released at ann_date.
    status[('000676.SZ', '20210429', '20201231')] = 'resolved_flag0_matches_updated_republication'
    # 601989.SH 20200630 manually adjudicated from
    # auto_screen_20261009_issuer_listing (2020 半年报, unit 万元): the headline
    # 扣非净利润 is -15,863.13万元 = -158,631,300 CNY = flag=1 exactly
    # (narrative "-1.59亿元" corroborates). flag=0 carries the raw 万元 figure
    # (-15,863.13) unconverted — a vendor unit error. The extractor misread the
    # PDF column merge "-15,863.13"+"2,945.15" as -15,863.132, hence the machine
    # screen marked differs. Only confirmed reverse case (flag=1 = original).
    status[('601989.SH', '20200828', '20200630')] = 'resolved_flag1_original_flag0_unit_error'

    ck['final_status'] = [status[(t, a, e)] for t, a, e in
                          zip(ck['ts_code'], ck['ann_date'], ck['end_date'])]
    ck.to_csv(REVIEW / 'update_flag_conflict_all204.csv', index=False, encoding='utf-8-sig')
    print(ck['final_status'].value_counts().to_string())
    print('total:', len(ck))


if __name__ == '__main__':
    main()
