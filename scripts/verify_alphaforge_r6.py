"""Independent raw-window and covariance reconstruction for r6."""
import argparse
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import traceback

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

import run_alphaforge_r6 as run
from alphaforge_r6_bridge_audit import audit_risk_bridge_reconstruction


def dec(value):
    if not isinstance(value, str):
        return None
    try:
        number = Decimal(value)
        return number if number.is_finite() and number > 0 else None
    except InvalidOperation:
        return None


def table_equal(actual, expected):
    a, b = actual.copy(), expected.copy()
    for frame in (a,b):
        for name in ('close_text', 'pre_close_text'):
            if name in frame:
                frame[name] = frame[name].fillna('')
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True), check_dtype=False,
                                  check_exact=True)


def reconstruct_risk(bars, calendar, schedule, targets, bridge_failures, out):
    """No production window/return/scaling helper is used here."""
    cal = pd.DatetimeIndex(calendar)
    assert cal.is_monotonic_increasing and not cal.has_duplicates
    assert not bars.duplicated(['ts_code','trade_date']).any()
    quotes = {code: group.set_index('trade_date').sort_index() for code,group in bars.groupby('ts_code')}
    indices = {date:i for i,date in enumerate(cal)}
    invalid_sources = {(str(x.ts_code),pd.Timestamp(x.formation_date)) for x in bridge_failures.itertuples(index=False)}
    input_errors, expected_rows = {}, []
    period_table = pd.read_csv(out/'risk_periods.csv', parse_dates=['signal_date','window_start','window_end'], float_precision='round_trip')
    assert not period_table.duplicated(['path','signal_date']).any()
    assert len(period_table) == len(targets)*len(schedule)
    covariances = 0
    for path,base in targets.items():
        all_targets = []
        assert not base.duplicated(['ts_code','signal_date']).any()
        assert np.isfinite(base.target_weight).all() and (base.target_weight >= 0).all()
        assert (base.trade_date == base.signal_date).all()
        assert set(base.signal_date).issubset(set(schedule.signal_date))
        for signal in schedule.signal_date:
            group = base.loc[(base.signal_date == signal) & (base.target_weight > 0)].sort_values('ts_code')
            codes = group.ts_code.tolist()
            actual = period_table.loc[(period_table.path == path) & (period_table.signal_date == signal)]
            assert len(actual) == 1
            actual = actual.iloc[0]
            assert int(actual.target_count) == len(codes)
            prefix = out/'risk_matrices'/f'{path}_{signal:%Y%m%d}'
            if not codes:
                assert actual.status == 'no_positive_targets' and actual.scale == 0
                continue
            end = indices.get(signal, -1)
            assert end >= 60
            dates = cal[end-60:end+1]
            matrix_columns, raw_rows, invalid = [], [], False
            for code in codes:
                frame = quotes[code].reindex(dates).copy()
                frame.index.name = 'date'
                frame['ts_code'],frame['signal_date'] = code,signal
                raw_rows.append(frame.reset_index())
                errors, numbers = [], []
                for index,date in enumerate(dates):
                    row = frame.loc[date]
                    for name in ('open','high','low','close','vol','amount'):
                        try:
                            ok = bool(np.isfinite(float(row[name])) and float(row[name]) > 0)
                        except (ValueError,TypeError):
                            ok = False
                        if not ok:
                            errors.append((date,name,'missing_or_nonpositive_quote'))
                    for name in ('close_text','pre_close_text') if index > 0 else ('close_text',):
                        n = dec(row[name])
                        if n is None:
                            errors.append((date,name,'invalid_decimal_reference'))
                        elif name == 'close_text' and float(n) != float(row['close']):
                            errors.append((date,name,'numeric_and_text_close_differ'))
                    if index > 0:
                        a,b = dec(row.close_text), dec(row.pre_close_text)
                        numbers.append(float(a/b-1) if a is not None and b is not None else np.nan)
                if not errors and not np.isfinite(numbers).all():
                    errors.append((signal,'returns','nonfinite_returns'))
                key = code,signal
                if key in input_errors:
                    assert input_errors[key] == errors
                else:
                    input_errors[key] = errors
                invalid |= bool(errors)
                matrix_columns.append(numbers)
            raw = pd.read_csv(str(prefix)+'_quotes.csv', parse_dates=['date','signal_date'],
                              converters={'close_text':str,'pre_close_text':str}, float_precision='round_trip')
            table_equal(raw, pd.concat(raw_rows, ignore_index=True))
            weights = group.target_weight.to_numpy(dtype=np.float64)
            table_equal(pd.read_csv(str(prefix)+'_weights.csv', float_precision='round_trip'),
                        pd.DataFrame(dict(ts_code=codes,original_weight=weights)))
            if invalid or any((c,signal) in invalid_sources for c in codes):
                assert actual.status == 'failed'
                assert actual.reason == ('invalid_quote_window' if invalid else 'source_bridge_failed')
                assert pd.isna(actual.sigma) and pd.isna(actual.scale)
                assert not Path(str(prefix)+'_covariance.csv').exists()
                continue
            matrix = np.asarray(matrix_columns,dtype=np.float64).T
            assert matrix.shape == (60,len(codes)) and np.isfinite(matrix).all()
            expected_matrix = pd.DataFrame(matrix,index=dates[1:],columns=codes).rename_axis('date')
            table_equal(pd.read_csv(str(prefix)+'_returns.csv',parse_dates=['date'],float_precision='round_trip'),
                        expected_matrix.reset_index())
            estimator = LedoitWolf(store_precision=False,assume_centered=False)
            covariance = estimator.fit(matrix).covariance_
            variance = float(252*weights@covariance@weights)
            if not math.isfinite(variance) or variance <= 0:
                assert actual.status == 'failed' and actual.reason == 'Invalid or zero predicted portfolio variance'
                continue
            sigma = math.sqrt(variance)
            scale = min(1., .15/sigma)
            assert actual.status == 'passed'
            assert math.isclose(actual.sigma,sigma,rel_tol=0,abs_tol=1e-12)
            assert math.isclose(actual.scale,scale,rel_tol=0,abs_tol=1e-12)
            assert actual.window_start == dates[1] and actual.window_end == signal
            table_equal(pd.read_csv(str(prefix)+'_covariance.csv',float_precision='round_trip'),
                        pd.DataFrame(covariance,index=codes,columns=codes).rename_axis('ts_code').reset_index())
            table_equal(pd.read_csv(str(prefix)+'_scaled_weights.csv',float_precision='round_trip'),
                        pd.DataFrame(dict(ts_code=codes,original_weight=weights,new_weight=weights*scale)))
            assert math.isclose(actual.original_exposure,float(weights.sum()),rel_tol=0,abs_tol=1e-12)
            assert math.isclose(actual.new_exposure,float((weights*scale).sum()),rel_tol=0,abs_tol=1e-12)
            assert .0 < scale <= 1 and np.max(weights*scale) <= .049+1e-12
            new = group.copy()
            new['target_weight'] = weights*scale
            all_targets.append(new)
            covariances += 1
        expected = pd.concat(all_targets,ignore_index=True) if all_targets else base.iloc[:0].copy()
        actual_targets = pd.read_csv(out/f'targets_{path}.csv',parse_dates=['trade_date','signal_date','execution_date'],float_precision='round_trip')
        table_equal(actual_targets,expected)
    expected_errors = sorted((code,signal,date,name,reason) for (code,signal),rows in input_errors.items()
                             for date,name,reason in rows)
    errors = pd.read_csv(out/'quote_failures.csv',parse_dates=['signal_date','date'])
    actual_errors = sorted(errors[['ts_code','signal_date','date','field','reason']].itertuples(index=False,name=None))
    assert actual_errors == expected_errors, 'Quote failures differ from independent reconstruction'
    failed = int(period_table.status.eq('failed').sum())
    return dict(path_periods=len(period_table), failed_path_periods=failed, covariances_reconstructed=covariances,
                quote_failure_count=len(expected_errors), raw_windows_exact=True, returns_exact=True,
                covariance_and_weight_reconstruction=True, partial_targets_grant_no_permission=True,
                risk_inputs_passed=not failed and not expected_errors)


