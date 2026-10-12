from link_financial_content_evidence_scopes import deduplicate


def test_redundant_api_flags_do_not_double_count_pdf_and_distinct_units_and_pdfs_survive():
    common=dict(ts_code='A',key_ann_date='20200420',end_date='20191231',pdf_sha256='pdf1',
        observed_document_unit='千元',reported_value_cny='1000.00',evidence_kind='early_field_check_record')
    rows=[dict(common,source_reference='flag0'),dict(common,reported_value_cny='1000',source_reference='flag1'),
        dict(common,pdf_sha256='pdf2',source_reference='different_pdf'),
        dict(common,observed_document_unit='元',source_reference='different_unit')]
    result=deduplicate(rows)
    assert len(result)==3
    assert result[0]['source_references']==['flag0','flag1']
