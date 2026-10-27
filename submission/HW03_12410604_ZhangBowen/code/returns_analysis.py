"""A1: explicit return statistics, convention-specific ACF, calendar audit."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import numpy as np
import pandas as pd
import scipy
from scipy.stats import norm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pandas.tseries.holiday import (AbstractHolidayCalendar, Holiday, nearest_workday,
    sunday_to_monday, USMartinLutherKingJr, USPresidentsDay, GoodFriday,
    USMemorialDay, USLaborDay, USThanksgivingDay)

ROOT = Path(__file__).resolve().parents[1]
START, END = "2021-10-14", "2026-10-14"

class EquityHolidays(AbstractHolidayCalendar):
    # Saturday New Year's Day is not observed on the preceding Friday by US exchanges.
    rules = [Holiday("New Year", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday)]

def expected_sessions(start=START, end=END):
    days = pd.bdate_range(start, end)
    holidays = EquityHolidays().holidays(start, end).union(pd.DatetimeIndex(["2025-01-09"]))
    return days.difference(holidays)

def log_returns(prices):
    x = np.asarray(prices, dtype=float)
    if x.ndim != 1 or len(x) < 2 or not np.isfinite(x).all() or np.any(x <= 0):
        raise ValueError("Prices must be a finite positive vector with at least two observations")
    return np.log(x[1:]) - np.log(x[:-1])

def acf(x, max_lag=20):
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or not np.isfinite(x).all() or not 0 <= max_lag < len(x):
        raise ValueError("Invalid series or lag")
    y = x - x.mean()
    denom = float(y @ y)
    if denom <= 0:
        raise ValueError("ACF is undefined for a constant series")
    return np.array([1.0] + [float(y[k:] @ y[:-k]) / denom for k in range(1, max_lag+1)])

def describe(r):
    r = np.asarray(r, dtype=float)
    if r.ndim != 1 or len(r) < 2 or not np.isfinite(r).all():
        raise ValueError("Need at least two finite returns")
    y = r-r.mean()
    m2 = float(np.mean(y*y))
    if m2 == 0:
        raise ValueError("Nonconstant return sample required")
    return dict(n=len(r), mean=float(r.mean()), variance=float(y@y/(len(r)-1)),
        sd=float(np.sqrt(y@y/(len(r)-1))), skewness=float(np.mean(y**3)/m2**1.5),
        excess_kurtosis=float(np.mean(y**4)/m2**2-3))

def audit_csv(path, require_window=True):
    f = pd.read_csv(path)
    if not {"Date", "AdjClose"}.issubset(f.columns):
        raise ValueError("CSV needs Date and AdjClose")
    f["Date"] = pd.to_datetime(f.Date, errors="raise")
    duplicated = int(f.Date.duplicated().sum())
    missing = int(f[["Date","AdjClose"]].isna().sum().sum())
    invalid = int((~np.isfinite(f.AdjClose.to_numpy(dtype=float)) | (f.AdjClose <= 0)).sum())
    if duplicated or missing or invalid:
        raise ValueError(f"Invalid input: duplicates={duplicated}, missing={missing}, invalid_prices={invalid}")
    was_sorted = bool(f.Date.is_monotonic_increasing)
    f = f.sort_values("Date").reset_index(drop=True)
    if require_window and (str(f.Date.iloc[0].date()) != START or str(f.Date.iloc[-1].date()) != END):
        raise ValueError("Required observation window is incomplete")
    expected = expected_sessions(str(f.Date.iloc[0].date()), str(f.Date.iloc[-1].date()))
    observed = pd.DatetimeIndex(f.Date)
    missing_sessions, unexpected = expected.difference(observed), observed.difference(expected)
    gaps = f.Date.diff().dt.days.fillna(0).astype(int)
    record = dict(price_rows=len(f), return_rows=len(f)-1, duplicates=duplicated,
        missing_entries=missing, nonpositive_or_nonfinite=invalid, originally_sorted=was_sorted,
        first_date=str(f.Date.iloc[0].date()), last_date=str(f.Date.iloc[-1].date()),
        expected_sessions=len(expected), missing_trading_sessions=[str(d.date()) for d in missing_sessions],
        unexpected_observations=[str(d.date()) for d in unexpected], max_calendar_gap_days=int(gaps.max()),
        nontrading_dates_filled=False,
        calendar_description="US equity holiday rules, Juneteenth from 2022; special Carter closure 2025-01-09; early closes remain trading observations.",
        calendar_reference="https://www.nasdaqtrader.com/trader.aspx?id=Calendar",
        special_closure_reference="https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2024-632")
    if require_window and (len(missing_sessions) or len(unexpected)):
        raise ValueError(f"Unexpected calendar gaps: {record}")
    return f, record

def run(path, expected_hash=None, seed=21603):
    raw_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if expected_hash and raw_hash != expected_hash:
        raise ValueError("Analyzed CSV hash differs from frozen input; do not silently substitute vendor revisions")
    f, audit = audit_csv(path)
    (ROOT/"results").mkdir(exist_ok=True)
    (ROOT/"figures").mkdir(exist_ok=True)
    r = log_returns(f.AdjClose)
    d = describe(r)
    z = (r-d["mean"])/d["sd"]
    rng = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(1,)))
    perm = rng.permutation(r)
    pd.DataFrame([d]).to_csv(ROOT/"results/A1_descriptive.csv", index=False)
    tails = pd.DataFrame([dict(threshold=k,observed=int((np.abs(z)>k).sum()),
        fitted_normal_probability=float(2*norm.sf(k)),
        fitted_normal_expected=len(r)*2*norm.sf(k)) for k in [3,4,5]])
    tails.to_csv(ROOT/"results/A1_tails.csv", index=False)
    a = pd.DataFrame(dict(lag=np.arange(1,21), returns=acf(r)[1:], permuted_returns=acf(perm)[1:],
        squared_returns=acf(r*r)[1:], permuted_squared_returns=acf(perm*perm)[1:]))
    a.to_csv(ROOT/"results/A1_acf.csv", index=False)
    h=1/252
    cal=dict(h=h,horizon_years=len(r)*h,m_hat=d["mean"]/h,
        sigma_hat=d["sd"]/np.sqrt(h), sigma_squared_hat=d["variance"]/h,
        mu_hat=(d["mean"]+.5*d["variance"])/h,
        log_drift_se=d["sd"]/(h*np.sqrt(len(r))))
    pd.DataFrame([cal]).to_csv(ROOT/"results/A1_calibration.csv",index=False)
    audit["analyzed_csv_sha256"] = raw_hash
    (ROOT/"results/A1_audit.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    env=dict(python=sys.version,numpy=np.__version__,pandas=pd.__version__,scipy=scipy.__version__,
        matplotlib=matplotlib.__version__,platform=platform.platform(),master_seed=seed,
        permutation_spawn_key=[1],rng="numpy Generator PCG64",sample_variance_divisor="n-1",
        higher_moments="m_k = mean((r-mean(r))**k); skew=m3/m2**1.5; excess=m4/m2**2-3")
    (ROOT/"results/A1_environment.json").write_text(json.dumps(env,indent=2),encoding="utf-8")
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False})
    def save(name):
        plt.tight_layout()
        plt.savefig(ROOT/f"figures/{name}.pdf",bbox_inches="tight")
        plt.savefig(ROOT/f"figures/{name}.png",dpi=180,bbox_inches="tight")
        plt.close()
    plt.figure(figsize=(7,4.1))
    plt.hist(r,bins=50,density=True,alpha=.55,label="MSFT adjusted log returns")
    grid=np.linspace(min(r),max(r),500)
    plt.plot(grid,norm.pdf(grid,d["mean"],d["sd"]),color="#bd5036",label="Fitted normal density")
    plt.xlabel("Daily log return (dimensionless)"); plt.ylabel("Density (per unit log return)")
    plt.title("A1: MSFT, 2021-10-14 to 2026-10-14"); plt.legend(); save("A1_histogram")
    plt.figure(figsize=(5.5,4.5))
    q=norm.ppf((np.arange(1,len(r)+1)-.5)/len(r))
    plt.scatter(q,np.sort(z),s=7,alpha=.7,label="Standardized observed returns")
    lim=[min(q.min(),z.min()),max(q.max(),z.max())]
    plt.plot(lim,lim,color="#bd5036",label="y = x")
    plt.xlabel("Theoretical N(0,1) quantile"); plt.ylabel("Observed standardized log return")
    plt.title("A1: Normal Q-Q diagnostic"); plt.legend(); save("A1_qq")
    for col,name,title in [("returns","A1_acf_returns","Returns"),("squared_returns","A1_acf_squared","Squared returns")]:
        plt.figure(figsize=(7,4.1))
        plt.axhline(0,color="gray",lw=.7)
        plt.plot(a.lag,a[col],"o-",label="Original order")
        plt.plot(a.lag,a["permuted_"+col],"s--",label="One seeded permutation")
        plt.xlabel("Lag (trading observations)"); plt.ylabel("Sample autocorrelation (dimensionless)")
        plt.xticks(np.arange(1,21)); plt.title("A1: "+title); plt.legend(); save(name)
    result=dict(descriptive=d,calibration=cal,audit=audit,tails=tails.to_dict("records"))
    (ROOT/"results/A1_summary.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
    return result

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--expected-hash")
    p.add_argument("--seed",type=int,default=21603)
    args=p.parse_args()
    run(args.input,args.expected_hash,args.seed)
