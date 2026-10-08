"""Compare preserved first run with an independently executed frozen run."""
import hashlib
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIRST = ROOT / 'output/continuous_2016_2025_first_complete'
SECOND = ROOT / 'output/continuous_2016_2025'


def main(revision=False):
    report = {'absolute_tolerance': 1e-6, 'relative_tolerance': 0,
              'first': str(FIRST), 'second': str(SECOND), 'checks': []}
    a = json.loads((FIRST / 'summary.json').read_text(encoding='utf-8'))
    b = json.loads((SECOND / 'summary.json').read_text(encoding='utf-8'))
    assert len(a['experiments']) == len(b['experiments']) == 12
    for key in ('source_sha256', 'metadata_sha256'):
        assert a[key] == b[key], key
    if revision:
        left_manifest=json.loads(json.dumps(a['data_manifest']))
        right_manifest=json.loads(json.dumps(b['data_manifest']))
        assert left_manifest['row_counts']['dividend']==23295
        assert right_manifest['row_counts']['dividend']==23296
        left_manifest['row_counts']['dividend']=23296
        assert left_manifest==right_manifest, 'Unexpected input change'
        x,y=(json.loads((folder/'frozen_protocol.json').read_text(encoding='utf-8')) for folder in (FIRST,SECOND))
        assert x['data_manifest_sha256']!=y['data_manifest_sha256']
        x.pop('data_manifest_sha256');y.pop('data_manifest_sha256')
        assert x==y
        report['scope']='Same CSV inputs and code; only dividend row-count metadata corrected'
    else:
        assert a['data_manifest']==b['data_manifest']
        assert (FIRST / 'frozen_protocol.json').read_bytes() == (SECOND / 'frozen_protocol.json').read_bytes()
    for experiment in a['experiments']:
        label = experiment['strategy']
        for filename in ('historical_targets.csv', 'orders.csv', 'holdings.csv',
                         'nav.csv', 'corporate_events.csv', 'monthly_returns.csv',
                         'cost_attribution.csv'):
            left, right = FIRST / label / filename, SECOND / label / filename
            x, y = pd.read_csv(left), pd.read_csv(right)
            # Holdings are serialized from a set; align by their unique economic key.
            if filename == 'holdings.csv':
                for frame in (x, y):
                    assert not frame.duplicated(['date', 'ts_code']).any()
                x = x.sort_values(['date', 'ts_code']).reset_index(drop=True)
                y = y.sort_values(['date', 'ts_code']).reset_index(drop=True)
            assert list(x.columns) == list(y.columns), (label, filename, 'columns')
            assert x.shape == y.shape, (label, filename, 'shape')
            diffs = {}
            for col in x:
                if pd.api.types.is_numeric_dtype(x[col]) and pd.api.types.is_numeric_dtype(y[col]):
                    np.testing.assert_allclose(x[col], y[col], rtol=0, atol=1e-6, equal_nan=True,
                                               err_msg=f'{label}/{filename}/{col}')
                    delta = (x[col].astype(float) - y[col].astype(float)).abs().max()
                    diffs[col] = 0.0 if pd.isna(delta) else float(delta)
                else:
                    pd.testing.assert_series_equal(x[col], y[col], check_names=True,
                                                   obj=f'{label}/{filename}/{col}')
            report['checks'].append({'strategy': label, 'file': filename, 'rows': len(x),
                                     'byte_equal': left.read_bytes() == right.read_bytes(),
                                     'maximum_absolute_difference': max(diffs.values(), default=0),
                                     'numeric_differences': diffs})
    report['summary_sha256'] = hashlib.sha256((SECOND / 'summary.json').read_bytes()).hexdigest()
    report['status'] = 'passed'
    report['maximum_absolute_difference'] = max(c['maximum_absolute_difference'] for c in report['checks'])
    (SECOND / 'reproduction_comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'maximum_absolute_difference')}, ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--revision',action='store_true')
    args=parser.parse_args()
    if args.revision:
        FIRST=ROOT/'output/continuous_2016_2025_dividend_r1_initial_metadata'
        SECOND=ROOT/'output/continuous_2016_2025_dividend_r1'
    main(args.revision)
