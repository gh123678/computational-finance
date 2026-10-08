"""A mirror value match must remain distinct from publication approval."""
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/announcement_financial_audit_20261007'
DATA = ROOT / 'data/announcement_financial_audit_2013_2020_r1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    pdf = OUT / 'evidence/603927_2013_halfyear_sina_mirror.pdf'
    assert sha(pdf) == 'f06ef739105a017dd0f4682e239bd59c8be9f7319521ba6934ea67953b727aee'
    with fitz.open(pdf) as doc:
        assert '430002' in doc[0].get_text()
        assert '48,313,832.29' in doc[67].get_text()
    with (OUT / 'original_document_check_queue.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = [r for r in csv.DictReader(stream) if (r['api'], r['ts_code'], r['ann_date'], r['end_date']) ==
                ('fina_indicator', '603927.SH', '20130830', '20130630')]
    assert len(rows) == 1
    row = rows[0]
    assert row['row_sha256'] == '6e12ca10994e24551eac987f8968fc5298d13583ed25a1eddbbc632b7ae4090e'
    raw = DATA / row['raw_path']
    assert sha(raw) == row['raw_sha256']
    data = json.loads(raw.read_text(encoding='utf-8'))['data']
    records = [dict(zip(data['fields'], values)) for values in data['items']]
    assert any((r['ts_code'], r['ann_date'], r['end_date'], str(r['update_flag'])) ==
               ('603927.SH', '20130830', '20130630', row['update_flag']) and
               Decimal(str(r['profit_dedt'])) == Decimal(row['profit_dedt']) for r in records)
    difference = Decimal(row['profit_dedt']) - Decimal('48313832.29')
    result = dict(ts_code='603927.SH', api='fina_indicator', ann_date='20130830', end_date='20130630',
        raw_path=row['raw_path'], raw_sha256=row['raw_sha256'], row_sha256=row['row_sha256'],
        pdf_file=str(pdf.relative_to(OUT)), pdf_sha256=sha(pdf), page=68, field='profit_dedt',
        original_value='48313832.29', unit='元', api_value=row['profit_dedt'], difference=str(difference),
        status='numeric_match_to_company_report_mirror_only' if difference == 0 else 'mirror_numeric_difference',
        original_document_company='中科软科技股份有限公司', original_document_security_code='430002',
        current_api_security_code='603927.SH', identity_status='same_company_name_old_code_clue_not_primary_mapping_approved',
        mirror_listed_day='20130829', api_ann_date='20130830', publication_status='one_day_discrepancy_unresolved',
        mirror_page_url='https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=1207541&stockid=603927',
        pdf_url='https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/SBGG/2013/2013-8/2013-08-29/1207541.PDF',
        roe_status='not_compared_unconfirmed_metric_definition', usable_in_verified_history=False,
        historical_version_status='unverified', source_sha256=sha(Path(__file__)))
    (OUT / 'evidence/sinosoft_mirror_case.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(mirror_value_difference=str(difference), verified_original_version_rows=0)))


if __name__ == '__main__':
    main()
