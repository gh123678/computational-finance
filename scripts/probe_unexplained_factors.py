"""Isolated API snapshots for eight factor-only anomalies; preserve old inputs."""
import json
from pathlib import Path

import pandas as pd

from quant_research.data import TushareClient, load_token

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/continuous_event_audit_20261005'


def main():
    events = pd.read_csv(OUT / 'events.csv', dtype={'event_date': str, 'prior_quote_date': str})
    events = events.loc[events.reference_gap.abs().lt(1e-12)]
    original = pd.read_csv(ROOT / 'data/continuous_2016_2025/adj_factor.csv', dtype={'trade_date': str})
    client = TushareClient(load_token(), cache=OUT / 'fresh_factor_probe', interval=1.3)
    results = []
    for code, group in events.groupby('ts_code'):
        params = {'ts_code': code,
                  'start_date': group.prior_quote_date.min().replace('-', ''),
                  'end_date': group.event_date.max().replace('-', '')}
        try:
            payload = client.query('adj_factor', params)
            fresh = pd.DataFrame(payload['items'], columns=payload['fields'])
            assert not fresh.duplicated(['ts_code', 'trade_date']).any()
            assert len(fresh) < 7000, 'possible endpoint truncation'
            fresh.adj_factor = pd.to_numeric(fresh.adj_factor)
            for event in group.itertuples(index=False):
                dates = [event.prior_quote_date.replace('-', ''), event.event_date.replace('-', '')]
                old = original.loc[original.ts_code.eq(code) & original.trade_date.isin(dates)].set_index('trade_date')
                new = fresh.loc[fresh.ts_code.eq(code) & fresh.trade_date.isin(dates)].set_index('trade_date')
                assert set(old.index) == set(new.index) == set(dates), 'missing comparison date'
                a, b = (float(new.at[d, 'adj_factor']) for d in dates)
                results.append({'ts_code': code, 'event_date': event.event_date,
                                'status': 'compared', 'query_rows': len(fresh),
                                'old_prior_factor': float(old.at[dates[0], 'adj_factor']),
                                'old_event_factor': float(old.at[dates[1], 'adj_factor']),
                                'new_prior_factor': a, 'new_event_factor': b,
                                'new_relative_change': b / a - 1,
                                'same_as_original': all(float(old.at[d, 'adj_factor']) == float(new.at[d, 'adj_factor']) for d in dates)})
        except Exception as error:
            results.append({'ts_code': code, 'status': 'failed', 'error_type': type(error).__name__})
    (OUT / 'fresh_factor_comparison.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
