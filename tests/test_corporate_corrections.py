import pandas as pd
import pytest
from quant_research.corporate_corrections import correct_actions


def record():
    return dict(ts_code='002260.SZ', ex_date='20200925', div_proc='实施',
                record_date='20200924', imp_ann_date='20200919', stk_div='1.1',
                stk_co_rate='1.1', cash_div=None, cash_div_tax=None, stk_bo_rate=None)


def test_non_shareholder_distribution_is_logged_and_other_events_preserved():
    original = pd.DataFrame([record(), dict(record(), ex_date='20200926')])
    result, audit = correct_actions(original)
    assert result.ex_date.tolist() == ['20200926']
    assert len(original) == 2
    assert len(audit) == 1 and audit[0]['original']['stk_div'] == '1.1'
    assert audit[0]['source'].startswith('https://static.cninfo.com.cn/')


def test_correction_refuses_changed_cash_distribution():
    with pytest.raises(ValueError, match='no longer matches'):
        correct_actions(pd.DataFrame([dict(record(), cash_div_tax='0.2')]))
