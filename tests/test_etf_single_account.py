from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from quant_research.etf_single_account import execute_order, simulate


def _market(n_eval, *, warmup=20, price="10.000", amount="100000"):
    start = datetime(2020, 1, 1)
    dates = [(start + timedelta(days=i)).strftime("%Y%m%d")
             for i in range(warmup + n_eval)]
    bars = [{"ts_code": "510330.SH", "trade_date": day, "open": price,
             "close": price, "amount": amount, "high": price,
             "low": price, "vol": "1000"} for day in dates]
    limits = [{"trade_date": day, "up_limit": "1000000.000",
               "down_limit": "0.001"} for day in dates]
    return bars, limits, dates, dates[warmup]


def _action(dates, *, cash="0.1000"):
    return {"ts_code": "510330.SH", "ann_date": dates[19],
            "record_date": dates[20], "ex_date": dates[21],
            "pay_date": dates[23], "cash_per_share": cash}


def test_record_ex_pay_separate_lock_receivable_and_cash_without_reinvestment():
    bars, limits, dates, start = _market(4)
    for bar in bars[21:]:
        bar["open"] = bar["close"] = "9.900"
    result = simulate(bars, [_action(dates)], limits,
                      {dates[20]: 1, dates[23]: 1}, 0, "100000", start)
    baseline, record, ex, waiting, pay = result["nav"]
    assert baseline["date"] == dates[19]
    assert baseline["equity"] == "100000.00"
    assert (record["shares"], record["sellable"], record["cash"], record["receivable"]) == (9800, 0, "2000.00", "0.00")
    assert (ex["cash"], ex["receivable"], ex["equity"]) == ("2000.00", "980.00", "100000.00")
    assert waiting["receivable"] == "980.00"
    assert (pay["shares"], pay["cash"], pay["receivable"]) == (9800, "2980.00", "0.00")
    assert len(result["orders"]) == 1
    assert result["events"] == [
        {"date": dates[20], "kind": "record", "event_id": dates[19], "shares": 9800,
         "amount": "980.00", "cash_after": "2000.00", "receivable_after": "0.00"},
        {"date": dates[21], "kind": "ex", "event_id": dates[19], "shares": 9800,
         "amount": "980.00", "cash_after": "2000.00", "receivable_after": "980.00"},
        {"date": dates[23], "kind": "pay", "event_id": dates[19], "shares": 9800,
         "amount": "980.00", "cash_after": "2980.00", "receivable_after": "0.00"},
    ]


def test_duplicate_projection_maps_once_and_conflicting_event_stops():
    bars, limits, dates, start = _market(4)
    action = _action(dates)
    single = simulate(bars, [action], limits, {dates[20]: 1}, 0, "100000", start)
    paired = simulate(bars, [action, dict(action)], limits, {dates[20]: 1}, 0, "100000", start)
    assert paired == single
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        simulate(bars, [action, dict(action, cash_per_share="0.2000")],
                 limits, {dates[20]: 1}, 0, "100000", start)


def test_zero_holdings_still_emit_all_three_dividend_events():
    bars, limits, dates, start = _market(4)
    result = simulate(bars, [_action(dates)], limits, {}, 0, "100000", start)
    assert [event["kind"] for event in result["events"]] == ["record", "ex", "pay"]
    assert all(event["shares"] == 0 and event["amount"] == "0.00" for event in result["events"])
    assert all(row["receivable"] == "0.00" for row in result["nav"])


def test_capacity_carries_fixed_remaining_and_state_reversal_cancels_old_buy():
    bars, limits, dates, start = _market(4, amount="1000")
    result = simulate(bars, [], limits, {dates[20]: 1, dates[22]: 0}, 0, "100000", start)
    orders = result["orders"]
    assert [row["side"] for row in orders] == ["buy", "buy", "sell", "sell"]
    assert [row["requested"] for row in orders] == [9800, 9300, 1000, 500]
    assert [row["filled"] for row in orders] == [500, 500, 500, 500]
    assert [row["status"] for row in orders] == ["partial", "partial", "partial", "filled"]
    assert all(row["prior_adv"] == "1000000.00" and row["capacity"] == "5000.00" for row in orders)
    assert result["nav"][2]["pending_remaining"] == 8800
    assert result["nav"][-1]["shares"] == 0
    assert result["nav"][-1]["cash"] == "100000.00"
    assert result["nav"][-1]["pending_side"] == ""


