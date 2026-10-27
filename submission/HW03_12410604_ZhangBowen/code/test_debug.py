"""Demanding post-pass I2 checks, independently compared with the A2 sampler."""
import itertools
import numpy as np
import pytest
import gbm
from ai_debug_repaired import terminal_report

@pytest.mark.parametrize("mu,sigma,T",list(itertools.product([-.11,0.,.17],[0.,.2,.8],[.125,.5,2.,3.75])))
def test_time_drift_grid_same_draws_against_independent_A2(mu,sigma,T):
    q=terminal_report(37.9,mu,sigma,T,257,937)
    x=gbm.exact_sampler(37.9,mu,sigma,T,257,np.random.default_rng(937))
    assert q['mean']==pytest.approx(x.mean(),rel=2e-14)
    if sigma==0:
        assert q['variance']==q['se']==0
    else:
        assert q['variance']==pytest.approx(x.var(ddof=1),rel=2e-14)
        assert q['se']==pytest.approx(x.std(ddof=1)/np.sqrt(len(x)),rel=2e-14)
    assert q['prediction_interval']==pytest.approx(gbm.prediction_interval(37.9,mu,sigma,T),rel=2e-14)
    assert q['prediction_interval']==q['fixed_population_prediction_interval']

def test_prediction_interval_exactly_invariant_to_count():
    small=terminal_report(count=29)
    large=terminal_report(count=100003)
    assert small['prediction_interval']==large['prediction_interval']
    assert small['mean_confidence_interval']!=large['mean_confidence_interval']

@pytest.mark.parametrize("bad",[dict(s0=0),dict(mu=np.nan),dict(sigma=-1),dict(horizon=-1),dict(count=1),dict(count=1.5),dict(count=True)])
def test_invalid_inputs_before_sampling(bad):
    with pytest.raises((ValueError,TypeError)): terminal_report(**bad)
