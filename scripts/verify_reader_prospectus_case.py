"""Check a visually inspected prospectus forecast, keeping precision differences."""
import csv
import json
from decimal import Decimal
import sys
from pathlib import Path
import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_reader_qualitative_forecasts import OUT, DATA, sha


def main():
    case = json.loads((OUT / 'remaining_evidence_r1/results/603999.SH_20151123.json').read_text(encoding='utf-8'))
    document = next(d for d in case['documents'] if d['announcement_id'] == '1201784200')
    pdf = OUT / 'remaining_evidence_r1' / document['file']
    assert sha(pdf) == document['sha256']
    with fitz.open(pdf) as doc:
        assert '净利润下降15-30%' in ''.join(doc[17].get_text().split())
        assert '14,119.72' in doc[304].get_text()
    with (OUT / 'original_document_check_queue.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = [r for r in csv.DictReader(stream) if (r['api'], r['ts_code'], r['ann_date'], r['end_date']) ==
                ('forecast', '603999.SH', '20151123', '20151231')]
    assert len(rows) == 1
    row = rows[0]
    assert row['row_sha256'] == '561a4beb49c07e16f6c741c077621a61ca1e512ab22112dab4a689e0253fe69e'
    assert sha(DATA / row['raw_path']) == row['raw_sha256']
    payload = json.loads((DATA / row['raw_path']).read_text(encoding='utf-8'))['data']
    raw = [dict(zip(payload['fields'], values)) for values in payload['items']]
    matching = [r for r in raw if (r['ts_code'], r['ann_date'], r['end_date']) ==
                ('603999.SH', '20151123', '20151231')]
    assert len(matching) == 1
    checks = []
    for field, value, unit, page in [('p_change_min', '-30', '%', 18),
                                    ('p_change_max', '-15', '%', 18),
                                    ('last_parent_net', '14119.72', '万元', 305)]:
        assert Decimal(str(matching[0][field])) == Decimal(row[field])
        difference = Decimal(row[field]) - Decimal(value)
        checks.append(dict(ts_code='603999.SH', api='forecast', ann_date='20151123', end_date='20151231',
            row_sha256=row['row_sha256'], raw_path=row['raw_path'], raw_sha256=row['raw_sha256'],
            field=field, api_value=row[field], original_value=value, difference=str(difference), unit=unit,
            page=page, pdf_file=document['file'], pdf_sha256=document['sha256'], source_url=document['url'],
            status='numeric_match' if difference == 0 else 'precision_difference_cause_unconfirmed',
            usable_in_verified_history=False))
    (OUT / 'evidence/reader_prospectus_checks.json').write_text(json.dumps(dict(checks=checks,
        source_sha256=sha(Path(__file__)), verified_original_version_rows=0), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(fields=3, matches=2, differences=1, verified_original_version_rows=0)))


if __name__ == '__main__':
    main()
