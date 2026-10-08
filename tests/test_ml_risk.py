import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ml_risk_features import FEATURES,compute_asset,matured_training
from ml_risk_model import risk_scale


def test_model_serialization_on_unicode_path(tmp_path):
    from ml_risk_model import fit_model
    from lightgbm import Booster
    rng=np.random.default_rng(42)
    training=pd.DataFrame(rng.normal(size=(1000,12)),columns=FEATURES)
    training['label']=training.ret20*.1
    training['sample_weight']=1/1000
    model=fit_model(training,FEATURES)
    path=tmp_path/'中文模型.txt'
    path.write_text(model.booster_.model_to_string(),encoding='utf-8')
    reloaded=Booster(model_str=path.read_text(encoding='utf-8'))
    np.testing.assert_array_equal(model.predict(training[FEATURES]),reloaded.predict(training[FEATURES],num_threads=4))


def market(n=110):
    dates=pd.bdate_range('20160101',periods=n)
    price=10*np.exp(np.cumsum(np.sin(np.arange(n))*.02+.001))
    bars=pd.DataFrame(dict(trade_date=dates,open=price*.999,high=price*1.02,low=price*.98,
                          close=price,adj_factor=1.,vol=10000+np.arange(n)*11,amount=1000+np.arange(n)**1.2))
    benchmark=pd.Series(np.linspace(100,110,n),index=dates)
    return dates,bars,benchmark


def test_future_perturbation_leaves_past_features_unchanged():
    dates,bars,benchmark=market()
    a,_=compute_asset(bars,dates,dates,benchmark)
    changed=bars.copy();changed.loc[changed.trade_date>dates[75],['open','high','low','close','amount']]*=3
    b,_=compute_asset(changed,dates,dates,benchmark)
    pd.testing.assert_frame_equal(a.loc[:75,FEATURES],b.loc[:75,FEATURES])
    assert a.loc[60,'log_adv20']==pytest.approx(np.log1p(bars.amount.iloc[41:61].mean()*1000))


def test_missing_and_unknown_actions_quarantine_full_lookback_and_labels():
    dates,bars,benchmark=market(160)
    result,_=compute_asset(bars,dates,dates,benchmark,[dates[70]])
    assert not result.loc[70:130,'feature_valid'].any()
    assert result.loc[131,'feature_valid']
    assert result.loc[60,'label_valid']==False
    bars.loc[80,'vol']=0
    result,_=compute_asset(bars,dates,dates,benchmark)
    assert not result.loc[80:140,'feature_valid'].any()
    assert result.loc[141,'feature_valid']


def test_mature_labels_and_future_open_alignment():
    dates,bars,benchmark=market(160)
    result,_=compute_asset(bars,dates,dates,benchmark)
    result['ts_code']='A'
    expected=bars.open.iloc[81]/bars.open.iloc[61]-1-(benchmark.iloc[81]/benchmark.iloc[61]-1)
    assert result.loc[60,'label']==pytest.approx(expected)
    training=matured_training(result,dates[100])
    assert training.label_end.max()<dates[100]
    assert dates[79] not in set(training.trade_date)
    assert np.allclose(training.groupby('trade_date').sample_weight.sum(),1.)


def test_future_changes_do_not_change_matured_training():
    dates,bars,benchmark=market(160)
    a,_=compute_asset(bars,dates,dates,benchmark);a['ts_code']='A'
    changed=bars.copy();changed.loc[changed.trade_date>=dates[100],['open','high','low','close']]*=2
    b,_=compute_asset(changed,dates,dates,benchmark);b['ts_code']='A'
    pd.testing.assert_frame_equal(matured_training(a,dates[100]),matured_training(b,dates[100]))


def test_risk_scale_budget_and_no_leverage():
    rng=np.random.default_rng(42)
    values=rng.normal(0,.05,(60,20));weights=np.full(20,.049)
    scale,sigma,cov=risk_scale(values,weights)
    assert 0<scale<=1
    assert scale*sigma<=.15+1e-12
    assert weights.sum()*scale<=.98+1e-12
    assert np.linalg.eigvalsh(cov).min()>=0
    low,_,_=risk_scale(values*.01,weights)
    assert low==1
    with pytest.raises(ValueError):
        risk_scale(np.zeros((60,20)),weights)
    with pytest.raises(ValueError):
        risk_scale(values[:59],weights)
