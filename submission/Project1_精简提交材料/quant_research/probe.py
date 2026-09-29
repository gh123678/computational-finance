"""Small account permission probes. No backtest and no performance claims."""
import json
from datetime import datetime, timezone
from .data import ROOT, DataError, TushareClient, load_token


PROBES = [
    ('calendar', 'trade_cal', {'exchange': 'SSE', 'start_date': '20231201', 'end_date': '20231229'}),
    ('listed', 'stock_basic', {'exchange': 'SSE', 'list_status': 'L', 'limit': 10}),
    ('delisted', 'stock_basic', {'exchange': 'SSE', 'list_status': 'D', 'limit': 10}),
    ('daily', 'daily', {'ts_code': '600000.SH', 'start_date': '20231201', 'end_date': '20231229'}),
    ('adjustment', 'adj_factor', {'ts_code': '600000.SH', 'start_date': '20231201', 'end_date': '20231229'}),
    ('limits', 'stk_limit', {'ts_code': '600000.SH', 'trade_date': '20231229'}),
    ('suspension', 'suspend_d', {'trade_date': '20231229'}),
    ('name_history', 'namechange', {'ts_code': '600000.SH'}),
    ('st_history', 'stock_st', {'trade_date': '20231229'}),
    ('industry_history', 'index_member_all', {'ts_code': '600000.SH', 'is_new': 'N'}),
    ('dividends', 'dividend', {'ts_code': '600000.SH'}),
    ('benchmark', 'index_daily', {'ts_code': '000300.SH', 'start_date': '20231201', 'end_date': '20231229'}),
]


def main():
    client = TushareClient(load_token())
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': [],
              'meaning': 'Nonempty small responses confirm access, not historical coverage.'}
    for name, api, params in PROBES:
        try:
            result = client.query(api, params, refresh=True)
            n = len(result['items'])
            check = dict(name=name, api=api, params=params, status='ok' if n else 'empty',
                         rows=n, fields=result['fields'])
        except DataError as exc:
            check = dict(name=name, api=api, params=params, status='error', error=str(exc))
        report['checks'].append(check)
        print(json.dumps(check, ensure_ascii=True), flush=True)
        out = ROOT / 'output' / 'data_probe.json'
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return int(any(c['status'] == 'error' for c in report['checks']))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except DataError as exc:
        print(str(exc))
        raise SystemExit(2)
