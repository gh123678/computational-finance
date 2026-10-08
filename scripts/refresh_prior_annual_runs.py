"""Refresh opened annual datasets with unchanged rules and verified cached data."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'output/annual_refresh_20261004'
DATASETS = ['out_of_sample_2024', 'out_of_sample_2025',
            *[f'development_{y}' for y in range(2016, 2021)]]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    RUN.mkdir(exist_ok=True)
    frozen_path = RUN / 'frozen_protocol.json'
    code = {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / 'quant_research').glob('*.py'))}
    if frozen_path.exists():
        frozen = json.loads(frozen_path.read_text(encoding='utf-8'))
        assert frozen['code_sha256'] == code, 'Core changed after freeze'
    else:
        inputs = {}
        outputs = {}
        for dataset in DATASETS:
            src = ROOT / 'output' / dataset
            summary = json.loads((src / 'summary.json').read_text(encoding='utf-8'))
            inputs[dataset] = dict(data=summary['data_manifest']['files_sha256'],
                                   metadata=summary['metadata_sha256'])
            for name, expected in inputs[dataset]['data'].items():
                assert digest(ROOT / 'data' / dataset / name) == expected, (dataset, name)
            for name, expected in inputs[dataset]['metadata'].items():
                assert digest(ROOT / 'data/audit' / name) == expected, (dataset, name)
            dst = RUN / 'annual_snapshot' / dataset
            if dst.exists():
                raise ValueError('Incomplete preparation; do not overwrite existing snapshot: ' + str(dst))
            shutil.copytree(src, dst)
            for path in src.rglob('*'):
                if path.is_file():
                    saved = dst / path.relative_to(src)
                    assert digest(saved) == digest(path)
                    outputs[str(saved.relative_to(ROOT))] = digest(saved)
        frozen = dict(created_utc=datetime.now(timezone.utc).isoformat(), code_sha256=code,
                      datasets=DATASETS, inputs=inputs, snapshot_sha256=outputs,
                      scope='Prior opened annual accounts, fixed parameters, no download or tuning')
        frozen_path.write_text(json.dumps(frozen, indent=2), encoding='utf-8')
        print('Seven complete annual snapshots and cached inputs verified; protocol frozen.', flush=True)
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    statuses = []
    for dataset in DATASETS:
        status = dict(dataset=dataset, status='running', steps=[])
        statuses.append(status)
        for stage, command in [
            ('research', [sys.executable, '-m', 'quant_research.research', '--dataset', dataset]),
            ('verify', [sys.executable, 'scripts/verify_annual.py', '--dataset', dataset]),
        ]:
            assert {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / 'quant_research').glob('*.py'))} == code
            status['stage'] = stage
            (RUN / 'status.json').write_text(json.dumps(statuses, indent=2), encoding='utf-8')
            print(dataset, stage, flush=True)
            with (RUN / f'{dataset}_{stage}.log').open('w', encoding='utf-8') as log:
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            status['steps'].append(dict(stage=stage, exit_code=result.returncode))
            if result.returncode:
                status['status'] = 'failed'
                break
        else:
            status['status'] = 'verified'
        (RUN / 'status.json').write_text(json.dumps(statuses, indent=2), encoding='utf-8')
        print(dataset, status['status'], flush=True)
    return int(any(s['status'] != 'verified' for s in statuses))


if __name__ == '__main__':
    sys.exit(main())
