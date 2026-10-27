"""Independent verification of supplied Part III; no claim of student chronology."""
from pathlib import Path
import importlib
import json
import sys
import numpy as np
from scipy.stats import norm
from scipy.integrate import quad
from scipy.special import expit
import student_tasks as t

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ai_logs'/'supplied_20261011'))


def main():
    findings = []
    for name in ['I2_repaired_pricer','I2_repaired_pricer_modelB']:
        module = importlib.import_module(name)
        f = module.call_mc
        expected = t.monte_carlo_binomial(100,100,1.2,.8,.05,1,100000,np.random.default_rng(20260927))
        actual = f(paths=100000,seed=20260927)
        assert np.isclose(actual['price'],expected['call']) and np.isclose(actual['se'],expected['call_se'])
        cases = [('one path',{'paths':1}),('boolean path count',{'paths':True}),('NaN spot',{'spot':np.nan}),
                 ('infinite spot',{'spot':np.inf}),('zero maturity',{'maturity':0}),('negative maturity',{'maturity':-.1})]
        exact = module.exact_price if hasattr(module,'exact_price') else module.exact_forward
        for label,kwargs in cases:
            with np.errstate(all='ignore'):
                try:
                    result = f(**kwargs)
                    finding = f'ACCEPTED: {result}'
                except ValueError:
                    finding = 'REJECTED with ValueError'
                except Exception as exc:
                    finding = f'Other error: {type(exc).__name__}'
            findings.append({'module':name,'check':label,'observed':finding})
        for label,kwargs in [('zero strike',{'strike':0}),('invalid option kind',{'kind':'invalid'})]:
            try:
                result = exact(**kwargs); finding = f'ACCEPTED price {result}'
            except ValueError:
                finding = 'REJECTED with ValueError'
            findings.append({'module':name,'check':label,'observed':finding})
    D0,rc,years,m = 10000,.05,2,12
    formula = {'assigned_wrong_formula':D0*(1+rc*years/m)**m,
               'earlier_logged_formula_before_revision':D0*(1+rc/m)**m,
               'correct_annual_formula':D0*(1+rc/m)**(m*years)}
    beta_skew = (-1/160)/(3/80)**1.5
    questions = []
    for label,s,u,d,r,T,hu,hd,real_p in [('A-i',80,1.25,.9,.04,.5,30,5,.6),('B-i',120,1.15,.85,.03,2,20,0,.5)]:
        p = t.risk_neutral_probability(u,d,r,T)
        delta = (hu-hd)/(s*(u-d));bank=np.exp(-r*T)*(hu-delta*u*s);price=delta*s+bank
        np.testing.assert_allclose([delta*u*s+bank*np.exp(r*T),delta*d*s+bank*np.exp(r*T)],[hu,hd],atol=1e-12)
        questions.append({'question':label,'probability':p,'delta':delta,'bank':bank,'price':price,
                          'real_world_discounted_expectation':np.exp(-r*T)*(real_p*hu+(1-real_p)*hd)})
    variance = quad(lambda x:x*x*expit(x)*expit(-x),-np.inf,np.inf)[0]
    fourth = quad(lambda x:x**4*expit(x)*expit(-x),-np.inf,np.inf)[0]
    rng = np.random.default_rng(20260927)
    U = rng.random(200000);X=-np.log1p(-U)/2;Y=-np.log1p(-(1-U))/2
    def ks(a):
        xs=np.sort(a); F=-np.expm1(-2*xs);n=len(a)
        return float(max(np.max(np.arange(1,n+1)/n-F),np.max(F-np.arange(n)/n)))
    result={'I1_compounding':formula,'I1_two_sided_KS_fresh_stream':{'X':ks(X),'Y':ks(Y),'exact_pointwise_equal_fraction':float(np.mean(X==Y)),
               'sample_covariance':float(np.cov(X,Y,ddof=1)[0,1]),'population_covariance':(1-np.pi**2/6)/4},
            'I1_support_normal_probability_below_minus_sqrt5':float(norm.cdf(-np.sqrt(5))),
            'I2_additional_findings':findings,'I3_replication':questions,
            'I3_beta':{'variance':3/80,'N_for_SE_0_005':1500,'population_skewness':beta_skew,'mean_skewness_N10':beta_skew/np.sqrt(10)},
            'I3_logistic':{'variance_quadrature':variance,'variance_analytical':np.pi**2/3,'fourth_moment_quadrature':fourth,
                            'population_excess_kurtosis':fourth/variance**2-3,'mean_excess_kurtosis_N10':(fourth/variance**2-3)/10,
                            'N_for_SE_0_02':int(np.ceil((np.pi**2/3)/.02**2))}}
    (ROOT/'results'/'part_iii_independent_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':main()