def verify_preparation():
    out = run.OUT
    protocol = run.load(out/'frozen_protocol.json')
    run.verify_inputs(protocol)
    run.verify_stage('preparation_sha256.json')
    protected = run.preservation()
    assert protected == protocol['protected_manifests']
    assert protocol['approval_spec_sha256'] == run.sha(run.SPEC)
    assert protocol['base_paths'] == run.PATH_MAP and protocol['window_returns'] == 60 and protocol['risk_target'] == .15
    assert protocol['order'] == [dict(path=p,bps=b,label=f'{p}_{b}bp') for p,b in run.ORDER]
    assert protocol['market_inventory_complete'] is False and protocol['live_enablement'] is False
    bars,full,calendar,schedule,targets,keys,events,evidence = run.load_risk_inputs()
    # Independently derive the positive-target union; do not trust the producer's key helper.
    expected_keys = set()
    for base in targets.values():
        expected_keys |= set(base.loc[base.target_weight>0,['ts_code','signal_date']].itertuples(index=False,name=None))
    actual_keys = pd.read_csv(out/'risk_keys.csv',parse_dates=['trade_date'])
    assert len(actual_keys) == len(expected_keys)
    assert set(actual_keys[['ts_code','trade_date']].itertuples(index=False,name=None)) == expected_keys
    common = pd.read_csv(run.R5/'reused_r3/common_samples.csv',usecols=['ts_code','trade_date'],parse_dates=['trade_date'])
    assert len(common) == 273794 and common.trade_date.nunique() == 154
    assert expected_keys.issubset(set(common[['ts_code','trade_date']].itertuples(index=False,name=None)))
    summary = run.load(out/'source_bridge_summary.json')
    columns = dict(parse_dates=['formation_date','bridge_left','bridge_right','cutoff'],
                   converters={'previous_close_text':str,'current_pre_close_text':str}, float_precision='round_trip')
    coverage = pd.read_csv(out/'source_bridge_coverage.csv',parse_dates=['formation_date'])
    failures = pd.read_csv(out/'source_bridge_failures.csv',**columns)
    trace = pd.read_csv(out/'source_bridge_trace.csv',**columns)
    bridge = audit_risk_bridge_reconstruction(bars,full,actual_keys,
                pd.DataFrame(columns=['ts_code','signal_date','execution_date','R_end','R_valid']),events,evidence,
                summary,coverage,failures,trace)
    risk = reconstruct_risk(bars,full,schedule,targets,failures,out)
    allowed = bool(bridge['source_bridge_passed'] and risk['risk_inputs_passed'])
    producer = run.load(out/'preparation_status.json')
    assert producer['risk_input_passed'] == allowed
    assert producer['risk_keys'] == len(expected_keys) and producer['path_periods'] == risk['path_periods']
    assert producer['failed_path_periods'] == risk['failed_path_periods']
    assert producer['source_failures'] == bridge['source_failure_count']
    assert producer['quote_failures'] == risk['quote_failure_count'] and producer['accounts_started'] == 0
    assert not (out/'experiment_protocol.json').exists()
    result = dict(status='passed' if allowed else 'risk_input_gate_failed', independent_reconstruction_passed=True,
                  conditional_account_attempt_allowed=allowed, accounts_started=0,
                  market_inventory_complete=False, live_enablement=False, bridge=bridge, risk=risk,
                  preparation_manifest_sha256=run.sha(out/'preparation_sha256.json'),
                  verifier_sha256=run.sha(__file__), protected_manifest_count=len(protected),
                  old_members_rehashed=sum(x['count'] for x in protected))
    run.verify_inputs(protocol)
    run.save(out/'preparation_audit.json',result,exclusive=True)
    return result


