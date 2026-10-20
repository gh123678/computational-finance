"""Independent, decimal-based ledger for the approved single-ETF experiment.

Inputs are admitted, unadjusted CSV rows in ascending trading-date order. The
caller supplies only already formed monthly execution dates in ``schedule``.
No signal is formed here, and importing this module never runs an account.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext


CENT = Decimal("0.01")
TICK = Decimal("0.001")
LOT = 100
PARTICIPATION = Decimal("0.005")
COMMISSION = Decimal("0.0003")


def _number(value, label: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {label}") from exc
    if not result.is_finite():
        raise ValueError(f"Nonfinite {label}")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _money_text(value: Decimal) -> str:
    return format(_money(value), ".2f")


def _date(value, label: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError(f"Invalid {label}: expected YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"Invalid {label}") from exc
    return value


def _suspended(value) -> bool:
    if value in (None, False, 0, "", "0", "false", "False"):
        return False
    if value in (True, 1, "1", "true", "True"):
        return True
    raise ValueError("suspended_at_open must be explicitly true or false")


@dataclass(frozen=True)
class Fill:
    """One opening attempt; ``sellable`` excludes shares bought today."""

    status: str
    reason: str
    filled: int
    price: Decimal | None
    notional: Decimal
    fee: Decimal
    slippage: Decimal
    cash: Decimal
    shares: int
    sellable: int
    capacity: Decimal


def execute_order(*, side: str, requested: int, cash, shares: int, sellable: int,
                  raw_open, up_limit, down_limit, prior_adv,
                  slippage_bps: int, suspended_at_open: bool = False) -> Fill:
    """Apply one ETF order without looking at current turnover or high/low.

    ``prior_adv`` is the exact mean of 20 prior complete sessions, in CNY, or
    None when that history is unavailable. Zero basis points disable both
    commission and slippage. This is a research fill primitive, not an order API.
    """
    with localcontext() as context:
        context.prec = 40
        return _execute_order(
            side=side, requested=requested, cash=cash, shares=shares,
            sellable=sellable, raw_open=raw_open, up_limit=up_limit,
            down_limit=down_limit, prior_adv=prior_adv,
            slippage_bps=slippage_bps, suspended_at_open=suspended_at_open,
        )


def _execute_order(*, side, requested, cash, shares, sellable, raw_open,
                   up_limit, down_limit, prior_adv, slippage_bps,
                   suspended_at_open):
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if any(type(n) is not int or n < 0 for n in (requested, shares, sellable)) or sellable > shares:
        raise ValueError("Invalid share quantities")
    if type(slippage_bps) is not int or not 0 <= slippage_bps < 10000:
        raise ValueError("slippage_bps must be a nonnegative integer below 10000")
    cash = _number(cash, "cash")
    if cash < 0:
        raise ValueError("Negative cash")
    capacity = Decimal(0)
    adv = None if prior_adv is None else _number(prior_adv, "prior_adv")
    if adv is not None:
        if adv < 0:
            raise ValueError("Negative prior_adv")
        capacity = adv * PARTICIPATION
    price = None

    def reject(reason):
        return Fill("rejected", reason, 0, price, Decimal(0), Decimal(0),
                    Decimal(0), cash, shares, sellable, capacity)

    try:
        opening = _number(raw_open, "raw_open")
        upper = _number(up_limit, "up_limit")
        lower = _number(down_limit, "down_limit")
    except ValueError:
        return reject("invalid_open_or_limits")
    if min(opening, upper, lower) <= 0 or lower > upper or not lower <= opening <= upper:
        return reject("invalid_open_or_limits")
    rate = Decimal(slippage_bps) / Decimal(10000)
    multiplier = Decimal(1) + rate if side == "buy" else Decimal(1) - rate
    price = (opening * multiplier).quantize(
        TICK, rounding=ROUND_CEILING if side == "buy" else ROUND_FLOOR)
    if _suspended(suspended_at_open):
        return reject("suspended_at_open")
    if (side == "buy" and opening == upper) or (side == "sell" and opening == lower):
        return reject("opening_price_limit")
    if price <= 0 or not lower <= price <= upper:
        return reject("slippage_outside_limits")
    if adv is None:
        return reject("insufficient_prior_history")

    capacity_shares = int((capacity / price).to_integral_value(rounding=ROUND_FLOOR))
    quantity = min(requested, capacity_shares)
    constraints = []
    if capacity_shares < requested:
        constraints.append("capacity")
    if side == "buy":
        affordable = int((cash / price).to_integral_value(rounding=ROUND_FLOOR))
        if affordable < quantity:
            constraints.append("cash")
        quantity = min(quantity, affordable) // LOT * LOT
    else:
        if sellable < quantity:
            constraints.append("t1")
        quantity = min(quantity, sellable)
        # Full liquidation may sell a residual odd lot; buys create whole lots.
        if quantity != shares:
            quantity = quantity // LOT * LOT

    def commission(notional):
        return Decimal(0) if slippage_bps == 0 else _money(max(Decimal(5), notional * COMMISSION))

    if side == "buy":
        while quantity > 0:
            notional = _money(price * quantity)
            if notional + commission(notional) <= cash:
                break
            if "cash" not in constraints:
                constraints.append("cash")
            quantity -= LOT
    if quantity <= 0:
        return reject("+".join(constraints) or "lot_or_zero_request")
    notional = _money(price * quantity)
    fee = commission(notional)
    cash_after = _money(cash - notional - fee if side == "buy" else cash + notional - fee)
    if cash_after < 0:
        return reject("insufficient_cash_for_fee")
    shares_after = shares + quantity if side == "buy" else shares - quantity
    sellable_after = sellable if side == "buy" else sellable - quantity
    status = "filled" if quantity == requested else "partial"
    reason = "" if status == "filled" else "+".join(constraints) or "lot"
    return Fill(status, reason, quantity, price, notional, fee,
                _money(abs(price - opening) * quantity), cash_after,
                shares_after, sellable_after, capacity)


def _actions_by_date(actions, trading_dates, evaluation_start, last_date):
    grouped = {kind: defaultdict(list) for kind in ("record", "ex", "pay")}
    seen_ids = {}
    seen_ex_dates = {}
    for row in actions:
        if row.get("ts_code", "510330.SH") != "510330.SH":
            raise ValueError("Only 510330.SH actions are permitted")
        event = {field: _date(row[field], field) for field in
                 ("ann_date", "record_date", "ex_date", "pay_date")}
        event["cash_per_share"] = _number(row["cash_per_share"], "cash_per_share")
        if event["cash_per_share"] < 0:
            raise ValueError("Negative cash distribution")
        if not event["ann_date"] <= event["record_date"] < event["ex_date"] <= event["pay_date"]:
            raise ValueError("Inconsistent dividend dates")
        event_id = event["ann_date"]
        if event_id in seen_ids:
            if seen_ids[event_id] != event:
                raise ValueError("Conflicting duplicate dividend event")
            continue
        if event["ex_date"] in seen_ex_dates:
            raise ValueError("Unresolved duplicate economic dividend event")
        seen_ids[event_id] = event
        seen_ex_dates[event["ex_date"]] = event_id
        for kind, field in (("record", "record_date"), ("ex", "ex_date"), ("pay", "pay_date")):
            day = event[field]
            if evaluation_start <= day <= last_date and day not in trading_dates:
                raise ValueError(f"Dividend {kind} date has no admitted bar")
            grouped[kind][day].append(event)
    for calendar in grouped.values():
        for values in calendar.values():
            values.sort(key=lambda event: event["ann_date"])
    return grouped


def simulate(bars: list[dict], actions: list[dict], limits: list[dict],
             schedule: dict[str, int], slippage_bps: int,
             initial_cash="1000000.00", evaluation_start="20180101") -> dict:
    """Return nav, order-attempt and dividend-event rows for one fixed path.

    At least one bar must precede evaluation_start to supply the cash baseline.
    Amount is the raw vendor field in thousands of CNY. The optional
    suspended_at_open flag is used only when explicitly supplied; absent flags
    carry the admitted ordinary quoted-opening assumption.
    """
    with localcontext() as context:
        context.prec = 40
        return _simulate(bars, actions, limits, schedule, slippage_bps,
                         initial_cash, evaluation_start)


def _simulate(bars, actions, limits, schedule, slippage_bps, initial_cash, evaluation_start):
    evaluation_start = _date(evaluation_start, "evaluation_start")
    if type(slippage_bps) is not int or not 0 <= slippage_bps < 10000:
        raise ValueError("Invalid slippage_bps")
    cash = _money(_number(initial_cash, "initial_cash"))
    if cash < 0:
        raise ValueError("Negative initial_cash")
    days = []
    amounts = []
    closes = []
    for bar in bars:
        day = _date(bar["trade_date"], "trade_date")
        if days and day <= days[-1]:
            raise ValueError("Bars must have unique ascending dates")
        if bar.get("ts_code", "510330.SH") != "510330.SH":
            raise ValueError("Only 510330.SH bars are permitted")
        close = _number(bar["close"], "close")
        amount = _number(bar["amount"], "amount")
        if close <= 0 or amount < 0:
            raise ValueError("Invalid close or amount")
        days.append(day)
        closes.append(close)
        amounts.append(amount * Decimal(1000))
    before = [index for index, day in enumerate(days) if day < evaluation_start]
    evaluation = [index for index, day in enumerate(days) if day >= evaluation_start]
    if not before or not evaluation:
        raise ValueError("A pre-evaluation baseline and evaluation bars are required")
    date_set = set(days)
    limit_by_date = {}
    for row in limits:
        day = _date(row["trade_date"], "limit trade_date")
        if day in limit_by_date:
            raise ValueError("Duplicate limit date")
        limit_by_date[day] = row
    if any(days[index] not in limit_by_date for index in evaluation):
        raise ValueError("Missing evaluation-day limit input")
    for day, state in schedule.items():
        _date(day, "schedule date")
        if day not in date_set or day < evaluation_start or type(state) is not int or state not in (0, 1):
            raise ValueError("Invalid execution schedule")
    dividend_dates = _actions_by_date(actions, date_set, evaluation_start, days[-1])
    shares = 0
    sellable = 0
    receivable = Decimal(0)
    state = 0
    pending_side = ""
    pending_remaining = 0
    locked = {}
    open_receivables = {}
    orders = []
    events = []
    nav = [{"date": days[before[-1]], "cash": _money_text(cash), "shares": 0,
            "sellable": 0, "receivable": "0.00", "equity": _money_text(cash),
            "market_value": "0.00", "state": 0, "pending_side": "",
            "pending_remaining": 0, "fee_today": "0.00", "slippage_today": "0.00",
            "buy_notional": "0.00", "sell_notional": "0.00"}]

    def append_event(day, kind, event, locked_shares, amount):
        events.append({"date": day, "kind": kind, "event_id": event["ann_date"],
                       "shares": locked_shares, "amount": _money_text(amount),
                       "cash_after": _money_text(cash),
                       "receivable_after": _money_text(receivable)})

    for index in evaluation:
        day = days[index]
        bar = bars[index]
        sellable = shares  # Yesterday's buys become sellable only at this open.
        fee_today = Decimal(0)
        slippage_today = Decimal(0)
        buy_notional = Decimal(0)
        sell_notional = Decimal(0)

        for event in dividend_dates["ex"].get(day, []):
            event_id = event["ann_date"]
            entitled = locked.get(event_id, 0)
            amount = _money(Decimal(entitled) * event["cash_per_share"])
            open_receivables[event_id] = amount
            receivable = _money(receivable + amount)
            append_event(day, "ex", event, entitled, amount)
        for event in dividend_dates["pay"].get(day, []):
            event_id = event["ann_date"]
            amount = open_receivables.pop(event_id, Decimal(0))
            cash = _money(cash + amount)
            receivable = _money(receivable - amount)
            append_event(day, "pay", event, locked.get(event_id, 0), amount)

        new_state = schedule.get(day, state)
        if new_state != state:
            state = new_state
            pending_side = ""
            pending_remaining = 0
            if state == 1:
                opening = _number(bar["open"], "entry open")
                if opening <= 0:
                    raise ValueError("Cannot fix entry target at invalid open")
                open_equity = cash + Decimal(shares) * opening + receivable
                total_target = int((Decimal("0.98") * open_equity / opening / LOT)
                                   .to_integral_value(rounding=ROUND_FLOOR)) * LOT
                pending_remaining = max(total_target - shares, 0)
                pending_side = "buy" if pending_remaining else ""
            elif shares:
                pending_side = "sell"
                pending_remaining = shares

        if pending_remaining:
            prior_adv = sum(amounts[index - 20:index], Decimal(0)) / Decimal(20) if index >= 20 else None
            boundary = limit_by_date[day]
            requested = pending_remaining
            fill = execute_order(
                side=pending_side, requested=requested, cash=cash, shares=shares,
                sellable=sellable, raw_open=bar["open"], up_limit=boundary["up_limit"],
                down_limit=boundary["down_limit"], prior_adv=prior_adv,
                slippage_bps=slippage_bps,
                suspended_at_open=_suspended(bar.get("suspended_at_open")),
            )
            cash, shares, sellable = fill.cash, fill.shares, fill.sellable
            pending_remaining -= fill.filled
            orders.append({"date": day, "side": pending_side, "requested": requested,
                           "filled": fill.filled, "raw_open": str(bar["open"]),
                           "price": "" if fill.price is None else format(fill.price, ".3f"),
                           "notional": _money_text(fill.notional), "fee": _money_text(fill.fee),
                           "slippage": _money_text(fill.slippage),
                           "prior_adv": "" if prior_adv is None else _money_text(prior_adv),
                           "capacity": _money_text(fill.capacity), "status": fill.status,
                           "reason": fill.reason, "remaining": pending_remaining})
            fee_today = fill.fee
            slippage_today = fill.slippage
            if pending_side == "buy":
                buy_notional = fill.notional
            else:
                sell_notional = fill.notional
            if pending_remaining == 0:
                pending_side = ""

        for event in dividend_dates["record"].get(day, []):
            locked[event["ann_date"]] = shares
            amount = _money(Decimal(shares) * event["cash_per_share"])
            append_event(day, "record", event, shares, amount)
        market_value = _money(Decimal(shares) * closes[index])
        equity = _money(cash + receivable + market_value)
        nav.append({"date": day, "cash": _money_text(cash), "shares": shares,
                    "sellable": sellable, "receivable": _money_text(receivable),
                    "equity": _money_text(equity), "market_value": _money_text(market_value),
                    "state": state, "pending_side": pending_side,
                    "pending_remaining": pending_remaining, "fee_today": _money_text(fee_today),
                    "slippage_today": _money_text(slippage_today),
                    "buy_notional": _money_text(buy_notional),
                    "sell_notional": _money_text(sell_notional)})
        if cash < 0 or receivable < 0 or not 0 <= sellable <= shares:
            raise ValueError("Account conservation invariant failed")
    return {"nav": nav, "orders": orders, "events": events}
