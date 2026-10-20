"""Hand-calculated fixtures for the independent auditor; no producer imports."""
from calendar import monthrange
from copy import deepcopy
from datetime import date, timedelta

import numpy as np
import pytest

from quant_research.etf_independent_audit import (
    IndependentAuditError, audit_case, independently_prepare,
)


def _money(value):
    return f"{value:.2f}"


def _nav(day, cash, shares, sellable, ar, value, state, *, fee=0, slip=0,
         buy=0, sell=0, side="", remaining=0):
    return dict(date=day, cash=_money(cash), shares=shares, sellable=sellable,
                receivable=_money(ar), market_value=_money(value),
                equity=_money(cash + ar + value), state=state,
                pending_side=side, pending_remaining=remaining,
                fee_today=_money(fee), slippage_today=_money(slip),
                buy_notional=_money(buy), sell_notional=_money(sell))


def _order(day, side, raw, price, notional, *, fee=0, slip=0, filled=900,
           requested=900, remaining=0, status="filled"):
    return dict(date=day, side=side, requested=requested, filled=filled,
                raw_open=raw, price=price, notional=_money(notional),
                fee=_money(fee), slippage=_money(slip), prior_adv="10000000.00",
                capacity="50000.00", status=status, reason="fixture",
                remaining=remaining)


def _fixture(bps=0):
    # Twenty-one historical weekdays establish the full lagged amount window.
    warm = []
    day = date(2017, 12, 1)
    while day <= date(2017, 12, 29):
        if day.weekday() < 5:
            warm.append(day.strftime("%Y%m%d"))
        day += timedelta(days=1)
    days = warm + ["20180102", "20180103", "20180104", "20180105"]
    bars = [dict(ts_code="510330.SH", trade_date=day, open="10.000",
                 close="10.000", high="10.100", low="9.800", pre_close="10.000",
                 amount="10000", vol="100000") for day in days]
    for row in bars[-3:]:
        row.update(open="9.900", close="9.900")
    limits = [dict(trade_date=day, down_limit="8.000", up_limit="12.000")
              for day in days]
    actions = [dict(ts_code="510330.SH", ann_date="20171228", record_date="20180102",
                    ex_date="20180103", pay_date="20180105", cash_per_share="0.10")]
    schedule = {"20180102": 1, "20180104": 0}
    if bps == 0:
        # 900*10=9000; ex cash 900*.1=90; sell 900*9.9=8910.
        nav = [_nav("20171229", 10000, 0, 0, 0, 0, 0),
               _nav("20180102", 1000, 900, 0, 0, 9000, 1, buy=9000),
               _nav("20180103", 1000, 900, 900, 90, 8910, 1),
               _nav("20180104", 9910, 0, 0, 90, 0, 0, sell=8910),
               _nav("20180105", 10000, 0, 0, 0, 0, 0)]
        orders = [_order("20180102", "buy", "10.000", "10.000", 9000),
                  _order("20180104", "sell", "9.900", "9.900", 8910)]
        cash_record, cash_ex, cash_pay = 1000, 1000, 10000
    else:
        # Buy ceil(10*1.001,.001)=10.010; sell floor(9.9*.999,.001)=9.890.
        # Both commissions are the fixed minimum 5; slippage is 9 each way.
        nav = [_nav("20171229", 10000, 0, 0, 0, 0, 0),
               _nav("20180102", 986, 900, 0, 0, 9000, 1, fee=5, slip=9, buy=9009),
               _nav("20180103", 986, 900, 900, 90, 8910, 1),
               _nav("20180104", 9882, 0, 0, 90, 0, 0, fee=5, slip=9, sell=8901),
               _nav("20180105", 9972, 0, 0, 0, 0, 0)]
        orders = [_order("20180102", "buy", "10.000", "10.010", 9009, fee=5, slip=9),
                  _order("20180104", "sell", "9.900", "9.890", 8901, fee=5, slip=9)]
        cash_record, cash_ex, cash_pay = 986, 986, 9972
    events = [dict(date=day, kind=kind, event_id="20171228", shares=900,
                   amount="90.00", cash_after=_money(cash), receivable_after=_money(ar))
              for day, kind, cash, ar in [("20180102", "record", cash_record, 0),
                                          ("20180103", "ex", cash_ex, 90),
                                          ("20180105", "pay", cash_pay, 0)]]
    return dict(bars=bars, actions=actions, limits=limits, schedule=schedule,
                slippage_bps=bps, initial_cash="10000.00",
                result=dict(nav=nav, orders=orders, events=events))


@pytest.mark.parametrize("bps", [0, 10])
def test_hand_ledger_verifies_dividend_lock_ex_pay_and_adverse_prices(bps):
    report = audit_case(**_fixture(bps))
    assert report["status"] == "PASS"
    assert report["days"] == 4
    assert report["orders_checked"] == 2 and report["events_checked"] == 3


def test_internally_balanced_false_cash_is_rejected():
    case = _fixture()
    # Preserve the NAV identity while booking dividend cash on record day early.
    case["result"]["nav"][1]["cash"] = "1090.00"
    case["result"]["nav"][1]["equity"] = "10090.00"
    with pytest.raises(IndependentAuditError, match="cash"):
        audit_case(**case)


