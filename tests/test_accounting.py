import pandas as pd
import pytest
from quant_research.accounting import Action, Ledger, normalize_actions

D = pd.Timestamp


def action():
    return Action('A', D('2020-01-06'), D('2020-01-07'), D('2020-01-09'), D('2020-01-10'), 1., 1.)


def test_ex_date_keeps_receivable_and_unlisted_shares_out_of_spendable_cash():
    ledger = Ledger(5000, dividend_tax=0)
    ledger.positions['A'] = 500
    ledger.mark({'A': 10.})
    ledger.record(D('2020-01-06'), [action()])
    before = ledger.components()['equity']
    ledger.morning(D('2020-01-07'), [action()])
    assert ledger.cash == 5000
    assert ledger.positions['A'] == 500
    assert ledger.pending_shares('A') == 500
    assert ledger.receivable == 500
    assert ledger.components()['equity'] == before
    ledger.morning(D('2020-01-09'), [action()])
    assert ledger.cash == 5500
    assert ledger.pending_shares('A') == 500
    ledger.morning(D('2020-01-10'), [action()])
    assert ledger.positions['A'] == 1000
    assert ledger.pending_shares('A') == 0
    assert ledger.components()['equity'] == before


def test_sale_after_record_does_not_remove_cash_entitlement():
    ledger = Ledger(5000, dividend_tax=.2)
    ledger.positions['A'] = 500
    a = Action('A', D('2020-01-06'), D('2020-01-07'), D('2020-01-09'), pd.NaT, 1., 0.)
    ledger.record(a.record, [a])
    ledger.positions['A'] = 0
    ledger.morning(a.ex, [a])
    assert ledger.receivable == 400
    ledger.morning(a.cash_pay, [a])
    assert ledger.cash == 5400


def test_duplicate_ex_application_fails():
    ledger = Ledger()
    ledger.morning(action().ex, [action()])
    with pytest.raises(ValueError, match='twice'):
        ledger.morning(action().ex, [action()])


def test_missing_bonus_listing_date_not_assumed_immediate():
    with pytest.raises(ValueError, match='stock listing date'):
        Action('A', D('2020-01-06'), D('2020-01-07'), pd.NaT, pd.NaT, 0., 1.)


def test_repeated_announcement_with_missing_unused_stock_date_is_one_action():
    row = dict(ts_code='A', div_proc='实施', record_date='20200106', ex_date='20200107',
               pay_date='20200109', div_listdate=None, cash_div_tax=.4, stk_div=0, stk_bo_rate=None)
    assert len(normalize_actions(pd.DataFrame([row, row]), {'A'})) == 1
