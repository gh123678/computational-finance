"""Resume the three registered validation years; save failures without hiding them."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main(revision='initial'):
    suffix = '' if revision == 'initial' else '_' + revision
    destination = ROOT / 'output' / ('validation_run_20261004' + suffix)
    destination.mkdir(parents=True, exist_ok=True)
    frozen_path = destination / 'frozen_protocol.json'
    code = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / 'quant_research').glob('*.py'))}
    if frozen_path.exists():
        frozen = json.loads(frozen_path.read_text(encoding='utf-8'))
        if frozen['code_sha256'] != code:
            raise ValueError('Code changed since validation freeze; document a revision before rerunning')
    else:
        frozen = dict(created_utc=datetime.now(timezone.utc).isoformat(),
                      code_sha256=code,
                      protocol_sha256=hashlib.sha256((ROOT / 'docs/2026-10-04-validation-protocol.md').read_bytes()).hexdigest(),
                      datasets=['validation_2021', 'validation_2022', 'validation_2023'],
                      scope='Fixed current rules; supplementary validation, not a new sealed test')
        frozen_path.write_text(json.dumps(frozen, indent=2), encoding='utf-8')
    environment = os.environ.copy()
    environment['PYTHONIOENCODING'] = 'utf-8'
    statuses = []
    for dataset in frozen['datasets']:
        steps = [('download', [sys.executable, '-m', 'quant_research.download', '--dataset', dataset,
                                '--interval', '0.4', '--workers', '12']),
                 ('research', [sys.executable, '-m', 'quant_research.research', '--dataset', dataset]),
                 ('verify', [sys.executable, 'scripts/verify_annual.py', '--dataset', dataset])]
        item = dict(dataset=dataset, steps=[], status='running')
        statuses.append(item)
        for stage, command in steps:
            print(f'{dataset}: {stage}', flush=True)
            item['stage'] = stage
            (destination / 'status.json').write_text(json.dumps(statuses, indent=2), encoding='utf-8')
            with (destination / f'{dataset}_{stage}.log').open('w', encoding='utf-8') as log:
                result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            item['steps'].append(dict(stage=stage, exit_code=result.returncode))
            if result.returncode:
                item['status'] = 'failed'
                print(f'{dataset}: {stage} failed; see saved log', flush=True)
                break
        else:
            item['status'] = 'verified'
            print(f'{dataset}: verified', flush=True)
        (destination / 'status.json').write_text(json.dumps(statuses, indent=2), encoding='utf-8')
    return int(any(item['status'] != 'verified' for item in statuses))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', choices=['initial', 'r2', 'r3'], default='initial',
                        help='Separate documented data-evidence corrections from the original frozen run')
    sys.exit(main(parser.parse_args().revision))
