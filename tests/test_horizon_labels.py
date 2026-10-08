import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from horizon_labels import asset_labels,training_samples


def data():
    cal=pd.bdate_range('20170102',periods=70)
    price=10+np.arange(70)*.1
    g=pd.DataFrame(dict(trade_date=cal,open=price,high=price+.1,low=price-.1,close=price,adj_factor=1.,vol=1.,amount=1.))
    s=pd.DataFrame(dict(signal_date=[cal[0],cal[65]],execution_date=[cal[1],cal[66]],next_execution=[cal[4],pd.NaT]))
    return cal,g,s,pd.Series(100.,index=cal)


def test_intermediate_missing_only_rejects_full_window():
    cal,g,s,b=data();g=g.loc[g.trade_date.ne(cal[2])]
    a=asset_labels(g,cal,s,b).iloc[:4].set_index('variant')
    assert a.loc[['A','B'],'label_valid'].eq(False).all()
    assert a.loc[['C','D'],'label_valid'].all()
    assert a.loc['D','sessions']==3
    assert a.loc['D','label']==pytest.approx(10.4/10.1-1)
    assert a.loc['C','missing_dates']==cal[2].strftime('%Y-%m-%d')


def test_missing_endpoint_never_filled():
    cal,g,s,b=data();g=g.loc[g.trade_date.ne(cal[1])]
    a=asset_labels(g,cal,s,b).iloc[:4]
    assert not a.label_valid.any() and a.endpoint_missing.all()


def test_unknown_event_rejected_even_endpoint_variants():
    cal,g,s,b=data();a=asset_labels(g,cal,s,b,[cal[2]]).iloc[:4]
    assert not a.label_valid.any() and a.unknown_adjustment.all()


def test_boundary_and_invalid_point_reasons():
    cal,g,s,b=data();g.loc[2,'vol']=0
    a=asset_labels(g,cal,s,b)
    assert a.iloc[0].middle_invalid and not a.iloc[0].label_valid
    assert a.iloc[2].label_valid
    assert a.iloc[4:].outside_period.all()
    with pytest.raises(ValueError):asset_labels(g,cal[::-1],s,b)


def test_common_long_maturity_and_future_perturbation():
    cal,g,s,b=data()
    x=pd.DataFrame(dict(trade_date=[cal[0]],ts_code=['X'],reference_end=[cal[21]],D_end=[cal[4]],D_valid=[True],D_label=[.01]))
    assert training_samples(x,'D',cal[20]).empty
    assert training_samples(x,'D',cal[22]).sample_weight.iloc[0]==1
    past=asset_labels(g,cal,s,b).iloc[:4]
    g.loc[g.trade_date>=cal[22],['open','high','low','close']]*=3
    pd.testing.assert_frame_equal(past,asset_labels(g,cal,s,b).iloc[:4])
