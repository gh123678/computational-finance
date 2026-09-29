import pandas as pd
from quant_research.universe import historical_universe


def test_name_changes_are_a_risk_exclusion_ledger():
    calendar = pd.bdate_range('2010-01-01', '2020-12-31')
    meta = pd.DataFrame({'ts_code': ['600000.SH', '600001.SH', '600002.SH', '600003.SH'],
                         'list_date': ['20150101'] * 4, 'delist_date': [None] * 4})
    names = pd.DataFrame({
        'ts_code': ['600001.SH', '600002.SH', '600003.SH'],
        'name': ['*ST风险', '*ST未来公告', '普通曾用名'],
        'start_date': ['20150101'] * 3,
        'end_date': [None] * 3,
        'ann_date': ['20150101', '20210101', '20150101'],
    })
    sectors = pd.DataFrame({'ts_code': ['600000.SH', '600001.SH', '600002.SH'],
                            'l1_code': ['X', 'Y', 'Z'],
                            'in_date': ['20150101'] * 3, 'out_date': [None] * 3})
    result = historical_universe('2020-12-31', meta, names, sectors, calendar)
    assert result.ts_code.tolist() == ['600000.SH', '600002.SH']
