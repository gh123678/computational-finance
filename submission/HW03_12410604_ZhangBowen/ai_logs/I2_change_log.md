# HW03 I2 — Model B code change log

## Provenance and scope

The original instructor file is [ai_debug_exercise.py](../code/ai_debug_exercise.py). It was supplied after the root assistant's initial diagnosis; no student pre-AI debugging records were supplied. The original instructor file was left unchanged. A separately prompted DeepSeek repair session (Model B) wrote [ai_debug_proposed.py](../code/ai_debug_proposed.py) for the first proposal and [ai_debug_repaired.py](../code/ai_debug_repaired.py) for the compatibility repair. The full actual exchange is archived in [I2_model_B.md](I2_model_B.md).

The first proposal corrected GBM terminal scaling and log drift, used sample variance with `ddof=1`, computed the sample mean's SE with `sqrt(count)`, and separated the mean confidence interval from the GBM population prediction interval. It validated real finite inputs and treated zero horizon or zero volatility as exact point masses. The repair restored the original `prediction_interval` key as an alias for the analytical interval in both branches; the clearer `fixed_population_prediction_interval` key stayed available. There was no numerical change to interval endpoints between versions.

## Actual check results reported by the orchestrator

The original instructor file passed 1/11 checks. The first proposal passed 8/11; its three failures were `KeyError: 'prediction_interval'` in the fixed interval and two deterministic-limit checks. The repaired file passed 11/11 direct checks. An additional `python -m pytest code/test_debug.py -q` run passed 44 cases in 0.13 seconds: 36 cases from a 3 × 3 × 4 parameter grid, one count-invariance case, and seven invalid-parameter cases. The grid compared same-draw outputs with `A2_gbm.exact_sampler` and fixed quantiles and included exact zero variance for `sigma=0`.

For the repaired default report, the orchestrator supplied `mean=117.10066413325876`, `variance=2701.3508504693427`, `se=0.1643578671822357`, `mean_confidence_interval=[116.77852271358158, 117.42280555293594]`, and `fixed_population_prediction_interval=[46.693856862072145, 246.34371117703844]`. These are reported outcomes of the orchestrator's test runs, not tests run by Model B during its first two exchanges.

## Full first proposed source

This is the full proposed patch saved as [ai_debug_proposed.py](../code/ai_debug_proposed.py):

```python
"""Estimate GBM terminal statistics and report distinct uncertainty intervals."""

import numpy as np


def terminal_report(s0=100., mu=.08, sigma=.3, horizon=2., count=100000, seed=21603):
    """Simulate GBM at ``horizon`` years and summarize terminal prices."""
    for name, value in (("s0", s0), ("mu", mu), ("sigma", sigma), ("horizon", horizon)):
        if (isinstance(value, (bool, np.bool_))
                or not isinstance(value, (int, float, np.integer, np.floating))
                or not np.isfinite(value)):
            raise ValueError(f"{name} must be a finite real number")
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if sigma < 0:
        raise ValueError("sigma must be nonnegative")
    if horizon < 0:
        raise ValueError("horizon must be nonnegative")
    if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)) or count < 2:
        raise ValueError("count must be an integer of at least 2")

    # A zero horizon or zero volatility has an exact point-mass distribution.
    if horizon == 0 or sigma == 0:
        terminal = float(s0 * np.exp(mu * horizon))
        if not np.isfinite(terminal):
            raise ValueError("terminal price is not finite for these inputs")
        return {
            "mean": terminal,
            "variance": 0.0,
            "se": 0.0,
            "mean_confidence_interval": [terminal, terminal],
            "fixed_population_prediction_interval": [terminal, terminal],
        }

    rng = np.random.default_rng(seed)
    z = rng.standard_normal(count)
    log_drift = (mu - 0.5 * sigma**2) * horizon
    log_scale = sigma * np.sqrt(horizon)
    samples = s0 * np.exp(log_drift + log_scale * z)
    if not np.all(np.isfinite(samples)):
        raise ValueError("simulated terminal prices are not finite for these inputs")

    average = float(samples.mean())
    variance = float(samples.var(ddof=1))
    se = float(np.sqrt(variance / count))
    mean_confidence_interval = [average - 1.96 * se, average + 1.96 * se]
    fixed_population_prediction_interval = [
        float(s0 * np.exp(log_drift - 1.96 * log_scale)),
        float(s0 * np.exp(log_drift + 1.96 * log_scale)),
    ]
    if not np.all(np.isfinite(fixed_population_prediction_interval)):
        raise ValueError("prediction-interval endpoint is not finite for these inputs")

    return {
        "mean": average,
        "variance": variance,
        "se": se,
        "mean_confidence_interval": mean_confidence_interval,
        "fixed_population_prediction_interval": fixed_population_prediction_interval,
    }
```

