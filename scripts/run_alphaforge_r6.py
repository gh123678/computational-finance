"""Approved risk-budget r6: one frozen preparation and at most six accounts."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import traceback

import numpy as np
import pandas as pd
import sklearn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_alphaforge_r5 as r5
from run_retention_development import sha as _sha
from alphaforge_r6_bridges import audit_risk_bridges
from alphaforge_r6_risk import target_keys, risk_inputs, prepare_targets, EMPTY_LABELS

OUT = ROOT/'output/alphaforge_risk_budget_2018_2020_r6'
R5 = r5.OUT
SPEC = ROOT/'docs/superpowers/specs/2026-10-19-alphaforge-risk-budget-r6-design.md'
PLAN = ROOT/'docs/superpowers/plans/2026-10-19-alphaforge-r6-implementation.md'
PROOF = Path('D:/QuantResearchEvidence/alphaforge_post_r5_diagnostics_20261019_r1/path_relocation_readonly_audit.json')
R5_SHA = 'b89beebd817eb2e4420f5130ec9d9e0a1e1be70f7d1da6dc67304c66e7175e95'
SPEC_SHA = '19b0dd58e0cbf60a0afcb192f66ec0e2131697e35815d6b1dbf10aaa43cd9740'
PROOF_SHA = 'fa3942702cb29844af29bc0d828588b7bca47dabe8bf7dd54c638196f8188ac7'
PATH_MAP = dict(zip(r5.PATHS, ('case_negative_risk15_common200_r6', 'three_risk15_case_common200_r6')))
PATHS = tuple(PATH_MAP.values())
ORDER = [(path, bps) for path in PATHS for bps in (0, 10, 30)]
load = r5.read_json
save = r5.persist
OLD_ROOT = Path('C:/Users/Admin/Documents/ChatGPT/计算金融')


def sha(path):
    return _sha(Path(path))


def relocated(path):
    p = Path(path)
    try:
        return ROOT/p.relative_to(OLD_ROOT)
    except ValueError:
        return p


def check_disk():
    for drive in (Path('C:/'), Path('D:/')):
        if shutil.disk_usage(drive).free < 6*1024**3:
            raise RuntimeError('6GiB disk floor: ' + str(drive))


def preservation():
    if sha(PROOF) != PROOF_SHA:
        raise RuntimeError('Relocation proof changed')
    proof = load(PROOF)
    if proof['r5_manifest_sha256'] != R5_SHA or proof['status'] != 'passed':
        raise RuntimeError('Unexpected relocation proof')
    if proof['historical_manifest_members_sum'] != 3539 or len(proof['historical_checks']) != 17:
        raise RuntimeError('Historical protection scope changed')
    rows = [r5.check_manifest(R5/'output_sha256.json', R5_SHA, 206)]
    for item in proof['historical_checks']:
        path = relocated(item['recorded_path'])
        if path != Path(item['observed_path']):
            raise RuntimeError('Relocation mapping differs')
        rows.append(r5.check_manifest(path, item['expected_manifest_sha256'], item['expected_members']))
    return rows


def fingerprint_stage(name):
    return {p.relative_to(OUT).as_posix(): sha(p) for p in OUT.rglob('*')
            if p.is_file() and p.name != 'runner.lock' and p.name != name}


def verify_stage(name):
    for member, expected in load(OUT/name).items():
        if sha(OUT/member) != expected:
            raise RuntimeError('Stage artifact changed: '+member)


def verify_inputs(protocol):
    for filename, expected in protocol['inputs'].items():
        if sha(filename) != expected:
            raise RuntimeError('Frozen input changed: '+filename)
    for row in protocol['protected_manifests']:
        if sha(row['path']) != row['sha256']:
            raise RuntimeError('Protected manifest changed')
    for filename, expected in protocol['source_snapshot'].items():
        if sha(OUT/'source_before'/filename) != expected:
            raise RuntimeError('Source snapshot changed: '+filename)


def freeze():
    if (OUT/'frozen_protocol.json').exists():
        raise RuntimeError('Existing r6 preparation; never repeat')
    check_disk()
    if sha(SPEC) != SPEC_SHA:
        raise RuntimeError('Approved r6 design changed')
    protected = preservation()
    old = load(R5/'frozen_protocol.json')
    inputs, mappings = {}, []
    def bind(path, expected=None, recorded=None):
        actual = relocated(path)
        digest = sha(actual)
        if expected and digest != expected:
            raise RuntimeError('Original frozen input changed: '+str(actual))
        key = str(actual)
        if key in inputs and inputs[key] != digest:
            raise RuntimeError('Conflicting frozen input')
        inputs[key] = digest
        if recorded is not None and str(actual) != str(recorded):
            mappings.append(dict(recorded=str(recorded), actual=str(actual), sha256=digest))
    for name, digest in old['inputs'].items():
        bind(ROOT/name, digest)
    for field in ('external_inputs', 'original_r4_external_inputs'):
        for name, digest in old[field].items():
            bind(name, digest, recorded=name)
    for name, digest in old['original_r4_inputs'].items():
        bind(ROOT/name, digest)
    sources = sorted(set([*ROOT.joinpath('scripts').glob('*r6*.py'),
                          *ROOT.joinpath('tests').glob('*r6*.py'),
                          *[ROOT/n for n in old['inputs'] if n.endswith('.py')],
                          ROOT/'scripts/verify_alphaforge_r5_account.py',
                          ROOT/'scripts/alphaforge_r5_preparation_audit.py',
                          ROOT/'scripts/ml_risk_model.py']))
    for p in [*sources, SPEC, PLAN, ROOT/'docs/2026-10-19-alphaforge-r6-engineering.md',
              *sorted((ROOT/'tmp').glob('alphaforge_r6_engineering*.log')), PROOF,
              R5/'evidence_mapping.json', R5/'verification.json', R5/'summary.json',
              R5/'annual_returns.csv', *sorted((R5/'reused_r3').glob('*'))]:
        bind(p)
    if str(ROOT/'tmp/alphaforge_r6_engineering_final.log') not in inputs:
        raise RuntimeError('Final engineering evidence absent')
    snapshot = OUT/'source_before'
    snapshot.mkdir()
    source_map = {}
    for p in sources:
        relative = p.relative_to(ROOT)
        dest = snapshot/relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        source_map[relative.as_posix()] = sha(p)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    protocol = dict(version='r6', client_date='2026-10-19', approval='Human 继续我们的任务 after delivered precise r6 design',
                    approval_spec_sha256=sha(SPEC), source_commit=commit, workspace=str(ROOT),
                    relocation_proof_sha256=sha(PROOF), explicit_relocation_mappings=mappings,
                    protected_manifests=protected, inputs=inputs, source_snapshot=source_map,
                    initial_cash=1000000, fixed_keys=273794, periods=154, account_sessions=790,
                    performance_observations=730, window_returns=60, risk_target=.15, costs=[0,10,30],
                    paths=list(PATHS), base_paths=PATH_MAP,
                    order=[dict(path=p, bps=b, label=f'{p}_{b}bp') for p,b in ORDER],
                    versions=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
                                  sklearn=sklearn.__version__),
                    conditional_account_attempt_allowed=False, market_inventory_complete=False, live_enablement=False,
                    scope='Retrospective fixed historical development; no unseen or forward claim')
    save(OUT/'frozen_protocol.json', protocol, exclusive=True)
    return protocol


def load_risk_inputs():
    base = R5/'reused_r3'
    targets = {new: pd.read_csv(base/f'targets_{old}.csv',
                              parse_dates=['trade_date','signal_date','execution_date'], float_precision='round_trip')
               for old,new in PATH_MAP.items()}
    keys = target_keys(targets)
    bars = pd.read_csv(base/'raw_bars.csv', parse_dates=['trade_date'],
                       converters={'close_text': str, 'pre_close_text': str}, float_precision='round_trip')
    bars = bars.loc[bars.ts_code.isin(set(keys.ts_code))].copy()
    full, _, calendar, schedule = r5.previous.calendars()
    recorded_schedule = pd.read_csv(base/'schedule.csv', parse_dates=['signal_date','execution_date','next_execution'])
    pd.testing.assert_frame_equal(recorded_schedule, schedule, check_dtype=False)
    events = pd.read_csv(base/'events.csv', dtype=str)
    evidence = load(R5/'evidence_mapping.json')
    return bars, full, calendar, schedule, targets, keys, events, evidence


def preparation():
    protocol = freeze()
    bars, full, calendar, schedule, targets, keys, events, evidence = load_risk_inputs()
    assert len(schedule) == 154 and len(calendar) == 790
    common = pd.read_csv(R5/'reused_r3/common_samples.csv', usecols=['ts_code','trade_date'], parse_dates=['trade_date'])
    assert len(common) == 273794 and common.trade_date.nunique() == 154
    assert common.groupby('trade_date').size().min() >= 200
    common_index = pd.MultiIndex.from_frame(common[['ts_code','trade_date']])
    assert pd.MultiIndex.from_frame(keys[['ts_code','trade_date']]).isin(common_index).all()
    keys.to_csv(OUT/'risk_keys.csv', index=False)
    print('r6 auditing 60 internal bridges for', len(keys), 'unique fixed target keys', flush=True)
    bridge = audit_risk_bridges(bars, full, keys, EMPTY_LABELS, events, evidence)
    save(OUT/'source_bridge_summary.json', bridge['summary'], exclusive=True)
    columns = ['kind','ts_code','formation_date','bridge_left','bridge_right','cutoff','reason','passed']
    for name in ('coverage', 'failures', 'trace'):
        frame = bridge[name]
        if not len(frame.columns):
            frame = pd.DataFrame(columns=columns)
        frame.to_csv(OUT/f'source_bridge_{name}.csv', index=False)
    windows, returns, failures = risk_inputs(bars, full, keys)
    failures.to_csv(OUT/'quote_failures.csv', index=False)
    periods, _ = prepare_targets(targets, schedule, windows, returns, bridge['failures'], OUT)
    failed = int(periods.status.eq('failed').sum())
    passed = bool(bridge['summary']['passed'] and failures.empty and failed == 0)
    save(OUT/'preparation_status.json', dict(state='awaiting_independent_audit', risk_input_passed=passed,
         risk_keys=len(keys), source_failures=len(bridge['failures']), quote_failures=len(failures),
         path_periods=len(periods), failed_path_periods=failed, accounts_started=0), exclusive=True)
    verify_inputs(protocol)
    save(OUT/'preparation_sha256.json', fingerprint_stage('preparation_sha256.json'), exclusive=True)
    print('r6 production preparation complete; scientific admission', passed, 'failed path periods', failed, flush=True)


def load_account_inputs():
    values = list(r5.load_account_inputs())
    values[9] = {path: pd.read_csv(OUT/f'targets_{path}.csv',
                      parse_dates=['trade_date','signal_date','execution_date'], float_precision='round_trip') for path in PATHS}
    return tuple(values)


def accounts():
    from alphaforge_r5_account import simulate_exposure, AccountRunFailure
    from quant_research.backtest import Config, summarize
    protocol = load(OUT/'frozen_protocol.json')
    verify_inputs(protocol)
    verify_stage('preparation_sha256.json')
    audit = load(OUT/'preparation_audit.json')
    if not audit['conditional_account_attempt_allowed'] or audit['market_inventory_complete']:
        raise RuntimeError('Full independent risk preparation permission required')
    save(OUT/'experiment_protocol.json', dict(order=protocol['order'],
         preparation_audit_sha256=sha(OUT/'preparation_audit.json'), runner_sha256=sha(__file__)), exclusive=True)
    statuses = [dict(strategy=f'{p}_{b}bp', path=p, slippage_bps=b, status='not_started') for p,b in ORDER]
    bars,actions,rights,universe,suspensions,evidence,full,calendar,schedule,targets,corrections = load_account_inputs()
    sectors = pd.read_csv(ROOT/'data/audit/industry_history.csv', dtype=str)
    industries = {}
    for date in calendar:
        stamp = date.strftime('%Y%m%d')
        sector = sectors.loc[(sectors.in_date <= stamp) & (sectors.out_date.isna() | (sectors.out_date > stamp))]
        counts = sector.groupby('ts_code').l1_code.nunique()
        sector = sector.loc[sector.ts_code.isin(counts[counts == 1].index)].drop_duplicates('ts_code')
        industries[date] = dict(zip(sector.ts_code, sector.l1_code))
    summaries = []
    save(OUT/'status.json', statuses)
    for status in statuses:
        check_disk()
        path, bps, label = status['path'], status['slippage_bps'], status['strategy']
        folder = OUT/label
        folder.mkdir()
        shutil.copy2(OUT/f'targets_{path}.csv', folder/'historical_targets.csv')
        status['status'] = 'running'
        save(OUT/'status.json', statuses)
        config = Config(slippage_bps=bps, zero_trading_costs=bps == 0)
        print('r6 account starting', label, flush=True)
        try:
            result = simulate_exposure(bars.loc[bars.ts_code.isin(set(targets[path].ts_code))], calendar,
                     targets[path], actions, suspensions, industries=industries, config=config,
                     rebalance_dates=schedule.execution_date.tolist(), rights=rights, universe=universe,
                     full_calendar=full, evidence=evidence,
                     progress=lambda date,count: print(label, count, str(date.date()), flush=True))
            r5.save_account(folder, result)
            summary = summarize(result['nav'], result['orders'], schedule.execution_date.iloc[0], pd.Timestamp('20180101'))
            summary.update(strategy=label, path=path, config=asdict(config))
            summaries.append(summary)
            status.update(status='completed', completed_sessions=len(result['nav']))
        except AccountRunFailure as error:
            r5.save_account(folder, error.partial)
            failure = dict(date=str(error.date.date()), reason=str(error.original),
                           type='data_or_economic_failure' if isinstance(error.original, ValueError) else 'engineering_failure',
                           guard_row=getattr(error.original, 'row', None), completed_sessions=len(error.partial['nav']))
            save(folder/'failure.json', failure, exclusive=True)
            (folder/'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
            status.update(status='failed', **failure)
        except Exception:
            status.update(status='engineering_failure', error=traceback.format_exc())
            (folder/'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        save(OUT/'status.json', statuses)
        save(OUT/'summary.json', dict(experiments=summaries, experiment_statuses=statuses,
             corrections=corrections, market_inventory_complete=False, live_enablement=False))
        verify_inputs(protocol)
        if status['status'] != 'completed':
            break
    save(OUT/'accounts_sha256.json', fingerprint_stage('accounts_sha256.json'), exclusive=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['preparation', 'accounts'], required=True)
    stage = parser.parse_args().stage
    OUT.mkdir(exist_ok=True)
    if (OUT/'output_sha256.json').exists():
        raise RuntimeError('Sealed r6; never overwrite')
    marker = 'frozen_protocol.json' if stage == 'preparation' else 'experiment_protocol.json'
    if (OUT/marker).exists():
        raise RuntimeError('Existing r6 stage; never repeat')
    check_disk()
    with r5.exclusive_stage(OUT, stage):
        try:
            {'preparation': preparation, 'accounts': accounts}[stage]()
        except Exception:
            with (OUT/f'failure_{stage}_{os.getpid()}.txt').open('x', encoding='utf-8') as stream:
                stream.write(traceback.format_exc())
            raise


if __name__ == '__main__':
    main()
