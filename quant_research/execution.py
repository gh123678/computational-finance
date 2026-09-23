"""One-order accounting primitive for a main-board research simulator.

Prices are unadjusted. Fees are caller-supplied scenarios, not verified broker
tariffs. Corporate actions must be applied by a separate daily event ledger.
"""
from dataclasses import dataclass
from math import isfinite
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


@dataclass(frozen=True)
class FeeSchedule:
    commission: float = .0003
    minimum_commission: float = 5.
    sell_tax: float = .0005
    transfer: float = .00001
    slippage_bps: float = 10.

    def __post_init__(self):
        if any(not isfinite(x) or x < 0 for x in (self.commission, self.minimum_commission, self.sell_tax, self.transfer, self.slippage_bps)):
            raise ValueError('Fee assumptions must be finite and nonnegative.')
        if self.slippage_bps >= 10000:
            raise ValueError('Slippage must be below 100%.')

    def cost(self, notional, side):
        if side not in ('buy', 'sell') or not isfinite(notional) or notional < 0:
            raise ValueError('Invalid side/notional.')
        if notional == 0:
            return 0.
        return round(max(self.minimum_commission, notional * self.commission)
                     + notional * self.transfer + (notional * self.sell_tax if side == 'sell' else 0), 2)


@dataclass(frozen=True)
class Fill:
    status: str
    reason: str
    shares: int
    price: float
    fee: float
    cash_after: float
    shares_after: int
    sellable_after: int


def execute_order(*, side, requested, cash, held, sellable, raw_open,
                  up_limit, down_limit, suspended, prior_adv_cny,
                  fees=FeeSchedule(), participation=.005):
    """Apply one order; buys cannot become sellable in the current session.

    Caller resets sellable at the next session after processing corporate events.
    Never use today's final turnover to set prior_adv_cny.
    """
    if side not in ('buy', 'sell'):
        raise ValueError('side must be buy or sell')
    if any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in (requested, held, sellable)) or sellable > held:
        raise ValueError('Invalid integer share quantities')
    if not isfinite(cash) or cash < 0 or not isfinite(participation) or not 0 < participation <= 1:
        raise ValueError('Invalid cash or participation')

    def reject(reason):
        return Fill('rejected', reason, 0, 0., 0., cash, held, sellable)

    if suspended:
        return reject('suspended')
    if any(not isfinite(x) or x <= 0 for x in (raw_open, up_limit, down_limit, prior_adv_cny)):
        return reject('missing_or_invalid_market_data')
    if down_limit > up_limit or raw_open < down_limit - 1e-8 or raw_open > up_limit + 1e-8:
        return reject('inconsistent_price_limits')
    if (side == 'buy' and raw_open >= up_limit - 1e-8) or (side == 'sell' and raw_open <= down_limit + 1e-8):
        return reject('price_limit')
    price = raw_open * (1 + fees.slippage_bps / 10000 * (1 if side == 'buy' else -1))
    price = float(Decimal(str(price)).quantize(Decimal('0.01'), rounding=ROUND_CEILING if side == 'buy' else ROUND_FLOOR))
    if price > up_limit + 1e-8 or price < down_limit - 1e-8 or price <= 0:
        return reject('slippage_outside_limits')
    capacity = int(prior_adv_cny * participation / price)
    qty = min(requested, capacity)
    if side == 'buy':
        qty = min(qty, int(cash / price)) // 100 * 100
        while qty > 0 and round(qty * price, 2) + fees.cost(qty * price, side) > cash + 1e-8:
            qty -= 100
    else:
        qty = min(qty, sellable)
        # Permit complete liquidation of odd shares; otherwise sell whole lots.
        if qty != held:
            qty = qty // 100 * 100
    if qty <= 0:
        return reject('cash_capacity_lot_or_t1')
    notional = round(qty * price, 2)
    fee = fees.cost(notional, side)
    if side == 'buy':
        return Fill('filled', '', qty, price, fee, round(cash - notional - fee, 2), held + qty, sellable)
    cash_after = round(cash + notional - fee, 2)
    if cash_after < 0:
        return reject('insufficient_cash_for_fee')
    return Fill('filled', '', qty, price, fee, cash_after, held - qty, sellable - qty)
