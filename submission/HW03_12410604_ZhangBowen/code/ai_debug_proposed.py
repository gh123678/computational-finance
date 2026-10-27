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
