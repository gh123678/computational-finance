"""Frozen LightGBM regression and LedoitWolf covariance-based risk scaling."""
import numpy as np
from sklearn.covariance import LedoitWolf

PARAMETERS=dict(n_estimators=200,learning_rate=.05,max_depth=4,num_leaves=15,
                min_child_samples=200,reg_lambda=10,colsample_bytree=1.,subsample=1.,
                random_state=42,n_jobs=4,deterministic=True,force_col_wise=True,verbosity=-1)


def fit_model(training,features):
    from lightgbm import LGBMRegressor
    if training.empty:
        raise ValueError('No matured training samples')
    model=LGBMRegressor(**PARAMETERS)
    model.fit(training[features],training.label,sample_weight=training.sample_weight)
    return model


def risk_scale(returns,weights):
    values=np.asarray(returns,dtype=float)
    w=np.asarray(weights,dtype=float)
    if values.shape!=(60,len(w)) or not np.isfinite(values).all() or not np.isfinite(w).all():
        raise ValueError('Risk requires 60 common finite return observations')
    covariance=LedoitWolf(store_precision=False).fit(values).covariance_
    variance=float(w@covariance@w*252)
    if not np.isfinite(variance) or variance<=0:
        raise ValueError('Invalid or zero predicted portfolio variance')
    sigma=np.sqrt(variance)
    scale=min(1.,.15/sigma)
    return scale,sigma,covariance
