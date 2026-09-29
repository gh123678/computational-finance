import pandas as pd
from quant_research.universe import historical_universe


def test_future_name_announcement_and_unknown_industry_do_not_enter():
    calendar = pd.bdate_range('2010-01-01', '2020-12-31')
    meta = pd.DataFrame({'ts_code': ['600000.SH','600001.SH','600002.SH'],
                         'list_date': ['20150101']*3, 'delist_date': [None]*3})
    names = pd.DataFrame({'ts_code': meta.ts_code, 'name': ['A','B','C'],
                          'start_date': ['20150101']*3, 'end_date': [None]*3,
                          'ann_date': ['20150101','20210101','20150101']})
    sectors = pd.DataFrame({'ts_code': ['600000.SH','600001.SH'], 'l1_code':['X','Y'],
                            'in_date':['20150101']*2, 'out_date':[None]*2})
    result = historical_universe('2020-12-31', meta, names, sectors, calendar)
    assert result.ts_code.tolist() == ['600000.SH']
