"""Reproduce all final A2/A3 experiments, tables, and figures.

Run: python code/experiments_gbm.py --run-tests
The fixed final counts are A2 100000, A3 20000, stress 100000.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scipy
from scipy.integrate import quad
from scipy.stats import norm

from gbm import (
    coupled_terminals,
    density,
    exact_sampler,
    model_moments,
    prediction_interval,
    product_moments,
)

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "results"
FIGURES = BASE / "figures"
MASTER_SEED = 21603


def stream(key: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence(MASTER_SEED, spawn_key=(key,)))


def csv_table(name: str, rows: list[dict]) -> None:
    with (RESULTS / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save_figure(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(FIGURES / f"{name}.png", dpi=180)
    fig.savefig(FIGURES / f"{name}.pdf")
    plt.close(fig)


def describe(x: np.ndarray) -> dict[str, float]:
    n = len(x)
    mean = float(np.mean(x))
    variance = float(np.var(x, ddof=1))
    fourth = float(np.mean((x - mean) ** 4))
    # Plug-in form of Var(unbiased sample variance), a Monte Carlo diagnostic.
    variance_se = math.sqrt(max(0.0, (fourth - (n - 3) / (n - 1) * variance**2) / n))
    return {
        "sample_mean": mean,
        "sample_variance_n_minus_1": variance,
        "mean_mcse": math.sqrt(variance / n),
        "variance_mcse_plugin": variance_se,
    }


def error_summary(errors: np.ndarray) -> dict[str, float]:
    squared = errors**2
    mse = float(np.mean(squared))
    mse_se = float(np.std(squared, ddof=1) / math.sqrt(len(errors)))
    rmse = math.sqrt(mse)
    return {
        "mse": mse,
        "mse_mcse": mse_se,
        "rmse": rmse,
        "rmse_mcse_delta": mse_se / (2 * rmse) if rmse else 0.0,
    }


def run_a2() -> dict:
    print("A2: exact terminal sampling, M=100000, SeedSequence(21603, spawn_key=(2,)).")
    norm_rows = []
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    grid = np.linspace(0.02, 4.0, 1800)
    for mu in (0.05, 0.20):
        integral, quadrature_error = quad(
            lambda x: density(x, 1, mu, 0.4, 1), 0, np.inf, epsabs=1e-11
        )
        moments = model_moments(1, mu, 0.4, 1)
        norm_rows.append({
            "S0": 1, "mu_per_year": mu, "sigma_per_sqrt_year": 0.4, "T_years": 1,
            "density_integral_0_infinity": integral,
            "quadrature_error_estimate": quadrature_error,
            "mean": moments["mean"], "median": moments["median"],
        })
        ax.plot(grid, density(grid, 1, mu, 0.4, 1), label=f"Annual drift = {mu:.2f}")
    ax.set(xlabel="Terminal price (price units)", ylabel="Probability density (1 / price unit)",
           title="A2(a): GBM terminal densities; S0 = 1, T = 1 year, volatility = 0.40")
    ax.legend()
    ax.grid(alpha=0.2)
    save_figure(fig, "A2_density_comparison")
    csv_table("A2_density_normalization.csv", norm_rows)

    S0, mu, sigma, T, M = 100.0, 0.08, 0.30, 2.0, 100000
    sample = exact_sampler(S0, mu, sigma, T, M, stream(2))
    moments = model_moments(S0, mu, sigma, T)
    stats = describe(sample)
    ci_low = stats["sample_mean"] - 1.96 * stats["mean_mcse"]
    ci_high = stats["sample_mean"] + 1.96 * stats["mean_mcse"]
    pi_low, pi_high = prediction_interval(S0, mu, sigma, T)
    inside = (sample >= pi_low) & (sample <= pi_high)
    coverage = float(np.mean(inside))
    # The assignment fixes z=1.96, giving normal coverage 2*Phi(1.96)-1.
    model_coverage = float(2 * norm.cdf(1.96) - 1)
    coverage_mcse = math.sqrt(model_coverage * (1 - model_coverage) / M)
    moment_row = {
        "M": M, "S0": S0, "mu_per_year": mu, "sigma_per_sqrt_year": sigma,
        "T_years": T, **stats,
        "analytical_mean": moments["mean"],
        "analytical_variance": moments["variance"],
        "mean_error_in_mcse": (stats["sample_mean"] - moments["mean"]) / stats["mean_mcse"],
        "mean_ci95_lower": ci_low, "mean_ci95_upper": ci_high,
        "fixed_prediction95_lower": pi_low, "fixed_prediction95_upper": pi_high,
    }
    coverage_row = {
        "M": M, "inside_count": int(np.count_nonzero(inside)),
        "empirical_fraction": coverage, "model_fraction_using_z1_96": model_coverage,
        "binomial_mcse_model": coverage_mcse,
        "binomial_mcse_plugin": math.sqrt(coverage * (1 - coverage) / M),
        "fraction_error_in_mcse": (coverage - model_coverage) / coverage_mcse,
        "mc_interval95_lower": coverage - 1.96 * coverage_mcse,
        "mc_interval95_upper": coverage + 1.96 * coverage_mcse,
    }
    csv_table("A2_terminal_moments.csv", [moment_row])
    csv_table("A2_prediction_coverage.csv", [coverage_row])
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    ax.hist(sample, bins=90, density=True, color="#6b9ac4", alpha=0.62,
            label=f"Exact samples (M = {M:,})")
    grid = np.linspace(max(1e-4, sample.min() * 0.7), sample.max() * 1.02, 2200)
    ax.plot(grid, density(grid, S0, mu, sigma, T), color="#a63d40", lw=1.8,
            label="Analytical lognormal density")
    ax.axvline(pi_low, color="#3b6c42", ls="--", lw=1.2, label="Fixed 95% prediction bounds")
    ax.axvline(pi_high, color="#3b6c42", ls="--", lw=1.2)
    ax.set(xlabel="Terminal price (price units)", ylabel="Probability density (1 / price unit)",
           title="A2(b): exact GBM at T = 2 years; S0 = 100, drift = 0.08, volatility = 0.30")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.15)
    save_figure(fig, "A2_terminal_histogram")
    print(json.dumps({"moments": moment_row, "coverage": coverage_row}, indent=2))
    return {"normalization": norm_rows, "terminal": moment_row, "coverage": coverage_row}


def run_a3() -> dict:
    S0, mu, sigma, T, M = 100.0, 0.08, 0.30, 1.0, 20000
    ns = [16, 32, 64, 128, 256]
    print("A3: M=20000, n=16,32,64,128,256, batch=1000, spawn_key=(3,).")
    output = coupled_terminals(S0, mu, sigma, T, M, ns, stream(3), batch_size=1000)
    exact = output["exact"]
    deterministic = S0 * math.exp(mu * T)
    analytical_exact = model_moments(S0, mu, sigma, T)
    exact_stats = describe(exact)
    rows, checks = [], []
    for n in ns:
        for method in ("euler", "wrong"):
            values = output[method][n]
            stats = describe(values)
            errors = error_summary(values - exact)
            deterministic_errors = error_summary(values - deterministic)
            theory = product_moments(S0, mu, sigma, T, n, method)
            cross_values = values * exact
            cross = float(np.mean(cross_values))
            cross_se = float(np.std(cross_values, ddof=1) / math.sqrt(M))
            row = {
                "method": method, "n": n, "h_years": T / n, "M": M,
                **stats,
                "analytical_discrete_mean": theory["mean"],
                "analytical_discrete_variance": theory["variance"],
                "sample_exact_mean": exact_stats["sample_mean"],
                "sample_exact_variance": exact_stats["sample_variance_n_minus_1"],
                "analytical_exact_mean": analytical_exact["mean"],
                "analytical_exact_variance": analytical_exact["variance"],
                "rmse_against_coupled_exact": errors["rmse"],
                "rmse_exact_mcse_delta": errors["rmse_mcse_delta"],
                "analytical_rmse_against_coupled_exact": theory["rmse_against_exact"],
                "rmse_against_deterministic": deterministic_errors["rmse"],
                "rmse_deterministic_mcse_delta": deterministic_errors["rmse_mcse_delta"],
                "analytical_rmse_against_deterministic": theory["rmse_against_deterministic"],
                "nonpositive_multiplier_count": output["nonpositive_multipliers"][method][n],
                "nonpositive_terminal_count": int(np.count_nonzero(values <= 0)),
            }
            rows.append(row)
            checks.append({
                "method": method, "n": n, "M": M,
                "sample_coupled_cross_moment": cross,
                "analytical_coupled_cross_moment": theory["cross_moment_with_exact"],
                "cross_moment_mcse": cross_se,
                "cross_moment_error_in_mcse": (cross - theory["cross_moment_with_exact"]) / cross_se,
                "sample_coupled_mse": errors["mse"],
                "analytical_coupled_mse": theory["mse_against_exact"],
                "mse_mcse": errors["mse_mcse"],
                "mse_error_in_mcse": (errors["mse"] - theory["mse_against_exact"]) / errors["mse_mcse"],
            })
    csv_table("A3_convergence.csv", rows)
    csv_table("A3_coupled_moment_checks.csv", checks)
    csv_table("A3_exact_reference.csv", [{
        "M": M, "S0": S0, "mu_per_year": mu, "sigma_per_sqrt_year": sigma,
        "T_years": T, **exact_stats,
        "analytical_mean": analytical_exact["mean"],
        "analytical_variance": analytical_exact["variance"],
        "deterministic_limit_wrong_model": deterministic,
    }])
    euler_rows = [row for row in rows if row["method"] == "euler"]
    wrong_rows = [row for row in rows if row["method"] == "wrong"]
    h = np.array([r["h_years"] for r in euler_rows])
    log_h = np.log(h)
    log_error = np.log([r["rmse_against_coupled_exact"] for r in euler_rows])
    slope = float(np.sum((log_h - log_h.mean()) * (log_error - log_error.mean()))
                  / np.sum((log_h - log_h.mean()) ** 2))
    intercept = float(log_error.mean() - slope * log_h.mean())
    csv_table("A3_error_slope.csv", [{
        "fit": "OLS log(RMSE_Euler_exact) on log(h), all five resolutions",
        "observed_slope": slope, "intercept": intercept,
        "expected_asymptotic_strong_order": 0.5,
        "qualification": "One coupled Monte Carlo run is evidence, not a rate proof.",
    }])
    fig, ax = plt.subplots(figsize=(7.4, 4.8))
    for selected, label, color in (
        (euler_rows, "Euler vs coupled exact", "#27699b"),
        (wrong_rows, "Wrong scaling vs coupled exact", "#a63d40"),
    ):
        ax.loglog(h, [r["rmse_against_coupled_exact"] for r in selected], "o-", color=color, label=label)
        ax.loglog(h, [r["analytical_rmse_against_coupled_exact"] for r in selected], "--", color=color, alpha=0.6)
    ax.loglog(h, [r["rmse_against_deterministic"] for r in wrong_rows], "s-", color="#47834d",
              label="Wrong scaling vs deterministic limit")
    ax.loglog(h, [r["analytical_rmse_against_deterministic"] for r in wrong_rows], "--", color="#47834d", alpha=0.6)
    ax.loglog(h, np.exp(intercept) * h**slope, ":", color="#333333",
              label=f"Euler fitted slope = {slope:.3f}")
    ax.set(xlabel="Step size h (years)", ylabel="Terminal RMSE (price units)",
           title="A3(b): coupled errors; dashed curves are exact finite-step formulas")
    ax.legend(fontsize=8)
    ax.grid(which="both", alpha=0.2)
    save_figure(fig, "A3_coupled_error")
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    for selected, label, color in (
        (euler_rows, "Euler", "#27699b"), (wrong_rows, "Wrong scaling", "#a63d40")
    ):
        ax.plot(h, [r["sample_variance_n_minus_1"] for r in selected], "o", color=color,
                label=f"{label}: sample variance")
        ax.plot(h, [r["analytical_discrete_variance"] for r in selected], "-", color=color,
                label=f"{label}: product-moment formula")
    ax.axhline(analytical_exact["variance"], color="#333333", ls="--", label="Exact GBM variance")
    ax.set(xlabel="Step size h (years)", ylabel="Terminal price variance (price units squared)",
           title="A3(b): variance survives for GBM/Euler and vanishes for wrong scaling")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2)
    save_figure(fig, "A3_variance")

    stress_M, stress_n, stress_count = 100000, 1000, 0
    stress_rng = stream(4)
    for start in range(0, stress_M, stress_n):
        z = stress_rng.standard_normal(min(stress_n, stress_M - start))
        multiplier = 1 + 0.08 + z  # sigma = h = T = 1
        stress_count += int(np.count_nonzero(multiplier <= 0))
    p = float(norm.cdf(-1.08))
    observed = stress_count / stress_M
    stress_mcse = math.sqrt(p * (1 - p) / stress_M)
    stress = {
        "M": stress_M, "S0": 100, "mu_per_year": 0.08, "sigma_per_sqrt_year": 1,
        "T_years": 1, "h_years": 1,
        "threshold_Y": -1.08, "analytical_nonpositive_probability": p,
        "nonpositive_count": stress_count, "observed_fraction": observed,
        "binomial_mcse_model": stress_mcse,
        "binomial_mcse_plugin": math.sqrt(observed * (1 - observed) / stress_M),
        "fraction_error_in_mcse": (observed - p) / stress_mcse,
        "clipped_or_discarded": False,
    }
    csv_table("A3_stress.csv", [stress])
    # Conservative dominant-array bound: fine + coarse grids plus 12 batch vectors.
    working_bytes_bound = 8 * 1000 * (2 * max(ns) + 12)
    terminal_bytes = 8 * M * (1 + 2 * len(ns))
    complexity = {
        "batch_size_paths": 1000,
        "fine_grid_per_batch_bytes": 8 * 1000 * max(ns),
        "dominant_working_arrays_upper_estimate_bytes": working_bytes_bound,
        "retained_terminal_arrays_bytes": terminal_bytes,
        "saved_csv_rows": {"convergence": len(rows), "coupled_checks": len(checks), "stress": 1},
        "time_complexity": "O(M * (n_max + sum(n))); geometric resolutions make sum(n) < 2*n_max.",
        "peak_working_array_complexity": "O(B*n_max); B <= 1000. Excludes retained terminal outputs.",
        "retained_output_complexity": "O(M*K) terminal arrays for K resolutions; no full paths saved.",
        "memory_scope": "Array estimate excludes Python, plotting, RNG overhead, and figure buffers; not a measured process RSS.",
        "independent_paths_warning": "Independent reference paths add physical path variation and do not measure pathwise discretization error.",
    }
    (RESULTS / "A3_complexity.json").write_text(json.dumps(complexity, indent=2), encoding="utf-8")
    summary = {"euler_observed_slope": slope, "exact_reference": exact_stats,
               "max_abs_cross_moment_z": max(abs(c["cross_moment_error_in_mcse"]) for c in checks),
               "max_abs_mse_z": max(abs(c["mse_error_in_mcse"]) for c in checks),
               "stress": stress, "complexity": complexity}
    print(json.dumps(summary, indent=2))
    return summary


class Tee:
    def __init__(self, *handles):
        self.handles = handles

    def write(self, data):
        for handle in self.handles:
            handle.write(data)
            handle.flush()
        return len(data)

    def flush(self):
        for handle in self.handles:
            handle.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-tests", action="store_true", help="Run actual validation tests before final simulations.")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone(timedelta(hours=8))).isoformat()
    environment = {
        "run_started_China_Standard_Time": started,
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "numpy": np.__version__, "scipy": scipy.__version__, "matplotlib": matplotlib.__version__,
        "master_seed": MASTER_SEED,
        "generator": "numpy.random.default_rng / PCG64",
        "seed_sequence_spawn_keys": {"A2": [2], "A3": [3], "stress": [4]},
        "A2_parameters": {"S0": 100, "mu": 0.08, "sigma": 0.30, "T": 2, "M": 100000},
        "A3_parameters": {"S0": 100, "mu": 0.08, "sigma": 0.30, "T": 1, "M": 20000,
                          "steps": [16, 32, 64, 128, 256], "batch_size": 1000},
        "variance_divisor": "n-1",
        "source_sha256": {name: hashlib.sha256((BASE / "code" / name).read_bytes()).hexdigest()
                          for name in ("gbm.py", "experiments_gbm.py", "test_gbm.py")},
        "invocation": [sys.executable, *sys.argv],
    }
    (RESULTS / "A2_A3_environment.json").write_text(json.dumps(environment, indent=2), encoding="utf-8")
    with (RESULTS / "A2_A3_execution.txt").open("w", encoding="utf-8") as log:
        with contextlib.redirect_stdout(Tee(sys.stdout, log)):
            start_clock = time.perf_counter()
            print(f"Actual execution began: {started}")
            print(json.dumps(environment, indent=2))
            if args.run_tests:
                process = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", str(BASE / "code" / "test_gbm.py")],
                    capture_output=True, text=True, encoding="utf-8", errors="replace"
                )
                print(process.stdout)
                print(process.stderr)
                print(f"Actual pytest exit status: {process.returncode}")
                if process.returncode:
                    raise RuntimeError("Validation failed; final simulations were not run.")
            a2 = run_a2()
            a3 = run_a3()
            summary = {"A2": a2, "A3": a3, "elapsed_seconds": time.perf_counter() - start_clock}
            (RESULTS / "A2_A3_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(f"Actual execution completed in {summary['elapsed_seconds']:.3f} seconds.")


if __name__ == "__main__":
    main()
