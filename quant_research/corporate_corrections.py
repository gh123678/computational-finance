"""Narrow, source-verified event corrections; never delete a security's history."""
import math
import pandas as pd

DEAO_SOURCE = 'https://static.cninfo.com.cn/finalpage/2020-09-19/1208460598.PDF'


def correct_actions(frame):
    frame = frame.copy()
    mask = frame.ts_code.eq('002260.SZ') & frame.ex_date.eq('20200925') & frame.div_proc.eq('实施')
    audit = []
    for row in frame.loc[mask].to_dict('records'):
        def amount(field):
            value = row.get(field)
            return 0. if pd.isna(value) else float(value)
        if (row.get('record_date') != '20200924' or row.get('imp_ann_date') != '20200919'
                or not math.isclose(amount('stk_div'), 1.1)
                or not math.isclose(amount('stk_co_rate'), 1.1)
                or any(amount(f) != 0 for f in ['cash_div', 'cash_div_tax', 'stk_bo_rate'])):
            raise ValueError('Verified Deao correction no longer matches source row; review required')
        audit.append(dict(ts_code=row['ts_code'], ex_date=row['ex_date'],
                          action='exclude_non_shareholder_distribution', source=DEAO_SOURCE,
                          reason='Restructuring shares go to investors, not existing shareholders; announcement specifies no ex-price adjustment.',
                          original={k: None if pd.isna(v) else v for k, v in row.items()}))
    return frame.loc[~mask].copy(), audit
