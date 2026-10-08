"""Verify inspected fixed forecasts; API empty text is not no-risk evidence."""
import csv,json,sys
from decimal import Decimal
from pathlib import Path
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_reader_qualitative_forecasts import OUT,DATA,sha,compact

def main():
    with (OUT/'original_document_check_queue.csv').open(encoding='utf-8-sig',newline='') as f:queue=list(csv.DictReader(f))
    checks=[];qualitative=[]
    for ann,end,identifier,page in [('20171221','20171231','1204243589',1),('20160826','20160930','1202621221',19)]:
        rows=[r for r in queue if (r['api'],r['ts_code'],r['ann_date'],r['end_date'])==('forecast','603996.SH',ann,end)]
        assert len(rows)==1
        row=rows[0];raw_file=DATA/row['raw_path'];assert sha(raw_file)==row['raw_sha256']
        data=json.loads(raw_file.read_text(encoding='utf-8'))['data']
        records=[dict(zip(data['fields'],values)) for values in data['items']]
        raw=[r for r in records if (r['ts_code'],r['ann_date'],r['end_date'],str(r['update_flag']))==('603996.SH',ann,end,row['update_flag'])]
        assert len(raw)==1
        access=json.loads((OUT/f'remaining_evidence_r2_fixed_r1/results/603996.SH_{ann}.json').read_text(encoding='utf-8'))
        d=next(d for d in access['documents'] if d['announcement_id']==identifier)
        pdf=OUT/'remaining_evidence_r2_fixed_r1'/d['file'];assert sha(pdf)==d['sha256']
        with fitz.open(pdf) as doc:text=compact(doc[page-1].get_text())
        base=dict(ts_code='603996.SH',api='forecast',ann_date=ann,end_date=end,row_sha256=row['row_sha256'],raw_path=row['raw_path'],raw_sha256=row['raw_sha256'],pdf_file=str(pdf.relative_to(OUT)),pdf_sha256=d['sha256'],source_url=d['url'],page=page,usable_in_verified_history=False)
        if ann=='20171221':
            assert '中新科技集团股份有限公司' in text and '增长20%到50%' in text and '11761.84万元' in text
            assert compact(row['change_reason']) in text
            for field,value,unit in [('p_change_min','20','%'),('p_change_max','50','%'),('last_parent_net','11761.84','万元')]:
                assert Decimal(str(raw[0][field]))==Decimal(row[field])
                checks.append(dict(**base,field=field,api_value=row[field],original_value=value,unit=unit,difference=str(Decimal(row[field])-Decimal(value))))
        else:
            assert '累计净利润可能与上年同期相比向下发生大幅度变动' in text
            assert row['change_reason']=='' and raw[0]['change_reason'] in [None,'']
            fields=['p_change_min','p_change_max','net_profit_min','net_profit_max']
            assert all(row[f]=='' and raw[0][f] is None for f in fields)
            qualitative.append(dict(**base,api_type=row['type'],api_change_reason_empty=True,
                original_explicit_downward_warning=True,original_numeric_range_absent_in_warning=True,
                status='api_reason_missing_despite_original_risk_explanation',
                last_parent_net_status='not_verified_by_warning_section'))
    (OUT/'evidence/zhongxin_forecast_checks.json').write_text(json.dumps(dict(checks=checks,qualitative_checks=qualitative,
        source_sha256=sha(Path(__file__)),verified_original_version_rows=0),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(numeric_fields=3,matched_fields=3,qualitative_warning_cases=1,historical_approvals=0)))

if __name__=='__main__':main()
