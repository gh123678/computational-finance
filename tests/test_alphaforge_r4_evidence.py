from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import alphaforge_r4_evidence as mapping
from alphaforge_r4_evidence import build_evidence, known_state, overlay_rights, validate_actions
from quant_research.accounting import Action
from quant_research.rights import RightsIssue, verified_rights


@pytest.fixture(scope='module')
def evidence():
    return build_evidence()


@pytest.fixture
def actions():
    return [
        Action('000756.SZ', pd.Timestamp('2018-01-25'), pd.Timestamp('2018-01-26'),
               pd.Timestamp('2018-01-26'), pd.NaT, .03),
        Action('600309.SH', pd.Timestamp('2018-01-25'), pd.Timestamp('2018-01-26'),
               pd.Timestamp('2018-01-26'), pd.NaT, 1.5),
        Action('600226.SH', pd.Timestamp('2018-03-23'), pd.Timestamp('2018-03-26'),
               pd.NaT, pd.Timestamp('2018-03-27'), 0., .3, 0.),
    ]


@pytest.fixture
def calendar():
    return pd.bdate_range('2017-01-01', '2021-01-01')


def test_frozen_sources_build_json_with_only_approved_scope(evidence):
    detached = json.loads(json.dumps(evidence))
    assert detached['evidence_manifest_sha256'] == mapping.EVIDENCE_MANIFEST_SHA256
    assert {(item['code'], item['ex']) for item in detached['ordinary_actions']} == {
        ('000756.SZ', '2018-01-26'), ('600309.SH', '2018-01-26'), ('600226.SH', '2018-03-26')}
    assert len({item['code'] for item in detached['status_events']}) == 9
    assert detached['source_facts']['date_conflicts'][0]['printed_date'] == '2020-01-05'
    assert '600677' in '\n'.join(detached['limitations'])
    assert len(detached['source_facts']['source_files']) == 32


def test_source_hashes_bind_actual_files_and_original_manifest(evidence):
    root = Path(evidence['evidence_root'])
    for relative, expected in evidence['source_facts']['source_files'].items():
        with (root / relative).open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected
    assert mapping._sha(root / 'output_sha256.json') == mapping.EVIDENCE_MANIFEST_SHA256


@pytest.mark.parametrize('filename', ['output_sha256.json', 'event_evidence_queue.csv',
                                     '000760_initial_20200706_complete_attempt2.pdf'])
def test_changed_source_fingerprint_is_rejected_without_modifying_old_files(monkeypatch, filename):
    original = mapping._sha
    monkeypatch.setattr(mapping, '_sha', lambda path: '0' * 64 if Path(path).name == filename else original(path))
    with pytest.raises(ValueError, match='fingerprint changed'):
        build_evidence()


def test_exact_three_original_actions_match_without_modification(evidence, actions, calendar):
    before = list(actions)
    results = validate_actions(iter(actions), evidence, calendar)
    assert len(results) == 3
    assert all(item['passed'] and item['record_ex_adjacent'] for item in results)
    assert actions == before
    capital = next(item for item in evidence['ordinary_actions'] if item['code'] == '600226.SH')
    assert capital['stock_pay'] == '2018-03-27'
    assert capital['stock_pay_semantics'] == 'listing_release_not_certified_custody_receipt'
    assert capital['taxable_bonus_per_share'] == '0'


@pytest.mark.parametrize('index,changes', [
    (0, {'cash_per_share': .030000000000000002}),
    (0, {'cash_pay': pd.Timestamp('2018-01-29')}),
    (0, {'stock_pay': pd.Timestamp('2018-01-26')}),
    (1, {'record': pd.Timestamp('2018-01-24')}),
    (1, {'ex': pd.Timestamp('2018-01-29'), 'cash_pay': pd.Timestamp('2018-01-29')}),
    (2, {'stock_per_share': .29999999999999993}),
    (2, {'stock_pay': pd.Timestamp('2018-03-28')}),
    (2, {'taxable_bonus_per_share': .3}),
])
def test_action_terms_are_exact_no_tolerance_or_date_repair(evidence, actions, calendar, index, changes):
    actions[index] = replace(actions[index], **changes)
    with pytest.raises(ValueError, match='conflicts|missing'):
        validate_actions(actions, evidence, calendar)


def test_nonadjacent_record_ex_stops_even_when_original_matches_source(evidence, actions, calendar):
    # Artificially insert an open session between the frozen Friday and Monday.
    altered = calendar.union(pd.DatetimeIndex(['2018-03-24']))
    with pytest.raises(ValueError, match='adjacent open'):
        validate_actions(actions, evidence, altered)


def test_missing_or_duplicate_approved_action_stops(evidence, actions, calendar):
    for altered in [actions[:-1], actions + [actions[0]]]:
        with pytest.raises(ValueError, match='missing or duplicated'):
            validate_actions(altered, evidence, calendar)


def test_special_distribution_cannot_be_allowlisted(evidence, actions, calendar):
    altered = deepcopy(evidence)
    altered['ordinary_actions'][0]['special_distribution'] = True
    with pytest.raises(ValueError, match='Special or unsourced'):
        validate_actions(actions, altered, calendar)


def test_later_restore_changes_state_only_when_public_and_effective(evidence):
    earlier = known_state('000629.SZ', '2018-08-15', evidence)
    announced_but_not_effective = known_state('000629.SZ', '2018-08-23', evidence)
    restored = known_state('000629.SZ', '2018-08-24', evidence)
    assert earlier['state'] == announced_but_not_effective['state'] == 'suspended_listing'
    assert earlier['end_date'] is None
    assert '2018-08-24' not in json.dumps(earlier)
    assert restored['state'] == 'listed' and restored['pre_open_known']


