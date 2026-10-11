import ocr_recovered_financial_candidates as scan


def row(text, *cells):
    return dict(text=text, cells=[dict(text=x) for x in cells])


def test_toc_locates_financial_end_instead_of_credential_tail():
    rows=[row('财务报表附注 | 19-107', '财务报表附注','19-107'),
          row('合并利润表 | 9', '合并利润表','9')]
    pages=scan.select_extra_pages(rows,113)
    assert 105 in pages and 106 in pages and 108 in pages
    assert 10 in pages
    assert 111 not in pages and 113 not in pages


def test_page_budget_and_real_document_bounds_apply_to_native_hits():
    pages=scan.select_extra_pages([],5,list(range(1,100)))
    assert all(1 <= p <= 5 for p in pages)
    assert len(set(pages))==len(pages)
    assert len(pages)+2 <= scan.MAX_PAGES
    pages=scan.select_extra_pages([],300,list(range(1,300)))
    assert len(pages)+2 <= scan.MAX_PAGES


def test_year_range_cannot_become_a_page_number_range():
    assert scan.toc_end([row('附注 2019-2020')],130) is None


def test_ratio_dedt_label_never_selects_money():
    rows=[row('净资产收益率（%） | 基本每股收益'),
          dict(text='扣除非经常性损益后的净利润 | -67.22 | -0.19',cells=[])]
    found=scan.candidate_context(rows)
    assert found[0]['role']=='dedt_label_in_ratio_context'
    assert found[0]['selected_financial_value'] is None
    assert found[0]['financial_field_verified'] is False
    assert found[0]['usable_in_verified_history'] is False


def test_parent_profit_remains_distinct_from_dedt():
    found=scan.candidate_context([dict(text='归属于母公司股东的净利润 | 10,803,619.31',cells=[])])
    assert found[0]['role']=='parent_net_profit_not_dedt'
    assert found[0]['selected_financial_value'] is None


def test_financial_page_mentioning_license_is_not_dropped():
    assert scan.credential_only('营业执照 注册会计师执业证书')
    assert not scan.credential_only('财务报表附注 公司于某日取得营业执照')


def test_real_access_schema_can_record_ocr_state_without_approving_fields():
    item=dict(status='downloaded_readable_candidate_only', ts_code='000595.SZ',
        financial_field_verified=False, usable_in_verified_history=False)
    recorded=scan.evidence_record(item,status='bounded_ocr_pass_only',financial_field_verified=True,
        usable_in_verified_history=True,selected_financial_value='10.01')
    assert item['status']=='downloaded_readable_candidate_only'
    assert recorded['source_access_status']=='downloaded_readable_candidate_only'
    assert recorded['status']=='bounded_ocr_pass_only'
    assert recorded['financial_field_verified'] is False
    assert recorded['usable_in_verified_history'] is False
    assert recorded['selected_financial_value'] is None
