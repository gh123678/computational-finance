"""A rounded earlier disclosure comparison is not API-version identification."""
import csv,json,sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_reader_qualitative_forecasts import OUT,DATA,sha,compact

def main():
    with (OUT/'original_document_check_queue.csv').open(encoding='utf-8-sig',newline='') as f:
        rows=[r for r in csv.DictReader(f) if (r['api'],r['ts_code'],r['ann_date'],r['end_date'])==('fina_indicator','603998.SH','20141204','20140930')]
    assert len(rows)==1
    row=rows[0];raw=DATA/row['raw_path'];assert sha(raw)==row['raw_sha256']
    payload=json.loads(raw.read_text(encoding='utf-8'))['data']
    records=[dict(zip(payload['fields'],v)) for v in payload['items']]
    assert any((r['ts_code'],r['ann_date'],r['end_date'],str(r['update_flag']))==('603998.SH','20141204','20140930',row['update_flag']) and Decimal(str(r['profit_dedt']))==Decimal(row['profit_dedt']) for r in records)
    index=OUT/'remaining_evidence_r1/results/603998.SH_20141114.json'
    access=json.loads(index.read_text(encoding='utf-8'));d=next(d for d in access['documents'] if d['announcement_id']=='1200392005')
    pdf=OUT/'remaining_evidence_r1'/d['file'];assert sha(pdf)==d['sha256']
    with fitz.open(pdf) as doc:
        text=compact(doc[317].get_text());assert '5,918.80' in text and '2014年1-9月' in text and '单位：万元' in text
    original_cny=Decimal('5918.80')*10000
    result=dict(ts_code='603998.SH',api='fina_indicator',ann_date=row['ann_date'],end_date=row['end_date'],row_sha256=row['row_sha256'],raw_path=row['raw_path'],raw_sha256=row['raw_sha256'],field='profit_dedt',api_value_cny=row['profit_dedt'],original_printed_value='5918.80',original_unit='万元',original_normalized_cny=str(original_cny),difference_cny=str(Decimal(row['profit_dedt'])-original_cny),document_current_index_day='20141114',api_minus_document_index_calendar_days=(datetime.strptime(row['ann_date'],'%Y%m%d')-datetime.strptime('20141114','%Y%m%d')).days,pdf_file=str(pdf.relative_to(OUT)),pdf_sha256=d['sha256'],page=318,source_url=d['url'],index_file=str(index.relative_to(OUT)),index_sha256=sha(index),comparison_status='rounded_earlier_disclosure_only_api_version_identity_not_confirmed',usable_in_verified_history=False,source_sha256=sha(Path(__file__)))
    (OUT/'evidence/fangsheng_earlier_disclosure_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(date_gap_days=20,value_difference_cny=result['difference_cny'],historical_approvals=0)))

if __name__=='__main__':main()
