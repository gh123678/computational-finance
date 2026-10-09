"""Classify each round-3 screened update_flag conflict key by whether the
flag=0 / flag=1 API values match the candidate original-document text.

Reads auto_screen_20261009_conflict_keys/profit_dedt_screen.csv, writes
auto_screen_20261009_conflict_keys/key_classification.csv.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'announcement_financial_audit_20261007' / 'auto_screen_20261009_conflict_keys'
MATCH = {'value_matches_dated_original', 'value_matches_needs_manual_confirm'}


def main() -> None:
    sc = pd.read_csv(OUT / 'profit_dedt_screen.csv', dtype=str, encoding='utf-8-sig')
    rows = []
    for (ts, ad, ed), g in sc.groupby(['ts_code', 'ann_date', 'end_date']):
        rec = {'ts_code': ts, 'ann_date': ad, 'end_date': ed}
        for flag in ['0', '1']:
            sts = set(g.loc[g['update_flag'] == flag, 'status'])
            rec[f'flag{flag}_matched'] = bool(sts & MATCH)
            rec[f'flag{flag}_statuses'] = '|'.join(sorted(sts))
        m0, m1 = rec['flag0_matched'], rec['flag1_matched']
        if m0 and m1:
            rec['classification'] = 'both_flags_match_original_text'
        elif m0:
            rec['classification'] = 'flag0_matches_revision_pattern'
        elif m1:
            rec['classification'] = 'flag1_matches_original'
        elif 'not_found_in_candidate_text' in (rec['flag0_statuses'] + rec['flag1_statuses']) \
                and 'value_differs_from_dated_original' not in (rec['flag0_statuses'] + rec['flag1_statuses']):
            rec['classification'] = 'unresolved_extraction_not_found'
        else:
            rec['classification'] = 'unresolved_true_difference'
        rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / 'key_classification.csv', index=False, encoding='utf-8-sig')
    print(df['classification'].value_counts().to_string())


if __name__ == '__main__':
    main()
