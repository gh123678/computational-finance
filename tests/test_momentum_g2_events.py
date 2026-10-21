import sys
from pathlib import Path
import hashlib
import json

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from momentum_g2_events import (EventBook, bridge_terms, build_event_book,
                                bound_source_inputs, display_price, next_session, ordinary_reason)


def fact(calendar, **updates):
    row = dict(code='000001.SZ', event_id='one', version=1, kind='ordinary',
        source_available_date=calendar[10].strftime('%Y-%m-%d'),
        record=calendar[19], ex=calendar[20], cash_pay=calendar[22], stock_pay=calendar[23],
        cash_per_share='1', stock_per_share='.2', taxable_bonus_per_share='.1')
    row.update(updates)
    return row


def test_date_only_is_next_exchange_session_and_detached():
    cal = pd.bdate_range('2017-01-02', periods=40)
    book = EventBook(cal, [fact(cal)])
    assert next_session(cal[4], cal) == cal[5].strftime('%Y-%m-%d')
    assert not book.view(cal[10])
    assert len(book.view(cal[11])) == 1
    view = book.view(cal[11]); view[0]['cash_div_tax'] = '999'
    assert book.view(cal[11])[0]['cash_div_tax'] == '1'
    assert not ordinary_reason(book.view(cal[11])[0], cal)


def test_cancellation_changes_only_after_available_date():
    cal = pd.bdate_range('2017-01-02', periods=40)
    v1 = fact(cal)
    v2 = fact(cal, version=2, kind='cancelled', status='cancelled',
              source_available_date=cal[18])
    book = EventBook(cal, [v1, v2])
    assert book.known_for_code('000001.SZ', cal[18])[0]['kind'] == 'ordinary'
    assert book.known_for_code('000001.SZ', cal[19])[0]['kind'] == 'cancelled'
    d, s, _, reason = bridge_terms(book, '000001.SZ', cal[20])
    assert not reason and d == 0 and s == 0


def test_conflicting_duplicates_not_summed_or_last_selected():
    cal = pd.bdate_range('2017-01-02', periods=40)
    book = EventBook(cal, [fact(cal), fact(cal, source_available_date=cal[12], cash_per_share='2')])
    assert book.view(cal[11])[0]['kind'] == 'ordinary'
    assert book.view(cal[13])[0]['kind'] == 'conflict'
    assert book.exposure_issues('000001.SZ', cal[13], cal[0])


def test_same_source_equivalent_raw_duplicates_fold_and_missing_not_zero():
    cal = pd.bdate_range('2017-01-02', periods=40)
    raw = dict(ts_code='000001.SZ', div_proc='实施', imp_ann_date=cal[10],
        record_date=cal[19], ex_date=cal[20], pay_date=cal[20], div_listdate=None,
        cash_div_tax='1', stk_div='0', stk_bo_rate=None)
    book = build_event_book(pd.DataFrame([raw, raw]), cal)
    assert len(book.versions) == 1
    assert book.versions[0]['equivalent_duplicate_count'] == 2
    missing = dict(raw, cash_div_tax=None)
    event = build_event_book(pd.DataFrame([missing]), cal).view(cal[20])[0]
    assert ordinary_reason(event, cal) == 'missing_or_invalid_ordinary_amount'


def test_proposal_date_does_not_replace_missing_implementation_publication():
    cal = pd.bdate_range('2017-01-02', periods=40)
    raw = dict(ts_code='000001.SZ', div_proc='实施', ann_date=cal[5], imp_ann_date=None,
               ex_date=cal[20], record_date=cal[19], cash_div_tax='1', stk_div='0')
    book = build_event_book(pd.DataFrame([raw]), cal)
    assert not book.view(cal[30])
    assert book.unknown_effective('000001.SZ', cal[20])


def test_frozen_revision_binding_and_cancel_identity():
    cal = pd.bdate_range('2017-01-02', periods=40)
    raw = dict(ts_code='000001.SZ', div_proc='实施', imp_ann_date=cal[10],
        record_date=cal[19], ex_date=cal[20], pay_date=cal[20], div_listdate=None,
        cash_div_tax='1', stk_div='0', stk_bo_rate=None)
    original = dict(code='000001.SZ', record=str(cal[19].date()), ex=str(cal[20].date()),
                    cash_pay=str(cal[20].date()), stock_pay=None, cash_per_share='1',
                    stock_per_share='0', taxable_bonus_per_share='0')
    versions = [dict(original, event_id='r5-original', known_date=str(cal[10].date()),
                     version=1, role='planned_distribution', original_action=original),
                dict(original, event_id='r5-original', known_date=str(cal[18].date()),
                     version=2, role='cancelled', original_action=original)]
    book = build_event_book(pd.DataFrame([raw]), cal, {'event_versions': versions})
    assert len({v['event_id'] for v in book.versions}) == 1
    assert book.view(cal[18])[0]['kind'] == 'ordinary'
    assert book.view(cal[19])[0]['kind'] == 'cancelled'


def test_unsupported_rights_registry_does_not_invent_publication():
    cal = pd.bdate_range('2017-01-02', periods=40)
    issue = dict(code='000001.SZ', record=cal[19], ex=cal[20], source='old annual registry')
    book = build_event_book(pd.DataFrame(), cal, rights=[issue])
    assert not book.view(cal[30])
    assert book.unknown_effective('000001.SZ', cal[20])[0]['role'] == 'rights_issue'


def test_half_cent_display_is_fixed_decimal_half_up():
    assert str(display_price('10.005')) == '10.01'
    assert str(display_price('10.0049999999')) == '10.00'


def test_inventory_roundtrip_preserves_publication_and_available_date():
    cal = pd.bdate_range('2017-01-02', periods=40)
    book = EventBook(cal, [fact(cal)])
    rebuilt = EventBook.from_inventory(cal, book.to_inventory())
    assert rebuilt.view(cal[11]) == book.view(cal[11])


def test_stock_component_conflict_is_not_hidden_by_total_rate():
    cal = pd.bdate_range('2017-01-02', periods=40)
    raw = dict(ts_code='000001.SZ', div_proc='实施', imp_ann_date=cal[10],
        record_date=cal[19], ex_date=cal[20], pay_date=None, div_listdate=cal[23],
        cash_div_tax='0', stk_div='.2', stk_bo_rate='.1', stk_co_rate='.2')
    event = build_event_book(pd.DataFrame([raw]), cal).view(cal[20])[0]
    assert event['kind'] == 'conflict' and event['reason'] == 'stock_total_component_conflict'


def test_mapping_parent_binding_checks_only_consumed_members(tmp_path):
    mapping = tmp_path / 'evidence_mapping.json'
    mapping.write_text('{}', encoding='utf-8')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    prep = tmp_path / 'preparation_sha256.json'
    prep.write_text(json.dumps({mapping.name: sha(mapping), 'irrelevant_missing.csv': 'old'}), encoding='utf-8')
    parent = tmp_path / 'output_sha256.json'
    parent.write_text(json.dumps({mapping.name: sha(mapping), prep.name: sha(prep)}), encoding='utf-8')
    paths = bound_source_inputs({}, mapping)
    assert set(paths) == {str(mapping), str(prep), str(parent)}
    mapping.write_text('{"changed":true}', encoding='utf-8')
    with pytest.raises(ValueError, match='does not bind'):
        bound_source_inputs({}, mapping)
