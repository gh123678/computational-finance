"""Read-only inventory of unresolved validation events; never clear quarantine."""
import hashlib
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/validation_event_audit_20261004'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, snapshots, sources = [], [], {}
    for year in (2021, 2022, 2023):
        dataset = f'validation_{year}'
        folder = ROOT / 'output' / dataset
        issue_path = folder / 'unexplained_adjustments.csv'
        issues = pd.read_csv(issue_path, parse_dates=['trade_date', 'prior_date'])
        codes = set(issues.ts_code)
        root = ROOT / 'data' / dataset
        daily = pd.read_csv(root / 'daily.csv', usecols=['ts_code', 'trade_date', 'open', 'close', 'pre_close', 'vol'],
                            dtype={'trade_date': str})
        daily = daily.loc[daily.ts_code.isin(codes)].copy()
        adj = pd.read_csv(root / 'adj_factor.csv', dtype={'trade_date': str})
        daily = daily.merge(adj, on=['ts_code', 'trade_date'], validate='one_to_one')
        daily.trade_date = pd.to_datetime(daily.trade_date)
        provenance = [issue_path, root / 'daily.csv', root / 'adj_factor.csv', folder / 'summary.json']
        holdings = {}
        summary = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
        for exp in summary['experiments']:
            path = folder / exp['strategy'] / 'holdings.csv'
            h = pd.read_csv(path, parse_dates=['date'])
            holdings[exp['strategy']] = h
            provenance.append(path)
        sources.update({str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in provenance})
        for issue in issues.itertuples(index=False):
            frame = daily.loc[daily.ts_code.eq(issue.ts_code)].sort_values('trade_date')
            index = frame.index[frame.trade_date.eq(issue.trade_date)]
            assert len(index) == 1
            pos = frame.index.get_loc(index[0])
            before = frame.iloc[pos - 1]
            after = frame.iloc[pos]
            held = []
            for label, h in holdings.items():
                matched = h.loc[h.ts_code.eq(issue.ts_code) & h.date.eq(issue.prior_date)]
                if not matched.empty and (matched.shares.gt(0) | matched.pending_shares.gt(0)).any():
                    held.append(label)
            rows.append(dict(dataset=dataset, ts_code=issue.ts_code,
                             trade_date=issue.trade_date.strftime('%Y-%m-%d'),
                             prior_date=issue.prior_date.strftime('%Y-%m-%d'),
                             relative_change=issue.relative_change,
                             previous_close=float(before.close), event_pre_close=float(after.pre_close),
                             reference_price_gap=float(after.pre_close / before.close - 1),
                             previous_factor=float(before.adj_factor), event_factor=float(after.adj_factor),
                             held_before_event=','.join(held), status='unresolved_in_frozen_run'))
            for record in frame.iloc[max(0, pos-3):pos+6].to_dict('records'):
                record.update(dataset=dataset, event_date=issue.trade_date.strftime('%Y-%m-%d'))
                snapshots.append(record)
    observations = pd.DataFrame(rows)
    unique = observations.groupby(['ts_code', 'trade_date'], as_index=False).agg(
        datasets=('dataset', lambda x: ','.join(x)), observations=('dataset', 'size'),
        relative_change=('relative_change', 'first'), reference_price_gap=('reference_price_gap', 'first'),
        held_before_event=('held_before_event', lambda x: ','.join(sorted(set(filter(None, x))))))
    observations.to_csv(OUT / 'observations.csv', index=False)
    unique.to_csv(OUT / 'unique_events.csv', index=False)
    pd.DataFrame(snapshots).to_csv(OUT / 'nearby_quotes.csv', index=False)
    (OUT / 'input_sha256.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')
    print(unique.to_string(index=False))
    print('observations', len(observations), 'unique', len(unique),
          'held events', observations.held_before_event.ne('').sum())


if __name__ == '__main__':
    main()
