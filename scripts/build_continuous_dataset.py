"""Stitch validated cached windows; reject every inconsistent overlap."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NAMES = [*[f'development_{y}' for y in range(2016, 2021)],
         *[f'validation_{y}' for y in range(2021, 2024)],
         'out_of_sample_2024', 'out_of_sample_2025']
OUT = ROOT / 'data/continuous_2016_2025'
APIS = ['daily', 'adj_factor', 'stk_limit', 'suspend_d', 'dividend', 'benchmark', 'calendar']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected(name, api, lo, hi):
    pieces = []
    field = 'ex_date' if api == 'dividend' else 'cal_date' if api == 'calendar' else 'trade_date'
    for chunk in pd.read_csv(ROOT / 'data' / name / (api + '.csv'), dtype=str, chunksize=100000):
        mask = chunk[field].fillna('').between(lo, hi)
        if api not in ('calendar', 'benchmark'):
            mask &= chunk.ts_code.str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ)$').fillna(False)
        pieces.append(chunk.loc[mask].fillna(''))
    if not pieces:
        return pd.read_csv(ROOT / 'data' / name / (api + '.csv'), dtype=str, nrows=0)
    return pd.concat(pieces, ignore_index=True)


def compare_overlap(left, right, api):
    if set(left.columns) != set(right.columns):
        raise ValueError('Column mismatch')
    columns = sorted(left.columns)
    a = Counter(left[columns].itertuples(index=False, name=None))
    b = Counter(right[columns].itertuples(index=False, name=None))
    if a != b:
        return dict(left_only=list((a-b).items())[:5], right_only=list((b-a).items())[:5],
                    left_only_rows=sum((a-b).values()), right_only_rows=sum((b-a).values()), columns=columns)
    if api not in ('dividend', 'suspend_d'):
        keys = ['exchange', 'cal_date'] if api == 'calendar' else ['ts_code', 'trade_date']
        if left.duplicated(keys).any() or right.duplicated(keys).any():
            raise ValueError('Duplicate primary keys')
    return None


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT / 'manifest.json').exists():
        raise ValueError('Completed continuous dataset already exists; preserve its provenance')
    manifests, inputs = {}, {}
    for name in NAMES:
        m = json.loads((ROOT / 'data' / name / 'manifest.json').read_text(encoding='utf-8'))
        manifests[name] = m
        for file, expected in m['files_sha256'].items():
            path = ROOT / 'data' / name / file
            assert digest(path) == expected, (name, file)
            inputs[str(path.relative_to(ROOT))] = expected
    checks, counts = [], {}
    for api in APIS:
        print('Checking overlaps:', api, flush=True)
        for left, right in zip(NAMES, NAMES[1:]):
            lo, hi = manifests[right]['start'], manifests[left]['end']
            a, b = selected(left, api, lo, hi), selected(right, api, lo, hi)
            conflict = compare_overlap(a, b, api)
            row = dict(api=api, left=left, right=right, start=lo, end=hi,
                       left_rows=len(a), right_rows=len(b), conflict=conflict)
            checks.append(row)
            if conflict:
                (OUT / 'stitch_failure.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
                raise ValueError(f'Conflicting overlap: {api}, {left}, {right}')
        destination = OUT / (api + '.csv.partial')
        if api == 'calendar':
            # Complete history remains available for listing-age calculations.
            frame = selected(NAMES[-1], api, '20100101', '20251231')
            frame.to_csv(destination, index=False)
            counts[api] = len(frame)
        else:
            total = 0
            header = True
            for index, name in enumerate(NAMES):
                year = name[-4:]
                lo = '20151101' if index == 0 else year + '0101'
                hi = year + '1231'
                frame = selected(name, api, lo, hi)
                if api in ('suspend_d', 'dividend'):
                    frame = frame.drop_duplicates()
                frame.to_csv(destination, index=False, mode='w' if header else 'a', header=header)
                header = False
                total += len(frame)
            counts[api] = total
        print(api, counts[api], 'rows staged', flush=True)
    for api in APIS:
        (OUT / (api + '.csv.partial')).replace(OUT / (api + '.csv'))
    manifest = dict(start='20151101', end='20251231', evaluation_start='20160101',
                    title='2016–2025 连续账户固定规则研究', dataset='continuous_2016_2025',
                    source_datasets=NAMES, input_sha256=inputs, row_counts=counts,
                    files_sha256={api+'.csv': digest(OUT / (api+'.csv')) for api in APIS},
                    scope='Main-board cached observations; overlap equality checked before stitching; one continuous account')
    (OUT / 'overlap_checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Continuous dataset committed; all overlaps consistent.', flush=True)


if __name__ == '__main__':
    main()
