"""Check saved weekly/biweekly experiments, without rerunning or tuning them."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.factors import biweekly_schedule
from quant_research.datasets import dataset_config

DATASETS = [*(f'development_{y}' for y in range(2016, 2021)),
            'out_of_sample_2024', 'out_of_sample_2025']


def main():
    rows, checks, findings = [], [], []
    for dataset in DATASETS:
        output = ROOT / 'output' / dataset
        data = ROOT / 'data' / dataset
        spec = dataset_config(dataset)
        summary_path = output / 'summary.json'
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        verification = json.loads((output / 'verification.json').read_text(encoding='utf-8'))
        verified = (verification['status'] == 'passed' and
                    verification['summary_sha256'] == hashlib.sha256(summary_path.read_bytes()).hexdigest())
        mismatched_code = [name for name, digest in summary['source_sha256'].items()
                           if hashlib.sha256((ROOT / 'quant_research' / name).read_bytes()).hexdigest() != digest]
        manifest = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))
        mismatched_data = [name for name, digest in manifest['files_sha256'].items()
                           if hashlib.sha256((data / name).read_bytes()).hexdigest() != digest]
        raw_cal = pd.read_csv(data / 'calendar.csv', dtype=str)
        cal = pd.DatetimeIndex(pd.to_datetime(raw_cal.loc[raw_cal.is_open.eq('1'), 'cal_date'])).sort_values()
        cal = cal[(cal >= pd.Timestamp(spec['start'])) & (cal <= pd.Timestamp(spec['end']))]
        expected_schedule = biweekly_schedule(cal)
        expected_schedule = expected_schedule.loc[
            expected_schedule.execution_date.ge(pd.Timestamp(summary['first_execution']))]
        check = dict(dataset=dataset, verification_matches_summary=verified,
                     changed_source_files=mismatched_code, changed_data_files=mismatched_data,
                     experiments=len(summary['experiments']), biweekly_checks=[])
        for experiment in summary['experiments']:
            label = experiment['strategy']
            folder = output / label
            rows.append(dict(dataset=dataset, strategy=label,
                             total_return=experiment['total_return'],
                             max_drawdown=experiment['max_drawdown'],
                             gross_turnover=experiment['gross_turnover'],
                             total_cost=experiment['total_fees'] + experiment['total_slippage']))
            if 'biweekly' not in label:
                continue
            targets = pd.read_csv(folder / 'historical_targets.csv', parse_dates=['execution_date', 'signal_date'])
            orders = pd.read_csv(folder / 'orders.csv', parse_dates=['date'])
            nav = pd.read_csv(folder / 'nav.csv')
            actual_schedule = targets[['signal_date', 'execution_date']].drop_duplicates().sort_values('execution_date')
            allowed = set(expected_schedule.execution_date)
            off_schedule = orders.loc[~orders.date.isin(allowed)]
            schedule_matches = actual_schedule.reset_index(drop=True).equals(expected_schedule.reset_index(drop=True))
            identity_error = float((nav.equity - nav[['cash', 'stock_value', 'bonus_value', 'receivable']].sum(axis=1)).abs().max())
            cost_matches = bool(np.isclose(orders.fee.sum() + orders.slippage_cost.sum(),
                                           experiment['total_fees'] + experiment['total_slippage'], atol=1e-6, rtol=0))
            entry = dict(strategy=label, schedule_matches=schedule_matches,
                         off_schedule_order_rows=len(off_schedule),
                         maximum_nav_identity_error=identity_error,
                         order_cost_matches_summary=cost_matches)
            check['biweekly_checks'].append(entry)
        checks.append(check)
        if not verified or mismatched_code or mismatched_data:
            findings.append(f'{dataset}: stale summary/verification/source/data evidence')
        for entry in check['biweekly_checks']:
            if (not entry['schedule_matches'] or entry['off_schedule_order_rows'] or
                    entry['maximum_nav_identity_error'] > 1e-6 or not entry['order_cost_matches_summary']):
                findings.append(f"{dataset}/{entry['strategy']}: schedule/accounting audit failed")
    destination = ROOT / 'output' / 'current_research_audit_20261003'
    destination.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(destination / 'experiment_metrics.csv', index=False)
    report = dict(status='passed' if not findings else 'findings', checks=checks, findings=findings,
                  limitations=['2021-2023 validation absent from the registered experiment matrix.',
                               '2024-2025 have been reused after observing the weekly baseline; biweekly confirmation is not a fresh holdout.',
                               'Biweekly changes both frequency and rank-buffer retention; causal attribution is not isolated.',
                               'This audit confirms saved-output consistency, not live feasibility.'])
    (destination / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
