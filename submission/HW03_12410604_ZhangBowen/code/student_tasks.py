"""Completed instructor interfaces for HW03; AI assistance is disclosed.

The unchanged supplied scaffold is preserved under source_instructor/. Numerical
primitives are shared with gbm.py and returns_analysis.py to keep one definition
of each convention. No unavailable source data or independent student attempt is
implied by this implementation.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from numbers import Integral
from pathlib import Path
import platform
import sys
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

import gbm as _gbm
import returns_analysis as _returns


def _sample(values, minimum=2) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or len(x) < minimum or not np.isfinite(x).all():
        raise ValueError(f"Require a one-dimensional finite sample of length >= {minimum}.")
    return x


def _positive_integer(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return int(value)


def _increments(values) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    if x.ndim != 2 or min(x.shape) == 0 or not np.isfinite(x).all():
        raise ValueError("Brownian increments must be a nonempty finite 2D array.")
    return x


def load_prices(path: str | Path, date_column: str = "Date",
                price_column: str = "Price") -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read, strictly validate, order, and audit a CSV without deleting rows.

    ISO dates must be exactly YYYY-MM-DD. When the default 'Price' is absent,
    provider field 'AdjClose', 'Adj Close', or 'Close' is accepted in that order
    and exposed transparently as canonical 'Price'. An explicitly requested
    nondefault field must exist. Currency/adjustment units require the separate
    provenance record; they are never inferred from numerical values.

    US-equity calendar comparisons are diagnostics under a stated assumption,
    not a universal calendar for every exchange. No gaps are filled.
    """
    source = Path(path)
    frame = pd.read_csv(source, dtype={date_column: "string"})
    if date_column not in frame:
        raise ValueError(f"Missing date column: {date_column}")
    selected = price_column
    if selected not in frame and price_column == "Price":
        selected = next((name for name in ("AdjClose", "Adj Close", "Close") if name in frame), "Price")
    if selected not in frame:
        raise ValueError(f"Missing price column: {price_column}")
    if len(frame) < 2:
        raise ValueError("At least two price observations are required.")
    if frame[date_column].isna().any():
        raise ValueError("Missing dates, including NaT/empty values, are invalid.")
    date_text = frame[date_column].astype("string")
    if not date_text.str.fullmatch(r"\d{4}-\d{2}-\d{2}", na=False).all():
        raise ValueError("Dates must be strict ISO YYYY-MM-DD strings.")
    try:
        dates = pd.to_datetime(date_text, format="%Y-%m-%d", exact=True, errors="raise")
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid ISO calendar date.") from exc
    if dates.isna().any():
        raise ValueError("Missing dates/NaT are invalid.")
    if dates.duplicated().any():
        raise ValueError("Duplicate dates are invalid; no rows were silently removed.")
    try:
        prices = pd.to_numeric(frame[selected], errors="raise").to_numpy(dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError("Prices must be numeric.") from exc
    if not np.isfinite(prices).all() or np.any(prices <= 0):
        raise ValueError("Prices must be positive and finite, with no missing values.")
    original_sorted = bool(dates.is_monotonic_increasing)
    frame[date_column] = dates
    frame[selected] = prices
    frame = frame.sort_values(date_column, kind="stable").reset_index(drop=True)
    # Canonical aliases allow the original interface's default names to work.
    frame["Date"] = frame[date_column]
    frame["Price"] = frame[selected]
    expected = _returns.expected_sessions(str(frame.Date.iloc[0].date()), str(frame.Date.iloc[-1].date()))
    observed = pd.DatetimeIndex(frame.Date)
    gaps = frame.Date.diff().dt.days
    gap_records = [
        {"previous_date": str(frame.Date.iloc[i-1].date()),
         "next_date": str(frame.Date.iloc[i].date()), "calendar_days": int(gaps.iloc[i])}
        for i in range(1, len(frame)) if gaps.iloc[i] > 1
    ]
    audit = {
        "source_path": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "price_rows": len(frame), "return_rows": len(frame)-1,
        "date_column": date_column, "selected_price_column": selected,
        "canonical_price_alias": "Price", "price_alias_added": selected != "Price",
        "originally_sorted": original_sorted, "sorting_performed": not original_sorted,
        "duplicates": 0, "missing_entries": 0, "nonpositive_or_nonfinite_prices": 0,
        "first_date": str(frame.Date.iloc[0].date()), "last_date": str(frame.Date.iloc[-1].date()),
        "max_calendar_gap_days": int(gaps.max()), "calendar_gaps": gap_records,
        "missing_us_equity_sessions": [str(d.date()) for d in expected.difference(observed)],
        "unexpected_us_equity_dates": [str(d.date()) for d in observed.difference(expected)],
        "calendar_assumption": "Diagnostic uses the supplied US-equity calendar; confirm exchange in provenance.",
        "price_units": "Per asset unit; currency and split/dividend adjustment must be read from provenance.",
        "nontrading_dates_filled": False, "rows_deleted": 0,
    }
    return frame, audit


def log_returns(prices: np.ndarray) -> np.ndarray:
    """Adjacent natural-log price differences; validate finite positive prices."""
    return _returns.log_returns(prices)


def descriptive_stats(values: np.ndarray) -> dict[str, float]:
    """Variance uses n-1; skew=m3/m2^1.5 and excess=m4/m2^2-3 use m_k/n.

    These higher sample moments are uncorrected moment ratios. A constant
    sample has undefined standardized higher moments and is rejected explicitly.
    """
    return _returns.describe(_sample(values))


def standardize(values: np.ndarray) -> np.ndarray:
    """Subtract the sample mean and divide by sample SD with divisor n-1."""
    x = _sample(values)
    sd = float(np.std(x, ddof=1))
    if sd <= 0:
        raise ValueError("A constant sample cannot be standardized.")
    return (x - float(np.mean(x))) / sd


def qq_coordinates(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return Phi^-1((i-.5)/n), sorted standardized values; reference is y=x."""
    z = standardize(values)
    theoretical = norm.ppf((np.arange(1, len(z) + 1) - 0.5) / len(z))
    return theoretical, np.sort(z)


def acf(values: np.ndarray, max_lag: int) -> np.ndarray:
    """Specified centered-sum ACF including rho(0)=1; constant input fails."""
    x = _sample(values)
    if isinstance(max_lag, bool) or not isinstance(max_lag, Integral) or not 0 <= max_lag < len(x):
        raise ValueError("max_lag must be an integer from 0 through n-1.")
    return _returns.acf(x, int(max_lag))


def fit_gbm(returns: np.ndarray, step: float = 1 / 252) -> dict[str, float]:
    """T8 moment estimators; m/mu/SE are per year, sigma per sqrt(year).

    Sample variance uses n-1, so its volatility/drift transform is not the
    normal variance MLE. Constant returns legitimately estimate sigma=0 here.
    """
    x = _sample(returns)
    if not math.isfinite(step) or step <= 0:
        raise ValueError("step must be a positive finite number of years.")
    mean = float(x.mean())
    variance = float(x.var(ddof=1))
    m, sigma2 = mean / step, variance / step
    sigma = math.sqrt(sigma2)
    se = sigma / math.sqrt(len(x) * step)
    return {"n": len(x), "step_years": step, "observed_horizon_years": len(x) * step,
            "m_hat": m, "sigma_hat": sigma, "sigma_squared_hat": sigma2,
            "mu_hat": m + sigma2 / 2, "log_drift_se": se}


def gbm_moments(s0: float, mu: float, sigma: float,
                horizon: float) -> dict[str, float]:
    """Derived GBM mean/variance/median; T=0 and sigma=0 are point masses."""
    return _gbm.model_moments(s0, mu, sigma, horizon)


def gbm_quantiles(probabilities: np.ndarray, s0: float, mu: float,
                  sigma: float, horizon: float) -> np.ndarray:
    """Exponentiate normal quantiles; probabilities must be strictly inside (0,1)."""
    _gbm.model_moments(s0, mu, sigma, horizon)
    p = _sample(probabilities, minimum=1)
    if np.any((p <= 0) | (p >= 1)):
        raise ValueError("Quantile probabilities must lie strictly inside (0,1).")
    return s0 * np.exp((mu - 0.5 * sigma**2) * horizon + sigma * math.sqrt(horizon) * norm.ppf(p))


def gbm_density(x: np.ndarray, s0: float, mu: float,
                sigma: float, horizon: float) -> np.ndarray:
    """Explicit ordinary lognormal density, zero off support; point mass fails."""
    return _gbm.density(x, s0, mu, sigma, horizon)


def exact_terminal(s0: float, mu: float, sigma: float, horizon: float,
                   count: int, rng: np.random.Generator) -> np.ndarray:
    """Exact law from the supplied generator, with no reseeding/time stepping."""
    return _gbm.exact_sampler(s0, mu, sigma, horizon, count, rng)


def mean_ci(values: np.ndarray) -> dict[str, float | tuple[float, float]]:
    """Sample mean and sample-SD/sqrt(n) approximate 95% mean confidence interval."""
    x = _sample(values)
    mean = float(np.mean(x))
    se = float(np.std(x, ddof=1) / math.sqrt(len(x)))
    return {"n": len(x), "mean": mean, "standard_error": se,
            "ci95": (mean - 1.96 * se, mean + 1.96 * se)}


def coupled_terminals(increments: np.ndarray, s0: float, mu: float,
                      sigma: float, step: float) -> dict[str, np.ndarray]:
    """Consume actual Brownian increments and retain all signed Euler values.

    *_nonpositive_multipliers is a path-by-step boolean matrix; *_nonpositive_path
    flags any path that encountered one. *_nonpositive_terminal instead tests
    the sign at the end, since two negative multipliers can restore positivity.
    Exact terminal values use the same rowwise sum of Brownian increments.
    """
    increments = _increments(increments)
    if not math.isfinite(step) or step <= 0:
        raise ValueError("step must be positive finite years.")
    paths, steps = increments.shape
    horizon = steps * step
    _gbm.model_moments(s0, mu, sigma, horizon)
    euler = np.full(paths, s0, dtype=float)
    wrong = np.full(paths, s0, dtype=float)
    euler_flags = np.zeros(increments.shape, dtype=bool)
    wrong_flags = np.zeros(increments.shape, dtype=bool)
    for j in range(steps):
        euler_multiplier = 1 + mu * step + sigma * increments[:, j]
        wrong_multiplier = 1 + mu * step + sigma * math.sqrt(step) * increments[:, j]
        euler_flags[:, j] = euler_multiplier <= 0
        wrong_flags[:, j] = wrong_multiplier <= 0
        euler *= euler_multiplier
        wrong *= wrong_multiplier
    exact = s0 * np.exp((mu - 0.5 * sigma**2) * horizon + sigma * increments.sum(axis=1))
    return {"exact": exact, "euler": euler, "wrong": wrong,
            "euler_nonpositive_multipliers": euler_flags,
            "wrong_nonpositive_multipliers": wrong_flags,
            "euler_nonpositive_path": euler_flags.any(axis=1),
            "wrong_nonpositive_path": wrong_flags.any(axis=1),
            "euler_nonpositive_terminal": euler <= 0,
            "wrong_nonpositive_terminal": wrong <= 0}


def coarsen_increments(finest: np.ndarray, coarse_steps: int) -> np.ndarray:
    """Sum consecutive fine increments, preserving each terminal Brownian sum."""
    finest = _increments(finest)
    coarse_steps = _positive_integer(coarse_steps, "coarse_steps")
    if finest.shape[1] % coarse_steps:
        raise ValueError("coarse_steps must divide the finest step count.")
    return finest.reshape(finest.shape[0], coarse_steps, finest.shape[1] // coarse_steps).sum(axis=2)


def discrete_moments(s0: float, mu: float, sigma: float, horizon: float,
                     steps: int, alpha: float) -> dict[str, float]:
    """Moments of product[1+mu*h+sigma*h**alpha*Y], for any finite alpha.

    Euler is alpha=.5 and the wrong scaling is alpha=1. No logarithm is
    needed, so negative multipliers are included in these exact moments.
    """
    _gbm.model_moments(s0, mu, sigma, horizon)
    steps = _positive_integer(steps, "steps")
    if not math.isfinite(alpha):
        raise ValueError("alpha must be finite.")
    if horizon == 0:
        return {"mean": float(s0), "variance": 0.0, "second_moment": float(s0**2),
                "nonpositive_multiplier_probability": 0.0}
    h = horizon / steps
    a = 1 + mu * h
    noise_sd = sigma * h**alpha
    mean = s0 * a**steps
    second = s0**2 * (a**2 + noise_sd**2)**steps
    probability = float(norm.cdf(-a / noise_sd)) if noise_sd > 0 else float(a <= 0)
    return {"mean": mean, "variance": max(0.0, second - mean**2),
            "second_moment": second, "nonpositive_multiplier_probability": probability}


def run_coupled_experiment(output_dir: str | Path, seed: int = 21603) -> None:
    """Write final A3 outputs under output_dir/{results,figures}, B<=1000.

    Existing experiment logic is shared, with destinations/seed set for this
    serial call and restored even if it fails. The seed is never reset inside
    a loop. A3 uses spawn key (3,), stress testing uses (4,).
    """
    if isinstance(seed, bool) or not isinstance(seed, Integral) or seed < 0:
        raise ValueError("seed must be a nonnegative integer.")
    import experiments_gbm as experiments
    root = Path(output_dir).resolve()
    results, figures = root / "results", root / "figures"
    results.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    previous = experiments.RESULTS, experiments.FIGURES, experiments.MASTER_SEED
    try:
        experiments.RESULTS, experiments.FIGURES, experiments.MASTER_SEED = results, figures, int(seed)
        with (results / "A3_interface_execution.txt").open("w", encoding="utf-8") as handle:
            with redirect_stdout(experiments.Tee(sys.stdout, handle)):
                metadata = {"started_China_Standard_Time": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                            "master_seed": int(seed), "A3_spawn_key": [3], "stress_spawn_key": [4],
                            "python": sys.version, "numpy": np.__version__, "platform": platform.platform(),
                            "batch_size": 1000, "M": 20000, "stress_M": 100000,
                            "step_counts": [16, 32, 64, 128, 256],
                            "destinations": {"results": str(results), "figures": str(figures)}}
                print(json.dumps(metadata, indent=2))
                summary = experiments.run_a3()
        (results / "A3_interface_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        (results / "A3_interface_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    finally:
        experiments.RESULTS, experiments.FIGURES, experiments.MASTER_SEED = previous
