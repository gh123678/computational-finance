"""Retain manual scan-page evidence separately from release/version approval."""
import csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_reader_qualitative_forecasts import OUT,DATA,sha

def main():
    with (OUT/'original_document_check_queue.csv').open(encoding='utf-8-sig',newline='') as f:queue=list(csv.DictReader(f))
    cases=[('603998.SH','20141114','20140630','1200392012',['贺焕华','曹湘琦'],[88,89],89,'20140721','天健审〔2014〕2-234号'),
           ('605288.SH','20200518','20191231','1207821156',['沈培强','胡青'],list(range(118,125)),124,'20200304','天健审〔2020〕498号')]
    checks=[]
    for code,ann,end,identifier,signers,pages,sign_page,date,report_id in cases:
        rows=[r for r in queue if (r['api'],r['ts_code'],r['ann_date'],r['end_date'])==('fina_audit',code,ann,end)]
        assert len(rows)==1
        row=rows[0];raw_file=DATA/row['raw_path'];assert sha(raw_file)==row['raw_sha256']
        data=json.loads(raw_file.read_text(encoding='utf-8'))['data']
        raw=[dict(zip(data['fields'],values)) for values in data['items']]
        matched=[r for r in raw if (r['ts_code'],r['ann_date'],r['end_date'])==(code,ann,end)]
        assert len(matched)==1
        for field in ['audit_sign','audit_agency','audit_result']:assert matched[0][field]==row[field]
        assert set(row['audit_sign'].split(','))==set(signers)
        assert row['audit_fees']=='' and matched[0]['audit_fees'] is None
        access=json.loads((OUT/f'fixed_large_appendices_r1/results/{code}_{ann}.json').read_text(encoding='utf-8'))
        assert access['status']=='downloaded_readable_appendix_only' and access['announcement_id']==identifier
        pdf=OUT/'fixed_large_appendices_r1'/access['pdf_file'];assert sha(pdf)==access['pdf_sha256']
        for page in pages:
            rendered=pdf.with_name(f'{pdf.stem}_page{page}.png');assert rendered.exists()
        checks.append(dict(ts_code=code,api='fina_audit',ann_date=ann,end_date=end,row_sha256=row['row_sha256'],
            raw_path=row['raw_path'],raw_sha256=row['raw_sha256'],pdf_file=str(pdf.relative_to(OUT)),pdf_sha256=access['pdf_sha256'],source_url=access['source_url'],
            evidence_method='manual_visual_review_of_scanned_audit_pages_not_text_or_OCR_assertion',reviewed_pages=pages,
            sign_page=sign_page,original_signers=signers,signer_names_match=True,document_signature_day=date,original_report_id=report_id,
            report_period_matches_api_end=True,original_audit_agency='天健会计师事务所（特殊普通合伙）',api_audit_agency=row['audit_agency'],agency_status='legal_suffix_difference_pending',
            api_audit_result=row['audit_result'],opinion_status='fair_presentation_wording_read_not_independent_legal_category_approval',
            api_audit_fees=row['audit_fees'],fee_status='missing_not_zero_not_verified',
            publication_status='signature_day_is_not_first_publication_day',usable_in_verified_history=False))
    (OUT/'evidence/fixed_appendix_audit_checks.json').write_text(json.dumps(dict(checks=checks,source_sha256=sha(Path(__file__)),historical_approvals=0),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(audit_cases=2,matched_signer_sets=2,missing_fees=2,historical_approvals=0)))

if __name__=='__main__':main()
