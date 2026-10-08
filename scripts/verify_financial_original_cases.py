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
    original_field_amounts = {
        ('000004_2013_annual_forecast_original.pdf', 'last_parent_net'):
            ('2005254.96', '元', '0.0001'),
    }
    original_bank_amounts = {
        '000001_2012_annual_original.pdf': ('13385220', '千元', '1000'),
        '000001_2013_annual_original.pdf': ('15166', '百万元', '1000000'),
        '000001_2014_annual_original.pdf': ('19841', '百万元', '1000000'),
        '000001_2015_annual_original.pdf': ('21902', '百万元', '1000000'),
        '000001_2016_annual_original.pdf': ('22606', '百万元', '1000000'),
        '000001_2017_annual_original.pdf': ('23162', '百万元', '1000000'),
        '000001_2018_annual_original.pdf': ('24700', '百万元', '1000000'),
        '000001_2019_annual_original.pdf': ('28086', '百万元', '1000000'),
    }
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
          'last_parent_net': ('-66871.25', '万元')}),
        ('000004.SZ', 'forecast', '20130413', '20130331',
         '000004_2013_q1_forecast_original.pdf',
         '474fd844f6c5487f528b5d3e79d80f575fe68b83c3f81f8ee6778f30e175ea22',
         'https://static.cninfo.com.cn/finalpage/2013-04-13/62355550.PDF', 1,
         {'p_change_min': ('1087.51', '%'), 'p_change_max': ('17712.61', '%'),
          'net_profit_min': ('10', '万元'), 'net_profit_max': ('150', '万元'),
          'last_parent_net': ('0.8421', '万元')}),
        ('000002.SZ', 'forecast', '20150403', '20150331',
         '000002_2015_q1_forecast_original.pdf',
         '0a4f7d8d97c3c4d036589e01970bed0958c451891a154debdbff9edf154810bc',
         'https://static.cninfo.com.cn/finalpage/2015-04-03/1200784294.PDF', 1,
         {'p_change_min': ('-61', '%'), 'p_change_max': ('-54', '%'),
          'net_profit_min': ('60000', '万元'), 'net_profit_max': ('70000', '万元'),
          'last_parent_net': ('152948', '万元')}),
        ('000001.SZ', 'fina_indicator', '20130308', '20121231',
         '000001_2012_annual_original.pdf',
         'c90498736be8cd13338c9c460ea458e946c7f04a673c23b77101f1da129632f5',
         'https://static.cninfo.com.cn/finalpage/2013-03-08/62193049.PDF', 8,
         {'profit_dedt': (str(Decimal('13385220') * Decimal('1000')), '元')}),
        ('000001.SZ', 'fina_indicator', '20140307', '20131231',
         '000001_2013_annual_original.pdf',
         '6f2f7f9f879a1468b552fed305cbfef115ec305f9ab0aef57442d0cb41ded06d',
         'https://static.cninfo.com.cn/finalpage/2014-03-07/63646360.PDF', 7,
         {'profit_dedt': (str(Decimal('15166') * Decimal('1000000')), '元')}),
        ('000001.SZ', 'fina_indicator', '20150313', '20141231',
         '000001_2014_annual_original.pdf',
         '72b8a629952d764911c9ae32749729cb9ccf053dad6575bece4a431ed647d45b',
         'https://static.cninfo.com.cn/finalpage/2015-03-13/1200694563.PDF', 8,
         {'profit_dedt': (str(Decimal('19841') * Decimal('1000000')), '元')}),
        ('000001.SZ', 'fina_indicator', '20160310', '20151231',
         '000001_2015_annual_original.pdf',
         '67398b0340aebf7bc9786866b0a5981c216bce5ab74605f18af8db036e7871c7',
         'https://static.cninfo.com.cn/finalpage/2016-03-10/1202033390.PDF', 7,
         {'profit_dedt': (str(Decimal('21902') * Decimal('1000000')), '元')}),
        ('000001.SZ', 'fina_indicator', '20170317', '20161231',
         '000001_2016_annual_original.pdf',
         '4226a89d6662c3e33818f9e94afe7e00c081b36d90642a5de6ccd61fbefb9c83',
         'https://static.cninfo.com.cn/finalpage/2017-03-17/1203167519.PDF', 7,
         {'profit_dedt': (str(Decimal('22606') * Decimal('1000000')), '元')}),
        ('000001.SZ', 'fina_indicator', '20180315', '20171231',
         '000001_2017_annual_original.pdf',
         '50e65f55a9102cad4aefb36959dcae3b1ee435fc024866342a591e06021ff26c',
         'https://static.cninfo.com.cn/finalpage/2018-03-15/1204477157.PDF', 7,
         {'profit_dedt': (str(Decimal('23162') * Decimal('1000000')), '元')}),
        ('000001.SZ', 'fina_indicator', '20190307', '20181231',
         '000001_2018_annual_original.pdf',
         '92d47109123b7d5ed6311d3da23443d2b9ff2e77e4470494c403a5966f10cc73',
         'https://static.cninfo.com.cn/finalpage/2019-03-07/1205881066.PDF', 10,
         {'profit_dedt': (str(Decimal('24700') * Decimal('1000000')), '元')}),
        ('000001.SZ', 'fina_indicator', '20200214', '20191231',
         '000001_2019_annual_original.pdf',
         '691e15ea9ad0d4d8a11852266909d5be5dd8870ba8f80a015b2cf9e46a7eb670',
         'https://static.cninfo.com.cn/finalpage/2020-02-14/1207305488.PDF', 19,
         {'profit_dedt': (str(Decimal('28086') * Decimal('1000000')), '元')}),
        ('603766.SH', 'forecast', '20130403', '20130331',
         '603766_2013_q1_forecast_original.pdf',
         '30ede936cdd4f8ef9649f664e4793b24067a7e65c691be1c4547aad66c40a2c4',
         'https://static.cninfo.com.cn/finalpage/2013-04-03/62319049.PDF', 1,
         {'last_parent_net': ('8238.18', '万元')}),
        ('000004.SZ', 'forecast', '20140122', '20131231',
         '000004_2013_annual_forecast_original.pdf',
         '79fdf10ec412f5c361f0f257e2a1d2ccde1ed50b92998062fdcc335ecd811f5f',
         'https://static.cninfo.com.cn/finalpage/2014-01-22/63509209.PDF', 1,
         {'net_profit_min': ('-300', '万元'), 'net_profit_max': ('-100', '万元'),
          'last_parent_net': (str(Decimal('2005254.96') * Decimal('0.0001')), '万元')}),
        ('000004.SZ', 'forecast', '20170124', '20161231',
         '000004_2016_annual_forecast_original.pdf',
         '98d815cbdb39184b0ab02a0cab11ae543d7d3ad2263067916444a9c6949ca160',
         'https://static.cninfo.com.cn/finalpage/2017-01-24/1203045709.PDF', 1,
         {'p_change_min': ('2706.51', '%'), 'p_change_max': ('3508.37', '%'),
          'net_profit_min': ('3500', '万元'), 'net_profit_max': ('4500', '万元'),
          'last_parent_net': ('124.71', '万元')}),
        ('000004.SZ', 'forecast', '20180131', '20171231',
         '000004_2017_annual_forecast_original.pdf',
         'ab9af5f2c9573085b0211d32849f9bd5f0e1e51623ff351f8846004992354868',
         'https://static.cninfo.com.cn/finalpage/2018-01-31/1204375866.PDF', 1,
         {'p_change_min': ('-79.64', '%'), 'p_change_max': ('-59.29', '%'),
          'net_profit_min': ('800', '万元'), 'net_profit_max': ('1600', '万元'),
          'last_parent_net': ('3929.93', '万元')}),
        ('000004.SZ', 'forecast', '20190129', '20181231',
         '000004_2018_annual_forecast_original.pdf',
         '94e17d498ca5fb10b5720b311bf867622f3bad3c9fab880b3a45b885be9416a3',
         'https://static.cninfo.com.cn/finalpage/2019-01-29/1205806979.PDF', 1,
         {'p_change_min': ('-397.66', '%'), 'p_change_max': ('-298.44', '%'),
          'net_profit_min': ('-2550', '万元'), 'net_profit_max': ('-1700', '万元'),
          'last_parent_net': ('856.67', '万元')}),
        ('000004.SZ', 'forecast', '20200118', '20191231',
         '000004_2019_annual_forecast_original.pdf',
         'ab930107dbb4bf57188ddba013af254d1506ef9dfd118ac1b125a45f5d7bfde2',
         'https://static.cninfo.com.cn/finalpage/2020-01-18/1207263441.PDF', 1,
         {'p_change_min': ('112.33', '%'), 'p_change_max': ('124.67', '%'),
          'net_profit_min': ('250', '万元'), 'net_profit_max': ('500', '万元'),
          'last_parent_net': ('-2027.08', '万元')})]
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
                printed_value, printed_unit, multiplier = original_field_amounts.get(
                    (pdf, field), original_bank_amounts.get(pdf, (document_value, unit, '1')))
                assert Decimal(printed_value) * Decimal(multiplier) == Decimal(document_value)
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
                    original_document_value=printed_value,
                    original_document_unit=printed_unit,
                    conversion_multiplier=multiplier,
                    status='value_matches_dated_original' if difference == 0 else 'mismatch_to_dated_original',
                    pdf_file=pdf, pdf_sha256=expected_sha, page=page, source_url=url,
                    usable_in_verified_history=False))
    with (OUT / 'evidence/field_checks.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(checks[0]))
        writer.writeheader(); writer.writerows(checks)
    index_checks = []
    index_cases = [
        ('000673.SZ','20200122','1207277038','000673_202001_query.json','20200121','20191231'),
        ('000662.SZ','20200123','1207281857','000662_202001_query.json','20200123','20191231'),
        ('002280.SZ','20191025','1207012834','002280_201910_query.json','','20191231'),
        ('002280.SZ','20200122','1207276256','002280_202001_query.json','20200122','20191231'),
        ('603766.SH','20130403','62319049','603766_20130403_query.json','20130402','20130331'),
        ('000004.SZ','20140122','63509209','000004_20140122_company_query.json','20140122','20131231'),
        ('000004.SZ','20170124','1203045709','000004_20170124_company_query.json','','20161231'),
        ('000004.SZ','20180131','1204375866','000004_20180131_company_query.json','20180131','20171231'),
        ('000004.SZ','20190129','1205806979','000004_20190129_company_query.json','20190129','20181231'),
        ('000004.SZ','20200118','1207263441','000004_20200118_company_query.json','20200118','20191231')]
    for code, ann, identifier, name, signature, end in index_cases:
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
            api_rows = [r for r in csv.DictReader(stream) if (r['ts_code'],r['ann_date'],r['end_date']) == (code,ann,end)]
        assert len(api_rows) == 1
        index_checks.append(dict(ts_code=code, end_date=end, api_ann_date=ann, index_publication_day=index_date,
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
    audit_pdf=OUT/'evidence/000001_2012_audit_original.pdf'
    assert sha(audit_pdf)=='ffbcf98b4977458b72e835751b3f8248b829320b01fa7c0db9c321ae6a24c6ca'
    with (OUT/'fina_audit_records.csv').open(encoding='utf-8',newline='') as stream:
        audit_rows=[r for r in csv.DictReader(stream) if (r['ts_code'],r['ann_date'],r['end_date'])==('000001.SZ','20130308','20121231')]
    assert len(audit_rows)==1
    audit_row=audit_rows[0]
    assert sha(DATA/audit_row['raw_path'])==audit_row['raw_sha256']
    assert set(audit_row['audit_sign'].split(','))=={'昌华','周道君'}
    category_checks=dict(ts_code='000001.SZ',api='fina_audit',ann_date='20130308',end_date='20121231',
        pdf_file=audit_pdf.name,pdf_sha256=sha(audit_pdf),pdf_page=3,document_signature_day='20130307',
        source_url='https://static.cninfo.com.cn/finalpage/2013-03-08/62193053.PDF',
        row_sha256=audit_row['row_sha256'],raw_path=audit_row['raw_path'],raw_sha256=audit_row['raw_sha256'],
        signer_names_match=True,api_audit_agency=audit_row['audit_agency'],
        original_audit_agency='安永华明会计师事务所（特殊普通合伙）',
        agency_status='legal_suffix_difference_pending',api_audit_result=audit_row['audit_result'],
        audit_opinion_status='fair_presentation_text_read_category_not_independently_approved',
        api_audit_fees=audit_row['audit_fees'],audit_fees_status='missing_not_zero',usable_in_verified_history=False)
    (OUT/'evidence/audit_category_checks.json').write_text(json.dumps(category_checks,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'evidence/publication_index_checks.json').write_text(json.dumps(index_checks,ensure_ascii=False,indent=2),encoding='utf-8')
    result = dict(documents=documents, publication_index_checks=len(index_checks),
                  official_revision_matches_mirror=True, audit_signer_case_rows=1,
                  verifier_source_sha256=sha(Path(__file__)), field_checks=len(checks),
                  matched_fields=sum(Decimal(c['difference']) == 0 for c in checks),
                  mismatched_fields=sum(Decimal(c['difference']) != 0 for c in checks),
                  verified_original_version_rows=0,
                  limitation='Field checks only; full version and actual disclosure timing remain unverified.')
    (OUT / 'evidence/manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'documents'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
