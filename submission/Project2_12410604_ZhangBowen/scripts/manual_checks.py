"""Transparent small-sample arithmetic directly from the frozen ZIP records."""
import csv
import io
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def rows(name,digits):
    with zipfile.ZipFile(ROOT/"data/raw"/name) as arc:
        member=next(x for x in arc.namelist() if x.lower().endswith(".csv"))
        text=arc.read(member).decode("utf-8-sig")
    values={}
    for row in csv.reader(io.StringIO(text)):
        key=row[0].strip() if row else ""
        if key.isdigit() and len(key)==digits:
            values[key]=float(row[1])/100
        elif values:
            break
    return values


def main():
    daily=rows("fiz_daily.zip",8)
    monthly=rows("fiz_monthly.zip",6)
    saved=json.loads((ROOT/"results/summary.json").read_text(encoding="utf-8"))
    with (ROOT/"results/original_monthly.csv").open(encoding="utf-8",newline="") as stream:
        expected={row["date"]:row for row in csv.DictReader(stream)}
    cases=[("1926-08","1926-07"),("1933-03","1933-02"),("2008-10","2008-09"),("2015-04","2015-03")]
    records=[];samples=[]
    for investment,formation in cases:
        key=formation.replace("-","")
        obs=[(date,value) for date,value in daily.items() if date.startswith(key)]
        average=sum(x[1] for x in obs)/len(obs)
        deviations=[(date,value,(value-average)**2) for date,value in obs]
        rv=sum(x[2] for x in deviations)
        weight=saved["scale"]/rv
        excess=monthly[investment.replace("-","")]
        managed=weight*excess
        error=abs(managed-float(expected[investment]["managed_excess"]))
        assert abs(rv-float(expected[investment]["lag_rv"]))<1e-13
        assert error<1e-12
        records.append(dict(investment_month=investment,variance_month=formation,daily_count=len(obs),
            daily_mean=average,sum_centered_squares=rv,mean_centered_squares=rv/len(obs),
            scale=saved["scale"],weight=weight,market_excess=excess,managed_excess=managed,
            engine_managed_excess=float(expected[investment]["managed_excess"]),absolute_error=error))
        samples.extend(dict(investment_month=investment,formation_month=formation,date=date,
            daily_market_excess=value,daily_mean=average,centered_squared_return=sq) for date,value,sq in deviations)
    for name,values in [("results/manual_checks.csv",records),("data/sample_daily_for_manual_check.csv",samples)]:
        with (ROOT/name).open("w",encoding="utf-8",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(values[0]));writer.writeheader();writer.writerows(values)
    report={"status":"PASS","cases":len(records),"daily_observations":len(samples),
            "method":"Explicit Python scalar sum of centered squared daily returns; previous calendar month",
            "maximum_absolute_return_error":max(r["absolute_error"] for r in records)}
    (ROOT/"results/manual_checks.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
