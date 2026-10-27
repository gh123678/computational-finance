"""P1-compatible dataset, target and result contracts for monthly factor research.

The monthly backend deliberately permits fractional research-index units and
RF borrowing. It never pretends to be the P1 A-share raw-stock execution model.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from . import legacy
from .attribution import cost_breakdown
from .performance import summarize_monthly

INSTRUMENT="FRENCH_US_MARKET_RESEARCH_INDEX"


def load_factor_observations(frame,path,frequency):
    """Serialize source percent units, then actually execute the P1 CSV reader."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=frame.copy()*100
    dates=frame.index if frequency=="daily" else frame.index.to_timestamp("M")
    raw.insert(0,"ts_code",INSTRUMENT)
    raw.insert(0,"trade_date",pd.DatetimeIndex(dates).strftime("%Y%m%d"))
    # Daily RF has finer precision than the two-decimal factor columns.
    # Keep significant digits instead of rounding to a display precision.
    raw.to_csv(path,index=False,float_format="%.15g")
    loaded=legacy.read_market(path.parent,path.stem)
    numeric=["Mkt-RF","SMB","HML","RF"]
    result=loaded[numeric].astype(float)/100
    result.index=pd.DatetimeIndex(loaded.trade_date) if frequency=="daily" else pd.PeriodIndex(loaded.trade_date,freq="M")
    result.index.name="date"
    if not result.index.equals(frame.index):raise AssertionError("P1 data reader changed source dates")
    np.testing.assert_allclose(result.to_numpy(),frame[numeric].to_numpy(),atol=1e-15,rtol=0)
    return result


def register_datasets(config):
    # Exact source function dataset_config is retained, including unknown-name
    # refusal; only the two explicitly authorized P2 windows are registered.
    legacy.DATASETS.clear()
    legacy.DATASETS.update({
        "project2_core":{"start":config["replication_start"],"end":config["replication_end"],"frequency":"monthly","backend":"monthly_factor"},
        "project2_holdout":{"start":config["holdout_start"],"end":config["holdout_end"],"frequency":"monthly","backend":"monthly_factor"}})
    return {name:legacy.dataset_config(name) for name in legacy.DATASETS}


def select_dataset(panel,name):
    spec=legacy.dataset_config(name)
    selected=panel.loc[spec["start"]:spec["end"]].copy()
    expected=pd.period_range(spec["start"],spec["end"],freq="M")
    if not selected.index.equals(expected):raise ValueError("Registered dataset has missing months")
    return selected


def form_targets(panel,weights,daily_calendar):
    calendar=pd.DatetimeIndex(daily_calendar)
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:raise ValueError("Invalid source calendar")
    if not panel.index.equals(weights.index):raise ValueError("Target input months must match")
    groups=pd.Series(calendar,index=calendar.to_period("M")).groupby(level=0)
    first,last=groups.min(),groups.max()
    rows=[]
    for month,w in weights.items():
        if month-1 not in last.index or month not in first.index:raise ValueError("Missing signal/execution month calendar")
        rows.append({"month":str(month),"signal_date":last.loc[month-1],"execution_date":first.loc[month],
                     "ts_code":INSTRUMENT,"target_weight":float(w),"lag_rv":float(panel.loc[month,"lag_rv"]),
                     "instrument_type":"fractional_research_index","backend":"monthly_factor",
                     "execution_convention":"ideal_month_boundary_labelled_by_first_source_day"})
    targets=pd.DataFrame(rows)
    validate_targets(panel,targets)
    return targets


def validate_targets(panel,targets):
    required={"month","signal_date","execution_date","ts_code","target_weight"}
    if not required.issubset(targets):raise ValueError("Incomplete P1 target contract")
    if targets.empty or targets.duplicated(["execution_date","ts_code"]).any():raise ValueError("Empty or duplicate targets")
    if targets.month.tolist()!=panel.index.astype(str).tolist():raise ValueError("Missing, unordered or mismatched target months")
    signal=pd.DatetimeIndex(pd.to_datetime(targets.signal_date));execution=pd.DatetimeIndex(pd.to_datetime(targets.execution_date))
    months=pd.PeriodIndex(targets.month,freq="M")
    if not np.all(signal<execution):raise ValueError("Signal must strictly precede execution")
    if not signal.to_period("M").equals(months-1) or not execution.to_period("M").equals(months):
        raise ValueError("Signal/execution are not adjacent intended calendar months")
    if not execution.is_monotonic_increasing:raise ValueError("Unordered executions")
    if not targets.ts_code.eq(INSTRUMENT).all():raise ValueError("Unknown research instrument")
    if not np.isfinite(targets.target_weight).all() or (targets.target_weight<0).any():raise ValueError("Invalid target exposure")


