"""Read-only evidence inventory; never modify inputs or release quarantines."""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/continuous_event_audit_20261005'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    run = ROOT / 'output/continuous_2016_2025'
    issues = pd.read_csv(run / 'unexplained_adjustments.csv', parse_dates=['trade_date', 'prior_date'])
    selected = []
    for chunk in pd.read_csv(ROOT / 'data/continuous_2016_2025/daily.csv', chunksize=250000,
                             usecols=['ts_code', 'trade_date', 'open', 'close', 'pre_close'],
                             dtype={'trade_date': str}):
        selected.append(chunk.loc[chunk.ts_code.isin(issues.ts_code)])
    daily = pd.concat(selected, ignore_index=True)
    daily.trade_date = pd.to_datetime(daily.trade_date)
    summary = json.loads((run / 'summary.json').read_text(encoding='utf-8'))
    holdings = {e['strategy']: pd.read_csv(run / e['strategy'] / 'holdings.csv', parse_dates=['date'])
                for e in summary['experiments']}
    account_dates = pd.read_csv(run / summary['experiments'][0]['strategy'] / 'nav.csv',
                                usecols=['date'], parse_dates=['date']).date
    rows = []
    for issue in issues.itertuples(index=False):
        quotes = daily.loc[daily.ts_code.eq(issue.ts_code)].sort_values('trade_date')
        before = quotes.loc[quotes.trade_date.eq(issue.prior_date)].iloc[0]
        after = quotes.loc[quotes.trade_date.eq(issue.trade_date)].iloc[0]
        # Each ledger has every session: inspect last account date strictly before the event.
        held = []
        for label, frame in holdings.items():
            last_date = account_dates.loc[account_dates.lt(issue.trade_date)].max()
            own = frame.loc[frame.date.eq(last_date) & frame.ts_code.eq(issue.ts_code)]
            if not own.empty and (own.shares.sum() > 0 or own.pending_shares.sum() > 0):
                held.append(label)
        rows.append({'ts_code': issue.ts_code, 'event_date': issue.trade_date.strftime('%Y-%m-%d'),
                     'prior_quote_date': issue.prior_date.strftime('%Y-%m-%d'),
                     'factor_change': issue.relative_change,
                     'reference_gap': after.pre_close / before.close - 1,
                     'held_in_previous_account_session': '|'.join(held),
                     'held_experiments': len(held),
                     'status': 'quarantine_retained_pending_evidence'})
    pd.DataFrame(rows).to_csv(OUT / 'events.csv', index=False)
    fingerprints = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [run / 'summary.json', run / 'unexplained_adjustments.csv']}
    (OUT / 'input_sha256.json').write_text(json.dumps(fingerprints, indent=2), encoding='utf-8')
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == '__main__':
    main()
