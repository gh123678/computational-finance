"""MA216 HW-02 implementations. AI-assisted; see ai_logs/ai_use_declaration.md."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.stats import norm

FloatArray = NDArray[np.float64]


def _finite(value, name):
    a = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(a)):
        raise ValueError(f'{name} must be finite')
    return a


def _scalar(value, name, lower=None, strict=False):
    a = _finite(value, name)
    if a.ndim != 0:
        raise ValueError(f'{name} must be scalar')
    x = float(a)
    if lower is not None and (x <= lower if strict else x < lower):
        raise ValueError(f'{name} outside domain')
    return x


def _count(value, name, minimum=1):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return int(value)


def _asset(s, strike):
    a = _finite(s, 'asset price')
    if np.any(a < 0):
        raise ValueError('asset price must be nonnegative')
    return a, _scalar(strike, 'strike', 0)


def call_payoff(s: ArrayLike, strike: float) -> FloatArray:
    """Long call, preserving input shape; finite s>=0, strike>=0."""
    a, k = _asset(s, strike)
    return np.asarray(np.maximum(a-k, 0), dtype=float)


def put_payoff(s: ArrayLike, strike: float) -> FloatArray:
    a, k = _asset(s, strike)
    return np.asarray(np.maximum(k-a, 0), dtype=float)


def butterfly_payoff(s: ArrayLike, strikes: tuple[float, float, float], kind: str = 'call') -> FloatArray:
    k = _finite(strikes, 'strikes')
    if k.shape != (3,) or k[0] <= 0 or not np.all(np.diff(k) > 0):
        raise ValueError('require three positive increasing strikes')
    if not np.isclose(k[1]-k[0], k[2]-k[1], rtol=1e-12, atol=1e-12):
        raise ValueError('strikes must be equally spaced')
    if kind not in ('call', 'put'):
        raise ValueError('kind must be call or put')
    f = call_payoff if kind == 'call' else put_payoff
    return f(s,k[0])-2*f(s,k[1])+f(s,k[2])


def financed_profit(payoff: ArrayLike, initial_cost: float, rate: float, maturity: float) -> FloatArray:
    v = _finite(payoff, 'payoff')
    cost = _scalar(initial_cost, 'initial cost')
    r = _scalar(rate, 'rate')
    t = _scalar(maturity, 'maturity', 0)
    return np.asarray(v-cost*np.exp(r*t), dtype=float)


def nominal_from_continuous(rate: float, frequency: int) -> float:
    r = _scalar(rate, 'rate')
    m = _count(frequency, 'frequency')
    return float(m*np.expm1(r/m))


def continuous_from_nominal(nominal: float, frequency: int) -> float:
    rc = _scalar(nominal, 'nominal rate')
    m = _count(frequency, 'frequency')
    if rc/m <= -1:
        raise ValueError('compounding base must be positive')
    return float(m*np.log1p(rc/m))


def rate_for_total_periods(rate: float, years: float, periods: int) -> float:
    r = _scalar(rate, 'rate')
    t = _scalar(years, 'years', 0, True)
    n = _count(periods, 'periods')
    return float(n/t*np.expm1(r*t/n))


def exponential_quantile(p: ArrayLike, rate: float) -> FloatArray:
    q = _finite(p, 'probability')
    lam = _scalar(rate, 'rate', 0, True)
    if np.any((q < 0) | (q >= 1)):
        raise ValueError('probability must be in [0,1)')
    return np.asarray(-np.log1p(-q)/lam, dtype=float)


def exponential_samples(rate: float, size: int | tuple[int, ...], rng: np.random.Generator) -> FloatArray:
    _scalar(rate, 'rate', 0, True)
    dims = size if isinstance(size, tuple) else (size,)
    for dim in dims:
        _count(dim, 'size', 0)
    if not isinstance(rng, np.random.Generator):
        raise ValueError('rng must be a NumPy Generator')
    return exponential_quantile(rng.random(size), rate)


def standardized_exponential_sums(n: int, replications: int, rate: float, rng: np.random.Generator,
                                  batch_size: int = 250) -> FloatArray:
    n = _count(n, 'summands')
    m = _count(replications, 'replications')
    b = _count(batch_size, 'batch size')
    lam = _scalar(rate, 'rate', 0, True)
    z = np.empty(m)
    for start in range(0,m,b):
        count = min(b,m-start)
        x = exponential_samples(lam,(count,n),rng)
        z[start:start+count] = (lam*x.sum(axis=1)-n)/np.sqrt(n)
    return z


def normal_qq(sample: ArrayLike) -> tuple[FloatArray, FloatArray]:
    a = _finite(sample,'sample')
    if a.ndim != 1 or a.size == 0:
        raise ValueError('sample must be a nonempty one-dimensional array')
    return norm.ppf((np.arange(1,a.size+1)-0.5)/a.size), np.sort(a)


def risk_neutral_probability(up: float, down: float, rate: float, maturity: float) -> float:
    u = _scalar(up,'up',0,True)
    d = _scalar(down,'down',0,True)
    r = _scalar(rate,'rate')
    t = _scalar(maturity,'maturity',0,True)
    growth = np.exp(r*t)
    if not d < growth < u:
        raise ValueError('no-arbitrage requires 0 < down < exp(rate*maturity) < up')
    return float((growth-d)/(u-d))


def exact_binomial(spot: float, strike: float, up: float, down: float, rate: float,
                   maturity: float, kind: str = 'call') -> dict[str,float]:
    s = _scalar(spot,'spot',0,True)
    k = _scalar(strike,'strike',0)
    p = risk_neutral_probability(up,down,rate,maturity)
    if kind not in ('call','put'):
        raise ValueError('kind must be call or put')
    f = call_payoff if kind == 'call' else put_payoff
    hu, hd = map(float, f([up*s,down*s],k))
    delta = (hu-hd)/(s*(up-down))
    bank = np.exp(-rate*maturity)*(up*hd-down*hu)/(up-down)
    return {'price':float(delta*s+bank),'delta':float(delta),'bank':float(bank),
            'probability':p,'payoff_up':hu,'payoff_down':hd}


def monte_carlo_binomial(spot: float, strike: float, up: float, down: float, rate: float,
                         maturity: float, paths: int, rng: np.random.Generator) -> dict[str,float]:
    model = exact_binomial(spot,strike,up,down,rate,maturity)
    n = _count(paths,'paths',2)
    if not isinstance(rng,np.random.Generator):
        raise ValueError('rng must be a NumPy Generator')
    terminal = np.where(rng.random(n) < model['probability'],spot*up,spot*down)
    discount = np.exp(-rate*maturity)
    call = discount*call_payoff(terminal,strike)
    put = discount*put_payoff(terminal,strike)
    out = {}
    for name,y in [('call',call),('put',put)]:
        mean, se = float(y.mean()),float(y.std(ddof=1)/np.sqrt(n))
        out.update({name:mean,name+'_se':se,name+'_ci_low':mean-1.96*se,name+'_ci_high':mean+1.96*se})
    paired = call-put
    out['parity_residual'] = float(paired.mean()-(spot-strike*discount))
    out['parity_se'] = float(paired.std(ddof=1)/np.sqrt(n))
    return out


def load_parameters() -> dict:
    return json.loads((Path(__file__).resolve().parents[1]/'data'/'assignment_parameters.json').read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status',action='store_true')
    args = parser.parse_args()
    if args.status:
        print('A1-A5 implemented. Run experiments.py and pytest for verification.')
        print(json.dumps(load_parameters(),indent=2))
    else:
        parser.print_help()
