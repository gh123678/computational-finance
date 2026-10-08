"""Reproduce visually reviewed annual-report audit evidence; no history approval."""
import csv
import json
from decimal import Decimal
from pathlib import Path
import sys
import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_reader_qualitative_forecasts import OUT, DATA, sha, compact


def main():
    with (OUT / 'original_document_check_queue.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    checks = []
    for ann, end, identifier, opinion_page, sign_page, fee_page, amount, signature in [
        ('20180420', '20171231', '1204664508', 58, 61, 32, '640000', '2018年4月18日'),
        ('20190426', '20181231', '1206100044', 64, 67, 34, '650000', '2019年4月24日'),
    ]:
        matching = [r for r in rows if (r['api'], r['ts_code'], r['ann_date'], r['end_date']) ==
                    ('fina_audit', '603999.SH', ann, end)]
        assert len(matching) == 1
        row = matching[0]
        raw_file = DATA / row['raw_path']
        assert sha(raw_file) == row['raw_sha256']
        data = json.loads(raw_file.read_text(encoding='utf-8'))['data']
        raw_rows = [dict(zip(data['fields'], values)) for values in data['items']]
        raw_matching = [r for r in raw_rows if (r['ts_code'], r['ann_date'], r['end_date']) ==
                        ('603999.SH', ann, end)]
        assert len(raw_matching) == 1
        raw = raw_matching[0]
        for field in ['audit_sign', 'audit_agency', 'audit_result']:
            assert raw[field] == row[field]
        assert Decimal(str(raw['audit_fees'])) == Decimal(row['audit_fees']) == Decimal(amount)
        assert set(row['audit_sign'].split(',')) == {'高明来', '刘富锦'}
        result = json.loads((OUT / f'remaining_evidence_r1/results/603999.SH_{ann}.json').read_text(encoding='utf-8'))
        document = next(d for d in result['documents'] if d['announcement_id'] == identifier)
        pdf_file = OUT / 'remaining_evidence_r1' / document['file']
        assert sha(pdf_file) == document['sha256']
        with fitz.open(pdf_file) as doc:
            opinion = compact(doc[opinion_page - 1].get_text())
            signing = compact(doc[sign_page - 1].get_text())
            fee = compact(doc[fee_page - 1].get_text())
            assert '一、审计意见' in opinion and '公允反映' in opinion
            assert all(name in signing for name in ['高明来', '刘富锦', signature])
            assert '中喜会计师事务所（特殊普通合伙）' in signing
            assert '境内会计师事务所报酬' in fee
            assert format(Decimal(amount), ',.2f') in fee and '单位：元' in fee
        checks.append(dict(ts_code='603999.SH', api='fina_audit', ann_date=ann, end_date=end,
            row_sha256=row['row_sha256'], raw_path=row['raw_path'], raw_sha256=row['raw_sha256'],
            pdf_file=document['file'], pdf_sha256=document['sha256'], source_url=document['url'],
            reviewed_audit_pages=list(range(opinion_page, sign_page + 1)),
            fee_page=fee_page, sign_page=sign_page, document_signature_day=signature,
            api_audit_fees=row['audit_fees'], original_audit_fees=amount, fee_unit='元',
            audit_fee_difference='0', fee_scope='domestic_financial_statement_auditor_not_internal_control_fee',
            signer_names_match=True, api_audit_agency=row['audit_agency'],
            original_audit_agency='中喜会计师事务所（特殊普通合伙）', agency_status='legal_suffix_difference_pending',
            api_audit_result=row['audit_result'],
            opinion_status='consistent_with_unmodified_opinion_wording_not_independent_legal_classification',
            candidate_available_date=row['candidate_available_date'],
            publication_status='current_index_and_signature_do_not_prove_archived_release_time',
            usable_in_verified_history=False))
    (OUT / 'evidence/reader_audit_checks.json').write_text(json.dumps(dict(checks=checks,
        source_sha256=sha(Path(__file__)), verified_original_version_rows=0), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(audit_cases=2, matched_fees=2, matched_signer_sets=2, verified_original_version_rows=0)))


if __name__ == '__main__':
    main()
