import refine_scan_page_locations as refine


def footer(page,text,y=970,confidence=.99):
    return dict(page=page,rows=[dict(center_y=y,cells=[dict(text=text,confidence=confidence)])])


def test_real_nine_page_offset_requires_multiple_footer_pages():
    r=refine.infer_offset([footer(110,'101'),footer(111,'102')],{110:1000,111:1000})
    assert r['offset']==9
    assert refine.infer_offset([footer(110,'101')],{110:1000})['offset'] is None


def test_body_amounts_low_confidence_and_competing_numbering_are_rejected():
    assert refine.printed_footer(footer(110,'101',y=600),1000) is None
    assert refine.printed_footer(footer(110,'101',confidence=.5),1000) is None
    assert refine.infer_offset([footer(110,'101'),footer(111,'102'),footer(10,'9')],{110:1000,111:1000,10:1000})['offset'] is None


def test_chinese_footer_and_page_suffix_do_not_parse_year_as_page():
    assert refine.printed_footer(footer(126,'第125页，共125页'),1000)==125
    rows=[dict(text='合并利润表 | 11页',cells=[dict(text='11页')]),
          dict(text='附注 | 19-125页',cells=[]),dict(text='附注2019-2020',cells=[])]
    t=refine.printed_targets(rows,131)
    assert t==dict(profit=[11],notes_end=125)
    assert refine.planned_pages(t,1,131,{126})==[12,13,125,127]


def test_unknown_offset_never_guesses_and_bounds_dedup_budget_hold():
    t=dict(profit=[1,1,10,20,30],notes_end=125)
    assert refine.planned_pages(t,None,131,set())==[]
    p=refine.planned_pages(t,9,125,{10})
    assert len(p)<=6 and len(set(p))==len(p) and all(1<=n<=125 for n in p)


def test_persisted_confidence_strings_and_invalid_values_are_handled():
    assert refine.printed_footer(footer(111,'102',confidence='0.99'),1000)==102
    for value in ['0.7460033148527145','NaN','Infinity','bad',None]:
        assert refine.printed_footer(footer(111,'102',confidence=value),1000) is None
