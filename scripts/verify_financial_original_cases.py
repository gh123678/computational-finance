"""Check manually inspected original tables against immutable API cache rows.

Field agreement is deliberately separate from historical publication/version approval.
The PDF pages listed here were rendered and visually inspected before transcription.
"""
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/announcement_financial_audit_20261007'
DATA = ROOT / 'data/announcement_financial_audit_2013_2020_r1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    cases = [
        ('000001.SZ', 'forecast', '20160121', '20151231',
         '000001_2015_forecast_original.pdf',
         '4bd8b0bb91c4d2766953b31a67ab5db63de165aee81f70ad2a2bdc46b54e1413',
         'https://static.cninfo.com.cn/finalpage/2016-01-21/1201929942.PDF', 1,
         {'p_change_min': ('5', '%'), 'p_change_max': ('15', '%'),
          'net_profit_min': ('2079206', '万元'), 'net_profit_max': ('2277225', '万元'),
          'last_parent_net': ('1980196', '万元')}),
        ('000488.SZ', 'fina_indicator', '20160331', '20151231',
         '000488_2015_annual_original.pdf',
         '88ed8cf49f7aca3c8a9a34bc1b22ce3b4a947cc5bce46cede272ddb676073667',
         'https://static.cninfo.com.cn/finalpage/2016-03-31/1202111959.PDF', 6,
         {'profit_dedt': ('719891359.63', '元')}),
        ('000547.SZ', 'fina_indicator', '20200430', '20191231',
         '000547_2019_annual_retry.pdf',
         '7019d05b98f96a3d2d964e173b2b3c9271c7b7c39308917e88400b10144a7d00',
         'https://static.cninfo.com.cn/finalpage/2020-04-30/1207685193.PDF', 6,
         {'profit_dedt': ('596512953.60', '元')}),
        ('002280.SZ', 'forecast', '20200122', '20191231',
         '002280_2019_forecast_revision_mirror.pdf',
         '3f89c2c5896c15ac74da0ea9e0e1fb2723f467bcb8724bf6cf3db6e106d7a009',
         'https://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESZ_STOCK/2020/2020-1/2020-01-22/5875483.PDF', 1,
         {'p_change_min': ('-348.62', '%'), 'p_change_max': ('-303.76', '%'),
          'net_profit_min': ('-300000', '万元'), 'net_profit_max': ('-270000', '万元'),
          'last_parent_net': ('-66871.25', '万元')})]
    checks, documents = [], []
    for code, api, ann, end, pdf, expected_sha, url, page, fields in cases:
        path = OUT / 'evidence' / pdf
        assert sha(path) == expected_sha, f'Original PDF changed: {pdf}'
        documents.append(dict(file=pdf, sha256=expected_sha, source_url=url,
                              source_kind='company_document_mirror' if 'sina.com.cn' in url else 'official_disclosure_host',
                              inspected_page=page, publication_status='dated_document_not_full_timing_proof'))
        with (OUT / f'{api}_records.csv').open(encoding='utf-8', newline='') as stream:
            records = [r for r in csv.DictReader(stream)
                       if (r['ts_code'], r['ann_date'], r['end_date']) == (code, ann, end)]
        assert len(records) == (1 if api == 'forecast' else 2), 'Unexpected case versions'
        for row in records:
            raw = DATA / row['raw_path']
            assert sha(raw) == row['raw_sha256'], 'Immutable cache hash mismatch'
            payload = json.loads(raw.read_text(encoding='utf-8'))['data']
            raw_rows = [dict(zip(payload['fields'], values)) for values in payload['items']]
            for field, (document_value, unit) in fields.items():
                assert any(str(r.get('ts_code')) == code and str(r.get('ann_date')) == ann
                           and str(r.get('end_date')) == end
                           and str(r.get('update_flag')) == row['update_flag']
                           and Decimal(str(r[field])) == Decimal(row[field]) for r in raw_rows)
                difference = Decimal(row[field]) - Decimal(document_value)
                checks.append(dict(ts_code=code, api=api, ann_date=ann, end_date=end,
                    update_flag=row['update_flag'], row_sha256=row['row_sha256'],
                    content_sha256=row['content_sha256'], raw_path=row['raw_path'],
                    raw_sha256=row['raw_sha256'], field=field, unit=unit,
                    api_value=row[field], original_value=document_value, difference=str(difference),
                    status='value_matches_dated_original' if difference == 0 else 'mismatch_to_dated_original',
                    pdf_file=pdf, pdf_sha256=expected_sha, page=page, source_url=url,
                    usable_in_verified_history=False))
    with (OUT / 'evidence/field_checks.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(checks[0]))
        writer.writeheader(); writer.writerows(checks)
    result = dict(documents=documents, verifier_source_sha256=sha(Path(__file__)), field_checks=len(checks),
                  matched_fields=sum(Decimal(c['difference']) == 0 for c in checks),
                  mismatched_fields=sum(Decimal(c['difference']) != 0 for c in checks),
                  verified_original_version_rows=0,
                  limitation='Field checks only; full version and actual disclosure timing remain unverified.')
    (OUT / 'evidence/manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'documents'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
