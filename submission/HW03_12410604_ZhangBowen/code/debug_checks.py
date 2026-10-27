"""Independent executable checks for the supplied I2 routine and actual patches."""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
from pathlib import Path
import numpy as np

def load(path):
    spec=importlib.util.spec_from_file_location("checked_terminal_module",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.terminal_report

def checks(path):
    report=load(path)
    rows=[]
    def record(name, fn):
        try:
            result=fn()
            passed=bool(result)
            detail="passed" if passed else "assertion false"
        except Exception as e:
            passed=False; detail=f"{type(e).__name__}: {e}"
        rows.append(dict(check=name,passed=passed,detail=detail))
    args=dict(s0=100.,mu=.08,sigma=.3,horizon=2.,count=100000,seed=21603)
    x=100*np.exp((.08-.5*.3**2)*2+.3*np.sqrt(2)*np.random.default_rng(21603).standard_normal(100000))
    out=report(**args)
    target=100*math.exp(.16)
    v=target**2*math.expm1(.18)
    pi=np.array([100*math.exp(.07-1.96*.3*math.sqrt(2)),100*math.exp(.07+1.96*.3*math.sqrt(2))])
    record("analytical_mean_within_5_model_MCSE",lambda: abs(out['mean']-target)<5*math.sqrt(v/100000))
    record("analytical_variance_within_5_percent",lambda: abs(out['variance']/v-1)<.05)
    record("same_draws_correct_drift_and_time",lambda: np.isclose(out['mean'],x.mean(),rtol=1e-13))
    record("variance_divisor_n_minus_1",lambda: np.isclose(out['variance'],x.var(ddof=1),rtol=1e-13))
    record("SE_is_sample_sd_over_sqrt_M",lambda: np.isclose(out['se'],x.std(ddof=1)/math.sqrt(len(x)),rtol=1e-13))
    record("fixed_population_prediction_interval",lambda: np.allclose(out['prediction_interval'],pi,rtol=1e-13))
    record("distinct_mean_confidence_interval",lambda: np.allclose(out['mean_confidence_interval'],[out['mean']-1.96*out['se'],out['mean']+1.96*out['se']],rtol=1e-13))
    record("quadrupling_M_halves_SE",lambda: .47<report(**(args|{'count':400000}))['se']/out['se']<.53)
    def zero_time():
        q=report(**(args|dict(horizon=0.)))
        return q['mean']==100 and q['variance']==0 and q['se']==0 and q['prediction_interval']==[100.,100.]
    record("T_zero_point_mass",zero_time)
    def zero_sigma():
        q=report(**(args|dict(sigma=0.)))
        return np.isclose(q['mean'],target) and q['variance']==0 and q['se']==0 and np.allclose(q['prediction_interval'],[target,target])
    record("sigma_zero_point_mass",zero_sigma)
    def invalid():
        for bad in [dict(s0=0),dict(s0=-1),dict(mu=float('nan')),dict(mu=float('inf')),dict(sigma=-.3),dict(horizon=-1),dict(count=1),dict(count=2.5),dict(count=True)]:
            try: report(**(args|bad))
            except (ValueError,TypeError): pass
            else: return False
        return True
    record("invalid_model_and_count_rejected",invalid)
    summary=dict(module=Path(path).name,checks=rows,passed=sum(r['passed'] for r in rows),total=len(rows),
                 actual_default_report=out,analytical_mean=target,analytical_variance=v,analytical_prediction_interval=pi.tolist())
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('module',type=Path)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    summary=checks(args.module)
    s=json.dumps(summary,indent=2)
    if args.output: args.output.write_text(s,encoding='utf8')
    print(s)
    raise SystemExit(0 if summary['passed']==summary['total'] else 1)
