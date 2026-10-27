"""AI-assisted repair, not a fabricated interaction or student pre-AI attempt.

Independent implementation: does not call student_tasks pricing functions.
"""
import numpy as np


def purported_call_mc(spot=100., strike=100., up=1.2, down=.8, rate=.05,
                      maturity=1., paths=10000, seed=20260927):
    values = np.asarray([spot,strike,up,down,rate,maturity],dtype=float)
    if not np.all(np.isfinite(values)) or spot <= 0 or strike < 0 or maturity <= 0:
        raise ValueError('invalid finite model parameters')
    growth = np.exp(rate*maturity)
    if not 0 < down < growth < up:
        raise ValueError('arbitrage-inconsistent tree')
    if isinstance(paths,(bool,np.bool_)) or not isinstance(paths,(int,np.integer)) or paths < 2:
        raise ValueError('paths must be an integer >=2')
    probability = (growth-down)/(up-down)
    rng = np.random.default_rng(seed)
    is_up = rng.random(paths) < probability
    terminal = np.where(is_up,up*spot,down*spot)
    discounted = np.exp(-rate*maturity)*np.maximum(terminal-strike,0.)
    price = float(discounted.mean())
    se = float(discounted.std(ddof=1)/np.sqrt(paths))
    return {'price':price,'se':se,'ci_low':price-1.96*se,'ci_high':price+1.96*se}
