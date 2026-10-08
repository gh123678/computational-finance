"""Recheck every current annual output with the corrected study calendar scope."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'output/annual_refresh_20261004'


def main():
    status_path = RUN / 'status.json'
    original = status_path.read_text(encoding='utf-8')
    statuses = json.loads(original)
    assert len(statuses) == 7 and all(s['status'] != 'running' for s in statuses)
    saved = RUN / 'status_before_calendar_scope_recheck.json'
    if not saved.exists():
        saved.write_text(original, encoding='utf-8')
    datasets = [*[f'development_{y}' for y in range(2016, 2021)],
                *[f'validation_{y}' for y in range(2021, 2024)],
                'out_of_sample_2024', 'out_of_sample_2025']
    verifier = ROOT / 'scripts/verify_annual.py'
    verifier_hash = hashlib.sha256(verifier.read_bytes()).hexdigest()
    checks = []
    for dataset in datasets:
        with (RUN / f'{dataset}_verify_calendar_scope_final.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([sys.executable, str(verifier), '--dataset', dataset],
                                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        assert hashlib.sha256(verifier.read_bytes()).hexdigest() == verifier_hash
        checks.append(dict(dataset=dataset, exit_code=result.returncode))
        print(dataset, 'passed' if result.returncode == 0 else 'failed', flush=True)
        for item in statuses:
            if item['dataset'] == dataset:
                assert item['steps'][0] == dict(stage='research', exit_code=0)
                item['steps'].append(dict(stage='verify_calendar_scope_final', exit_code=result.returncode))
                item['status'] = 'verified' if result.returncode == 0 else 'failed'
                item['stage'] = 'verify_calendar_scope_final'
        (RUN / 'calendar_scope_verification.json').write_text(
            json.dumps(dict(verifier_sha256=verifier_hash, checks=checks), indent=2), encoding='utf-8')
    status_path.write_text(json.dumps(statuses, indent=2), encoding='utf-8')
    return int(any(c['exit_code'] != 0 for c in checks))


if __name__ == '__main__':
    sys.exit(main())
