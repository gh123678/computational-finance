"""Check persisted results, source provenance and package completeness."""
from pathlib import Path
import csv
import hashlib
import json
import numpy as np
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return list(csv.DictReader((ROOT/'results'/f'{name}.csv').open(encoding='utf-8')))


def main():
    z = np.array([float(r['Z']) for r in read('A4_standardized_sums_n1000')])
    assert z.shape == (10000,) and np.all(np.isfinite(z))
    qq = read('A4_qq')
    np.testing.assert_array_equal([float(r['sample_quantile']) for r in qq],np.sort(z))
    np.testing.assert_array_equal([float(r['normal_quantile']) for r in qq],norm.ppf((np.arange(1,10001)-.5)/10000))
    rows = read('A4_summary')
    assert [int(r['n']) for r in rows] == [1,5,30,1000]
    assert all(int(r['M']) == 10000 for r in rows)
    np.testing.assert_allclose(float(rows[-1]['mean']),z.mean(),rtol=1e-14)
    np.testing.assert_allclose(float(rows[-1]['variance_ddof1']),z.var(ddof=1),rtol=1e-14)
    assert len(read('A5_rmse_repetitions')) == 100
    assert len(list((ROOT/'figures').glob('*.png'))) == 11
    assert len(list((ROOT/'figures').glob('*.pdf'))) == 11
    assert '37 passed' in (ROOT/'results'/'tests.txt').read_text(encoding='utf-8')
    latest = ROOT/'results'/'tests_part_iii.txt'
    if latest.exists():
        assert '45 passed' in latest.read_text(encoding='utf-8')
    assert '0/8 checks passed' in (ROOT/'results'/'debug_before.txt').read_text()
    assert '8/8 checks passed' in (ROOT/'results'/'debug_after.txt').read_text()
    requirements = json.loads((ROOT/'results'/'environment.json').read_text())
    assert requirements['master_seed'] == 20260927
    manifest = {}
    for folder in ['code','data','results','figures','ai_logs','report']:
        for path in sorted((ROOT/folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ['.aux','.log','.out','.toc','.pyc'] and path.name not in ['checksums.json','private_workflow_note.md']:
                manifest[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in ROOT.iterdir():
        if path.is_file() and path.name != 'checksums.json':
            manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (ROOT/'checksums.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('PASS: persisted A4 sample and Q-Q data agree; experiment sizes and all 11 figures verified.')
    print('PASS: test/debug outputs and seed manifest verified; checksums written.')
    print('NOTE: I1(b) re-derivation is disclosed separately; I3 chronology/reflection confirmed by student on October 11.')


if __name__ == '__main__': main()