def verify_accounts():
    from verify_alphaforge_r5_account import verify_account
    from quant_research.backtest import Config,summarize
    out = run.OUT
    protocol = run.load(out/'frozen_protocol.json')
    run.verify_inputs(protocol)
    run.verify_stage('preparation_sha256.json')
    run.verify_stage('accounts_sha256.json')
    assert run.load(out/'preparation_audit.json')['conditional_account_attempt_allowed']
    experiment = run.load(out/'experiment_protocol.json')
    assert experiment['runner_sha256'] == run.sha(run.ROOT/'scripts/run_alphaforge_r6.py')
    assert experiment['preparation_audit_sha256'] == run.sha(out/'preparation_audit.json')
    statuses = run.load(out/'status.json')
    assert [(s['path'],s['slippage_bps']) for s in statuses] == run.ORDER
    failures = [i for i,s in enumerate(statuses) if s['status'] != 'completed']
    if failures:
        first = failures[0]
        assert statuses[first]['status'] == 'failed'
        assert all(s['status']=='not_started' for s in statuses[first+1:])
        assert all(not (out/s['strategy']).exists() for s in statuses[first+1:])
    bars,actions,rights,universe,suspensions,evidence,full,calendar,schedule,targets,_ = run.load_account_inputs()
    records,boundaries,annual = [],[],[]
    summaries = run.load(out/'summary.json')['experiments']
    for status in statuses:
        if status['status']=='not_started':
            continue
        path,bps,label = status['path'],status['slippage_bps'],status['strategy']
        folder = out/label
        assert run.sha(folder/'historical_targets.csv') == run.sha(out/f'targets_{path}.csv')
        complete = status['status']=='completed'
        config = Config(slippage_bps=bps,zero_trading_costs=bps==0)
        audit = verify_account(folder,bars,calendar,targets[path],actions,rights,universe,suspensions,evidence,config,completed=complete)
        records.append(dict(strategy=label,**audit))
        boundaries.extend(dict(strategy=label,**row) for row in audit['year_boundaries'])
        if complete:
            nav = pd.read_csv(folder/'nav.csv',parse_dates=['date'],float_precision='round_trip')
            orders = pd.read_csv(folder/'orders.csv',parse_dates=['date'],float_precision='round_trip')
            recorded = [x for x in summaries if x['strategy']==label]
            assert len(recorded)==1 and recorded[0]['config']==asdict(config)
            for key,value in summarize(nav,orders,schedule.execution_date.iloc[0],pd.Timestamp('20180101')).items():
                actual=recorded[0][key]
                assert math.isclose(actual,value,rel_tol=0,abs_tol=1e-6) if isinstance(value,(float,int)) else actual==value
            previous=1000000.
            for year,group in nav.loc[nav.date>='20180101'].groupby(nav.date.dt.year):
                ending=float(group.equity.iloc[-1])
                annual.append(dict(strategy=label,year=int(year),return_value=ending/previous-1))
                previous=ending
        print('r6 independent account audit',label,audit['status'],flush=True)
    complete = len(records)==6 and all(s['status']=='completed' for s in statuses)
    gates=None
    if complete:
        assert len(boundaries)==12
        stats={s['strategy']:s for s in summaries}
        primary=f'{run.PATHS[0]}_10bp'
        stress=f'{run.PATHS[0]}_30bp'
        control=f'{run.PATHS[1]}_10bp'
        ic=pd.read_csv(run.R5/'reused_r3/factor_ic.csv',parse_dates=['signal_date'])
        # Reuse exactly the frozen signal evidence by its original primary identity.
        ic=ic.loc[ic.path.eq(run.r5.PATHS[0])] if 'path' in ic else ic
        from verify_alphaforge_case import strategy_gates
        # Existing IC logic binds named old paths; map account identities only in memory.
        mapped=pd.DataFrame(summaries).copy()
        for old,new in run.PATH_MAP.items():
            mapped['strategy']=mapped.strategy.str.replace(new,old,regex=False)
        mapped_annual=pd.DataFrame(annual).copy()
        for old,new in run.PATH_MAP.items():
            mapped_annual['strategy']=mapped_annual.strategy.str.replace(new,old,regex=False)
        original_ic=pd.read_csv(run.R5/'reused_r3/factor_ic.csv',parse_dates=['signal_date'])
        gates,_,_=strategy_gates(mapped.set_index('strategy'),mapped_annual,original_ic,schedule)
    pd.DataFrame(annual).to_csv(out/'annual_returns.csv',index=False)
    pd.DataFrame(boundaries).to_csv(out/'year_boundary_audit.csv',index=False)
    result=dict(status='passed' if complete else 'passed_partial_evidence_only',accounts=records,
                full_six_account_verification_passed=complete,year_boundaries=len(boundaries),
                accounts_started=len(records),completed_accounts=sum(s['status']=='completed' for s in statuses),
                gates=gates,research_gates_passed=all(gates.values()) if gates else None,
                market_inventory_complete=False,live_enablement=False)
    run.verify_inputs(protocol)
    run.save(out/('verification.json' if complete else 'partial_verification.json'),result,exclusive=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',choices=['preparation','accounts'],required=True)
    stage=parser.parse_args().stage
    if (run.OUT/'output_sha256.json').exists():
        raise RuntimeError('Sealed r6')
    markers=['preparation_audit.json'] if stage=='preparation' else ['verification.json','partial_verification.json']
    if any((run.OUT/name).exists() for name in markers):
        raise RuntimeError('Existing r6 audit; never overwrite')
    with run.r5.exclusive_stage(run.OUT,'independent_'+stage):
        try:
            result={'preparation':verify_preparation,'accounts':verify_accounts}[stage]()
            print(json.dumps({k:v for k,v in result.items() if k!='accounts'},ensure_ascii=False,default=str),flush=True)
        except Exception:
            with (run.OUT/f'failure_independent_{stage}.txt').open('x',encoding='utf-8') as stream:
                stream.write(traceback.format_exc())
            raise


if __name__=='__main__':
    main()
