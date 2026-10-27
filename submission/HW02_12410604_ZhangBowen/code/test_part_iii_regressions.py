import numpy as np
import pytest
import student_tasks as t
from ai_debug_repaired import purported_call_mc


@pytest.mark.parametrize('kwargs',[{'paths':1},{'paths':True},{'paths':2.5},{'spot':np.nan},{'spot':np.inf},{'maturity':0},{'maturity':-.1}])
def test_final_repair_rejects_observed_proposal_defects(kwargs):
    with pytest.raises(ValueError):purported_call_mc(**kwargs)


def test_zero_strike_and_invalid_kind():
    assert t.exact_binomial(100,0,1.2,.8,.05,1)['price'] == pytest.approx(100)
    out=purported_call_mc(strike=0,paths=10000)
    assert out['price'] > 0 and np.isfinite(out['se'])
    with pytest.raises(ValueError):t.exact_binomial(100,100,1.2,.8,.05,1,'invalid')
