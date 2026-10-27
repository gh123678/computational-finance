"""GBM primitives and bounded-batch coupled discretizations for HW03.

The update, product-moment, and Brownian aggregation logic is implemented here.
No random seed is changed inside a simulation or replication loop.
"""

from __future__ import annotations

import math
from numbers import Integral
from typing import Iterable

import numpy as np


def _model(S0: float, mu: float, sigma: float, T: float) -> tuple[float, ...]:
    values = tuple(float(x) for x in (S0, mu, sigma, T))
    if not all(math.isfinite(x) for x in values):
        raise ValueError("Model inputs must be finite real numbers.")
    if values[0] <= 0 or values[2] < 0 or values[3] < 0:
        raise ValueError("Require S0 > 0, sigma >= 0, and T >= 0.")
    return values


def _integer(value: int, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}.")
    return int(value)


def model_moments(S0: float, mu: float, sigma: float, T: float) -> dict[str, float]:
    """Return population GBM moments, including deterministic limiting cases."""
    S0, mu, sigma, T = _model(S0, mu, sigma, T)
    mean = S0 * math.exp(mu * T)
    variance = mean**2 * math.expm1(sigma**2 * T)
    return {
        "mean": mean,
        "variance": variance,
        "second_moment": mean**2 + variance,
        "median": S0 * math.exp((mu - 0.5 * sigma**2) * T),
    }


def prediction_interval(
    S0: float, mu: float, sigma: float, T: float, z: float = 1.96
) -> tuple[float, float]:
    """Central interval when z is the relevant positive normal quantile."""
    S0, mu, sigma, T = _model(S0, mu, sigma, T)
    if not math.isfinite(z) or z < 0:
        raise ValueError("z must be finite and nonnegative.")
    center = (mu - 0.5 * sigma**2) * T
    width = z * sigma * math.sqrt(T)
    return S0 * math.exp(center - width), S0 * math.exp(center + width)


def density(x, S0: float, mu: float, sigma: float, T: float):
    """Ordinary terminal lognormal density; zero outside its positive support.

    T=0 or sigma=0 is a point mass, which has no ordinary Lebesgue density.
    Infinite x values have limiting density zero; NaN evaluation points fail.
    """
    S0, mu, sigma, T = _model(S0, mu, sigma, T)
    if T == 0 or sigma == 0:
        raise ValueError("A point mass (T=0 or sigma=0) has no ordinary density.")
    x_values = np.asarray(x, dtype=float)
    if np.isnan(x_values).any():
        raise ValueError("Density evaluation points must not contain NaN.")
    result = np.zeros_like(x_values)
    positive = (x_values > 0) & np.isfinite(x_values)
    xp = x_values[positive]
    v = sigma**2 * T
    log_z = np.log(xp / S0) - (mu - 0.5 * sigma**2) * T
    result[positive] = np.exp(-log_z**2 / (2 * v)) / (xp * math.sqrt(2 * math.pi * v))
    return float(result) if result.ndim == 0 else result


