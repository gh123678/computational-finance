"""Frozen-source fill is distinct from replacing a contradictory cache value."""
from copy import deepcopy
import pandas as pd
import pytest
from momentum_g2_events import build_event_book
import momentum_g2_audit_repair1 as audit


def facts(special=False, cache_cash=None, source_cash='0'):
    calendar = pd.bdate_range('2017-11-20', '2018-01-31')
    original = dict(code='000001.SZ', event_id='frozen-primary', record='2018-01-03', ex='2018-01-04',
        cash_pay=None, stock_pay='2018-01-10', cash_per_share=source_cash,
        stock_per_share='0' if special else '.3', taxable_bonus_per_share='0', known_date='2017-12-20', sources=[])
    if special:
        original.update(role='special_reorganization', unsupported_special=True, version=1,
            original_action=dict(code='000001.SZ', record='2018-01-03', ex='2018-01-04',
                cash_pay=None, stock_pay='2018-01-10', cash_per_share='0', stock_per_share='.3', taxable_bonus_per_share='0'))
    raw = dict(ts_code='000001.SZ', ex_date='20180104', record_date='20180103', pay_date=None,
        div_listdate='20180110', imp_ann_date='20171220', div_proc='实施', cash_div_tax=cache_cash,
        stk_div='.3', stk_co_rate='.3', stk_bo_rate=None)
    evidence = {'event_versions' if special else 'ordinary_actions': [original]}
    book = build_event_book(pd.DataFrame([raw]), calendar, evidence)
    normalized = next(x for x in book.to_inventory() if x['raw_source'] == 'r5_bound_mapping')
    return normalized, original, evidence, raw


@pytest.mark.parametrize('special', [False, True])
def test_primary_source_fills_missing_cash_without_changing_special_role(special):
    fact, original, evidence, raw = facts(special)
    assert fact['kind'] == ('unsupported' if special else 'ordinary')
    assert audit._bind_normalized_fact(fact, original, evidence=evidence, raw_dividends=[raw]) == []


@pytest.mark.parametrize('special', [False, True])
def test_nonempty_cache_contradiction_is_still_a_conflict(special):
    fact, original, evidence, raw = facts(special, cache_cash='1')
    assert fact['kind'] == 'conflict'
    assert audit._bind_normalized_fact(fact, original, evidence=evidence, raw_dividends=[raw]) == []
    fact['kind'] = 'unsupported' if special else 'ordinary'
    assert 'kind' in audit._bind_normalized_fact(fact, original, evidence=evidence, raw_dividends=[raw])


def test_missing_primary_amount_is_not_invented_as_zero():
    fact, original, evidence, raw = facts(source_cash=None)
    fact['cash_per_share'] = fact['cash_div_tax'] = fact['D'] = '0'
    assert any(x in audit._bind_normalized_fact(fact, original, evidence=evidence, raw_dividends=[raw])
               for x in ('cash_per_share', 'cash_div_tax', 'D'))