def test_retry_does_not_recompute_target_after_price_changes():
    bars, limits, dates, start = _market(2, amount="1000")
    bars[21]["open"] = bars[21]["close"] = "20.000"
    result = simulate(bars, [], limits, {dates[20]: 1}, 0, "100000", start)
    first, retry = result["orders"]
    assert first["filled"] == 500
    assert retry["requested"] == 9300
    assert retry["filled"] == 200
    assert retry["remaining"] == 9100
    assert result["nav"][-1]["shares"] == 700


def test_new_long_after_partial_exit_buys_delta_from_existing_shares():
    bars, limits, dates, start = _market(3, amount="1000")
    bars[21]["open"] = bars[21]["close"] = "20.000"
    result = simulate(bars, [], limits,
                      {dates[20]: 1, dates[21]: 0, dates[22]: 1}, 0, "100000", start)
    buy, partial_exit, reentry = result["orders"]
    assert (buy["filled"], partial_exit["filled"], partial_exit["remaining"]) == (500, 200, 300)
    # Open equity is 99,000 cash + 300 * 10; target TOTAL is 9,900.
    assert reentry["side"] == "buy"
    assert reentry["requested"] == 9600
    assert reentry["filled"] == 500
    assert result["nav"][-1]["shares"] == 800


def test_new_long_above_total_target_keeps_existing_shares_without_reduction():
    bars, limits, dates, start = _market(3, amount="1000")
    bars[21]["open"] = bars[21]["close"] = "20.000"
    bars[22]["open"] = bars[22]["close"] = "100000.000"
    result = simulate(bars, [], limits,
                      {dates[20]: 1, dates[21]: 0, dates[22]: 1}, 0, "100000", start)
    assert len(result["orders"]) == 2
    assert result["nav"][-1]["shares"] == 300
    assert result["nav"][-1]["state"] == 1
    assert result["nav"][-1]["pending_remaining"] == 0
    assert result["nav"][-1]["pending_side"] == ""


def test_tick_rounding_minimum_commission_and_zero_cost_scenario():
    bars, limits, dates, start = _market(2, price="3.333")
    schedule = {dates[20]: 1, dates[21]: 0}
    cost = simulate(bars, [], limits, schedule, 10, "1000", start)
    buy, sell = cost["orders"]
    assert (buy["price"], buy["notional"], buy["fee"], buy["slippage"]) == ("3.337", "667.40", "5.00", "0.80")
    assert (sell["price"], sell["notional"], sell["fee"], sell["slippage"]) == ("3.329", "665.80", "5.00", "0.80")
    assert cost["nav"][-1]["cash"] == "988.40"
    free = simulate(bars, [], limits, schedule, 0, "1000", start)
    assert all(row["price"] == "3.333" and row["fee"] == "0.00" and row["slippage"] == "0.00" for row in free["orders"])
    assert free["nav"][-1]["equity"] == "1000.00"
    high_cost = simulate(bars, [], limits, schedule, 30, "1000", start)
    assert [row["price"] for row in high_cost["orders"]] == ["3.343", "3.323"]
    assert all(row["fee"] == "5.00" and row["slippage"] == "2.00" for row in high_cost["orders"])
    assert high_cost["nav"][-1]["equity"] == "986.00"


def test_commission_percentage_is_half_up_and_has_no_stock_selling_taxes():
    bars, limits, dates, start = _market(2)
    result = simulate(bars, [], limits, {dates[20]: 1, dates[21]: 0}, 10, "100000", start)
    buy, sell = result["orders"]
    assert (buy["notional"], buy["fee"]) == ("98098.00", "29.43")
    assert (sell["notional"], sell["fee"]) == ("97902.00", "29.37")
    assert result["nav"][-1]["cash"] == "99745.20"


def test_current_high_low_volume_and_turnover_do_not_gate_open_fill():
    bars, limits, dates, start = _market(1)
    ordinary = simulate(bars, [], limits, {dates[20]: 1}, 0, "100000", start)
    altered = [dict(bar) for bar in bars]
    altered[20].update(high="unavailable", low="999999", vol="0", amount="0")
    observed = simulate(altered, [], limits, {dates[20]: 1}, 0, "100000", start)
    assert observed == ordinary
    assert observed["orders"][0]["filled"] == 9800


