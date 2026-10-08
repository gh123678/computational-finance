"""Independently reconstruct cash and shares from saved transaction/event logs."""
from collections import defaultdict
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/continuous_2016_2025'


def value(row, key):
    item = row.get(key, 0)
    return 0 if pd.isna(item) else item


def main():
    summary = json.loads((OUT / 'summary.json').read_text(encoding='utf-8'))
    checks, boundaries = [], []
    allowed = {'ex', 'cash_settlement', 'stock_settlement', 'rights_subscribed',
               'rights_not_subscribed', 'delisting_zero_recovery'}
    for experiment in summary['experiments']:
        label = experiment['strategy']
        folder = OUT / label
        nav = pd.read_csv(folder / 'nav.csv', parse_dates=['date'])
        orders = pd.read_csv(folder / 'orders.csv', parse_dates=['date'])
        events = pd.read_csv(folder / 'corporate_events.csv', parse_dates=['date'])
        holdings = pd.read_csv(folder / 'holdings.csv', parse_dates=['date'])
        assert not holdings.duplicated(['date', 'ts_code']).any()
        assert set(events.event).issubset(allowed)
        event_days = {d: g.to_dict('records') for d, g in events.groupby('date')}
        trade_days = {d: g.to_dict('records') for d, g in orders.groupby('date')}
        holding_days = {d: g for d, g in holdings.groupby('date')}
        cash, receivable = 1000000., 0.
        shares, pending = defaultdict(int), defaultdict(int)
        max_cash_error = max_receivable_error = 0.
        previous = None
        for day in nav.to_dict('records'):
            date = day['date']
            for row in event_days.get(date, []):
                code, event = row['code'], row['event']
                if event == 'ex':
                    receivable += value(row, 'gross_cash') - value(row, 'assumed_tax')
                    pending[code] += int(value(row, 'bonus_shares'))
                elif event == 'cash_settlement':
                    amount = value(row, 'cash')
                    cash += amount
                    receivable -= amount
                elif event == 'stock_settlement':
                    amount = int(value(row, 'shares'))
                    shares[code] += amount
                    pending[code] -= amount
                elif event == 'rights_subscribed':
                    cash -= value(row, 'cost')
                    pending[code] += int(value(row, 'allotted_shares'))
                elif event == 'delisting_zero_recovery':
                    assert shares[code] + pending[code] == int(value(row, 'shares'))
                    shares[code] = pending[code] = 0
            for row in trade_days.get(date, []):
                amount = int(row['shares'])
                sign = 1 if row['side'] == 'buy' else -1
                assert row['side'] in ('buy', 'sell')
                shares[row['ts_code']] += sign * amount
                # A rejected order has zero quantity and may have no executable price.
                notional = amount * row['price'] if amount else 0.
                cash -= sign * notional + row['fee']
            cash_error = abs(cash - day['cash'])
            receivable_error = abs(receivable - day['receivable'])
            assert cash_error < 1e-6, (label, date, 'cash', cash_error)
            assert receivable_error < 1e-6, (label, date, 'receivable', receivable_error)
            max_cash_error = max(max_cash_error, cash_error)
            max_receivable_error = max(max_receivable_error, receivable_error)
            observed = holding_days.get(date)
            expected = {code: (shares[code], pending[code]) for code in set(shares) | set(pending)
                        if shares[code] or pending[code]}
            actual = {} if observed is None else {r.ts_code: (int(r.shares), int(r.pending_shares))
                                                   for r in observed.itertuples(index=False)}
            assert expected == actual, (label, date, 'shares')
            if previous is not None and previous['date'].year != date.year and previous['date'].year >= 2016:
                boundaries.append({'strategy': label, 'prior_date': previous['date'].strftime('%Y-%m-%d'),
                                   'next_date': date.strftime('%Y-%m-%d'),
                                   'prior_cash': previous['cash'], 'next_cash': day['cash'],
                                   'prior_equity': previous['equity'], 'next_equity': day['equity'],
                                   'prior_receivable': previous['receivable'], 'prior_bonus_value': previous['bonus_value'],
                                   'prior_position_count': previous['position_count'],
                                   'next_position_count': day['position_count'],
                                   'cash_reconstruction_error': cash_error,
                                   'share_reconstruction_exact': True})
            previous = day
        checks.append({'strategy': label, 'sessions': len(nav),
                       'maximum_cash_error': max_cash_error,
                       'maximum_receivable_error': max_receivable_error,
                       'shares_and_pending_exact_every_session': True})
    assert len(checks) == 12 and len(boundaries) == 108
    pd.DataFrame(boundaries).to_csv(OUT / 'year_boundary_audit.csv', index=False)
    result = {'status': 'passed', 'checks': checks, 'year_boundaries': len(boundaries),
              'summary_sha256': hashlib.sha256((OUT / 'summary.json').read_bytes()).hexdigest(),
              'boundaries_with_pending_value': sum(bool(r['prior_receivable'] or r['prior_bonus_value']) for r in boundaries)}
    (OUT / 'flow_reconstruction_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--revision',action='store_true')
    if parser.parse_args().revision:
        OUT=ROOT/'output/continuous_2016_2025_dividend_r1'
    main()
