import numpy as np
import pandas as pd
import pytest
from returns_analysis import log_returns,acf,describe,audit_csv,expected_sessions

def test_log_return_telescope_and_compound():
    prices=np.array([100.,110.,99.,123.])
    r=log_returns(prices)
    assert np.sum(r)==pytest.approx(np.log(123/100))
    assert np.expm1(np.sum(r))==pytest.approx(np.prod(prices[1:]/prices[:-1])-1)

@pytest.mark.parametrize("p",[[1,0],[1,-1],[1,np.nan],[1,np.inf],[1],[[1,2],[3,4]]])
def test_reject_bad_prices(p):
    with pytest.raises(ValueError): log_returns(p)

def test_acf_matches_hand_calculation():
    x=np.array([1.,2.,4.,3.]) # centered -1.5,-.5,1.5,.5; denominator=5
    assert acf(x,2)==pytest.approx([1.,.15,-.5])

def test_variance_divisor_and_moments():
    d=describe([-1.,0.,1.])
    assert d["variance"]==pytest.approx(1.)
    assert d["skewness"]==pytest.approx(0.)
    assert d["excess_kurtosis"]==pytest.approx(-1.5)

def test_permutation_preserves_marginal_not_acf():
    x=np.array([1.,2.,4.,7.,11.]); y=x[[2,0,4,1,3]]
    for k in ["mean","variance","skewness","excess_kurtosis"]:
        assert describe(x)[k]==pytest.approx(describe(y)[k])
    assert not np.allclose(acf(x,2),acf(y,2))

def test_calendar_exception_and_saturday_new_year():
    assert pd.Timestamp("2021-12-31") in expected_sessions("2021-12-30","2022-01-04")
    assert pd.Timestamp("2025-01-09") not in expected_sessions("2025-01-08","2025-01-10")
    assert len(expected_sessions())==1255

def test_audit_rejects_duplicate_and_missing_session(tmp_path):
    path=tmp_path/"input.csv"
    pd.DataFrame({"Date":["2026-10-13","2026-10-13"],"AdjClose":[10,11]}).to_csv(path,index=False)
    with pytest.raises(ValueError,match="duplicates"): audit_csv(path,False)
    pd.DataFrame({"Date":["2021-10-14","2026-10-14"],"AdjClose":[10,11]}).to_csv(path,index=False)
    with pytest.raises(ValueError,match="calendar"): audit_csv(path)

@pytest.mark.parametrize("x",[[1,1],[1,np.nan]])
def test_acf_rejects_undefined(x):
    with pytest.raises(ValueError): acf(x,1)