def account_to_p1_result(panel,targets,account):
    """Represent the funded account as P1 nav/orders/holdings/event tables."""
    nav=[];orders=[];holdings=[]
    baseline=pd.Timestamp(targets.signal_date.iloc[0])
    nav.append(dict(date=baseline,equity=1.,cash=1.,fees=0.,slippage_cost=0.,turnover=0.,position_count=0,
                    stale_value=0.,industry_target_breached=False,industry_constraint_applicable=False))
    old_units=0.;index_price=1.;previous_nav=1.
    for i,(month,row) in enumerate(account.iterrows()):
        target=targets.iloc[i];date=pd.Period(month,"M").to_timestamp("M")
        post_fee=previous_nav*(1-row.fee_fraction)
        units=post_fee*row.weight/index_price
        change=units-old_units
        fee=previous_nav*row.fee_fraction
        cash_after=post_fee-units*index_price
        orders.append(dict(date=target.execution_date,signal_date=target.signal_date,ts_code=INSTRUMENT,
            side="buy" if change>=0 else "sell",role="buy" if change>=0 else "sell",requested=abs(change),
            shares=abs(change),price=index_price,raw_open=np.nan,notional=abs(change)*index_price,
            price_convention="synthetic_month_boundary_not_market_open",
            fee=fee,slippage_cost=0.,status="filled",reason="fractional research-index execution",cash_after=cash_after))
        index_price*=1+row.rf+row.market_excess
        risky_value=units*index_price
        cash=float(row.nav)-risky_value
        nav.append(dict(date=date,equity=float(row.nav),cash=cash,fees=fee,slippage_cost=0.,
            turnover=float(row.one_way_turnover),position_count=int(units>0),stale_value=0.,
            industry_target_breached=False,industry_constraint_applicable=False))
        holdings.append(dict(date=date,ts_code=INSTRUMENT,shares=units,pending_shares=0.,mark=index_price,
            value=risky_value,weight=risky_value/row.nav,industry="NOT_APPLICABLE",cash=cash,
            financing_charge=post_fee*row.financing_fraction,instrument_type="fractional_research_index"))
        np.testing.assert_allclose(abs(change)*index_price/(1+row.rf+row.market_excess),previous_nav*row.one_way_turnover,atol=1e-8,rtol=1e-10)
        previous_nav=float(row.nav);old_units=units
    return dict(nav=pd.DataFrame(nav),orders=pd.DataFrame(orders),holdings=pd.DataFrame(holdings),
                corporate_events=pd.DataFrame(columns=["date","ts_code","event","amount"]))


def run_experiment(panel,weights,daily_calendar,output_dir,name,cost_bps=0.,financing_spread_bps=0.,backend="monthly_factor"):
    if backend!="monthly_factor":raise ValueError("Unregistered execution backend")
    from src.engine import simulate_monthly
    targets=form_targets(panel,weights,daily_calendar)
    # The backend receives the validated long-form P1 target weights, not a
    # parallel bypass path with the original Series.
    dispatched=pd.Series(targets.target_weight.to_numpy(),index=panel.index,name="weight")
    account=simulate_monthly(panel,dispatched,cost_bps,financing_spread_bps)
    result=account_to_p1_result(panel,targets,account)
    original_summary=legacy.summarize(result["nav"],result["orders"],targets.execution_date.iloc[0],
                                      evaluation_start=result["nav"].date.iloc[1])
    safe_keys=["total_return","max_drawdown","final_equity","total_fees","total_slippage","gross_turnover",
               "average_cash_weight","average_positions","filled_orders","rejected_orders"]
    period_free={key:original_summary[key] for key in safe_keys}
    converted=[pd.Series(account[col].to_numpy(),index=panel.index) for col in ["total_return","net_excess","weight","one_way_turnover"]]
    metrics=summarize_monthly(*converted)
    np.testing.assert_allclose(period_free["total_return"],metrics["total_return"],atol=1e-10,rtol=1e-12)
    np.testing.assert_allclose(period_free["max_drawdown"],metrics["max_drawdown_total"],atol=1e-12)
    np.testing.assert_allclose(period_free["gross_turnover"],metrics["total_turnover"],atol=1e-10)
    costs=cost_breakdown(result["orders"])
    np.testing.assert_allclose(costs.total_cost.sum(),result["nav"].fees.sum(),atol=1e-10)
    folder=Path(output_dir)/"p1_runs"/name;folder.mkdir(parents=True,exist_ok=True)
    targets.to_csv(folder/"targets.csv",index=False,float_format="%.16g")
    for key,frame in result.items():frame.to_csv(folder/f"{key}.csv",index=False,float_format="%.16g")
    costs.to_csv(folder/"cost_breakdown.csv",float_format="%.16g")
    evidence={"name":name,"backend":backend,"months":len(panel),"target_rows":len(targets),
              "result_tables":list(result),"p1_functions_executed_in_this_run":[
                 "summarize (period-free metrics only)","monthly_returns","cost_breakdown"],
              "legacy_period_free_summary":period_free,"monthly_metrics":metrics,
              "limitations":"Fractional research index, RF borrowing; stock rules and industry limits not applicable. Legacy 252 annual metrics discarded."}
    (folder/"contract_audit.json").write_text(json.dumps(evidence,indent=2,allow_nan=False),encoding="utf-8")
    return {"account":account,"metrics":metrics,"contract_audit":evidence,"targets":targets,**result}