## Full repaired source

This is the full repaired patch saved as [ai_debug_repaired.py](../code/ai_debug_repaired.py):

```python
"""Estimate GBM terminal statistics and report distinct uncertainty intervals."""

import numpy as np


def terminal_report(s0=100., mu=.08, sigma=.3, horizon=2., count=100000, seed=21603):
    """Simulate GBM at ``horizon`` years and summarize terminal prices."""
    for name, value in (("s0", s0), ("mu", mu), ("sigma", sigma), ("horizon", horizon)):
        if (isinstance(value, (bool, np.bool_))
                or not isinstance(value, (int, float, np.integer, np.floating))
                or not np.isfinite(value)):
            raise ValueError(f"{name} must be a finite real number")
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if sigma < 0:
        raise ValueError("sigma must be nonnegative")
    if horizon < 0:
        raise ValueError("horizon must be nonnegative")
    if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)) or count < 2:
        raise ValueError("count must be an integer of at least 2")

    # A zero horizon or zero volatility has an exact point-mass distribution.
    if horizon == 0 or sigma == 0:
        terminal = float(s0 * np.exp(mu * horizon))
        if not np.isfinite(terminal):
            raise ValueError("terminal price is not finite for these inputs")
        prediction_interval = [terminal, terminal]
        return {
            "mean": terminal,
            "variance": 0.0,
            "se": 0.0,
            "mean_confidence_interval": [terminal, terminal],
            "fixed_population_prediction_interval": prediction_interval,
            "prediction_interval": prediction_interval,
        }

    rng = np.random.default_rng(seed)
    z = rng.standard_normal(count)
    log_drift = (mu - 0.5 * sigma**2) * horizon
    log_scale = sigma * np.sqrt(horizon)
    samples = s0 * np.exp(log_drift + log_scale * z)
    if not np.all(np.isfinite(samples)):
        raise ValueError("simulated terminal prices are not finite for these inputs")

    average = float(samples.mean())
    variance = float(samples.var(ddof=1))
    se = float(np.sqrt(variance / count))
    mean_confidence_interval = [average - 1.96 * se, average + 1.96 * se]
    prediction_interval = [
        float(s0 * np.exp(log_drift - 1.96 * log_scale)),
        float(s0 * np.exp(log_drift + 1.96 * log_scale)),
    ]
    if not np.all(np.isfinite(prediction_interval)):
        raise ValueError("prediction-interval endpoint is not finite for these inputs")

    return {
        "mean": average,
        "variance": variance,
        "se": se,
        "mean_confidence_interval": mean_confidence_interval,
        "fixed_population_prediction_interval": prediction_interval,
        "prediction_interval": prediction_interval,
    }
```

## Limits of the checks

The checks establish agreement with the specified GBM formulas and an independent same-draw implementation on the tested inputs. They do not show that GBM fits observed market data, that each finite Monte Carlo run has exactly 95% realized coverage, or that all extreme finite parameter combinations are numerically representable. The confidence interval for the mean is a large-sample approximation; the prediction interval uses fixed model parameters, with exact coverage (2\Phi(1.96)-1\), slightly different from 0.95.
