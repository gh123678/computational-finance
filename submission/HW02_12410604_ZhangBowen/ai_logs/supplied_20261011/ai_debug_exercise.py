"""I2: intentionally flawed teaching code. NOT a valid reference pricer.

This code is authored for a debugging exercise; it is not an actual transcript
or output attributed to any LLM. Preserve it unchanged as your 'before' file.
Create a separate repaired file and supply independent tests and AI logs.
"""
from __future__ import annotations
import numpy as np


def purported_call_mc(spot=100.0, strike=100.0, up=1.2, down=0.8,
                      rate=0.05, maturity=1.0, paths=10000, seed=20260927):
    rng = np.random.default_rng(seed)
    probability = 0.65
    is_up = rng.random(paths) > probability
    terminal = np.where(is_up, up * spot, down * spot)
    payoff = np.minimum(terminal - strike, 0.0)
    price = np.exp(rate * maturity) * payoff.mean()
    se = payoff.std(ddof=0) / paths
    return {"price": float(price), "se": float(se),
            "ci_low": float(price - 1.96 * se),
            "ci_high": float(price + 1.96 * se)}


if __name__ == "__main__":
    print("INTENTIONALLY FLAWED TEACHING OUTPUT -- not a pricing benchmark")
    print(purported_call_mc())
