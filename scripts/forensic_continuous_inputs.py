"""Trace a missing dividend and recheck the failed group's saved target universe."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/continuous_event_audit_20261005'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=True)
    public = dict(api_name='dividend', params={'ex_date': '20250609'}, fields='')
    key = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
    cache = ROOT / 'data/raw/dividend' / (key + '.json')
    provenance = {'cache_path': str(cache.relative_to(ROOT)), 'cache_exists': cache.exists(),
                  'query': public, 'tables': []}
    if cache.exists():
        saved = json.loads(cache.read_text(encoding='utf-8'))
        payload = saved['data']
        checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        assert checksum == saved['sha256']
        records = pd.DataFrame(payload['items'], columns=payload['fields'])
        provenance.update(cache_sha256=sha(cache), checksum_valid=True,
                          retrieved_at=saved['retrieved_at'], response_rows=len(records),
                          matching_code_rows=int(records.ts_code.eq('001323.SZ').sum()))
    for name in ('out_of_sample_2025', 'continuous_2016_2025'):
        path = ROOT / 'data' / name / 'dividend.csv'
        frame = pd.read_csv(path, dtype=str)
        rows = frame.loc[frame.ts_code.eq('001323.SZ') & frame.ex_date.eq('20250609')]
        provenance['tables'].append({'dataset': name, 'file_sha256': sha(path), 'matching_rows': len(rows)})
    (OUT / 'missing_dividend_provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')

    old = ROOT / 'output/continuous_2016_2017_check_prequote_r2'
    new = ROOT / 'output/continuous_2016_2017_check'
    target = old / 'combined/historical_targets.csv'
    codes = set(pd.read_csv(target).ts_code)
    root = ROOT / 'data/continuous_2016_2025'
    pieces = []
    for chunk in pd.read_csv(root / 'daily.csv', chunksize=100000, dtype={'trade_date': str},
                             usecols=['ts_code', 'trade_date', 'open', 'close', 'amount', 'vol']):
        pieces.append(chunk.loc[chunk.ts_code.isin(codes) & chunk.trade_date.le('20171231')])
    bars = pd.concat(pieces, ignore_index=True)
    adj = pd.read_csv(root / 'adj_factor.csv', dtype={'trade_date': str})
    bars = bars.merge(adj, on=['ts_code', 'trade_date'], validate='one_to_one')
    # The only price-factor source correction is August 2018, outside this window.
    invalid = bars.loc[(bars[['open', 'close', 'adj_factor']] <= 0).any(axis=1)
                       | (bars[['amount', 'vol']] < 0).any(axis=1)]
    finite = np.isfinite(bars[['open', 'close', 'adj_factor', 'amount', 'vol']].to_numpy(float)).all()
    a, b = (json.loads((folder / 'frozen_protocol.json').read_text(encoding='utf-8')) for folder in (old, new))
    report = {'status': 'failure_not_reproduced_root_cause_unresolved', 'checked_rows': len(bars),
              'target_codes': len(codes), 'invalid_rows': len(invalid), 'all_finite': bool(finite),
              'target_file_bytes_equal': sha(target) == sha(new / 'combined/historical_targets.csv'),
              'source_differences': [k for k, value in a['source_sha256'].items() if b['source_sha256'][k] != value],
              'data_manifest_equal': a['data_manifest_sha256'] == b['data_manifest_sha256'],
              'metadata_equal': a['metadata_sha256'] == b['metadata_sha256'],
              'missing_evidence': 'The failing process did not save its exact in-memory simulation input; raw-data revalidation cannot prove its runtime state.',
              'input_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [root/'daily.csv', root/'adj_factor.csv', target, old/'combined/failure.txt']}}
    (OUT / 'numeric_guard_forensics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(provenance, ensure_ascii=False))
    print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
