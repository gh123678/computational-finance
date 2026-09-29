"""Frozen development-window market data; no held-out period requests."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import argparse
import pandas as pd
from .data import ROOT, TushareClient, load_token, DataError
from .audit import table
from .datasets import DATASETS, dataset_config

def main(dataset='development_2020q4', interval=1.3, workers=5):
    spec = dataset_config(dataset)
    start, end = spec['start'], spec['end']
    client = TushareClient(load_token(), interval=interval)
    out = ROOT / 'data' / dataset
    out.mkdir(parents=True, exist_ok=True)
    cal = table(client.query('trade_cal', {'exchange': 'SSE', 'start_date': '20100101', 'end_date': end}))
    cal.to_csv(out / 'calendar.csv', index=False)
    dates = sorted(cal.loc[cal.is_open.eq(1) & cal.cal_date.between(start, end), 'cal_date'])

    def day(date):
        result = {}
        # Reject possible truncation for every historical session.
        # Cross-interface coverage is checked before any strategy is evaluated.
        for api, cap, params in [
            ('daily', 6000, {'trade_date': date}),
            # 2026-09-29 spot-check: single-date adj_factor returns >5400 rows intact
            # (paged limit/offset cross-check on 20231101 returned an identical code set),
            # so the legacy 5000 endpoint-cap assumption no longer holds for 2024+ sessions.
            ('adj_factor', 7000, {'trade_date': date}),
            ('stk_limit', 5800, {'trade_date': date}),
            ('suspend_d', 5000, {'trade_date': date}),
            ('dividend', 2000, {'ex_date': date}),
        ]:
            frame = table(client.query(api, params))
            if len(frame) >= cap:
                raise DataError(f'{api}/{date}: possible truncation at endpoint cap; partition query required')
            result[api] = frame
        daily, adj = result['daily'], result['adj_factor']
        if daily.empty or adj.empty:
            raise DataError(f'{date}: empty market response')
        if result['stk_limit'].empty:
            raise DataError(f'{date}: empty price-limit response; execution coverage unavailable')
        if not set(daily.ts_code).issubset(set(adj.ts_code)):
            raise DataError(f'{date}: adjustment coverage incomplete')
        for api in ['daily', 'adj_factor', 'stk_limit']:
            if result[api].duplicated(['trade_date', 'ts_code']).any():
                raise DataError(f'{date}/{api}: duplicate rows')
        return date, result

    results, failures = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(day, date): date for date in dates}
        for f in as_completed(futures):
            try:
                date, result = f.result()
            except DataError as exc:
                failures.append(dict(date=futures[f], error=str(exc)))
                print(f'{futures[f]} failed: {exc}; other dates continue and remain cached', flush=True)
                continue
            results.append((date, result))
            print(f'{len(results)}/{len(dates)} dates complete: {date}, {len(result["daily"])} daily bars', flush=True)
    if failures:
        (out / 'download_failures.json').write_text(json.dumps(failures, indent=2), encoding='utf-8')
        raise DataError(f'{len(failures)} dates failed; rerun to resume cached downloads. See download_failures.json')
    results.sort(key=lambda pair: pair[0])
    hashes = {}
    for api in ['daily', 'adj_factor', 'stk_limit', 'suspend_d', 'dividend']:
        frame = pd.concat([r[api] for _, r in results], ignore_index=True)
        path = out / f'{api}.csv'
        frame.to_csv(path, index=False)
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    benchmark = table(client.query('index_daily', {'ts_code': '000300.SH', 'start_date': start, 'end_date': end}))
    benchmark.to_csv(out / 'benchmark.csv', index=False)
    hashes['benchmark.csv'] = hashlib.sha256((out / 'benchmark.csv').read_bytes()).hexdigest()
    hashes['calendar.csv'] = hashlib.sha256((out / 'calendar.csv').read_bytes()).hexdigest()
    manifest = dict(**spec, dataset=dataset, sessions=len(dates), files_sha256=hashes,
                    scope='All daily API equities; strategy subsequently filters historical main-board A shares.',
                    corporate_action_query='Dividend records queried by realized ex-date in this window.')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', choices=DATASETS, default='development_2020q4')
    parser.add_argument('--interval', type=float, default=1.3, help='Seconds between API starts; obey account limits')
    parser.add_argument('--workers', type=int, choices=range(1, 13), default=5)
    args = parser.parse_args()
    if args.interval < .4:
        parser.error('This downloader requires at least 0.4 seconds between requests')
    main(args.dataset, args.interval, args.workers)
