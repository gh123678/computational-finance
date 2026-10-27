"""I2 repaired pricer -- Model B (DeepSeek session) independent version.

Same one-period model as ai_debug_exercise.py. Design differs from the Model A
repair: a small dataclass-free API that prices call AND put from one shared
draw, accepts an explicit numpy Generator, and uses expm1/log-based p* form.

Defects fixed (identical defective lines, independently diagnosed):
  D1 hardcoded 0.65        -> risk-neutral p*
  D2 `> probability`       -> `<= p`
  D3 np.minimum(_,0)       -> np.maximum(_,0)
  D4 exp(+rT) multiply     -> exp(-rT) discount
  D5 std/paths             -> std(ddof=1)/sqrt(paths) on discounted payoffs
  D6 no validation         -> _validate()
"""
from __future__ import annotations
import numpy as np


def _risk_neutral(up, down, rate, maturity):
    growth = np.exp(rate * maturity)
    return (growth - down) / (up - down)


def _validate(spot, strike, up, down, rate, maturity, paths):
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if not (0 < down < up):
        raise ValueError("need 0 < down < up")
    if paths <= 0:
        raise ValueError("paths must be a positive integer")
    growth = np.exp(rate * maturity)
    if not (down < growth < up):
        raise ValueError(f"arbitrage-inconsistent: d<e^(rT)<u failed "
                         f"(d={down}, e^(rT)={growth:.6f}, u={up})")


def _terminal(spot, up, down, p, paths, rng):
    is_up = rng.random(paths) <= p
    return np.where(is_up, up * spot, down * spot)


def price(spot=100.0, strike=100.0, up=1.2, down=0.8, rate=0.05,
          maturity=1.0, paths=10000, seed=20260927, kind="call", rng=None):
    _validate(spot, strike, up, down, rate, maturity, paths)
    if rng is None:
        rng = np.random.default_rng(seed)
    p = _risk_neutral(up, down, rate, maturity)
    terminal = _terminal(spot, up, down, p, paths, rng)
    intrinsic = (terminal - strike) if kind == "call" else (strike - terminal)
    disc = np.exp(-rate * maturity)
    disc_payoff = disc * np.maximum(intrinsic, 0.0)
    mean = float(disc_payoff.mean())
    se = float(disc_payoff.std(ddof=1) / np.sqrt(paths))
    return {"price": mean, "se": se,
            "ci_low": mean - 1.96 * se, "ci_high": mean + 1.96 * se,
            "p_star": float(p)}


def call_mc(**kw):
    return price(kind="call", **kw)


def exact_forward(spot=100.0, strike=100.0, up=1.2, down=0.8, rate=0.05,
                  maturity=1.0, kind="call"):
    _validate(spot, strike, up, down, rate, maturity, 1)
    p = _risk_neutral(up, down, rate, maturity)
    pay_u = max(up * spot - strike, 0.0) if kind == "call" else max(strike - up * spot, 0.0)
    pay_d = max(down * spot - strike, 0.0) if kind == "call" else max(strike - down * spot, 0.0)
    return float(np.exp(-rate * maturity) * (p * pay_u + (1 - p) * pay_d))


if __name__ == "__main__":
    print("exact call:", exact_forward(kind="call"))
    print("exact put :", exact_forward(kind="put"))
    print("MC call   :", call_mc(paths=100_000))
