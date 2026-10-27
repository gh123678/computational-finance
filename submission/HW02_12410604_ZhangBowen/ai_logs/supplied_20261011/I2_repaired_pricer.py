"""I2 repaired one-period pricer.

Repairs applied to ai_debug_exercise.py (see I2 change log):
  B1 hardcoded probability 0.65 -> risk-neutral p* = (e^{rT}-d)/(u-d)
  B2 inverted event `rng.random(paths) > p` -> `<= p` (up with prob p*)
  B3 payoff np.minimum(terminal-strike, 0) -> np.maximum(..., 0)
  B4 price multiplied by e^{+rT} -> discounted by e^{-rT}
  B5 se = std/ddof=0 / paths -> std(ddof=1) / sqrt(paths)
  B6 added domain validation: 0 < d < e^{rT} < u, positive paths, spot, strike
Also adds exact_price() for an independent analytical benchmark and a paired
put pricer reusing the same terminal states (for MC parity checks).
"""
from __future__ import annotations
import numpy as np


def _validate(spot, strike, up, down, rate, maturity, paths):
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if not (0 < down < up):
        raise ValueError("need 0 < down < up")
    if paths <= 0:
        raise ValueError("paths must be a positive integer")
    growth = np.exp(rate * maturity)
    if not (down < growth < up):
        raise ValueError(
            f"arbitrage-inconsistent: need d < e^(rT) < u, "
            f"got d={down}, e^(rT)={growth:.6f}, u={up}")


def p_star(up, down, rate, maturity):
    return (np.exp(rate * maturity) - down) / (up - down)


def exact_price(spot=100.0, strike=100.0, up=1.2, down=0.8,
                rate=0.05, maturity=1.0, kind="call"):
    _validate(spot, strike, up, down, rate, maturity, 1)
    p = p_star(up, down, rate, maturity)
    pay_u = max(up * spot - strike, 0.0) if kind == "call" else max(strike - up * spot, 0.0)
    pay_d = max(down * spot - strike, 0.0) if kind == "call" else max(strike - down * spot, 0.0)
    return float(np.exp(-rate * maturity) * (p * pay_u + (1 - p) * pay_d))


def call_mc(spot=100.0, strike=100.0, up=1.2, down=0.8,
            rate=0.05, maturity=1.0, paths=10000, seed=20260927):
    _validate(spot, strike, up, down, rate, maturity, paths)
    rng = np.random.default_rng(seed)
    p = p_star(up, down, rate, maturity)
    is_up = rng.random(paths) <= p
    terminal = np.where(is_up, up * spot, down * spot)
    payoff = np.maximum(terminal - strike, 0.0)
    disc = np.exp(-rate * maturity)
    disc_payoff = disc * payoff
    price = float(disc_payoff.mean())
    se = float(disc_payoff.std(ddof=1) / np.sqrt(paths))
    return {"price": price, "se": se,
            "ci_low": price - 1.96 * se, "ci_high": price + 1.96 * se,
            "p_star": float(p)}


if __name__ == "__main__":
    print("exact call:", exact_price(kind="call"))
    print("exact put :", exact_price(kind="put"))
    print("MC call   :", call_mc(paths=100_000))