@pytest.mark.parametrize("corruption", ["order_fill", "omitted_day", "duplicated_event", "false_sellable"])
def test_economic_fields_and_exact_sequences_cannot_be_forged(corruption):
    case = _fixture()
    if corruption == "order_fill":
        case["result"]["orders"][0]["filled"] = 800
    elif corruption == "omitted_day":
        case["result"]["nav"].pop(2)
    elif corruption == "duplicated_event":
        case["result"]["events"].append(deepcopy(case["result"]["events"][-1]))
    else:
        case["result"]["nav"][1]["sellable"] = 900
    with pytest.raises(IndependentAuditError):
        audit_case(**case)


def test_suspended_entry_retries_original_quantity_despite_price_change():
    case = _fixture()
    case["bars"][-4]["suspended_at_open"] = True
    for row in case["bars"][-3:]:
        row.update(open="5.000", close="5.000")
    for row in case["limits"]:
        row["down_limit"] = "4.000"
    case["result"] = dict(
        nav=[_nav("20171229", 10000, 0, 0, 0, 0, 0),
             _nav("20180102", 10000, 0, 0, 0, 0, 1, side="buy", remaining=900),
             _nav("20180103", 5500, 900, 0, 0, 4500, 1, buy=4500),
             _nav("20180104", 10000, 0, 0, 0, 0, 0, sell=4500),
             _nav("20180105", 10000, 0, 0, 0, 0, 0)],
        orders=[_order("20180102", "buy", "10.000", "10.000", 0,
                       filled=0, remaining=900, status="rejected"),
                _order("20180103", "buy", "5.000", "5.000", 4500),
                _order("20180104", "sell", "5.000", "5.000", 4500)],
        events=[dict(date=day, kind=kind, event_id="20171228", shares=0,
                     amount="0.00", cash_after="10000.00", receivable_after="0.00")
                for day, kind in [("20180102", "record"), ("20180103", "ex"), ("20180105", "pay")]],
    )
    # Ex is processed before the delayed buy, so its cash_after is still 10000.
    assert audit_case(**case)["status"] == "PASS"


def _monthly_bars(closes=None):
    result = []
    for index in range(108):
        year, month0 = 2017 + index // 12, index % 12
        month = month0 + 1
        day = f"{year}{month:02d}{monthrange(year, month)[1]:02d}"
        close = str(closes[index] if closes is not None else 100 + index)
        result.append(dict(ts_code="510330.SH", trade_date=day, close=close))
    return result


def test_full_fixed_reference_has_108_months_and_no_same_close_execution():
    prepared = independently_prepare(_monthly_bars(), [])
    assert len(prepared["monthly"]) == 108
    assert len(prepared["schedule"]) == 96
    assert next(iter(prepared["schedule"])) == "20180131"
    assert "20251231" in prepared["schedule"]  # The November state executes here.
    assert prepared["monthly"][-1]["execution_date"] == ""
    assert prepared["daily"][0]["k"] == 1.0
    assert prepared["monthly"][8]["sma10"] is None


def test_current_month_is_included_and_exact_tie_retains_previous_long():
    closes = [1] * 9 + [10, 2] + [2] * 97
    prepared = independently_prepare(_monthly_bars(closes), [])
    october, november = prepared["monthly"][9:11]
    assert october["state"] == 1 and october["sma10"] == 1.9
    assert november["k"] == november["sma10"] == 2.0
    assert november["state"] == 1


def test_future_prices_and_actions_do_not_change_past_reference():
    bars = _monthly_bars()
    actions = [dict(ann_date="20250101", record_date="20250130", ex_date="20250131",
                    pay_date="20250203", cash_per_share="0.066")]
    original = independently_prepare(bars, actions)
    changed_bars = deepcopy(bars)
    for row in changed_bars:
        if row["trade_date"] >= "20250101":
            row["close"] = str(float(row["close"]) * 3)
    changed_actions = deepcopy(actions)
    changed_actions[0]["cash_per_share"] = "0.660"
    changed = independently_prepare(changed_bars, changed_actions)
    assert original["daily"][:96] == changed["daily"][:96]
    assert original["monthly"][:96] == changed["monthly"][:96]
    assert {d: s for d, s in original["schedule"].items() if d < "20250101"} == {
        d: s for d, s in changed["schedule"].items() if d < "20250101"}


def test_single_dividend_economic_event_is_added_once_and_duplicate_input_fails():
    bars = _monthly_bars([10] * 108)
    action = dict(ann_date="20180101", record_date="20180130", ex_date="20180131",
                  pay_date="20180202", cash_per_share="0.079")
    prepared = independently_prepare(bars, [action])
    ex = prepared["daily"][12]
    expected = np.float64(1) * ((np.float64(10) + np.float64("0.079")) / np.float64(10))
    assert ex["k"] == float(expected) and ex["dividend_per_share"] == 0.079
    with pytest.raises(IndependentAuditError, match="Duplicate economic event"):
        independently_prepare(bars, [action, action])
