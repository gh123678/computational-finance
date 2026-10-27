"""Past-month variance signals, descriptive regression, and funded monthly accounts."""
import numpy as np
import pandas as pd
import statsmodels.api as sm


def fit_scale(panel):
    """Ex-post scale only: equal unconditional sample standard deviations."""
    valid = panel.dropna(subset=["market_excess", "lag_rv"])
    raw = valid.market_excess / valid.lag_rv
    if len(valid) < 24 or (valid.lag_rv <= 0).any() or raw.std(ddof=1) <= 0:
        raise ValueError("Insufficient or invalid calibration observations")
    return float(valid.market_excess.std(ddof=1) / raw.std(ddof=1))


def managed_weights(panel, scale, cap=None):
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Scale must be positive")
    if panel.lag_rv.isna().any() or (panel.lag_rv <= 0).any():
        raise ValueError("Every investment month needs preceding-month variance")
    weights = scale / panel.lag_rv
    if cap is not None:
        if not np.isfinite(cap) or cap <= 0:
            raise ValueError("Invalid leverage cap")
        weights = weights.clip(upper=cap)
    return weights.rename("weight")


def regression(managed_excess, market_excess, covariance="HC1", hac_lags=6):
    if not managed_excess.index.equals(market_excess.index):
        raise ValueError("Regression dates must match exactly")
    x = sm.add_constant(market_excess.rename("market"))
    if covariance == "HAC":
        fit = sm.OLS(managed_excess, x, missing="raise").fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags, "use_correction": True})
    else:
        fit = sm.OLS(managed_excess, x, missing="raise").fit(cov_type=covariance)
    residual = np.asarray(fit.resid)
    return {"n": int(fit.nobs), "alpha_annual_pct": float(fit.params["const"] * 1200),
            "alpha_se_annual_pct": float(fit.bse["const"] * 1200),
            "alpha_t": float(fit.tvalues["const"]), "beta": float(fit.params["market"]),
            "beta_se": float(fit.bse["market"]), "r_squared": float(fit.rsquared),
            "rmse_paper_units": float(np.sqrt(np.sum(residual**2)/(len(residual)-2))*1200),
            "covariance": covariance}


def simulate_monthly(panel, weights, cost_bps=0., financing_spread_bps=0., initial_drift_weight=0.):
    """Self-financing one-risky-asset account, cash/borrowing at RF.

    w is risky weight AFTER paying proportional transaction cost. Solve
    fee = k*abs(w*(1-fee)-drift) exactly against PRE-trade wealth.
    Trade at the month boundary; hold shares (not weights) within the month.
    No terminal liquidation; costs charged when the next rebalance happens.
    """
    if not panel.index.equals(weights.index) or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("Need finite nonnegative aligned target weights")
    if panel[["market_excess", "rf"]].isna().any().any():
        raise ValueError("Missing account returns")
    if cost_bps < 0 or financing_spread_bps < 0:
        raise ValueError("Costs cannot be negative")
    k = float(cost_bps)/10000
    spread = float(financing_spread_bps)/10000/12
    drift = float(initial_drift_weight)
    wealth = 1.
    rows = []
    for month, w in weights.items():
        if k*w >= 1:
            raise ValueError("Transaction cost/target combination is infeasible")
        f, rf = float(panel.at[month, "market_excess"]), float(panel.at[month, "rf"])
        market_total = rf + f
        if market_total <= -1:
            raise ValueError("Market asset becomes nonpositive")
        fee = k*(w-drift)/(1+k*w) if w >= drift else k*(drift-w)/(1-k*w)
        if not 0 <= fee < 1:
            raise ValueError("Infeasible transaction cost")
        turnover = abs(w*(1-fee)-drift)
        financing = max(w-1., 0.)*spread
        gross_total = rf + w*f - financing
        total = (1-fee)*(1+gross_total)-1
        if total <= -1 or not np.isfinite(total):
            raise ValueError("Portfolio insolvency; do not compound invalid NAV")
        wealth *= 1+total
        rows.append({"month": str(month), "market_excess": f, "rf": rf,
                     "weight": float(w), "pretrade_weight": drift,
                     "one_way_turnover": turnover, "fee_fraction": fee,
                     "financing_fraction": financing, "gross_excess": w*f,
                     "net_excess": total-rf, "total_return": total, "nav": wealth})
        # Post-fee assets and post-fee wealth have the same (1-fee) scale.
        drift = w*(1+market_total)/(1+gross_total)
    return pd.DataFrame(rows).set_index("month")


def block_sharpe_difference(left, right, seed=20261020, repetitions=2000, block_months=12):
    """Paired circular-block bootstrap; approximate 95% interval, not a causal test."""
    a, b = np.asarray(left, float), np.asarray(right, float)
    if a.shape != b.shape or len(a) < 24:
        raise ValueError("Need matching sufficiently long samples")
    def sr(x):
        return x.mean()/x.std(ddof=1)*np.sqrt(12)
    rng = np.random.default_rng(seed)
    draws=[]
    n = len(a)
    for _ in range(repetitions):
        starts=rng.integers(0,n,size=int(np.ceil(n/block_months)))
        idx=np.concatenate([(s+np.arange(block_months))%n for s in starts])[:n]
        draws.append(sr(a[idx])-sr(b[idx]))
    low, high = np.quantile(draws,[.025,.975])
    return {"difference": float(sr(a)-sr(b)), "ci95_low": float(low), "ci95_high": float(high),
            "seed": seed, "repetitions": repetitions, "block_months": block_months}
