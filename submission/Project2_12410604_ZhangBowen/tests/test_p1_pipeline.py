"""P1 source reuse, integration contracts and cash/holdings reconciliation."""
import ast
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from p1_platform import legacy
from p1_platform.pipeline import (INSTRUMENT,load_factor_observations,register_datasets,select_dataset,
                                  form_targets,validate_targets,run_experiment)

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    calendar=pd.bdate_range("2019-12-01","2020-03-31")
    dates=pd.period_range("2020-01",periods=3,freq="M")
    panel=pd.DataFrame({"market_excess":[.1,-.08,.03],"rf":[.001,.002,.001],"lag_rv":[.001,.003,.002]},index=dates)
    return panel,pd.Series([1.4,.2,1.8],index=dates),calendar


def test_exact_p1_function_source_provenance():
    manifest=json.loads((ROOT/"p1_platform/function_provenance.json").read_text(encoding="utf-8"))
    extracted=(ROOT/"p1_platform/legacy.py").read_text(encoding="utf-8")
    nodes={n.name:n for n in ast.parse(extracted).body if isinstance(n,ast.FunctionDef)}
    for row in manifest["functions"]:
        source=ROOT/row["reference_file"]
        assert hashlib.sha256(source.read_bytes()).hexdigest()==row["source_file_sha256"]
        segment=ast.get_source_segment(extracted,nodes[row["function"]])
        assert hashlib.sha256(segment.encode()).hexdigest()==row["function_utf8_sha256"]


def test_source_loader_is_actually_called_and_preserves_daily_rf_precision(tmp_path,monkeypatch):
    frame=pd.DataFrame({"Mkt-RF":[.001,-.002],"SMB":[0.,.0001],"HML":[.0001,0.],"RF":[.00009,.000091]},
                       index=pd.DatetimeIndex(["2020-01-02","2020-01-03"],name="date"))
    calls=[];original=legacy.read_market
    def spy(*args):calls.append(args);return original(*args)
    monkeypatch.setattr(legacy,"read_market",spy)
    restored=load_factor_observations(frame,tmp_path/"daily.csv","daily")
    assert len(calls)==1
    np.testing.assert_allclose(restored,frame,atol=1e-15,rtol=0)


def test_registered_sample_selection_calls_original_p1_config(monkeypatch):
    config={"replication_start":"2020-01","replication_end":"2020-02","holdout_start":"2020-03","holdout_end":"2020-03"}
    register_datasets(config)
    panel,_,_=fixture()
    assert len(select_dataset(panel,"project2_core"))==2
    with pytest.raises(ValueError,match="Unregistered"):select_dataset(panel,"unregistered_window")
    returned=legacy.dataset_config("project2_core");returned["start"]="1900-01"
    assert legacy.dataset_config("project2_core")["start"]=="2020-01"


@pytest.mark.parametrize("mutation",["future","same_day","wrong_month","duplicate","missing","wrong_instrument"])
def test_target_contract_rejects_invalid_formation_and_dates(mutation):
    panel,weights,calendar=fixture();targets=form_targets(panel,weights,calendar)
    if mutation=="future":targets.loc[0,"signal_date"]=pd.Timestamp("2020-02-01")
    elif mutation=="same_day":targets.loc[0,"signal_date"]=targets.loc[0,"execution_date"]
    elif mutation=="wrong_month":targets.loc[0,"signal_date"]=pd.Timestamp("2019-11-29")
    elif mutation=="duplicate":targets=pd.concat([targets,targets.iloc[:1]],ignore_index=True)
    elif mutation=="missing":targets=targets.iloc[1:]
    else:targets.loc[0,"ts_code"]="UNKNOWN"
    with pytest.raises(ValueError):validate_targets(panel,targets)


@pytest.mark.parametrize("cost,spread",[(0,0),(10,0),(30,200)])
def test_pipeline_executes_legacy_analysis_and_exports_p1_contract(tmp_path,monkeypatch,cost,spread):
    panel,weights,calendar=fixture()
    calls=[];original=legacy.summarize
    def spy(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(legacy,"summarize",spy)
    result=run_experiment(panel,weights,calendar,tmp_path,"check",cost,spread)
    assert len(calls)==1
    assert set(["nav","orders","holdings","corporate_events"]).issubset(result)
    nav,orders,holdings=result["nav"],result["orders"],result["holdings"]
    np.testing.assert_allclose(holdings.value+holdings.cash,nav.equity.iloc[1:])
    np.testing.assert_allclose(orders.fee.sum(),nav.fees.sum())
    assert (tmp_path/"p1_runs/check/targets.csv").exists()
    evidence=json.loads((tmp_path/"p1_runs/check/contract_audit.json").read_text())
    assert "annualized_return" not in evidence["legacy_period_free_summary"]
    # Reconstruct risky units, cash and end NAV from exported orders only.
    cash=1.;units=0.;price=1.
    for i,order in enumerate(orders.itertuples()):
        change=order.shares*(1 if order.side=="buy" else -1)
        cash-=change*order.price+order.fee;units+=change
        cash=cash*(1+panel.rf.iloc[i])-max(-cash,0)*spread/10000/12
        price*=1+panel.rf.iloc[i]+panel.market_excess.iloc[i]
        assert units*price+cash==pytest.approx(nav.equity.iloc[i+1],abs=1e-12)


def test_backend_refuses_unregistered_dispatch(tmp_path):
    panel,weights,calendar=fixture()
    with pytest.raises(ValueError,match="backend"):
        run_experiment(panel,weights,calendar,tmp_path,"check",backend="stock_unlimited")
