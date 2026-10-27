"""Run identical checks on original and repaired code, saving actual evidence."""
import importlib
import sys
import numpy as np
from student_tasks import exact_binomial, monte_carlo_binomial


def run(module):
    f = importlib.import_module(module).purported_call_mc
    exact = exact_binomial(100,100,1.2,.8,.05,1)['price']
    out = f(paths=100000,seed=35)
    results = []
    results.append(('analytical benchmark: absolute error < 5 reported SE',abs(out['price']-exact) < 5*out['se']))
    results.append(('call no-arbitrage bounds',100-100*np.exp(-.05) <= out['price'] <= 100))
    expected = monte_carlo_binomial(100,100,1.2,.8,.05,1,100000,np.random.default_rng(35))
    results.append(('discounted payoff and risk-neutral draw reconstruction',np.isclose(out['price'],expected['call'],rtol=1e-13)))
    results.append(('sample SE divided by sqrt(N)',np.isclose(out['se'],expected['call_se'],rtol=1e-13)))
    zero = f(strike=1000,paths=10000)
    results.append(('zero payoff when strike above both states',zero['price'] == 0 and zero['se'] == 0))
    for label,kw in [('invalid tree',{'up':1.01}),('boundary tree',{'up':np.exp(.05)}),('invalid count',{'paths':1})]:
        try:
            f(**kw)
            passed = False
        except ValueError:
            passed = True
        results.append((label,passed))
    print(f'Module: {module}; analytical call={exact:.12f}; actual output={out}')
    for label,passed in results:
        print(f'{"PASS" if passed else "FAIL"}: {label}')
    print(f'{sum(bool(p) for _,p in results)}/{len(results)} checks passed')
    return all(p for _,p in results)


if __name__ == '__main__':
    sys.exit(0 if run(sys.argv[1]) else 1)
