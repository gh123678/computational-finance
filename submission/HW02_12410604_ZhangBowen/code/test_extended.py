"""Independent identities, input checks and reproducible statistical checks."""
import numpy as np
import pytest
import student_tasks as t
from ai_debug_repaired import purported_call_mc


@pytest.mark.parametrize('bad',[-1,np.nan,np.inf])
def test_bad_assets(bad):
    with pytest.raises(ValueError): t.call_payoff([bad],50)
    with pytest.raises(ValueError): t.put_payoff([bad],50)


@pytest.mark.parametrize('bad',[0,-1,1.5,True])
def test_period_domain(bad):
    with pytest.raises(ValueError): t.nominal_from_continuous(.05,bad)
    with pytest.raises(ValueError): t.rate_for_total_periods(.05,2,bad)


def test_strikes_and_shapes():
    assert t.call_payoff(np.ones((2,3)),0).shape == (2,3)
    for strikes in [(40,50,61),(0,1,2),(60,50,40),(40,50)]:
        with pytest.raises(ValueError): t.butterfly_payoff([50],strikes)
    with pytest.raises(ValueError): t.butterfly_payoff([50],(40,50,60),'invalid')


def test_butterfly_continuity_and_financed_break_even():
    eps = 1e-7
    for k in [40,50,60]:
        v = t.butterfly_payoff([k-eps,k,k+eps],(40,50,60))
        assert np.max(np.abs(v-v[1])) <= eps*1.01
    cost = 12-2*5+2
    f = cost*np.exp(.05)
    np.testing.assert_allclose(t.financed_profit(t.butterfly_payoff([40+f,60-f],(40,50,60)),cost,.05,1),0,atol=1e-13)
    assert float(t.financed_profit(0,-4,.05,1)) == pytest.approx(4*np.exp(.05))


@pytest.mark.parametrize('r',[0,1e-12,.05,-.03])
@pytest.mark.parametrize('years',[1,2])
def test_rate_limits_and_conventions(r,years):
    for m in [1,12,365]:
        rc = t.nominal_from_continuous(r,m)
        assert t.continuous_from_nominal(rc,m) == pytest.approx(r,abs=1e-15)
        assert t.rate_for_total_periods(r,years,m*years) == pytest.approx(rc,abs=1e-15)
    with pytest.raises(ValueError): t.continuous_from_nominal(-12,12)
    with pytest.raises(ValueError): t.rate_for_total_periods(r,0,10)


def test_inverse_endpoints_and_generator_consumption():
    p = [0,1e-16,.5,np.nextafter(1.,0.)]
    q = t.exponential_quantile(p,2)
    np.testing.assert_allclose(-np.expm1(-2*q),p,rtol=1e-14)
    for bad in [[1],[-.01],[np.nan],[np.inf]]:
        with pytest.raises(ValueError): t.exponential_quantile(bad,1)
    for rate in [0,-1,np.inf,np.nan]:
        with pytest.raises(ValueError): t.exponential_samples(rate,10,np.random.default_rng(2))
    a,b = np.random.default_rng(9),np.random.default_rng(9)
    np.testing.assert_array_equal(t.exponential_samples(2,(2,3),a),-np.log1p(-b.random((2,3)))/2)
    assert a.random() == b.random()


def test_batching_invariance_and_theoretical_scaling():
    z = t.standardized_exponential_sums(30,123,1,np.random.default_rng(20),17)
    z2 = t.standardized_exponential_sums(30,123,2,np.random.default_rng(20),123)
    np.testing.assert_array_equal(z,z2)
    for n,m,b in [(0,10,2),(3,0,2),(3,10,0),(1.5,10,2)]:
        with pytest.raises(ValueError): t.standardized_exponential_sums(n,m,1,np.random.default_rng(1),b)
    for sample in [[],[[1,2]],[np.nan]]:
        with pytest.raises(ValueError): t.normal_qq(sample)


def test_tree_benchmarks_bounds_and_limit():
    args = (100,100,1.2,.8,.05,1)
    c,p = t.exact_binomial(*args),t.exact_binomial(*args,'put')
    disc = np.exp(-.05)
    # Hand replication: call = .5*S0 - 40*discount; put = -.5*S0 + 60*discount.
    assert c['price'] == pytest.approx(50-40*disc)
    assert p['price'] == pytest.approx(-50+60*disc)
    assert max(100-100*disc,0) <= c['price'] <= 100
    assert max(100*disc-100,0) <= p['price'] <= 100*disc
    assert t.exact_binomial(100,0,1.2,.8,.05,1)['price'] == pytest.approx(100)
    for u,d,r,T in [(1, .8,0,1),(1.2,1,0,1),(1.2,0,.05,1),(1.2,.8,.05,0)]:
        with pytest.raises(ValueError): t.risk_neutral_probability(u,d,r,T)


def test_mc_against_hand_reconstructed_draws():
    args = (100,100,1.2,.8,.05,1)
    n,seed = 10000,14
    pstar = (np.exp(.05)-.8)/.4
    indicators = np.random.default_rng(seed).random(n) < pstar
    discount = np.exp(-.05)
    y = 20*discount*indicators
    diff = 20*discount*(2*indicators.astype(int)-1)
    out = t.monte_carlo_binomial(*args,n,np.random.default_rng(seed))
    assert out['call'] == pytest.approx(y.mean())
    assert out['call_se'] == pytest.approx(y.std(ddof=1)/np.sqrt(n))
    assert out['parity_se'] == pytest.approx(diff.std(ddof=1)/np.sqrt(n))
    assert out['parity_se'] == pytest.approx(2*out['call_se'])
    repair = purported_call_mc(*args,n,seed)
    assert repair['price'] == pytest.approx(out['call'])
    assert repair['se'] == pytest.approx(out['call_se'])


def test_standard_error_scale_over_independent_repetitions():
    rng = np.random.default_rng(71)
    means = []
    for n in [1000,10000]:
        estimates = [t.monte_carlo_binomial(100,100,1.2,.8,.05,1,n,rng)['call_se'] for _ in range(30)]
        means.append(np.mean(estimates))
    assert .29 < means[1]/means[0] < .34


@pytest.mark.parametrize('paths',[0,1,2.5,True])
def test_mc_bad_count(paths):
    with pytest.raises(ValueError): t.monte_carlo_binomial(100,100,1.2,.8,.05,1,paths,np.random.default_rng(1))
    with pytest.raises(ValueError): purported_call_mc(paths=paths)
