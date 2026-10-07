"""Check manually inspected original tables against immutable API cache rows.

Field agreement is deliberately separate from historical publication/version approval.
The PDF pages listed here were rendered and visually inspected before transcription.
"""
import csv
import hashlib
import json
from decimal import Decimal
from datetime import datetime, timezone, timedelta
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
         '002280_2019_forecast_revision_official.pdf',
         '3f89c2c5896c15ac74da0ea9e0e1fb2723f467bcb8724bf6cf3db6e106d7a009',
         'https://static.cninfo.com.cn/finalpage/2020-01-22/1207276256.PDF', 1,
         {'p_change_min': ('-348.62', '%'), 'p_change_max': ('-303.76', '%'),
          'net_profit_min': ('-300000', '万元'), 'net_profit_max': ('-270000', '万元'),
          'last_parent_net': ('-66871.25', '万元')}),
        ('000673.SZ', 'forecast', '20200122', '20191231',
         '000673_2019_forecast_original.pdf',
         '60041f45d46cca69766da4d7e9532e7e2b500c7e30b85fffa3442dc453753c93',
         'https://static.cninfo.com.cn/finalpage/2020-01-22/1207277038.PDF', 1,
         {'net_profit_min': ('-60000', '万元'), 'net_profit_max': ('-45000', '万元'),
          'last_parent_net': ('-160100.35', '万元')}),
        ('000662.SZ', 'forecast', '20200123', '20191231',
         '000662_2019_forecast_original.pdf',
         'eeb3e053dc9b8121b5262bb671558ea92607af3c8e1fb56fe123a2410e70645e',
         'https://static.cninfo.com.cn/finalpage/2020-01-23/1207281857.PDF', 1,
         {'net_profit_min': ('-345000', '万元'), 'net_profit_max': ('-275000', '万元'),
          'last_parent_net': ('15086.75', '万元')}),
        ('002280.SZ', 'forecast', '20191025', '20191231',
         '002280_2019_q3_original.pdf',
         'bcbeea7d147a776d891d6893de2a65a118f1a6f9d38394f07a7a9be9e499d75e',
         'https://static.cninfo.com.cn/finalpage/2019-10-25/1207012834.PDF', 6,
         {'net_profit_min': ('0', '万元'), 'net_profit_max': ('5000', '万元'),
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
    index_checks = []
    index_cases = [
        ('000673.SZ','20200122','1207277038','000673_202001_query.json','20200121'),
        ('000662.SZ','20200123','1207281857','000662_202001_query.json','20200123'),
        ('002280.SZ','20191025','1207012834','002280_201910_query.json',''),
        ('002280.SZ','20200122','1207276256','002280_202001_query.json','20200122')]
    for code, ann, identifier, name, signature in index_cases:
        path = OUT/'evidence'/name
        payload = json.loads(path.read_text(encoding='utf-8'))
        matches = [item for item in payload.get('announcements') or []
                   if item['secCode'] == code[:6] and item['announcementId'] == identifier]
        assert len(matches) == 1, 'Missing/ambiguous public index record'
        item = matches[0]
        index_date = datetime.fromtimestamp(item['announcementTime']/1000, timezone.utc).astimezone(
            timezone(timedelta(hours=8))).strftime('%Y%m%d')
        assert index_date == ann, 'API publication date does not match retrieved index day'
        assert item['adjunctUrl'].startswith('finalpage/'+datetime.strptime(ann,'%Y%m%d').strftime('%Y-%m-%d')+'/')
        with (OUT/'forecast_records.csv').open(encoding='utf-8', newline='') as stream:
            api_rows = [r for r in csv.DictReader(stream) if (r['ts_code'],r['ann_date'],r['end_date']) == (code,ann,'20191231')]
        assert len(api_rows) == 1
        index_checks.append(dict(ts_code=code, api_ann_date=ann, index_publication_day=index_date,
            document_signature_day=signature, announcement_id=identifier, title=item['announcementTitle'],
            source_url='https://static.cninfo.com.cn/'+item['adjunctUrl'], index_file=name,
            index_sha256=sha(path), retrieved_file_time_utc=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
            query_endpoint='https://www.cninfo.com.cn/new/hisAnnouncement/query',
            candidate_available_date=api_rows[0]['candidate_available_date'],
            status='current_official_index_day_matches_api', usable_in_verified_history=False,
            limitation='Current index proves listed day only; not an archived original release timestamp/version chain.'))
    official = OUT/'evidence/002280_2019_forecast_revision_official.pdf'
    mirror = OUT/'evidence/002280_2019_forecast_revision_mirror.pdf'
    assert sha(official) == sha(mirror), 'Official revision PDF differs from prior mirror'
    (OUT/'evidence/publication_index_checks.json').write_text(json.dumps(index_checks,ensure_ascii=False,indent=2),encoding='utf-8')
    result = dict(documents=documents, publication_index_checks=len(index_checks),
                  official_revision_matches_mirror=True, verifier_source_sha256=sha(Path(__file__)), field_checks=len(checks),
                  matched_fields=sum(Decimal(c['difference']) == 0 for c in checks),
                  mismatched_fields=sum(Decimal(c['difference']) != 0 for c in checks),
                  verified_original_version_rows=0,
                  limitation='Field checks only; full version and actual disclosure timing remain unverified.')
    (OUT / 'evidence/manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'documents'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
