"""Reproduce fixed original checks, retaining profit-definition uncertainty."""
import csv,json,sys
from decimal import Decimal
from pathlib import Path
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_reader_qualitative_forecasts import OUT,DATA,sha,compact

def main():
    with (OUT/'original_document_check_queue.csv').open(encoding='utf-8-sig',newline='') as f:queue=list(csv.DictReader(f))
    cases=[('forecast','20200518','20200630','1207821155',21,{'p_change_min':('-27.36','%'),'p_change_max':('-17.36','%'),'net_profit_min':('6725.83','万元'),'net_profit_max':('7651.76','万元')}),('fina_indicator','20201030','20200930','1208651962',3,{'profit_dedt':('95123385.95','元')})]
    checks=[]
    for api,ann,end,identifier,page,fields in cases:
        rows=[r for r in queue if (r['api'],r['ts_code'],r['ann_date'],r['end_date'])==(api,'605288.SH',ann,end)]
        assert len(rows)==1
        row=rows[0];raw_file=DATA/row['raw_path'];assert sha(raw_file)==row['raw_sha256']
        payload=json.loads(raw_file.read_text(encoding='utf-8'))['data']
        records=[dict(zip(payload['fields'],values)) for values in payload['items']]
        matching=[r for r in records if (r['ts_code'],r['ann_date'],r['end_date'],str(r['update_flag']))==('605288.SH',ann,end,row['update_flag'])]
        assert len(matching)==1
        access=json.loads((OUT/f'remaining_evidence_r1/results/605288.SH_{ann}.json').read_text(encoding='utf-8'))
        document=next(d for d in access['documents'] if d['announcement_id']==identifier)
        pdf=OUT/'remaining_evidence_r1'/document['file'];assert sha(pdf)==document['sha256']
        with fitz.open(pdf) as doc:
            text=compact(doc[page-1].get_text());assert '扣除非经常性损益' in text
            if api=='forecast':
                assert '6,725.83' in text and '7,651.76' in text
                assert '亦不代表公司所做的盈利预测' in compact(doc[445].get_text())
            else:assert '95,123,385.95' in text and '单位：元' in text
        for field,(value,unit) in fields.items():
            assert Decimal(str(matching[0][field]))==Decimal(row[field])
            difference=Decimal(row[field])-Decimal(value)
            checks.append(dict(ts_code='605288.SH',api=api,ann_date=ann,end_date=end,row_sha256=row['row_sha256'],raw_path=row['raw_path'],raw_sha256=row['raw_sha256'],field=field,api_value=row[field],original_value=value,unit=unit,difference=str(difference),original_profit_definition='扣非归母净利润',api_forecast_metric_definition_status='not_independently_verified' if api=='forecast' else 'deducted_profit_label_matches',last_parent_net_status='not_checked_not_assumed_comparable',pdf_file=document['file'],pdf_sha256=document['sha256'],page=page,source_url=document['url'],usable_in_verified_history=False))
    (OUT/'evidence/kaidi_original_field_checks.json').write_text(json.dumps(dict(checks=checks,source_sha256=sha(Path(__file__)),verified_original_version_rows=0),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(fields=5,matches=3,differences=2,historical_approvals=0)))

if __name__=='__main__':main()
