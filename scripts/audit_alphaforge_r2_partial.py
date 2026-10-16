"""Audit completed r2 controls after the three primary accounts stopped.

This adds supplementary evidence only. It never runs an account, recomputes
the preparation formulas, changes frozen sources, or assesses strategy gates.
"""
from dataclasses import asdict
import json
from pathlib import Path
import traceback

import numpy as np
import pandas as pd

import verify_alphaforge_case as old
import verify_alphaforge_r2 as r2
from quant_research.backtest import Config, summarize

ROOT, OUT = r2.ROOT, r2.OUT
FILENAMES = ('partial_account_audit.json', 'partial_annual_returns.csv',
             'partial_account_operations.csv', 'partial_year_boundary_audit.csv',
             'partial_completed_comparison.csv')
EXPECTED_FAILURE = 'Unexplained corporate action for held 000998.SZ on 2020-01-02'


def main(out=OUT):
    out = Path(out)
    if any((out/name).exists() for name in FILENAMES):
        raise RuntimeError('Existing partial-audit evidence; inspect rather than overwrite')
    assert not (out/'verification.json').exists(), 'Full verification must not be implied'
    protocol = old.read_json(out/'frozen_protocol.json')
    prior_counts = r2.check_fingerprints(protocol)
    prepared = old.read_json(out/'preparation_audit.json')
    assert prepared['status'] == 'passed' and prepared['engineering_preparation_verified']
    assert prepared['formation_dates'] == 154
    assert prepared['verifier_sha256'] == old.sha(ROOT/'scripts/verify_alphaforge_r2.py')
    assert old.read_json(out/'preparation_status.json')['state'] == 'completed'
    for name, expected in old.read_json(out/'preparation_sha256.json').items():
        assert old.sha(out/name) == expected, 'Prepared artifact changed: '+name
    stage = old.read_json(out/'experiment_stage.json')
    assert stage['state'] == 'failed' and stage['accounts'] == 6
    summary = old.read_json(out/'summary.json')
    statuses = old.read_json(out/'status.json')
    assert summary['experiment_statuses'] == statuses
    expected_all = {f'{path}_{cost}bp' for path in old.PATHS for cost in (0,10,30)}
    expected_primary = {f'{old.PRIMARY}_{cost}bp' for cost in (0,10,30)}
    expected_controls = expected_all-expected_primary
    assert len(statuses) == 6 and {item['strategy'] for item in statuses} == expected_all
    assert {item['strategy'] for item in statuses if item['status'] == 'failed'} == expected_primary
    assert {item['strategy'] for item in statuses if item['status'] == 'completed'} == expected_controls
    assert len(summary['experiments']) == 3
    assert {item['strategy'] for item in summary['experiments']} == expected_controls
    assert summary['source_sha256'] == protocol['source_sha256']
    experiment = old.read_json(out/'experiment_protocol.json')
    assert old.sha(ROOT/'scripts/run_alphaforge_r2.py') == experiment['runner_sha256']
    assert old.sha(out/'simulation_adapter_block.py.txt') == experiment['adapter_sha256']
    last_failure = old.read_json(out/'last_failure.json')
    assert last_failure['stage'] == 'accounts'
    assert (out/last_failure['failure']).is_file()
    failed = []
    inputs = [out/name for name in ('frozen_protocol.json','preparation_audit.json',
              'preparation_status.json','preparation_sha256.json','experiment_protocol.json',
              'experiment_stage.json','status.json','summary.json','last_failure.json',
              'common_samples.csv','schedule.csv','factor_ic.csv','factor_groups.csv',
              'targets_case_negative_retention_common200.csv',
              'targets_three_retention_case_common200.csv','simulation_adapter_block.py.txt')]
    inputs.append(out/last_failure['failure'])
    for status in statuses:
        if status['strategy'] not in expected_primary:
            continue
        assert status['status'] == 'failed' and status['error'] == EXPECTED_FAILURE
        failure = out/status['strategy']/'failure.txt'
        text = failure.read_text(encoding='utf-8')
        assert text.rstrip().endswith('ValueError: '+EXPECTED_FAILURE)
        inputs.append(failure)
        target = out/status['strategy']/'historical_targets.csv'
        assert old.sha(target) == old.sha(out/f'targets_{old.PRIMARY}.csv')
        inputs.append(target)
        failed.append(dict(strategy=status['strategy'], status='failed',
                           code='000998.SZ', date='2020-01-02', error=EXPECTED_FAILURE,
                           failure_file=failure.relative_to(out).as_posix(),
                           failure_sha256=old.sha(failure), performance_inferred=False,
                           ledger_files_present=[name for name in ('nav.csv','orders.csv','holdings.csv','corporate_events.csv')
                                                 if (failure.parent/name).exists()]))
    for item in summary['experiments']:
        inputs.extend(out/item['strategy']/name for name in
                      ('historical_targets.csv','nav.csv','orders.csv','corporate_events.csv','holdings.csv'))
    before = {path.relative_to(out).as_posix():old.sha(path) for path in inputs}
    calendar, schedule = r2.schedule_and_calendar()
    saved_schedule = pd.read_csv(out/'schedule.csv',parse_dates=['signal_date','execution_date'])
    pd.testing.assert_frame_equal(saved_schedule,schedule)
    common = pd.read_csv(out/'common_samples.csv',parse_dates=['trade_date','D_end','reference_end'],float_precision='round_trip')
    ic = old.verify_diagnostics(common,schedule,out)
    old.verify_targets(common,schedule,out)
    assert len(ic) == 154*3
    checks, annual, boundaries, operations = [], [], [], []
    expected_calendar = calendar[calendar >= '2017-10-01']
    for item in summary['experiments']:
        strategy = item['strategy']
        print('Independently audit completed control',strategy,flush=True)
        assert item['path'] == old.PATHS[1]
        folder = out/strategy
        assert old.sha(folder/'historical_targets.csv') == old.sha(out/f'targets_{item["path"]}.csv')
        cost = int(strategy.rsplit('_',1)[1][:-2])
        assert item['config'] == asdict(Config(slippage_bps=cost,zero_trading_costs=cost == 0))
        nav = pd.read_csv(folder/'nav.csv',parse_dates=['date'],float_precision='round_trip')
        orders = pd.read_csv(folder/'orders.csv',parse_dates=['date'],float_precision='round_trip')
        events = pd.read_csv(folder/'corporate_events.csv',parse_dates=['date'],float_precision='round_trip')
        holdings = pd.read_csv(folder/'holdings.csv',parse_dates=['date'],float_precision='round_trip')
        assert pd.DatetimeIndex(nav.date).equals(expected_calendar)
        assert nav.loc[nav.date.eq(pd.Timestamp('2017-12-29')),'equity'].iloc[0] == 1_000_000
        assert orders.date.isin(schedule.execution_date).all()
        if cost == 0:
            assert orders[['fee','slippage_cost']].eq(0).all().all()
        record, edges = old.reconstruct_account(nav,orders,events,holdings)
        assert len(edges) == 2
        checks.append(dict(strategy=strategy,**record))
        boundaries.extend(dict(strategy=strategy,**edge) for edge in edges)
        operations.append(dict(strategy=strategy,**old.summarize_operations(nav,orders)))
        calculated = summarize(nav,orders,schedule.execution_date.iloc[0],pd.Timestamp('2018-01-01'))
        for name,value in calculated.items():
            if isinstance(value,(float,int)):
                assert np.isclose(value,item[name],rtol=0,atol=1e-6),(strategy,name)
        assert abs(float(orders.fee.sum())-item['total_fees']) < 1e-6
        assert abs(float(orders.slippage_cost.sum())-item['total_slippage']) < 1e-6
        previous_equity = 1_000_000.
        for year,group in nav.loc[nav.date >= '2018-01-01'].groupby(nav.date.dt.year):
            ending = float(group.equity.iloc[-1])
            annual.append(dict(strategy=strategy,year=int(year),start_equity=previous_equity,
                               end_equity=ending,return_value=ending/previous_equity-1))
            previous_equity = ending
    assert len(checks) == 3 and len(failed) == 3 and len(boundaries) == 6 and len(annual) == 9
    assert r2.check_fingerprints(protocol) == prior_counts
    after = {path.relative_to(out).as_posix():old.sha(path) for path in inputs}
    assert before == after
    pd.DataFrame(annual).to_csv(out/'partial_annual_returns.csv',index=False)
    pd.DataFrame(operations).to_csv(out/'partial_account_operations.csv',index=False)
    pd.DataFrame(boundaries).to_csv(out/'partial_year_boundary_audit.csv',index=False)
    pd.DataFrame(summary['experiments']).drop(columns=['config']).to_csv(out/'partial_completed_comparison.csv',index=False)
    result = dict(status='passed',partial_only=True,completed_accounts_verified=3,
                  failed_primary_accounts=3,year_boundaries=6,accounts=checks,failed_accounts=failed,
                  diagnostics_verified=True,diagnostic_factor_periods=len(ic),targets_verified_for_both_paths=True,
                  full_six_account_verification_passed=False,research_gates_assessable=False,
                  research_gates_evaluated=False,primary_performance_available=False,
                  preparation_audit_recomputed=False,preparation_audit_sha256=old.sha(out/'preparation_audit.json'),
                  preparation_audit_status=prepared['status'],old_artifacts=prior_counts,
                  input_sha256_before=before,input_sha256_after=after,inputs_unchanged=True,
                  auditor_sha256=old.sha(Path(__file__)),broker_connected=False,
                  scope='Completed controls and factor diagnostics only; primary stopped at the original unexplained-action guard; no control promotion.')
    old.persist('partial_account_audit.json',result,out)
    print(json.dumps({key:result[key] for key in ('status','completed_accounts_verified','failed_primary_accounts',
                      'year_boundaries','full_six_account_verification_passed','research_gates_assessable')},ensure_ascii=False),flush=True)
    return result


if __name__ == '__main__':
    try:
        main()
    except Exception:
        failure = OUT/f'partial_account_audit_failure_{pd.Timestamp.now():%Y%m%dT%H%M%S}.txt'
        failure.write_text(traceback.format_exc(),encoding='utf-8')
        raise
