"""Offline end-to-end reproduction: python run_project.py [--output results]."""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from src.data import read_french_zip, monthly_panel
from src.engine import fit_scale, managed_weights, regression, block_sharpe_difference
from p1_platform.pipeline import load_factor_observations, register_datasets, select_dataset, run_experiment

ROOT=Path(__file__).resolve().parent


def dump(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default="results",help="Separate output directory, relative to project root")
    args=parser.parse_args()
    out=(ROOT/args.output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    figures=out/"figures"
    figures.mkdir(exist_ok=True)
    config=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
    # These values define the fixed research protocol rather than silently
    # changing labels or formulas when someone edits an unsupported setting.
    fixed={"variance_aggregation":"sum_centered_squares","variance_ddof":0,
           "variance_lag_months":1,"annualization_months":12,"regression_se":"HC1",
           "hac_lags_sensitivity":6,"leverage_cap":2.0,"financing_spread_bps_sensitivity":200}
    for key,value in fixed.items():
        if config.get(key)!=value:
            raise ValueError("Unsupported change to fixed protocol setting: "+key)
    registered=register_datasets(config)
    manifest=json.loads((ROOT/"data/source_manifest.json").read_text(encoding="utf-8"))
    for record in manifest:
        actual=hashlib.sha256((ROOT/"data/raw"/record["file"]).read_bytes()).hexdigest()
        if actual!=record["sha256"]:
            raise ValueError("Frozen input checksum mismatch: "+record["file"])
    daily={v:read_french_zip(ROOT/f"data/raw/{v}_daily.zip","daily") for v in ["fiz","ciz"]}
    monthly={v:read_french_zip(ROOT/f"data/raw/{v}_monthly.zip","monthly") for v in ["fiz","ciz"]}
    # P2 source adapter -> exact P1 read_market -> normal factor schema.
    for v in daily:
        daily[v]=load_factor_observations(daily[v],out/f"p1_inputs/{v}_daily.csv","daily")
        monthly[v]=load_factor_observations(monthly[v],out/f"p1_inputs/{v}_monthly.csv","monthly")
    # Current CIZ extends farther; trim full panels to mutual complete months.
    panels={v:monthly_panel(daily[v],monthly[v].loc[:daily[v].index[-1].to_period("M")],
                            ddof=config["variance_ddof"],aggregation=config["variance_aggregation"]) for v in daily}
    start,end=config["replication_start"],config["replication_end"]
    core=select_dataset(panels["fiz"],"project2_core")
    execution_evidence={}
    def execute(panel,w,name,cost=0,spread=0):
        result=run_experiment(panel,w,daily["fiz"].index,out,name,cost,spread)
        execution_evidence[name]=result["contract_audit"]
        return result["account"]
    scale=fit_scale(core)
    weights=managed_weights(core,scale)
    core["weight"]=weights
    core["managed_excess"]=weights*core.market_excess
    reg=regression(core.managed_excess,core.market_excess)
    dump(out/"original_regression.json",reg)
    core.to_csv(out/"original_monthly.csv",float_format="%.16g")
    account=execute(core,weights,"original_managed")
    market=execute(core,pd.Series(1.,index=core.index),"original_market")
    account.to_csv(out/"original_account.csv",float_format="%.16g")
    market.to_csv(out/"original_market_account.csv",float_format="%.16g")
    original_metrics=execution_evidence["original_managed"]["monthly_metrics"]
    market_metrics=execution_evidence["original_market"]["monthly_metrics"]
    original={"n":1065,"alpha_annual_pct":4.86,"alpha_se_annual_pct":1.56,"beta":.61,
              "beta_se":.05,"r_squared":.37,"rmse_paper_units":51.39}
    rows=[{"metric":key,"paper":value,"reproduction":reg[key],"difference":reg[key]-value,
           "source":"Table I, Panel A, column 1 (Mkt), published PDF p.9 / journal p.1619"}
          for key,value in original.items()]
    rows.append({"metric":"sharpe","paper":.51,"reproduction":original_metrics["sharpe"],
                 "difference":original_metrics["sharpe"]-.51,
                 "source":"Table II, Mkt row, univariate; Table V instead reports rounded 0.52"})
    pd.DataFrame(rows).to_csv(out/"comparison.csv",index=False,float_format="%.10g")
    # One-factor-at-a-time diagnostics, always retain the original case.
    variants={
        "baseline_FIZ_ddof0":core,
        "variance_ddof1":monthly_panel(daily["fiz"],monthly["fiz"],ddof=1).loc[start:end],
        "month_end_2015_12":panels["fiz"].loc[start:"2015-12"],
        "start_1927_01":panels["fiz"].loc["1927-01":end],
        "daily_CIZ_only":monthly_panel(daily["ciz"],monthly["fiz"]).loc[start:end],
        "monthly_CIZ_only":monthly_panel(daily["fiz"],monthly["ciz"].loc[:monthly["fiz"].index[-1]]).loc[start:end],
        "both_CIZ":panels["ciz"].loc[start:end],
    }
    lag2=core.copy()
    lag2["lag_rv"]=panels["fiz"].rv.shift(2).reindex(lag2.index)
    variants["two_month_lag"]=lag2.dropna()
    variants["two_month_common_baseline"]=core.loc[lag2.dropna().index]
    meanrv=monthly_panel(daily["fiz"],monthly["fiz"],aggregation="mean_centered_squares").loc[start:end]
    variants["mean_squared_daily_deviations"]=meanrv
    sensitivity=[]
    for label,panel in variants.items():
        c=fit_scale(panel)
        w=managed_weights(panel,c)
        result=regression(w*panel.market_excess,panel.market_excess)
        result.update(variant=label,scale=c,sharpe=float((w*panel.market_excess).mean()/(w*panel.market_excess).std(ddof=1)*np.sqrt(12)),
                      start=str(panel.index[0]),end=str(panel.index[-1]),max_weight=float(w.max()))
        sensitivity.append(result)
    pd.DataFrame(sensitivity).to_csv(out/"sensitivities.csv",index=False,float_format="%.12g")
    robust=[regression(core.managed_excess,core.market_excess,covariance=x) for x in ["HC0","HC1","HAC"]]
    pd.DataFrame(robust).to_csv(out/"standard_error_sensitivity.csv",index=False,float_format="%.12g")
    # Training uses data only through core end; no 2016+ outcome changes c.
    holdout=select_dataset(panels["fiz"],"project2_holdout")
    holdout.to_csv(out/"holdout_inputs.csv",float_format="%.16g")
    accounts={}
    holdout_rows=[]
    for cost in config["one_way_cost_bps"]:
        for name,cap in [("market",None),("uncapped",None),("cap2",config["leverage_cap"])]:
            w=pd.Series(1.,index=holdout.index) if name=="market" else managed_weights(holdout,scale,cap)
            a=execute(holdout,w,f"holdout_{name}_{cost}bp",cost)
            accounts[(name,cost)]=a
            a.to_csv(out/f"holdout_{name}_{cost}bp.csv",float_format="%.16g")
            m=execution_evidence[f"holdout_{name}_{cost}bp"]["monthly_metrics"].copy()
            m.update(strategy=name,cost_bps=cost,financing_spread_bps=0,
                     alpha_annual_pct=regression(pd.Series(a.net_excess.values,index=holdout.index),holdout.market_excess)["alpha_annual_pct"])
            holdout_rows.append(m)
    for name,cap in [("uncapped",None),("cap2",config["leverage_cap"])]:
        a=execute(holdout,managed_weights(holdout,scale,cap),f"holdout_{name}_10bp_spread200",10,
                  config["financing_spread_bps_sensitivity"])
        a.to_csv(out/f"holdout_{name}_10bp_spread200.csv",float_format="%.16g")
        m=execution_evidence[f"holdout_{name}_10bp_spread200"]["monthly_metrics"].copy()
        m.update(strategy=name,cost_bps=10,financing_spread_bps=200,
                 alpha_annual_pct=regression(pd.Series(a.net_excess.values,index=holdout.index),holdout.market_excess)["alpha_annual_pct"])
        holdout_rows.append(m)
    holdout_metrics=pd.DataFrame(holdout_rows)
    holdout_metrics.to_csv(out/"holdout_metrics.csv",index=False,float_format="%.12g")
    bootstrap={
        "original_managed_minus_market":block_sharpe_difference(core.managed_excess,core.market_excess,
            config["random_seed"],config["bootstrap_repetitions"],config["bootstrap_block_months"]),
        "holdout_cap2_minus_uncapped_10bp":block_sharpe_difference(accounts[("cap2",10)].net_excess,accounts[("uncapped",10)].net_excess,
            config["random_seed"]+1,config["bootstrap_repetitions"],config["bootstrap_block_months"])}
    dump(out/"bootstrap.json",bootstrap)
    # Intermediates support locating where source-vintage differences enter.
    vintage_diff=pd.DataFrame(index=core.index)
    vintage_diff["FIZ_monthly_excess"]=core.market_excess
    vintage_diff["CIZ_monthly_excess"]=variants["both_CIZ"].market_excess
    vintage_diff["monthly_excess_difference"]=vintage_diff.CIZ_monthly_excess-vintage_diff.FIZ_monthly_excess
    vintage_diff["FIZ_lag_rv"]=core.lag_rv
    vintage_diff["CIZ_lag_rv"]=variants["both_CIZ"].lag_rv
    vintage_diff["lag_rv_difference"]=vintage_diff.CIZ_lag_rv-vintage_diff.FIZ_lag_rv
    vintage_diff.to_csv(out/"vintage_monthly_differences.csv",float_format="%.16g")
    coverage=[]
    for v in ["fiz","ciz"]:
        coverage.append({"vintage":v,"daily_rows":len(daily[v]),"daily_start":str(daily[v].index[0].date()),
                         "daily_end":str(daily[v].index[-1].date()),"monthly_rows":len(monthly[v]),
                         "monthly_start":str(monthly[v].index[0]),"monthly_end":str(monthly[v].index[-1]),
                         "core_months":len(panels[v].loc[start:end]),"core_min_daily_count":int(panels[v].loc[start:end].daily_count.min())})
    pd.DataFrame(coverage).to_csv(out/"data_coverage.csv",index=False)
    quantiles=weights.quantile([0,.01,.25,.5,.75,.9,.99,1]).rename("weight").to_frame()
    quantiles.index.name="quantile"
    quantiles.to_csv(out/"weight_quantiles.csv",float_format="%.12g")
    environments={"python":sys.version,"platform":platform.platform(),
                  "delivery_version":config["delivery_version"],"entrypoint":"python -m p1_platform",
                  "source_files_sha256":{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [ROOT/"run_project.py",*sorted((ROOT/"src").glob("*.py")),*sorted((ROOT/"p1_platform").glob("*.py"))]},
                  "packages":{x:importlib.metadata.version(x) for x in ["numpy","pandas","scipy","statsmodels","matplotlib","reportlab","pytest","requests"]},
                  "created_at_utc":datetime.now(timezone.utc).isoformat(),
                  "config_sha256":hashlib.sha256((ROOT/"config.json").read_bytes()).hexdigest()}
    dump(out/"environment.json",environments)
    summary={"scale":scale,"calibration_start":str(core.index[0]),"calibration_end":str(core.index[-1]),
             "replication_sample_endpoint_is_inferred":True,"core_regression":reg,
             "original_managed_metrics":original_metrics,"original_market_metrics":market_metrics,
             "holdout_months":len(holdout),"holdout_start":str(holdout.index[0]),"holdout_end":str(holdout.index[-1]),
             "core_variance_match_absolute_error":float(abs(core.managed_excess.std(ddof=1)-core.market_excess.std(ddof=1))),
             "vintage_monthly_changed_count":int((abs(vintage_diff.monthly_excess_difference)>1e-14).sum()),
             "vintage_lag_rv_changed_count":int((abs(vintage_diff.lag_rv_difference)>1e-14).sum()),
             "bootstrap":bootstrap,
             "holdout_scale_policy":"Use unchanged original-sample c; no holdout calibration; caps not rescaled; starts from cash",
             "baseline_cost_policy":"Zero cost, RF financing, no leverage cap; core is descriptive paper comparison"}
    dump(out/"summary.json",summary)
    dump(out/"p1_integration_evidence.json",{"status":"PASS","registered_datasets":registered,
        "normalized_input_files":[f"p1_inputs/{v}_{frequency}.csv" for v in daily for frequency in ["daily","monthly"]],
        "experiments":execution_evidence,"experiment_count":len(execution_evidence),
        "target_rows_total":sum(x["target_rows"] for x in execution_evidence.values()),
        "original_stock_engine_modified":False})
    make_figures(figures,core,account,market,accounts,holdout_metrics,pd.DataFrame(sensitivity))
    print(json.dumps({"status":"completed","core_months":len(core),"alpha_annual_pct":reg["alpha_annual_pct"],
                      "beta":reg["beta"],"managed_sharpe":original_metrics["sharpe"],
                      "market_sharpe":market_metrics["sharpe"],"holdout_months":len(holdout)},indent=2))


def make_figures(folder,core,account,market,accounts,metrics,sensitivity):
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.spines.top":False,
                         "axes.spines.right":False,"figure.dpi":140,"savefig.dpi":180})
    colors={"market":"#687687","uncapped":"#1b6187","cap2":"#d28b26"}
    def save(name):
        plt.tight_layout();plt.savefig(folder/name,bbox_inches="tight",facecolor="white");plt.close()
    fig,ax=plt.subplots(figsize=(8.6,3.6))
    dates=core.index.to_timestamp()
    for a,label,color in [(market,"Market",colors["market"]),(account,"Volatility managed",colors["uncapped"])]:
        ax.plot(dates,a.nav.values,label=label,color=color,lw=1.4)
    ax.set(yscale="log",ylabel="Total-return wealth (RF included, log)",title="Original-window replication: 1926-08 to 2015-04")
    ax.legend(frameon=False);ax.grid(alpha=.2);save("original_cumulative.png")
    fig,ax=plt.subplots(figsize=(8.6,3.1))
    ax.plot(dates,core.weight,color=colors["uncapped"],lw=.8)
    ax.axhline(2,color=colors["cap2"],ls="--",lw=1,label="2x cap (extension only)")
    ax.set(ylabel="Risky-asset target weight",title="Lagged-variance signal: leverage is not capped in the core replication")
    ax.legend(frameon=False);ax.grid(alpha=.2);save("original_weights.png")
    fig,axs=plt.subplots(1,3,figsize=(8.6,3.0))
    original=[4.86,.61,.37]
    reg=regression(core.managed_excess,core.market_excess)
    for ax,title,key,value in zip(axs,["Alpha (%/year)","Market beta","R-squared"],["alpha_annual_pct","beta","r_squared"],original):
        ax.bar(["Paper","This run"],[value,reg[key]],color=[colors["market"],colors["uncapped"]],width=.6)
        ax.set_title(title);ax.grid(axis="y",alpha=.2)
        for i,num in enumerate([value,reg[key]]):ax.text(i,num,f"{num:.3f}",ha="center",va="bottom",fontsize=9)
        ax.margins(y=.22)
    save("original_comparison.png")
    fig,ax=plt.subplots(figsize=(8.6,3.6))
    for name in ["market","uncapped","cap2"]:
        a=accounts[(name,10)]
        ax.plot(pd.PeriodIndex(a.index,freq="M").to_timestamp(),a.nav,label=name,color=colors[name],lw=1.6)
    ax.set(ylabel="Total-return wealth",title="2016-2024 historical holdout: fixed training c, one-way cost 10 bp")
    ax.legend(frameon=False);ax.grid(alpha=.2);save("holdout_nav.png")
    fig,axs=plt.subplots(1,3,figsize=(8.6,3.0))
    selected=metrics.loc[(metrics.cost_bps==10)&(metrics.financing_spread_bps==0)].set_index("strategy").loc[["market","uncapped","cap2"]]
    for ax,title,key,factor in zip(axs,["CAGR total (%)","Sharpe (excess)","Max drawdown (%)"],["cagr_total","sharpe","max_drawdown_total"],[100,1,100]):
        ax.bar(selected.index,selected[key]*factor,color=[colors[x] for x in selected.index])
        ax.set_title(title);ax.grid(axis="y",alpha=.2);ax.tick_params(axis="x",labelsize=8)
    save("holdout_metrics.png")
    fig,ax=plt.subplots(figsize=(8.6,3.6))
    labels=["FIZ sum baseline","ddof=1 adjustment","End Dec2015","Start Jan1927","Daily CIZ only","Monthly CIZ only","Both CIZ","2-month lag","Common-month baseline","Mean of squares"]
    ax.barh(labels,sensitivity.alpha_annual_pct,color=colors["uncapped"])
    ax.axvline(4.86,color=colors["cap2"],ls="--",label="Paper alpha = 4.86%")
    ax.invert_yaxis();ax.set_xlabel("Alpha (% per year), separately normalized each case")
    ax.legend(frameon=False);ax.grid(axis="x",alpha=.2);save("sensitivity.png")


if __name__=="__main__":
    main()
