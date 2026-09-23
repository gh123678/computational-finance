"""Frozen development-window market data; no held-out period requests."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import pandas as pd
from .data import ROOT, TushareClient, load_token, DataError
from .audit import table

START, END = '20201001', '20201231'


def main():
    client = TushareClient(load_token())
    out = ROOT / 'data' / 'development_2020q4'
    out.mkdir(parents=True, exist_ok=True)
    cal = table(client.query('trade_cal', {'exchange': 'SSE', 'start_date': '20100101', 'end_date': END}))
    cal.to_csv(out / 'calendar.csv', index=False)
    dates = sorted(cal.loc[cal.is_open.eq(1) & cal.cal_date.between(START, END), 'cal_date'])

    def day(date):
        result = {}
        # Counts in this 2020 window are below the documented endpoint caps.
        # Cross-interface coverage is checked before any strategy is evaluated.
        for api, cap, params in [
            ('daily', 6000, {'trade_date': date}),
            ('adj_factor', 5000, {'trade_date': date}),
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
        if not set(daily.ts_code).issubset(set(adj.ts_code)):
            raise DataError(f'{date}: adjustment coverage incomplete')
        for api in ['daily', 'adj_factor', 'stk_limit']:
            if result[api].duplicated(['trade_date', 'ts_code']).any():
                raise DataError(f'{date}/{api}: duplicate rows')
        return date, result

    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(day, date) for date in dates]
        for f in as_completed(futures):
            date, result = f.result()
            results.append((date, result))
            print(f'{len(results)}/{len(dates)} dates complete: {date}, {len(result["daily"])} daily bars', flush=True)
    results.sort(key=lambda pair: pair[0])
    hashes = {}
    for api in ['daily', 'adj_factor', 'stk_limit', 'suspend_d', 'dividend']:
        frame = pd.concat([r[api] for _, r in results], ignore_index=True)
        path = out / f'{api}.csv'
        frame.to_csv(path, index=False)
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    benchmark = table(client.query('index_daily', {'ts_code': '000300.SH', 'start_date': START, 'end_date': END}))
    benchmark.to_csv(out / 'benchmark.csv', index=False)
    hashes['benchmark.csv'] = hashlib.sha256((out / 'benchmark.csv').read_bytes()).hexdigest()
    hashes['calendar.csv'] = hashlib.sha256((out / 'calendar.csv').read_bytes()).hexdigest()
    manifest = dict(start=START, end=END, sessions=len(dates), files_sha256=hashes,
                    scope='All daily API equities; strategy subsequently filters historical main-board A shares.',
                    corporate_action_query='Dividend records queried by realized ex-date in this window.')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest), flush=True)


if __name__ == '__main__':
    main()
