"""Two bounded new-window read-only queries; preserve all earlier evidence."""
from pathlib import Path
import sys
import json
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from quant_research.data import TushareClient,load_token

OUT=Path('D:/QuantResearchEvidence/alphaforge_000998_crosscheck_20261016_r1/vendor_refresh')


def main():
    if OUT.exists():raise RuntimeError('Existing fresh-query attempt; inspect without repeating')
    OUT.mkdir()
    protocol=dict(ts_code='000998.SZ',start_date='20191227',end_date='20200106')
    record=dict(recorded_at=datetime.now(timezone.utc).isoformat(),queries=[],
        scope='Current vendor response, not an independent source or proof of historical point-in-time identity',
        new_window_not_repetition_of_2018_probes=True,old_data_or_results_modified=False)
    try:
        client=TushareClient(load_token(),cache=OUT/'raw',interval=1.3)
        for api,fields in [('adj_factor','ts_code,trade_date,adj_factor'),
            ('daily','ts_code,trade_date,open,high,low,close,pre_close,vol,amount')]:
            query=dict(api=api,params=protocol,fields=fields)
            try:
                payload=client.query(api,protocol,fields)
                query.update(state='completed',rows=len(payload['items']),data=payload)
            except Exception as error:
                query.update(state='failed',error=str(error))
            record['queries'].append(query)
    finally:
        (OUT/'query_results.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':main()