def test_received_date_is_not_public_date_for_000950(evidence):
    earlier = known_state('000950.SZ', '2018-08-07', evidence)
    same_day = known_state('000950.SZ', '2018-08-28', evidence)
    assert earlier['state'] == 'suspended_listing'
    assert same_day['state'] == 'listed'
    assert not same_day['pre_open_known']
    assert same_day['certainty'] == 'publication_time_uncertain'


def test_000760_same_day_pause_cannot_use_printed_date_or_prior_halt_bypass(evidence):
    initial = known_state('000760.SZ', '2020-07-06', evidence)
    assert initial['state'] == 'suspended_listing'
    assert initial['known_date'] == '2020-07-06'
    assert initial['printed_date'] == initial['decision_received_date'] == '2020-07-03'
    assert not initial['usable_for_missing_quote'] and not initial['pre_open_known']
    next_day = known_state('000760.SZ', '2020-07-07', evidence)
    assert next_day['usable_for_missing_quote']


def test_earlier_halt_is_not_backfilled_before_its_publication(evidence):
    assert known_state('000760.SZ', '2020-06-18', evidence) is None
    assert not known_state('000760.SZ', '2020-06-19', evidence)['usable_for_missing_quote']
    assert known_state('000760.SZ', '2020-06-22', evidence)['state'] == 'suspended_trading'
    assert known_state('000792.SZ', '2020-05-18', evidence) is None


def test_later_002680_delisting_board_does_not_create_normal_restoration(evidence):
    earlier = known_state('002680.SZ', '2019-10-16', evidence)
    assert earlier['state'] == 'suspended_listing'
    assert earlier['end_date'] is None
    later = known_state('002680.SZ', '2019-11-28', evidence)
    assert later['state'] == 'delisted'
    events = [item for item in evidence['status_events'] if item['code'] == '002680.SZ']
    assert not any(item['state'] == 'listed' for item in events)
    assert next(item for item in events if item['state'] == 'delisting_board')['known_date'] == '2019-11-27'


def test_later_publication_perturbation_cannot_change_earlier_state(evidence):
    earlier = known_state('000760.SZ', '2020-12-31', evidence)
    altered = deepcopy(evidence)
    for item in altered['status_events']:
        if item['known_date'] > '2020-12-31':
            item.update(effective_date='2017-01-01', state='listed', printed_date='2017-01-01')
    assert known_state('000760.SZ', '2020-12-31', altered) == earlier
    earlier['state'] = 'changed_by_consumer'
    assert known_state('000760.SZ', '2020-12-31', evidence)['state'] == 'suspended_listing'


def test_600677_unknown_endpoint_and_000760_printed_year_conflict_survive(evidence):
    state = known_state('600677.SH', '2020-12-31', evidence)
    assert state['end_date'] is None
    assert not state['daily_status_coverage_certified']
    assert '期末' in state['limitations']
    after = known_state('000760.SZ', '2021-01-07', evidence)
    assert after['printed_date'] == '2020-01-05'
    assert after['date_conflict']['resolution'].startswith('unresolved')


def test_rights_overlay_leaves_original_terms_and_list_untouched(evidence):
    old = verified_rights()
    original = list(old)
    updated = overlay_rights(old, evidence)
    assert old == original and len(updated) == len(old) + 1
    for issue in old:
        assert any(item is issue for item in updated)
    new = next(item for item in updated if item.code == '600480.SH')
    assert new.record == pd.Timestamp('2019-06-11') and new.ex == pd.Timestamp('2019-06-20')
    assert (new.price, new.ratio, new.list_date) == (None, None, None)
    assert len(overlay_rights(updated, evidence)) == len(updated)
    terms = [item for item in old if item.price is not None]
    assert len(terms) == 2
    assert [(item.price, item.ratio, item.list_date) for item in updated if item.price is not None] == [
        (item.price, item.ratio, item.list_date) for item in terms]


def test_market_aggregate_and_later_listing_remain_source_facts_not_personal_entitlement(evidence):
    facts = evidence['source_facts']['rights_600480']
    assert facts['subscription_price'] == '8.74'
    assert facts['nominal_entitlement_ratio'] == '0.3'
    assert facts['new_issued_total'] == 95584568
    assert facts['unrestricted_new_share_list_date'] == '2019-07-03'
    assert evidence['rights_overlay'][0]['ratio'] is None
    assert evidence['rights_overlay'][0]['list_date'] is None
    assert not evidence['rights_overlay'][0]['usable_for_formation_eligibility']


def test_injected_rights_terms_or_conflicting_old_event_stop(evidence):
    changed = deepcopy(evidence)
    changed['rights_overlay'][0]['ratio'] = .2100432133
    with pytest.raises(ValueError, match='cannot inject'):
        overlay_rights([], changed)
    conflict = RightsIssue('600480.SH', pd.Timestamp('2019-06-10'), pd.Timestamp('2019-06-20'), 'old')
    with pytest.raises(ValueError, match='conflicts'):
        overlay_rights([conflict], evidence)
    terms = RightsIssue('600480.SH', pd.Timestamp('2019-06-11'), pd.Timestamp('2019-06-20'),
                        'old', 8.74, .3, pd.Timestamp('2019-07-03'))
    with pytest.raises(ValueError, match='subscription terms conflict'):
        overlay_rights([terms], evidence)
