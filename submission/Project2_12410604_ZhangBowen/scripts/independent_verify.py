"""Recompute saved results from the raw archives without importing project code.

Only Python's standard library and NumPy are used. Signal formation, OLS and
robust covariance, target sizing, funded trading, and performance statistics
are reconstructed separately from src/ and p1_platform/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile

import numpy as np


def month_number(label):
    year, month = map(int, label[:7].split("-"))
    return year * 12 + month - 1


def month_label(number):
    return f"{number // 12:04d}-{number % 12 + 1:02d}"


def read_raw(path, digits):
    """Strictly read the first numeric factor section; values become decimals."""
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        assert len(names) == 1, f"Expected one factor CSV in {path.name}"
        text = archive.read(names[0]).decode("utf-8-sig")
    rows = {}
    previous = ""
    for line in csv.reader(io.StringIO(text)):
        key = line[0].strip() if line else ""
        if not re.fullmatch(r"\d{" + str(digits) + "}", key):
            if rows:
                break
            continue
        assert len(line) == 5, f"Unexpected factor schema: {key}"
        assert key > previous, f"Duplicate/unordered observation: {key}"
        previous = key
        values = np.asarray([float(value) for value in line[1:]], dtype=float)
        assert np.isfinite(values).all() and np.all(values > -99.99)
        rows[key] = values / 100
    assert rows, f"No observations in {path.name}"
    return rows


def raw_panel(root, vintage, ddof=0):
    daily = read_raw(root / "data" / "raw" / f"{vintage}_daily.zip", 8)
    monthly = read_raw(root / "data" / "raw" / f"{vintage}_monthly.zip", 6)
    grouped = {}
    for date, values in daily.items():
        label = date[:4] + "-" + date[4:6]
        grouped.setdefault(label, []).append(values[0])
    panel = {}
    for date, values in monthly.items():
        label = date[:4] + "-" + date[4:6]
        obs = np.asarray(grouped[label])
        assert len(obs) >= 10
        panel[label] = {"market_excess": float(values[0]), "rf": float(values[3]),
                        "rv": float(np.sum((obs - obs.mean()) ** 2) * len(obs) / (len(obs) - ddof)),
                        "daily_count": len(obs)}
    labels = sorted(panel)
    assert [month_number(x) for x in labels] == list(range(month_number(labels[0]), month_number(labels[-1]) + 1))
    for label in labels:
        previous = month_label(month_number(label) - 1)
        panel[label]["lag_rv"] = panel[previous]["rv"] if previous in panel else math.nan
    return panel


def dates_between(panel, start, end):
    expected = [month_label(i) for i in range(month_number(start), month_number(end) + 1)]
    assert all(label in panel for label in expected), "Requested sample not present in source"
    return expected


def scale_for(panel, labels):
    returns = np.asarray([panel[label]["market_excess"] for label in labels])
    lagged = np.asarray([panel[label]["lag_rv"] for label in labels])
    assert np.isfinite(lagged).all() and np.all(lagged > 0)
    return float(np.std(returns, ddof=1) / np.std(returns / lagged, ddof=1))


def direct_regression(y, x, covariance="HC1", hac_lags=6):
    x, y = np.asarray(x), np.asarray(y)
    design = np.column_stack([np.ones(len(x)), x])
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    residual = y - design @ coef
    bread = np.linalg.inv(design.T @ design)
    score = residual[:, None] * design
    meat = score.T @ score
    if covariance == "HAC":
        for lag in range(1, hac_lags + 1):
            cross = score[lag:].T @ score[:-lag]
            meat += (1 - lag / (hac_lags + 1)) * (cross + cross.T)
        correction = len(x) / (len(x) - 2)
    else:
        assert covariance in {"HC0", "HC1"}, f"Unsupported independent covariance: {covariance}"
        correction = len(x) / (len(x) - 2) if covariance == "HC1" else 1
    standard_errors = np.sqrt(np.diag(bread @ meat @ bread * correction))
    return {"n": len(x), "alpha_annual_pct": float(coef[0] * 1200),
            "alpha_se_annual_pct": float(standard_errors[0] * 1200),
            "alpha_t": float(coef[0] / standard_errors[0]),
            "beta": float(coef[1]), "beta_se": float(standard_errors[1]),
            "r_squared": float(1 - residual @ residual / np.sum((y - y.mean()) ** 2)),
            "rmse_paper_units": float(np.sqrt(residual @ residual / (len(x) - 2)) * 1200)}


def book_account(panel, labels, weights, cost_bps, financing_spread_bps=0):
    """Trade risky dollars with a numerical root, then evolve risky dollars/cash."""
    wealth, risky_dollars = 1., 0.
    k, monthly_spread = cost_bps / 10000, financing_spread_bps / 10000 / 12
    result = []
    for label, weight in zip(labels, weights):
        old_wealth = wealth
        pretrade_weight = risky_dollars / old_wealth
        lower, upper = 0., 2 * max(weight * wealth, risky_dollars, 1.)
        for _ in range(100):
            new_risky = (lower + upper) / 2
            balance = new_risky - weight * (wealth - k * abs(new_risky - risky_dollars))
            if balance > 0:
                upper = new_risky
            else:
                lower = new_risky
        new_risky = (lower + upper) / 2
        traded = abs(new_risky - risky_dollars)
        fee_dollars = k * traded
        cash_dollars = old_wealth - fee_dollars - new_risky
        rf, market_excess = panel[label]["rf"], panel[label]["market_excess"]
        borrowing_charge = max(-cash_dollars, 0) * monthly_spread
        risky_dollars = new_risky * (1 + rf + market_excess)
        cash_dollars = cash_dollars * (1 + rf) - borrowing_charge
        wealth = risky_dollars + cash_dollars
        total = wealth / old_wealth - 1
        assert wealth > 0 and np.isfinite(wealth)
        result.append({"month": label, "market_excess": market_excess, "rf": rf,
                       "weight": weight, "pretrade_weight": pretrade_weight,
                       "one_way_turnover": traded / old_wealth,
                       "fee_fraction": fee_dollars / old_wealth,
                       "financing_fraction": borrowing_charge / (old_wealth - fee_dollars),
                       "gross_excess": weight * market_excess,
                       "net_excess": total - rf, "total_return": total, "nav": wealth})
    return result


def read_saved_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def read_saved_panel(path):
    rows = read_saved_csv(path)
    assert rows, f"Empty result file: {path.name}"
    date_key = next(key for key in rows[0] if key in {"", "date", "month"})
    return rows, [row[date_key][:7] for row in rows]


class Audit:
    def __init__(self):
        self.checks = []

    def close(self, name, saved, expected, atol=1e-11, rtol=1e-9):
        a, b = np.asarray(saved, float), np.asarray(expected, float)
        np.testing.assert_allclose(a, b, atol=atol, rtol=rtol, err_msg=name)
        self.checks.append({"check": name, "observations": int(a.size),
                            "maximum_absolute_error": float(np.max(np.abs(a - b))) if a.size else 0.})

    def assert_true(self, name, value):
        assert value, name
        self.checks.append({"check": name, "passed": True})


def independent_metrics(rows):
    total = np.asarray([row["total_return"] for row in rows])
    excess = np.asarray([row["net_excess"] for row in rows])
    weights = np.asarray([row["weight"] for row in rows])
    turnover = np.asarray([row["one_way_turnover"] for row in rows])
    nav = np.r_[1., np.cumprod(1 + total)]
    vol = np.std(excess, ddof=1) * np.sqrt(12)
    return {"months": len(total), "periods_per_year": 12,
            "total_return": nav[-1] - 1, "cagr_total": nav[-1] ** (12 / len(total)) - 1,
            "max_drawdown_total": np.max(1 - nav / np.maximum.accumulate(nav)),
            "final_nav": nav[-1], "annualized_mean_excess": excess.mean() * 12,
            "annualized_volatility_excess": vol,
            "sharpe": excess.mean() * 12 / vol,
            "average_weight": weights.mean(), "minimum_weight": weights.min(),
            "maximum_weight": weights.max(), "average_gross_exposure": np.abs(weights).mean(),
            "total_turnover": turnover.sum(), "average_monthly_turnover": turnover.mean(),
            "annualized_turnover": turnover.mean() * 12}


def verify(root, results=None):
    results = results or root / "results"
    audit = Audit()
    config = json.loads((root / "config.json").read_text(encoding="utf-8-sig"))
    manifest = json.loads((root / "data" / "source_manifest.json").read_text(encoding="utf-8-sig"))
    for item in manifest:
        actual = hashlib.sha256((root / "data" / "raw" / item["file"]).read_bytes()).hexdigest()
        audit.assert_true("source SHA256 " + item["file"], actual == item["sha256"])
    baseline = raw_panel(root, "fiz", config["variance_ddof"])
    original_dates = dates_between(baseline, config["replication_start"], config["replication_end"])
    original_scale = scale_for(baseline, original_dates)
    original_weights = np.asarray([original_scale / baseline[label]["lag_rv"] for label in original_dates])
    original_market = np.asarray([baseline[label]["market_excess"] for label in original_dates])
    original_managed = original_weights * original_market
    saved_original, saved_dates = read_saved_panel(results / "original_monthly.csv")
    audit.assert_true("original exact monthly sample", saved_dates == original_dates)
    for key in ["market_excess", "rf", "rv", "lag_rv", "daily_count"]:
        audit.close("original " + key, [float(row[key]) for row in saved_original],
                    [baseline[label][key] for label in original_dates])
    audit.close("original inverse variance weights", [float(row["weight"]) for row in saved_original], original_weights)
    audit.close("original managed excess return", [float(row["managed_excess"]) for row in saved_original], original_managed)
    audit.close("original equal volatility normalization", np.std(original_market, ddof=1), np.std(original_managed, ddof=1))
    saved_regression = json.loads((results / "original_regression.json").read_text(encoding="utf-8-sig"))
    independent_regression = direct_regression(original_managed, original_market,
                                              saved_regression.get("covariance", config["regression_se"]),
                                              config["hac_lags_sensitivity"])
    for key, value in independent_regression.items():
        audit.close("original regression " + key, saved_regression[key], value)

    holdout_dates = dates_between(baseline, config["holdout_start"], config["holdout_end"])
    # Freeze the scale before the first held-out return. No held-out observation
    # is used in the variance normalization; monthly lag signals update normally.
    training_end = config.get("training_end", month_label(month_number(config["holdout_start"]) - 1))
    training_start = config.get("training_start", config["replication_start"])
    training_dates = dates_between(baseline, training_start, training_end)
    audit.assert_true("calibration strictly precedes holdout", training_end < config["holdout_start"])
    training_scale = scale_for(baseline, training_dates)
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    audit.close("saved calibration scale", summary["scale"], training_scale)
    uncapped = np.asarray([training_scale / baseline[label]["lag_rv"] for label in holdout_dates])
    targets = {"market": np.ones(len(holdout_dates)), "uncapped": uncapped,
               "cap2": np.minimum(uncapped, config["leverage_cap"])}
    independently_rebuilt = {}
    for strategy, weights in targets.items():
        for cost in config["one_way_cost_bps"]:
            name = f"holdout_{strategy}_{cost}bp.csv"
            rows, dates = read_saved_panel(results / name)
            audit.assert_true(name + " exact monthly sample", dates == holdout_dates)
            rebuilt = book_account(baseline, holdout_dates, weights, cost)
            independently_rebuilt[strategy, float(cost)] = rebuilt
            for key in rebuilt[0]:
                if key != "month":
                    audit.close(name + " " + key, [float(row[key]) for row in rows], [row[key] for row in rebuilt])

    for strategy in ["uncapped", "cap2"]:
        rows, dates = read_saved_panel(results / f"holdout_{strategy}_10bp_spread200.csv")
        audit.assert_true(strategy + " financing exact monthly sample", dates == holdout_dates)
        rebuilt = book_account(baseline, holdout_dates, targets[strategy], 10, 200)
        independently_rebuilt[strategy, 10., 200.] = rebuilt
        for key in rebuilt[0]:
            if key != "month":
                audit.close(strategy + " financing " + key, [float(row[key]) for row in rows], [row[key] for row in rebuilt])
    metrics_rows = read_saved_csv(results / "holdout_metrics.csv")
    for row in metrics_rows:
        strategy = row.get("strategy", row.get("portfolio"))
        cost_key = next((key for key in ["cost_bps", "one_way_cost_bps"] if key in row), None)
        assert cost_key and strategy in targets, "Unrecognized metrics schema"
        cost = float(row[cost_key])
        spread = float(row.get("financing_spread_bps", 0))
        expected = independent_metrics(independently_rebuilt[strategy, cost, spread] if spread else independently_rebuilt[strategy, cost])
        for key, value in expected.items():
            if key in row:
                audit.close(f"metrics {strategy} {cost:g}bp {key}", float(row[key]), value)

    return {"status": "PASS", "implementation": "stdlib + NumPy; no engine, pandas, statsmodels, or P1 imports",
            "source_vintage": "French December 2024 FIZ pair",
            "original_sample": {"start": original_dates[0], "end": original_dates[-1], "n": len(original_dates), "scale": original_scale},
            "fixed_training_sample": {"start": training_dates[0], "end": training_dates[-1], "n": len(training_dates), "scale": training_scale},
            "holdout_sample": {"start": holdout_dates[0], "end": holdout_dates[-1], "n": len(holdout_dates)},
            "checks_passed": len(audit.checks), "checks": audit.checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--results", type=Path, default=None, help="Optional output directory to audit")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    results = args.results if args.results is None or args.results.is_absolute() else args.root / args.results
    report = verify(args.root, results)
    output = args.output or (results or args.root / "results") / "independent_verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {report['checks_passed']} independent checks; {output}")


if __name__ == "__main__":
    main()
