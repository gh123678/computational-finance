"""Frozen 52-date training, train-only weighted scales and alpha10 Ridge."""
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from price_amount_features import FEATURES


def training_samples(samples, fit_date):
    if samples.duplicated(['trade_date', 'ts_code']).any():
        raise ValueError('Duplicate training key')
    fit_date = pd.Timestamp(fit_date)
    for name in ('trade_date', 'D_end', 'reference_end'):
        if not pd.api.types.is_datetime64_any_dtype(samples[name]):
            raise ValueError('Parsed dates required: ' + name)
    for name in ('feature_valid', 'D_valid'):
        if samples[name].dtype != bool:
            raise ValueError('Boolean validity required: ' + name)
    candidate = samples.loc[samples.feature_valid & samples.D_valid &
                            samples.trade_date.lt(fit_date) &
                            samples.D_end.lt(fit_date) & samples.reference_end.lt(fit_date)].copy()
    if not np.isfinite(candidate[FEATURES + ['D_label']].to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite matured training input')
    counts = candidate.groupby('trade_date').size().sort_index()
    dates = counts.loc[counts.ge(200)].index[-52:]
    if len(dates) != 52:
        raise ValueError(f'Need52 qualifying matured dates; found {len(dates)}')
    result = candidate.loc[candidate.trade_date.isin(dates)].sort_values(['trade_date', 'ts_code'])
    result['label'] = result.D_label
    result['sample_weight'] = 1 / result.groupby('trade_date').ts_code.transform('size')
    if not np.allclose(result.groupby('trade_date').sample_weight.sum(), 1., rtol=0, atol=1e-12):
        raise ValueError('Date weights must total1')
    audit = dict(fit_date=fit_date.strftime('%Y-%m-%d'), samples=len(result), dates=52,
                 first_date=dates.min().strftime('%Y-%m-%d'),
                 last_date=dates.max().strftime('%Y-%m-%d'),
                 total_weight=float(result.sample_weight.sum()),
                 excluded_under200_dates={d.strftime('%Y-%m-%d'): int(n) for d, n in counts.items() if n < 200},
                 latest_label_end=result.D_end.max().strftime('%Y-%m-%d'),
                 latest_reference_end=result.reference_end.max().strftime('%Y-%m-%d'))
    return result.reset_index(drop=True), audit


def fit_scales(training):
    values = training[FEATURES].to_numpy(dtype=float)
    weights = training.sample_weight.to_numpy(dtype=float)
    if not len(values) or not np.isfinite(values).all() or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError('Invalid weighted scale input')
    mean = np.average(values, axis=0, weights=weights)
    variance = np.average((values - mean) ** 2, axis=0, weights=weights)
    if not np.isfinite(variance).all() or (variance <= 1e-12).any():
        raise ValueError('Constant or invalid feature variance')
    return dict(features=FEATURES, mean=mean.tolist(), variance=variance.tolist(),
                scale=np.sqrt(variance).tolist(), total_weight=float(weights.sum()))


def transform(frame, scales):
    if scales['features'] != FEATURES:
        raise ValueError('Feature order changed')
    values = frame[FEATURES].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError('Nonfinite prediction input')
    scale = np.asarray(scales['scale'], dtype=float)
    if scale.shape != (8,) or not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError('Invalid saved scale')
    return (values - np.asarray(scales['mean'])) / scale


def fit_models(training, scales):
    from lightgbm import LGBMRegressor
    from ml_risk_model import PARAMETERS
    matrix = transform(training, scales)
    label = training.label.to_numpy(dtype=float)
    if not np.isfinite(label).all():
        raise ValueError('Nonfinite training labels')
    weights = training.sample_weight.to_numpy(dtype=float)
    ridge = Ridge(alpha=10, fit_intercept=True, solver='svd')
    ridge.fit(matrix, label, sample_weight=weights)
    gbm = LGBMRegressor(**PARAMETERS)
    gbm.fit(matrix, label, sample_weight=weights)
    return ridge, gbm
