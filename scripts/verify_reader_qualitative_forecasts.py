"""Reproduce two visually inspected qualitative notices; never approve history."""
import csv
import hashlib
import json
from pathlib import Path
import re
import fitz

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/announcement_financial_audit_20261007'
DATA = ROOT / 'data/announcement_financial_audit_2013_2020_r1'


def compact(value):
    return re.sub(r'\s+', '', value)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    cases = [
        ('20181026', '20181231', '1205538883',
         '95ec8d1e5825cc8ce46ceb59fdf2e1f235e681fd65f17e737efac7af2709ad78',
         '不确定', 'qualitative_possible_decline'),
        ('20191026', '20191231', '1207019152',
         '3d14a8079ca54ed695fc09ffea59c8555f45f495a5aa649c1349e48bc90285b2',
         '预增', 'qualitative_operating_improvement_without_annual_range'),
    ]
    with (OUT / 'original_document_check_queue.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    checks = []
    for ann, end, identifier, expected_sha, api_type, interpretation in cases:
        matching = [r for r in rows if (r['api'], r['ts_code'], r['ann_date'], r['end_date']) ==
                    ('forecast', '603999.SH', ann, end)]
        assert len(matching) == 1
        row = matching[0]
        raw = DATA / row['raw_path']
        assert sha(raw) == row['raw_sha256']
        payload = json.loads(raw.read_text(encoding='utf-8'))['data']
        raw_rows = [dict(zip(payload['fields'], item)) for item in payload['items']]
        found = [r for r in raw_rows if (r['ts_code'], r['ann_date'], r['end_date']) ==
                 ('603999.SH', ann, end)]
        assert len(found) == 1
        assert found[0]['change_reason'] == row['change_reason']
        assert found[0]['type'] == row['type'] == api_type
        numeric = ['p_change_min', 'p_change_max', 'net_profit_min', 'net_profit_max']
        assert all(row[k] == '' and found[0].get(k) is None for k in numeric)
        pdf = OUT / 'remaining_evidence_r1/documents' / f'603999.SH_{ann}_{identifier}.pdf'
        assert sha(pdf) == expected_sha
        with fitz.open(pdf) as doc:
            text = doc[8].get_text()
            assert compact(row['change_reason']) in compact(text)
            assert '3.4' in text
        checks.append(dict(ts_code='603999.SH', api='forecast', ann_date=ann, end_date=end,
            row_sha256=row['row_sha256'], raw_path=row['raw_path'], raw_sha256=row['raw_sha256'],
            pdf_file=str(pdf.relative_to(OUT)), pdf_sha256=expected_sha, page=9,
            source_url=f'https://static.cninfo.com.cn/finalpage/{ann[:4]}-{ann[4:6]}-{ann[6:]}/{identifier}.PDF',
            api_change_reason_matches_original_after_whitespace_normalization=True,
            api_type=api_type, manual_original_interpretation=interpretation,
            original_forecast_section_has_numeric_range=False,
            api_numeric_range_missing_not_zero=True,
            last_parent_net_status='not_verified_by_this_qualitative_forecast_section',
            historical_publication_and_version_status='unverified', usable_in_verified_history=False))
    output = OUT / 'evidence/reader_qualitative_forecast_checks.json'
    output.write_text(json.dumps(dict(checks=checks, source_sha256=sha(Path(__file__)),
        verified_original_version_rows=0), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(qualitative_notices_checked=len(checks), verified_original_version_rows=0)))


if __name__ == '__main__':
    main()
