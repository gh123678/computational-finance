"""Plot saved diagnostics and three completed controls after the r2 stop.

No missing primary NAV is created or inferred. The inherited plotting routine
uses the actual number of completed summary entries, so its account figure
shows three controls. Keep that newly generated figure and copy it to a name
that explicitly communicates the narrower scope of this failed experiment.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

from PIL import Image

from alphaforge_case_diagnostics import render_figures
from run_retention_development import sha


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/alphaforge_case_2018_2020_r2'
PRIMARY = 'case_negative_retention_common200'
CONTROL = 'three_retention_case_common200'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main(out=OUT):
    out = Path(out)
    if out.resolve() == (ROOT / 'output/alphaforge_case_2018_2020_r1').resolve():
        raise ValueError('Partial r2 plots must not write into frozen r1')
    scope_file = out / 'figures/partial_figures_scope.json'
    if scope_file.exists():
        raise RuntimeError('Existing partial figures; inspect rather than overwrite')
    expected_figures = ['factor_ic.png', 'factor_groups.png', 'factor_coverage.png',
                        'account_performance.png', 'control_accounts_only.png']
    if any((out / 'figures' / name).exists() for name in expected_figures):
        raise RuntimeError('Preexisting figure evidence must be preserved before a separate plotting attempt')
    stage = load(out / 'experiment_stage.json')
    if stage['state'] != 'failed':
        raise RuntimeError('This wrapper is limited to the failed r2 experiment')
    preparation = load(out / 'preparation_audit.json')
    if preparation['status'] != 'passed' or preparation['engineering_preparation_verified'] is not True:
        raise RuntimeError('Independent preparation audit is required for factor diagnostic plots')
    summary = load(out / 'summary.json')
    status = summary['experiment_statuses']
    primary = {f'{PRIMARY}_{cost}bp' for cost in (0, 10, 30)}
    controls = {f'{CONTROL}_{cost}bp' for cost in (0, 10, 30)}
    if len(status) != 6 or {row['strategy'] for row in status} != primary | controls:
        raise RuntimeError('Expected all six fixed account statuses')
    if (any(row['status'] != 'failed' for row in status if row['strategy'] in primary)
            or any(row['status'] != 'completed' for row in status if row['strategy'] in controls)):
        raise RuntimeError('Expected exactly three failed primary accounts and three completed controls')
    experiments = summary['experiments']
    if len(experiments) != 3 or {row['strategy'] for row in experiments} != controls:
        raise RuntimeError('The plotted summary must contain only the three completed controls')
    primary_nav_present = {name: (out / name / 'nav.csv').exists() for name in sorted(primary)}
    if any(primary_nav_present.values()):
        raise RuntimeError('Primary NAV exists unexpectedly; inspect before plotting the failure scope')
    for name in controls:
        if not (out / name / 'nav.csv').is_file():
            raise FileNotFoundError('Actual control NAV missing: ' + name)
    files = ['summary.json', 'status.json', 'experiment_stage.json', 'preparation_audit.json',
             'factor_ic.csv', 'factor_groups.csv', 'common_samples.csv', 'feature_coverage.csv',
             'preparation_sha256.json']
    files += [name + '/nav.csv' for name in sorted(controls)]
    inputs = {name: sha(out / name) for name in files}
    prepared_hashes = load(out / 'preparation_sha256.json')
    for name in ('factor_ic.csv', 'factor_groups.csv', 'common_samples.csv', 'feature_coverage.csv'):
        if inputs[name] != prepared_hashes[name]:
            raise RuntimeError('Prepared plotting input changed: ' + name)
    outputs = render_figures(out)
    original = out / 'figures/account_performance.png'
    explicit = out / 'figures/control_accounts_only.png'
    shutil.copy2(original, explicit)
    if sha(original) != sha(explicit):
        raise RuntimeError('Control scope copy differs from actual account plot')
    outputs.append('figures/control_accounts_only.png')
    if any(sha(out / name) != expected for name, expected in inputs.items()):
        raise RuntimeError('A plotting input changed during figure creation')
    figures = []
    for name in outputs:
        with Image.open(out / name) as picture:
            width, height = picture.size
        figures.append(dict(path=name, width=width, height=height, sha256=sha(out / name),
                            scope='three_completed_controls_only' if name.endswith(('account_performance.png', 'control_accounts_only.png'))
                            else 'saved_full_preparation_factor_diagnostics'))
    result = dict(status='completed', recorded_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
                  experiment_state='failed', primary_accounts_failed=sorted(primary),
                  primary_nav_present=primary_nav_present, plotted_control_accounts=sorted(controls),
                  control_account_count=3, complete_six_account_verification_claimed=False,
                  all_strategy_gates_evaluable=False, primary_account_return_reported=False,
                  account_scope_note='Account figures show only the three completed old-three-factor controls. Primary accounts stopped; no primary NAV or inferred return is plotted.',
                  original_account_figure_preserved=True,
                  explicit_control_figure='figures/control_accounts_only.png',
                  original_account_figure='figures/account_performance.png',
                  account_figures_have_identical_content=True,
                  factor_note='IC, RankIC, fixed-group and coverage figures come from saved independently audited preparation. Label means and IC sums are not account NAV.',
                  figures=figures, inputs_sha256=inputs,
                  wrapper_sha256=sha(Path(__file__)),
                  plotting_source_sha256=sha(ROOT / 'scripts/alphaforge_case_diagnostics.py'),
                  strategy_or_data_modified=False, account_simulation_started=False)
    scope_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status='completed', primary_nav_present=primary_nav_present,
                          figures=[{k: row[k] for k in ('path', 'width', 'height')} for row in figures]), ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=OUT)
    arguments = parser.parse_args()
    main(arguments.out)
