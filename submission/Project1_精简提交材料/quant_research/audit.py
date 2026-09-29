"""Audit historical universe inputs without opening the held-out price test set."""
import json
from pathlib import Path
import pandas as pd
from .data import ROOT, DataError, TushareClient, load_token


def table(result):
    return pd.DataFrame(result['items'], columns=result['fields'])


def main():
    client = TushareClient(load_token())
    out = ROOT / 'data' / 'audit'
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for status in ['L', 'D', 'P']:
        for exchange in ['SSE', 'SZSE']:
            frame = table(client.paged('stock_basic', {'exchange': exchange, 'list_status': status},
                                      'ts_code,name,market,list_date,delist_date,list_status,exchange'))
            frames.append(frame)
            print(f'Universe {exchange}/{status}: {len(frame)}', flush=True)
    universe = pd.concat(frames, ignore_index=True).drop_duplicates('ts_code')
    universe = universe.loc[universe.market.eq('\u4e3b\u677f') & universe.ts_code.str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ)$')].copy()
    universe.to_csv(out / 'universe.csv', index=False)
    names = table(client.paged('namechange', {}, page_size=1000))
    names.to_csv(out / 'name_history.csv', index=False)
    print(f'Name history rows: {len(names)}', flush=True)
    industries = []
    for is_new in ['Y', 'N']:
        frame = table(client.paged('index_member_all', {'is_new': is_new}, page_size=1000))
        industries.append(frame)
        print(f'Industry {is_new}: {len(frame)}', flush=True)
    industry = pd.concat(industries, ignore_index=True).drop_duplicates()
    industry.to_csv(out / 'industry_history.csv', index=False)
    results = []
    for date in ['20161230', '20180102', '20180629', '20181228', '20201231', '20231229']:
        listed = universe.loc[(universe.list_date <= date) & (universe.delist_date.isna() | (universe.delist_date > date))]
        valid_names = names.loc[(names.start_date <= date) & (names.end_date.isna() | (names.end_date >= date))]
        # Missing announcement timestamps are explicitly counted, not silently treated as known.
        known_names = valid_names.loc[valid_names.ann_date.notna() & (valid_names.ann_date <= date)]
        active_industry = industry.loc[(industry.in_date <= date) & (industry.out_date.isna() | (industry.out_date > date))]
        active_industry = active_industry.loc[active_industry.ts_code.isin(listed.ts_code)]
        counts = active_industry.groupby('ts_code').l1_code.nunique()
        row = {'date': date, 'listed_mainboard': len(listed),
               'name_interval_covered': int(listed.ts_code.isin(valid_names.ts_code).sum()),
               'name_with_announcement': int(listed.ts_code.isin(known_names.ts_code).sum()),
               'industry_interval_covered': int(listed.ts_code.isin(active_industry.ts_code).sum()),
               'industry_conflicts': int((counts > 1).sum())}
        results.append(row)
        print(json.dumps(row), flush=True)
    report = {'coverage': results,
              'limits': ['Industry intervals are retrospective provider records; publication/vintage not verified.',
                         'Name records with missing announcement dates need independent verification.',
                         'Coverage samples do not prove full history completeness.']}
    (ROOT / 'output' / 'history_audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
