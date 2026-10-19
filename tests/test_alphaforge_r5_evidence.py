from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import alphaforge_r4_evidence as old
import alphaforge_r5_evidence as mapping
from quant_research.accounting import Action
from quant_research.rights import verified_rights


@pytest.fixture(scope='module')
def evidence():
    return mapping.build_evidence()


def actions_from(evidence):
    return [Action(r['code'],pd.Timestamp(r['record']),pd.Timestamp(r['ex']),
        pd.NaT if r['cash_pay'] is None else pd.Timestamp(r['cash_pay']),
        pd.NaT if r['stock_pay'] is None else pd.Timestamp(r['stock_pay']),
        float(r['cash_per_share']),float(r['stock_per_share']),float(r['taxable_bonus_per_share']))
        for r in evidence['ordinary_actions']]


def test_exact_23_source_scope_and_original_overlays_preserved(evidence):
    prior = old.build_evidence()
    assert len(evidence['ordinary_actions']) == 23
    assert {(r['code'],r['ex']) for r in evidence['ordinary_actions']} == mapping.APPROVED_CASH_KEYS | mapping.OLD_APPROVED_KEYS
    assert evidence['status_events'] == prior['status_events']
    assert len({r['code'] for r in evidence['status_events']}) == 9
    assert evidence['rights_overlay'] == prior['rights_overlay']
    assert [r for r in evidence['ordinary_actions'] if (r['code'],r['ex']) in mapping.OLD_APPROVED_KEYS] == prior['ordinary_actions']
    keys = {(r['code'],r['ex']) for r in evidence['ordinary_actions']}
    assert not keys & mapping.UNSUPPORTED_CAPITALIZATION_KEYS
    assert ('002470.SZ','2018-06-19') not in keys
    assert evidence['source_facts']['capitalization_origin_remains_unknown']


def test_every_consumed_absolute_file_is_bound_with_parent_and_submanifests(evidence):
    files = mapping.source_inputs(evidence)
    assert len(files) >= 98
    assert all(Path(path).is_absolute() and mapping._sha(path) == sha for path,sha in files.items())
    assert files[(mapping.EVIDENCE_ROOT/'output_sha256.json').as_posix()] == mapping.EVIDENCE_MANIFEST_SHA256
    assert files[(mapping.EXTERNAL_ROOT/'output_sha256.json').as_posix()] == mapping.EXTERNAL_MANIFEST_SHA256
    assert files[(mapping.ORIGIN_ROOT/'output_sha256.json').as_posix()] == mapping.ORIGIN_MANIFEST_SHA256
    assert files[(mapping.RIGHTS_600999_ROOT/'output_sha256.json').as_posix()] == mapping.RIGHTS_600999_MANIFEST_SHA256
    for r in evidence['ordinary_actions']:
        assert all(files[s['path']] == s['sha256'] for s in r['sources'])


@pytest.mark.parametrize('filename',['output_sha256.json','source_facts.json','1205273340.pdf','000977_1207403957.pdf','600999_1208080267.pdf'])
def test_source_changes_fail_without_editing_any_old_file(monkeypatch,filename):
    sha = mapping._sha
    monkeypatch.setattr(mapping,'_sha',lambda p:'0'*64 if Path(p).name == filename else sha(p))
    with pytest.raises(ValueError,match='fingerprint changed'):
        mapping.build_evidence()


def test_all_original_fields_exact_and_cash_amount_not_inferred_from_key_list(evidence):
    actions = actions_from(evidence)
    calendar = pd.bdate_range('2017-01-01','2021-01-01')
    assert len(mapping.validate_actions(actions,evidence,calendar)) == 23
    action = next(a for a in actions if a.code == '000426.SZ')
    assert action.cash_per_share == .019902 and action.stock_per_share == 0
    assert next(r for r in evidence['ordinary_actions'] if r['code']=='600282.SH')['cash_per_share'] == '0.3'
    altered = [replace(a,cash_per_share=.02) if a is action else a for a in actions]
    with pytest.raises(ValueError,match='conflicts with original field'):
        mapping.validate_actions(altered,evidence,calendar)


@pytest.mark.parametrize('mutate',[
    lambda rows:rows[:-1],
    lambda rows:rows+[rows[0]],
    lambda rows:[replace(rows[0],taxable_bonus_per_share=.1),*rows[1:]],
])
def test_missing_duplicate_or_changed_original_stops(evidence,mutate):
    with pytest.raises(ValueError,match='missing or duplicated|conflicts'):
        mapping.validate_actions(mutate(actions_from(evidence)),evidence,pd.bdate_range('2017','2021'))


def test_source_scope_cannot_silently_expand_or_split_mixed_action(evidence):
    changed = deepcopy(evidence)
    changed['ordinary_actions'].append(dict(changed['ordinary_actions'][0],code='002856.SZ',ex='2018-06-20'))
    with pytest.raises(ValueError,match='Exactly 23'):
        mapping.validate_actions(actions_from(evidence),changed,pd.bdate_range('2017','2021'))


def test_source_versions_keep_exact_original_identity_and_separate_roles(evidence):
    versions = evidence['event_versions']
    cancel = next(v for v in versions if v['role']=='cancelled')
    special = next(v for v in versions if v['role']=='special_reorganization')
    assert cancel['known_date']=='2019-07-20' and cancel['printed_date']=='2019-07-19'
    assert cancel['original_action']['record']=='2019-07-19'
    assert cancel['original_action']['ex']=='2019-07-22'
    assert not cancel['apply_distribution'] and not cancel['reference_explained']
    assert special['stock_per_share']=='0'
    assert special['original_action']['stock_per_share']=='0.5641598'
    assert special['company_total_expansion_per_old_total_share']=='0.5641598'
    assert special['unsupported_special'] and not special['ordinary']


def test_original_rights_objects_unchanged_and_600480_remains_date_only(evidence):
    rights = verified_rights()
    updated = mapping.overlay_rights(rights,evidence)
    assert all(any(old_issue is issue for issue in updated) for old_issue in rights)
    issue977 = next(i for i in updated if i.code=='000977.SZ' and i.ex.year==2020)
    assert issue977.ratio == .1177945
    issue480 = next(i for i in updated if i.code=='600480.SH')
    assert (issue480.price,issue480.ratio,issue480.list_date)==(None,None,None)