def exact_sampler(
    S0: float,
    mu: float,
    sigma: float,
    T: float,
    size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Sample terminal GBM directly, without time stepping."""
    S0, mu, sigma, T = _model(S0, mu, sigma, T)
    size = _integer(size, "size", minimum=0)
    if not isinstance(rng, np.random.Generator):
        raise TypeError("Pass an explicit numpy.random.Generator.")
    if T == 0 or sigma == 0:
        return np.full(size, S0 * math.exp(mu * T))
    z = rng.standard_normal(size)
    return S0 * np.exp((mu - 0.5 * sigma**2) * T + sigma * math.sqrt(T) * z)


def product_moments(
    S0: float,
    mu: float,
    sigma: float,
    T: float,
    n: int,
    method: str = "euler",
) -> dict[str, float]:
    """Exact finite-n product moments and errors under Brownian coupling.

    With a = 1+mu*h and Brownian coefficient c (sigma for Euler,
    sigma*sqrt(h) for the wrong scheme), E[P^2] = S0^2(a^2+c^2*h)^n.
    The exact-factor/product-factor cross moment per step is
    exp(mu*h)*(a + sigma*c*h). This gives an independent benchmark for
    the coupled mean squared error rather than comparing means alone.
    """
    S0, mu, sigma, T = _model(S0, mu, sigma, T)
    n = _integer(n, "n")
    if method not in {"euler", "wrong"}:
        raise ValueError("method must be 'euler' or 'wrong'.")
    h = T / n
    a = 1 + mu * h
    c = sigma if method == "euler" else sigma * math.sqrt(h)
    mean = S0 * a**n
    second = S0**2 * (a**2 + c**2 * h) ** n
    variance = max(0.0, second - mean**2)
    exact = model_moments(S0, mu, sigma, T)
    cross = S0**2 * (math.exp(mu * h) * (a + sigma * c * h)) ** n
    mse_exact = max(0.0, second + exact["second_moment"] - 2 * cross)
    deterministic_mse = variance + (mean - exact["mean"]) ** 2
    return {
        "mean": mean,
        "variance": variance,
        "second_moment": second,
        "cross_moment_with_exact": cross,
        "mse_against_exact": mse_exact,
        "rmse_against_exact": math.sqrt(mse_exact),
        "mse_against_deterministic": deterministic_mse,
        "rmse_against_deterministic": math.sqrt(deterministic_mse),
    }


def coupled_terminals(
    S0: float,
    mu: float,
    sigma: float,
    T: float,
    paths: int,
    steps: Iterable[int],
    rng: np.random.Generator,
    batch_size: int = 1000,
) -> dict:
    """Return exact/Euler/wrong terminals from the same finest Brownian grid.

    A coarse increment is an explicit sum of contiguous fine increments.
    Wrong updates use sigma*sqrt(h)*dW, equal to sigma*h*Y.
    Nonpositive multipliers are counted before updating; none are clipped.
    Working arrays have O(batch_size*max(steps)) entries. Returned terminal
    arrays have O(paths*(1+2*len(steps))) entries and are separate from working
    arrays. Only these terminals, rather than full paths, are retained.
    """
    S0, mu, sigma, T = _model(S0, mu, sigma, T)
    paths = _integer(paths, "paths")
    batch_size = _integer(batch_size, "batch_size")
    if batch_size > 1000:
        raise ValueError("HW03 requires batches of at most 1000 paths.")
    ns = sorted({_integer(n, "step count") for n in steps})
    if not ns:
        raise ValueError("At least one resolution is required.")
    finest_n = ns[-1]
    if any(finest_n % n for n in ns):
        raise ValueError("Every step count must divide the finest step count.")
    if not isinstance(rng, np.random.Generator):
        raise TypeError("Pass an explicit numpy.random.Generator.")
    exact = np.empty(paths)
    euler = {n: np.empty(paths) for n in ns}
    wrong = {n: np.empty(paths) for n in ns}
    nonpositive = {method: {n: 0 for n in ns} for method in ("euler", "wrong")}
    fine_sd = math.sqrt(T / finest_n)
    for start in range(0, paths, batch_size):
        stop = min(start + batch_size, paths)
        b = stop - start
        fine = rng.standard_normal((b, finest_n))
        fine *= fine_sd
        exact[start:stop] = S0 * np.exp(
            (mu - 0.5 * sigma**2) * T + sigma * fine.sum(axis=1)
        )
        for n in ns:
            h = T / n
            coarse = fine.reshape(b, n, finest_n // n).sum(axis=2)
            e = np.full(b, S0, dtype=float)
            w = np.full(b, S0, dtype=float)
            for j in range(n):
                e_multiplier = 1 + mu * h + sigma * coarse[:, j]
                w_multiplier = 1 + mu * h + sigma * math.sqrt(h) * coarse[:, j]
                nonpositive["euler"][n] += int(np.count_nonzero(e_multiplier <= 0))
                nonpositive["wrong"][n] += int(np.count_nonzero(w_multiplier <= 0))
                e *= e_multiplier
                w *= w_multiplier
            euler[n][start:stop] = e
            wrong[n][start:stop] = w
    return {
        "exact": exact,
        "euler": euler,
        "wrong": wrong,
        "nonpositive_multipliers": nonpositive,
        "paths": paths,
        "steps": ns,
        "batch_size": batch_size,
        "finest_steps": finest_n,
    }
