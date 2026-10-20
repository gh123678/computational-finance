"""Independent ETF reference calculations and full ledger reconciliation.

This module deliberately imports no production signal, account, or metric helpers.
Inputs are the already admitted raw rows; executing this module alone runs nothing.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import numpy as np


class IndependentAuditError(AssertionError):
    """The independent economic reconstruction does not match the submitted run."""


_CENT = Decimal("0.01")
_TICK = Decimal("0.001")
_ZERO = Decimal(0)
_NAV_MONEY = ("cash", "receivable", "equity", "market_value", "fee_today",
              "slippage_today", "buy_notional", "sell_notional")
_NAV_INT = ("shares", "sellable", "state", "pending_remaining")
_ORDER_MONEY = ("notional", "fee", "slippage", "prior_adv", "capacity")


def _rows(value):
    if hasattr(value, "to_dict") and not isinstance(value, Mapping):
        return [dict(row) for row in value.to_dict("records")]
    if isinstance(value, Mapping):
        raise IndependentAuditError("Expected row records, not a column mapping")
    return [dict(row) for row in value]


def _day(value):
    if hasattr(value, "strftime"):
        value = value.strftime("%Y%m%d")
    value = str(value).strip()
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        value = value[:10].replace("-", "")
    try:
        datetime.strptime(value, "%Y%m%d")
    except (ValueError, TypeError) as error:
        raise IndependentAuditError(f"Invalid date {value!r}") from error
    if len(value) != 8:
        raise IndependentAuditError(f"Noncanonical date {value!r}")
    return value


def _dec(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise IndependentAuditError(f"Invalid decimal {value!r}") from error
    if not result.is_finite():
        raise IndependentAuditError(f"Nonfinite decimal {value!r}")
    return result


def _money(value):
    return _dec(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def _text_money(value):
    return format(_money(value), ".2f")


def _integer(value):
    number = _dec(value)
    if number != number.to_integral_value():
        raise IndependentAuditError(f"Noninteger shares/state {value!r}")
    return int(number)


def _normal_bars(bars):
    result = []
    for source in _rows(bars):
        row = dict(source)
        row["date"] = _day(row.get("trade_date", row.get("date")))
        result.append(row)
    dates = [row["date"] for row in result]
    if not result or dates != sorted(dates) or len(dates) != len(set(dates)):
        raise IndependentAuditError("Bars must be nonempty, strictly date-ordered and unique")
    return result


def _normal_actions(actions):
    result = []
    ids = set()
    for source in _rows(actions):
        row = dict(source)
        for name in ("ann_date", "record_date", "ex_date", "pay_date"):
            row[name] = _day(row[name])
        row["cash"] = _dec(row["cash_per_share"])
        if row["cash"] < 0:
            raise IndependentAuditError("Negative cash distribution")
        if not row["ann_date"] <= row["record_date"] < row["ex_date"] <= row["pay_date"]:
            raise IndependentAuditError("Invalid action chronology")
        if row["ann_date"] in ids:
            raise IndependentAuditError("Duplicate economic event id in admitted actions")
        ids.add(row["ann_date"])
        result.append(row)
    return sorted(result, key=lambda item: (item["ann_date"], item["ex_date"]))


def independently_prepare(bars, actions, evaluation_start="20180101", evaluation_end="20251231"):
    """Build K, 108 monthly observations and a date->state evaluation schedule.

    Completeness against the exchange calendar is an admission responsibility;
    this separately requires all 108 fixed calendar months and ordered dates.
    The returned row tables are lists of dictionaries, with numeric float64
    results exposed as Python floats. No account is opened by this function.
    """
    rows = _normal_bars(bars)
    evaluation_start, evaluation_end = _day(evaluation_start), _day(evaluation_end)
    distributions = _normal_actions(actions)
    cash_by_ex = {}
    for action in distributions:
        cash_by_ex[action["ex_date"]] = (
            cash_by_ex.get(action["ex_date"], _ZERO) + action["cash"]
        )
    daily = []
    previous_close = None
    k = np.float64(1.0)
    for row in rows:
        close = np.float64(str(row["close"]))
        if not np.isfinite(close) or close <= 0:
            raise IndependentAuditError("Invalid raw close in reference index")
        distribution = np.float64(str(cash_by_ex.get(row["date"], _ZERO)))
        if previous_close is not None:
            k = np.float64(k * ((close + distribution) / previous_close))
        if not np.isfinite(k):
            raise IndependentAuditError("Nonfinite conditional total-return index")
        daily.append({"date": row["date"], "k": float(k),
                      "dividend_per_share": float(distribution)})
        previous_close = close
    ends = {}
    for index, row in enumerate(daily):
        ends[row["date"][:6]] = index
    expected_months = [f"{year}{month:02d}" for year in range(2017, 2026)
                       for month in range(1, 13)]
    if rows[0]["date"][:6] == "201701" and rows[-1]["date"][:6] == "202512":
        if list(ends) != expected_months:
            raise IndependentAuditError("Fixed reference needs all 108 months 2017-2025")
    monthly = []
    state = 0
    schedule = {}
    for month, last_index in ends.items():
        point = daily[last_index]
        monthly.append({"date": point["date"], "k": point["k"], "sma10": None,
                        "state": state,
                        "execution_date": daily[last_index + 1]["date"]
                        if last_index + 1 < len(daily) else ""})
        if len(monthly) >= 10:
            total = np.float64(0.0)
            for prior in monthly[-10:]:
                total = np.float64(total + np.float64(prior["k"]))
            average = np.float64(total / np.float64(10.0))
            if not np.isfinite(average):
                raise IndependentAuditError("Nonfinite ten-month mean")
            current = np.float64(point["k"])
            if current > average:
                state = 1
            elif current < average:
                state = 0
            monthly[-1]["sma10"] = float(average)
            monthly[-1]["state"] = state
            execute = monthly[-1]["execution_date"]
            if execute and evaluation_start <= execute <= evaluation_end:
                schedule[execute] = state
    return {"daily": daily, "monthly": monthly, "schedule": schedule}


def _schedule_rows(schedule):
    if isinstance(schedule, Mapping):
        pairs = list(schedule.items())
    else:
        pairs = [(row["date"], row["state"]) for row in _rows(schedule)]
    normalized = {}
    for date, state in pairs:
        date = _day(date)
        state = _integer(state)
        if state not in (0, 1) or date in normalized:
            raise IndependentAuditError("Schedule contains duplicate dates or nonbinary states")
        normalized[date] = state
    return normalized


def _suspended(value):
    if isinstance(value, bool):
        return value
    if str(value).strip().lower() in ("", "0", "false", "none", "nan"):
        return False
    if str(value).strip().lower() in ("1", "true"):
        return True
    raise IndependentAuditError("Ambiguous suspended_at_open flag")


def _fee(notional, bps):
    return _ZERO if bps == 0 else _money(max(Decimal("5"), notional * Decimal("0.0003")))


def _quote(raw, side, bps):
    fraction = Decimal(bps) / Decimal(10000)
    unrounded = raw * (1 + fraction if side == "buy" else 1 - fraction)
    direction = ROUND_CEILING if side == "buy" else ROUND_FLOOR
    return (unrounded / _TICK).to_integral_value(rounding=direction) * _TICK


def _expected_ledger(bars, actions, limits, schedule, bps, initial_cash, evaluation_start):
    rows = _normal_bars(bars)
    actions = _normal_actions(actions)
    schedule = _schedule_rows(schedule)
    evaluation_start = _day(evaluation_start)
    previous = [row for row in rows if row["date"] < evaluation_start]
    active = [row for row in rows if row["date"] >= evaluation_start]
    if not previous or not active:
        raise IndependentAuditError("Need an evaluation range and a pre-evaluation baseline")
    active_dates = {row["date"] for row in active}
    if not set(schedule).issubset(active_dates):
        raise IndependentAuditError("Schedule date is not an admitted evaluation trading date")
    limit_map = {}
    for limit in _rows(limits):
        date = _day(limit.get("trade_date", limit.get("date")))
        if date in limit_map:
            raise IndependentAuditError("Duplicate daily price boundary")
        limit_map[date] = (_dec(limit["down_limit"]), _dec(limit["up_limit"]))
    if not active_dates.issubset(limit_map):
        raise IndependentAuditError("Missing daily historical price boundary")
    if bps not in (0, 10, 30):
        raise IndependentAuditError("Only the frozen 0/10/30bp cases are allowed")
    cash = _money(initial_cash)
    if cash <= 0:
        raise IndependentAuditError("Initial cash must be positive")
    shares = 0
    state = 0
    pending_side = ""
    pending_remaining = 0
    receivable = _ZERO
    locked = {}
    due = {}
    nav, orders, events = [], [], []
    baseline = previous[-1]["date"]

    def event(date, kind, action, entitlement, amount):
        events.append({"date": date, "kind": kind, "event_id": action["ann_date"],
                       "shares": entitlement, "amount": _text_money(amount),
                       "cash_after": _text_money(cash),
                       "receivable_after": _text_money(receivable)})

    def mark(date, close, sellable, fee_today=_ZERO, slippage_today=_ZERO,
             buy_notional=_ZERO, sell_notional=_ZERO):
        market_value = _money(close * shares)
        return {"date": date, "cash": _text_money(cash), "shares": shares,
                "sellable": sellable, "receivable": _text_money(receivable),
                "equity": _text_money(cash + receivable + market_value),
                "market_value": _text_money(market_value), "state": state,
                "pending_side": pending_side, "pending_remaining": pending_remaining,
                "fee_today": _text_money(fee_today),
                "slippage_today": _text_money(slippage_today),
                "buy_notional": _text_money(buy_notional),
                "sell_notional": _text_money(sell_notional)}

    nav.append(mark(baseline, _dec(previous[-1]["close"]), 0))
    for index, row in enumerate(rows):
        date = row["date"]
        if date < evaluation_start:
            continue
        old_shares = shares
        sellable = old_shares
        for action in actions:
            if action["ex_date"] == date:
                entitlement = locked.get(action["ann_date"], 0)
                amount = _money(action["cash"] * entitlement)
                due[action["ann_date"]] = amount
                receivable = _money(receivable + amount)
                event(date, "ex", action, entitlement, amount)
        for action in actions:
            if action["pay_date"] == date:
                entitlement = locked.get(action["ann_date"], 0)
                amount = due.pop(action["ann_date"], _ZERO)
                cash = _money(cash + amount)
                receivable = _money(receivable - amount)
                event(date, "pay", action, entitlement, amount)
        try:
            raw_open = _dec(row["open"])
        except IndependentAuditError:
            raw_open = _ZERO
        if date in schedule and schedule[date] != state:
            state = schedule[date]
            pending_side, pending_remaining = "", 0
            if state == 0:
                pending_side = "sell" if shares else ""
                pending_remaining = shares
            else:
                if raw_open <= 0:
                    raise IndependentAuditError("Cannot define a new long target at an invalid raw open")
                open_equity = cash + receivable + shares * raw_open
                total_target = int((open_equity * Decimal("0.98") / raw_open / Decimal(100))
                                   .to_integral_value(rounding=ROUND_FLOOR)) * 100
                pending_remaining = max(total_target - shares, 0)
                pending_side = "buy" if pending_remaining else ""
        fee_today = slippage_today = buy_notional = sell_notional = _ZERO
        if pending_remaining:
            requested = pending_remaining
            lower, upper = limit_map[date]
            if lower <= 0 or upper < lower:
                raise IndependentAuditError("Invalid historical price boundary")
            prior_adv = None
            capacity = _ZERO
            if index >= 20:
                amounts = [_dec(day["amount"]) for day in rows[index - 20:index]]
                if any(amount < 0 for amount in amounts):
                    raise IndependentAuditError("Negative prior amount")
                prior_adv = sum(amounts, _ZERO) * Decimal(1000) / Decimal(20)
                capacity = prior_adv * Decimal("0.005")
            price = _quote(raw_open, pending_side, bps) if raw_open > 0 else None
            invalid = (raw_open <= 0 or _suspended(row.get("suspended_at_open", False))
                       or (pending_side == "buy" and raw_open >= upper)
                       or (pending_side == "sell" and raw_open <= lower)
                       or price is None or price <= 0 or price < lower or price > upper
                       or prior_adv is None)
            filled = 0
            if not invalid and price is not None:
                capacity_quantity = int((capacity / price / Decimal(100))
                                        .to_integral_value(rounding=ROUND_FLOOR)) * 100
                filled = min(requested, capacity_quantity)
                if pending_side == "sell":
                    filled = min(filled, sellable)
                else:
                    affordable = int((cash / price / Decimal(100))
                                     .to_integral_value(rounding=ROUND_FLOOR)) * 100
                    filled = min(filled, affordable)
                    while filled > 0 and price * filled + _fee(price * filled, bps) > cash:
                        filled -= 100
                filled = max(0, filled)
            notional = _money(price * filled) if price is not None else _ZERO
            fee_today = _fee(notional, bps) if filled else _ZERO
            slippage_today = _money(abs(price - raw_open) * filled) if price is not None else _ZERO
            side = pending_side
            if side == "buy":
                cash = _money(cash - notional - fee_today)
                shares += filled
                buy_notional = notional
            else:
                cash = _money(cash + notional - fee_today)
                shares -= filled
                sellable -= filled
                sell_notional = notional
            pending_remaining -= filled
            orders.append({"date": date, "side": side, "requested": requested,
                           "filled": filled, "raw_open": str(row["open"]),
                           "price": str(price) if price is not None else "",
                           "notional": _text_money(notional), "fee": _text_money(fee_today),
                           "slippage": _text_money(slippage_today),
                           "prior_adv": _text_money(prior_adv) if prior_adv is not None else "",
                           "capacity": _text_money(capacity),
                           "status": "filled" if filled == requested else "partial" if filled else "rejected",
                           "remaining": pending_remaining})
            if pending_remaining == 0:
                pending_side = ""
        for action in actions:
            if action["record_date"] == date:
                locked[action["ann_date"]] = shares
                event(date, "record", action, shares, _money(shares * action["cash"]))
        close = _dec(row["close"])
        if close <= 0 or cash < 0 or shares < 0 or receivable < 0 or not 0 <= sellable <= shares:
            raise IndependentAuditError("Invalid reconstructed cash, shares, receivable or mark")
        nav.append(mark(date, close, sellable, fee_today, slippage_today, buy_notional, sell_notional))
    return {"nav": nav, "orders": orders, "events": events}


def _same_decimal(actual, expected, context, money=False):
    if expected == "":
        if str(actual) != "":
            raise IndependentAuditError(f"{context}: expected an empty unavailable value")
        return
    left, right = _dec(actual), _dec(expected)
    if money:
        right = _money(right)
    if left != right:
        raise IndependentAuditError(f"{context}: {actual!r} != independent {expected!r}")


def _compare_rows(kind, actual_rows, expected_rows, integer_fields, money_fields,
                  text_fields, price_fields=()):
    actual_rows = _rows(actual_rows)
    if len(actual_rows) != len(expected_rows):
        raise IndependentAuditError(f"{kind} row count {len(actual_rows)} != {len(expected_rows)}")
    actual_dates = [_day(row.get("date", row.get("trade_date"))) for row in actual_rows]
    expected_dates = [row["date"] for row in expected_rows]
    if actual_dates != expected_dates or set(actual_dates) != set(expected_dates):
        raise IndependentAuditError(f"{kind} dates/order differ from independent reconstruction")
    for index, (actual, expected) in enumerate(zip(actual_rows, expected_rows)):
        prefix = f"{kind}[{index}] {expected['date']}"
        for field in integer_fields:
            if field not in actual or _integer(actual[field]) != expected[field]:
                raise IndependentAuditError(f"{prefix} {field} differs")
        for field in money_fields:
            if field not in actual:
                raise IndependentAuditError(f"{prefix} missing {field}")
            _same_decimal(actual[field], expected[field], prefix + " " + field, money=True)
        for field in price_fields:
            if field not in actual:
                raise IndependentAuditError(f"{prefix} missing {field}")
            _same_decimal(actual[field], expected[field], prefix + " " + field)
        for field in text_fields:
            if field not in actual or str(actual[field]) != expected[field]:
                raise IndependentAuditError(f"{prefix} {field} differs")
    return actual_rows


def audit_case(bars, actions, limits, schedule, slippage_bps, result,
               initial_cash="1000000.00", evaluation_start="20180101"):
    """Reconstruct every daily field, attempted order and entitlement independently.

    This admitted case has only ordinary cash distributions and 100-unit buys,
    so every actual holding is a whole lot. No share-conversion or odd-lot
    initial-holding scenario is admitted by this interface.

    Raises IndependentAuditError on the first mismatch. In particular, an
    internally balanced forged NAV or omitted rejected order cannot pass.
    """
    expected = _expected_ledger(bars, actions, limits, schedule, slippage_bps,
                                initial_cash, evaluation_start)
    for name in ("nav", "orders", "events"):
        if name not in result:
            raise IndependentAuditError(f"Missing result table {name}")
    nav = _compare_rows("nav", result["nav"], expected["nav"], _NAV_INT,
                        _NAV_MONEY, ("pending_side",))
    _compare_rows("orders", result["orders"], expected["orders"],
                  ("requested", "filled", "remaining"), _ORDER_MONEY,
                  ("side", "status"), ("raw_open", "price"))
    _compare_rows("events", result["events"], expected["events"], ("shares",),
                  ("amount", "cash_after", "receivable_after"), ("kind", "event_id"))
    boundaries = []
    evaluation_nav = nav[1:]
    for prior, current in zip(evaluation_nav, evaluation_nav[1:]):
        prior_date, current_date = _day(prior["date"]), _day(current["date"])
        if prior_date[:4] != current_date[:4]:
            boundaries.append({"from_date": prior_date, "to_date": current_date,
                               "status": "PASS",
                               "checked_fields": list(_NAV_INT) + list(_NAV_MONEY) + ["pending_side"]})
    return {"status": "PASS", "days": len(evaluation_nav),
            "baseline_date": expected["nav"][0]["date"],
            "orders_checked": len(expected["orders"]),
            "events_checked": len(expected["events"]),
            "year_boundaries": boundaries,
            "all_daily_fields_independently_reconstructed": True,
            "production_helpers_imported": False}


