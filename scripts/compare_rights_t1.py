"""Compare saved annual ledgers before and after the rights listing-day lock."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATASETS = [*(f'development_{y}' for y in range(2016, 2021)),
            'out_of_sample_2024', 'out_of_sample_2025']


def main():
    baseline = ROOT / 'output' / 'before_rights_t1_20261003'
    rows = []
    for dataset in DATASETS:
        old_folder = baseline / dataset
        new_folder = ROOT / 'output' / dataset
        old = json.loads((old_folder / 'summary.json').read_text(encoding='utf-8'))
        new = json.loads((new_folder / 'summary.json').read_text(encoding='utf-8'))
        old_experiments = {x['strategy']: x for x in old['experiments']}
        for experiment in new['experiments']:
            strategy = experiment['strategy']
            before = old_experiments[strategy]
            row = dict(dataset=dataset, strategy=strategy,
                       old_return=before['total_return'], new_return=experiment['total_return'],
                       return_change=experiment['total_return'] - before['total_return'])
            for name in ['nav', 'orders', 'holdings', 'corporate_events']:
                old_path = old_folder / strategy / f'{name}.csv'
                new_path = new_folder / strategy / f'{name}.csv'
                row[f'{name}_bytes_unchanged'] = old_path.read_bytes() == new_path.read_bytes()
                try:
                    before_table = pd.read_csv(old_path)
                    after_table = pd.read_csv(new_path)
                except pd.errors.EmptyDataError:
                    row[f'{name}_equivalent'] = row[f'{name}_bytes_unchanged']
                    continue
                # Holdings are emitted from a set of codes; CSV row order is
                # not economic information. Compare by natural record keys.
                keys = {'nav': ['date'], 'orders': ['date', 'ts_code', 'side'],
                        'holdings': ['date', 'ts_code'],
                        'corporate_events': ['date', 'code', 'event']}[name]
                before_table = before_table.sort_values(keys).reset_index(drop=True)
                after_table = after_table.sort_values(keys).reset_index(drop=True)
                try:
                    pd.testing.assert_frame_equal(before_table, after_table,
                                                  check_exact=False, rtol=1e-12, atol=1e-8)
                    row[f'{name}_equivalent'] = True
                except AssertionError:
                    row[f'{name}_equivalent'] = False
            rows.append(row)
    frame = pd.DataFrame(rows)
    destination = ROOT / 'output' / 'rights_t1_audit_20261003'
    destination.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination / 'before_after.csv', index=False)
    result = dict(experiments=len(frame), maximum_absolute_return_change=float(frame.return_change.abs().max()),
                  nonequivalent_ledger_files={name: int((~frame[f'{name}_equivalent']).sum())
                                             for name in ['nav', 'orders', 'holdings', 'corporate_events']},
                  serialized_file_changes={name: int((~frame[f'{name}_bytes_unchanged']).sum())
                                        for name in ['nav', 'orders', 'holdings', 'corporate_events']},
                  limitation='Zero historical impact does not replace listing-day liquidation regression tests.')
    (destination / 'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