def test_future_bar_perturbations_do_not_change_earlier_orders_or_nav():
    bars, limits, dates, start = _market(4, amount="1000")
    original = simulate(bars, [], limits, {dates[20]: 1}, 10, "100000", start)
    changed = [dict(bar) for bar in bars]
    for bar in changed[22:]:
        bar.update(open="20.000", close="21.000", amount="0")
    perturbed = simulate(changed, [], limits, {dates[20]: 1}, 10, "100000", start)
    assert perturbed["orders"][:2] == original["orders"][:2]
    assert perturbed["nav"][:3] == original["nav"][:3]


def test_no_prior_twenty_sessions_rejects_then_retries_fixed_intent():
    bars, limits, dates, start = _market(2, warmup=19)
    result = simulate(bars, [], limits, {dates[19]: 1}, 0, "100000", start)
    rejected, filled = result["orders"]
    assert rejected["status"] == "rejected"
    assert rejected["reason"] == "insufficient_prior_history"
    assert rejected["prior_adv"] == "" and rejected["capacity"] == "0.00"
    assert filled["requested"] == rejected["remaining"] == 9800
    assert filled["filled"] == 9800


def test_receivable_is_used_in_target_but_cannot_fund_buy_before_payment():
    bars, limits, dates, start = _market(4)
    result = simulate(bars, [_action(dates, cash="10.0000")], limits,
                      {dates[20]: 1, dates[21]: 0, dates[22]: 1}, 0, "10000", start)
    before_payment = result["nav"][3]
    assert (before_payment["cash"], before_payment["receivable"], before_payment["shares"]) == ("0.00", "9000.00", 1000)
    assert result["orders"][2]["requested"] == 1800
    assert result["orders"][2]["filled"] == 1000
    assert result["orders"][2]["remaining"] == 800
    assert result["orders"][3]["requested"] == 800
    assert result["events"][-1]["cash_after"] == "9000.00"
    assert result["nav"][-1]["cash"] == "1000.00"
    assert result["nav"][-1]["receivable"] == "0.00"
    assert result["nav"][-1]["shares"] == 1800


def test_low_level_t1_preserves_position_and_next_session_can_sell():
    market = {"raw_open": "10.000", "up_limit": "11.000", "down_limit": "9.000",
              "prior_adv": "1000000", "slippage_bps": 10}
    buy = execute_order(side="buy", requested=100, cash="2000", shares=0,
                        sellable=0, **market)
    assert (buy.shares, buy.sellable, buy.cash) == (100, 0, Decimal("994.00"))
    same_day = execute_order(side="sell", requested=100, cash=buy.cash,
                             shares=buy.shares, sellable=buy.sellable, **market)
    assert same_day.status == "rejected" and same_day.reason == "t1"
    assert (same_day.shares, same_day.sellable, same_day.cash) == (100, 0, buy.cash)
    next_day = execute_order(side="sell", requested=100, cash=buy.cash,
                             shares=buy.shares, sellable=buy.shares, **market)
    assert next_day.status == "filled" and next_day.shares == 0


def test_open_limit_slippage_bounds_suspension_and_invalid_price_rejections():
    base = {"side": "buy", "requested": 100, "cash": "2000", "shares": 0,
            "sellable": 0, "raw_open": "10.000", "up_limit": "11.000",
            "down_limit": "9.000", "prior_adv": "1000000", "slippage_bps": 10}
    opening_limit = execute_order(**dict(base, up_limit="10.000"))
    assert opening_limit.status == "rejected" and opening_limit.reason == "opening_price_limit"
    slip_limit = execute_order(**dict(base, raw_open="9.999", up_limit="10.000"))
    assert slip_limit.reason == "slippage_outside_limits"
    suspended = execute_order(**dict(base, suspended_at_open=True))
    assert suspended.reason == "suspended_at_open"
    invalid = execute_order(**dict(base, raw_open="NaN"))
    assert invalid.price is None and invalid.shares == 0 and invalid.cash == Decimal("2000")
    down_limit = execute_order(**dict(base, side="sell", cash="0", shares=100,
                                      sellable=100, raw_open="9.000"))
    assert down_limit.reason == "opening_price_limit" and down_limit.shares == 100
