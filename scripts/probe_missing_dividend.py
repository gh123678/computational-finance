"""Two isolated read-only API checks; never overwrite original research caches."""
import json
from pathlib import Path

import pandas as pd

from quant_research.data import TushareClient, load_token

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/continuous_event_audit_20261005'


def main():
    client = TushareClient(load_token(), cache=OUT / 'fresh_dividend_probe', interval=1.3)
    results = []
    for params in ({'ex_date': '20250609'}, {'ts_code': '001323.SZ'}):
        try:
            response = client.query('dividend', params)
            frame = pd.DataFrame(response['items'], columns=response['fields'])
            matching = frame.loc[frame.ts_code.eq('001323.SZ') & frame.ex_date.eq('20250609')]
            results.append({'params': params, 'status': 'completed', 'rows': len(frame),
                            'matching_records': matching.to_dict('records')})
        except Exception as error:
            # The client redacts its token in API errors; do not expose arbitrary error text.
            results.append({'params': params, 'status': 'failed', 'error_type': type(error).__name__})
    (OUT / 'fresh_dividend_probe.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
