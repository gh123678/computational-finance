"""Rebuild P1 exported orders/holdings/cash without importing the platform."""
import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
import independent_verify as source_audit

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results",type=Path,default=Path("results"))
    args=parser.parse_args();out=args.results if args.results.is_absolute() else ROOT/args.results
    audit=source_audit.Audit()
    config=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
    panel=source_audit.raw_panel(ROOT,"fiz")
    labels=source_audit.dates_between(panel,config["replication_start"],config["replication_end"])
    scale=source_audit.scale_for(panel,labels)
    raw_days=source_audit.read_raw(ROOT/"data/raw/fiz_daily.zip",8)
    calendar={}
    for day in raw_days:calendar.setdefault(day[:4]+"-"+day[4:6],[]).append(day)
    provenance=json.loads((ROOT/"p1_platform/function_provenance.json").read_text())
    extraction=(ROOT/"p1_platform/legacy.py").read_text(encoding="utf-8")
    functions={n.name:n for n in ast.parse(extraction).body if isinstance(n,ast.FunctionDef)}
    for item in provenance["functions"]:
        audit.assert_true("frozen P1 source "+item["function"],hashlib.sha256((ROOT/item["reference_file"]).read_bytes()).hexdigest()==item["source_file_sha256"])
        segment=ast.get_source_segment(extraction,functions[item["function"]])
        audit.assert_true("exact P1 function "+item["function"],hashlib.sha256(segment.encode()).hexdigest()==item["function_utf8_sha256"])
    total_rows=0
    folders=sorted((out/"p1_runs").iterdir())
    for folder in folders:
        targets=source_audit.read_saved_csv(folder/"targets.csv")
        orders=source_audit.read_saved_csv(folder/"orders.csv")
        holdings=source_audit.read_saved_csv(folder/"holdings.csv")
        nav=source_audit.read_saved_csv(folder/"nav.csv")
        n=len(targets);total_rows+=n
        audit.assert_true(folder.name+" contract row counts",len(orders)==len(holdings)==n and len(nav)==n+1)
        is_market=folder.name=="original_market" or folder.name.startswith("holdout_market_")
        cap=folder.name.startswith("holdout_cap2_")
        spread=200 if folder.name.endswith("spread200") else 0
        units=0.;cash=1.;price=1.;previous_nav=1.
        rebuilt={key:[] for key in ["equity","cash","units","mark","value","turnover","fee","target"]}
        for target,order,held in zip(targets,orders,holdings):
            month=target["month"];prior=source_audit.month_label(source_audit.month_number(month)-1)
            audit.assert_true(folder.name+" signal/execute "+month,
                target["signal_date"][:10].replace("-","")==calendar[prior][-1] and
                target["execution_date"][:10].replace("-","")==calendar[month][0] and
                target["signal_date"]<target["execution_date"])
            w=1. if is_market else scale/panel[month]["lag_rv"]
            if cap:w=min(w,config["leverage_cap"])
            audit.close(folder.name+" target "+month,float(target["target_weight"]),w)
            delta=float(order["shares"])*(1 if order["side"]=="buy" else -1)
            fee=float(order["fee"]);notional=abs(delta)*price
            audit.close(folder.name+" index trade price "+month,float(order["price"]),price,atol=1e-8)
            audit.close(folder.name+" notional "+month,float(order["notional"]),notional,atol=1e-8)
            cash-=delta*price+fee;units+=delta
            audit.close(folder.name+" post-fee target "+month,units*price/(previous_nav-fee),w,atol=1e-10)
            rf,f=panel[month]["rf"],panel[month]["market_excess"]
            cash=cash*(1+rf)-max(-cash,0)*spread/10000/12
            price*=1+rf+f
            value=units*price;equity=value+cash
            for key,val in [("equity",equity),("cash",cash),("units",units),("mark",price),("value",value),
                            ("turnover",notional/previous_nav),("fee",fee),("target",w)]:rebuilt[key].append(val)
            previous_nav=equity
        for key,source,column in [("equity",nav[1:],"equity"),("cash",nav[1:],"cash"),("units",holdings,"shares"),
                                  ("mark",holdings,"mark"),("value",holdings,"value"),("turnover",nav[1:],"turnover"),
                                  ("fee",nav[1:],"fees")]:
            audit.close(folder.name+" exported "+key,[float(x[column]) for x in source],rebuilt[key],atol=1e-8,rtol=1e-9)
        cost_rows=source_audit.read_saved_csv(folder/"cost_breakdown.csv")
        audit.close(folder.name+" P1 cost sum",sum(float(x["total_cost"]) for x in cost_rows),sum(rebuilt["fee"]),atol=1e-8)
    evidence=json.loads((out/"p1_integration_evidence.json").read_text())
    audit.assert_true("all registered run count",len(folders)==13==evidence["experiment_count"])
    audit.assert_true("all target rows",total_rows==evidence["target_rows_total"])
    result={"status":"PASS","implementation":"stdlib and NumPy; exact source fingerprints plus exported orders/cash reconstruction; no platform or engine imports",
            "experiments":len(folders),"target_rows":total_rows,"checks_passed":len(audit.checks),"checks":audit.checks}
    (out/"p1_independent_verification.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(f"PASS: {len(folders)} P1 runs, {total_rows} targets, {len(audit.checks)} independent integration checks")


if __name__=="__main__":main()
