from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest

from alphaforge_r5_evidence import build_evidence
from alphaforge_r5_events import distribution_view, rights_stage, audit_internal_reference_bridges
from quant_research.accounting import Action
from quant_research.rights import RightsIssue, verified_rights


@pytest.fixture(scope='module')
def evidence():
    return build_evidence()


def cancelled_action():
    return Action('600781.SH',pd.Timestamp('2019-07-19'),pd.Timestamp('2019-07-22'),pd.Timestamp('2019-07-22'),pd.NaT,.1)


def special_action():
    return Action('601258.SH',pd.Timestamp('2019-12-27'),pd.Timestamp('2019-12-30'),pd.NaT,pd.Timestamp('2019-12-31'),0,.5641598)


def test_plan_registration_preserved_until_later_cancel_version(evidence):
    action = cancelled_action()
    prior = distribution_view(action,'2019-07-19',evidence)
    assert prior['role']=='planned_distribution' and prior['apply_distribution']
    assert all(s['known_date'] <= '2019-07-19' for s in prior['sources'])
    same = distribution_view(action,'2019-07-20',evidence)
    assert same['role']=='cancelled' and not same['pre_open_known']
    final = distribution_view(action,'2019-07-22',evidence)
    assert final['pre_open_known'] and not final['apply_distribution'] and not final['reference_explained']
    assert action.cash_per_share==.1 and action.record==pd.Timestamp('2019-07-19')


def test_future_cancellation_perturbation_cannot_erase_earlier_plan(evidence):
    changed = deepcopy(evidence)
    for v in changed['event_versions']:
        if v['known_date'] > '2019-07-19':
            v.update(role='bad_future_mutation',apply_distribution=False,record='2017-01-01')
    assert distribution_view(cancelled_action(),'2019-07-19',changed)==distribution_view(cancelled_action(),'2019-07-19',evidence)


def test_wrong_original_tuple_rejected_and_consumers_cannot_mutate_versions(evidence):
    with pytest.raises(ValueError,match='does not bind original action'):
        distribution_view(replace(cancelled_action(),cash_per_share=.2),'2019-07-22',evidence)
    view = distribution_view(special_action(),'2019-12-30',evidence)
    view['sources'][0]['sha256']='bad'
    assert distribution_view(special_action(),'2019-12-30',evidence)['sources'][0]['sha256']!='bad'


def test_special_reorganization_never_becomes_ordinary_holder_bonus(evidence):
    prior = distribution_view(special_action(),'2019-12-23',evidence)
    known = distribution_view(special_action(),'2019-12-30',evidence)
    assert prior['role']=='original_distribution'
    assert known['role']=='special_reorganization' and known['unsupported_special']
    assert known['stock_per_share']=='0' and not known['apply_distribution'] and not known['reference_explained']


def issue977():
    return next(i for i in verified_rights() if i.code=='000977.SZ' and i.ex.year==2020)


def test_personal_quota_market_ratio_and_future_listing_are_separate(evidence):
    issue = issue977()
    subscription = rights_stage(issue,'2020-03-19',evidence,'subscription')
    assert subscription['stage_usable']
    assert subscription['price']==12.92 and subscription['quota_ratio']==.12
    assert subscription['market_ex_ratio'] is None
    assert subscription['list_date'] is None and subscription['listing_known_date'] is None
    assert not subscription['personal_actual_allocation_certified']
    assert int(1200*subscription['quota_ratio'])==144 and int(500*subscription['quota_ratio'])==60
    assert issue.ratio==.1177945 and issue.list_date==pd.Timestamp('2020-03-27')
    assert all(s['known_date'] < '2020-03-19' for s in subscription['sources'])
    close = rights_stage(issue,'2020-03-19',evidence,'subscription',timing='close')
    assert close['market_ex_ratio']=='.1177945'
    listing_same = rights_stage(issue,'2020-03-26',evidence,'listing')
    assert not listing_same['stage_usable'] and listing_same['list_date'] is None
    listing = rights_stage(issue,'2020-03-27',evidence,'listing')
    assert listing['stage_usable'] and listing['list_date']=='2020-03-27'


def test_future_listing_mutation_cannot_prefill_pending_obligation(evidence):
    altered = deepcopy(evidence)
    fact = next(s for s in altered['rights_stages'] if s['code']=='000977.SZ')
    fact['list_date']='2020-03-20'
    for s in fact['sources']:
        if s['role']=='listing': s['url']='future-mutated'
    assert rights_stage(issue977(),'2020-03-19',altered,'subscription')==rights_stage(issue977(),'2020-03-19',evidence,'subscription')


def test_subscribed_real_issue_original_identity_cannot_be_rewritten(evidence):
    with pytest.raises(ValueError,match='does not bind original rights'):
        rights_stage(replace(issue977(),ratio=.12),'2020-03-19',evidence,'subscription')
    unknown=RightsIssue('600001.SH',pd.Timestamp('2020-01-01'),pd.Timestamp('2020-01-02'),'not-authorized',1,.3,pd.Timestamp('2020-01-06'))
    assert not rights_stage(unknown,'2020-01-02',evidence,'subscription')['stage_usable']


def test_stage_source_unknown_fails_closed_and_no_new_subscriptions(evidence):
    too_early=rights_stage(issue977(),'2020-03-06',evidence,'record')
    assert not too_early['stage_usable'] and too_early['price'] is None
    missing = deepcopy(evidence)
    missing['rights_stages']=[]
    issue999=next(i for i in verified_rights() if i.code=='600999.SH')
    assert not rights_stage(issue999,'2020-07-20',missing,'subscription')['stage_usable']
    no_terms=next(i for i in verified_rights() if i.code=='600008.SH')
    stage=rights_stage(no_terms,'2020-10-01',evidence,'subscription')
    assert stage['stage_usable'] and stage['price'] is None and stage['quota_ratio'] is None
    assert stage['list_date'] is None


def test_generic_original_fixtures_keep_old_terms(evidence):
    generic=RightsIssue('A',pd.Timestamp('2020-01-01'),pd.Timestamp('2020-01-02'),'fixture',1,.3,pd.Timestamp('2020-01-06'))
    assert rights_stage(generic,'2020-01-02',evidence,'subscription')['stage_usable']
    assert rights_stage(generic,'2020-01-02',evidence,'subscription')['quota_ratio']==.3


def test_600999_prior_issuance_preserves_terms_and_later_listing_is_not_prefilled(evidence):
    issue=next(i for i in verified_rights() if i.code=='600999.SH')
    view=rights_stage(issue,'2020-07-20',evidence,'subscription')
    assert view['stage_usable'] and view['terms_known_date']=='2020-07-07'
    assert view['price']==7.46 and view['quota_ratio']==.3
    assert view['result_known_date'] is None and view['market_ex_ratio'] is None
    assert view['list_date'] is None and view['listing_known_date'] is None
    close=rights_stage(issue,'2020-07-20',evidence,'subscription',timing='close')
    assert close['result_known_date']=='2020-07-20' and close['market_ex_ratio'] is None
    assert rights_stage(issue,'2020-07-28',evidence,'listing')['list_date'] is None
    assert rights_stage(issue,'2020-07-29',evidence,'listing')['list_date']=='2020-07-31'
    assert issue.ratio==.3 and issue.price==7.46 and issue.list_date==pd.Timestamp('2020-07-31')


def reference_fixture(code,ex,known,kind='cash',changed=True):
    calendar=pd.bdate_range(end=pd.Timestamp(ex),periods=24)
    bars=pd.DataFrame(dict(ts_code=code,trade_date=calendar,close_text='10',pre_close_text='10'))
    if changed: bars.loc[bars.trade_date.eq(pd.Timestamp(ex)),'pre_close_text']='9.9'
    forms=pd.DataFrame([dict(ts_code=code,trade_date=calendar[-1],case_factor=123.456)])
    labels=pd.DataFrame(columns=['ts_code','signal_date','execution_date','R_end','R_valid'])
    events=pd.DataFrame([dict(code=code,event_id='old-event',event_date=ex,known_date=known,timing_verified=True,kind=kind)])
    return bars,calendar,forms,labels,events


def test_all_20_internal_bridges_audited_and_cancelled_reference_break_stops(evidence):
    args=reference_fixture('600781.SH','2019-07-22','2019-07-16')
    original_forms=args[2].copy(deep=True)
    result=audit_internal_reference_bridges(*args,evidence)
    assert result['summary']['formation_bridges']==20
    assert not result['summary']['passed'] and result['summary']['accounts_started']==0
    row=result['failures'].iloc[0]
    assert row['reason']=='unexplained_reference_change'
    assert row.bridge_left==pd.Timestamp('2019-07-19') and row.bridge_right==pd.Timestamp('2019-07-22')
    assert row.cutoff==pd.Timestamp('2019-07-22') and 'cancelled' in row.source_versions
    pd.testing.assert_frame_equal(args[2],original_forms)


def test_no_cancelled_break_and_first_point_reference_ignored(evidence):
    args=reference_fixture('600781.SH','2019-07-22','2019-07-16',changed=False)
    args[0].loc[3,'pre_close_text']='1'
    result=audit_internal_reference_bridges(*args,evidence)
    assert result['summary']['passed'] and result['summary']['formation_bridges']==20


def test_special_reference_contact_stops_even_continuous_quoted_prices(evidence):
    args=reference_fixture('601258.SH','2019-12-30','2019-12-24',kind='stock',changed=False)
    result=audit_internal_reference_bridges(*args,evidence)
    assert not result['summary']['passed']
    assert result['failures'].iloc[0].reason=='unsupported_special_reorganization_reference_bridge'


def test_unrelated_reference_break_still_stops_and_unknown_tax_does_not_add_quoted_gate(evidence):
    args=reference_fixture('002856.SZ','2018-06-20','2018-06-13',kind='cash_and_stock')
    assert audit_internal_reference_bridges(*args,evidence)['summary']['passed']
    args[0].loc[10,'pre_close_text']='7'
    assert not audit_internal_reference_bridges(*args,evidence)['summary']['passed']


def test_original_invalid_label_kept_diagnostic_and_label_uses_each_endpoint(evidence):
    args=reference_fixture('600781.SH','2019-07-22','2019-07-16')
    bars,calendar,forms,_,events=args
    labels=pd.DataFrame([dict(ts_code='600781.SH',signal_date='2019-07-18',execution_date='2019-07-19',R_end='2019-07-22',R_valid=False,R_week=float('nan'))])
    empty_forms=forms.iloc[:0]
    result=audit_internal_reference_bridges(bars,calendar,empty_forms,labels,events,evidence)
    assert result['summary']['passed']
    assert result['summary']['original_invalid_label_keys']==1 and result['summary']['label_bridges']==1
    assert result['summary']['diagnostic_invalid_label_bridges']==1
    assert result['trace'].iloc[0].cutoff==pd.Timestamp('2019-07-22')
    labels.loc[0,'R_valid']=True
    assert not audit_internal_reference_bridges(bars,calendar,empty_forms,labels,events,evidence)['summary']['passed']


def test_later_formation_knowledge_does_not_enter_earlier_label_endpoint(evidence):
    altered=deepcopy(evidence)
    cancellation=next(v for v in altered['event_versions'] if v['role']=='cancelled')
    cancellation['known_date']='2019-07-23'
    cancellation['sources'][0]['known_date']='2019-07-23'
    bars,calendar,forms,_,events=reference_fixture('600781.SH','2019-07-22','2019-07-16')
    labels=pd.DataFrame([dict(ts_code='600781.SH',signal_date='2019-07-18',execution_date='2019-07-19',R_end='2019-07-22',R_valid=True)])
    result=audit_internal_reference_bridges(bars,calendar,forms.iloc[:0],labels,events,altered)
    assert result['summary']['passed'] and result['summary']['label_bridges']==1
    assert 'planned_distribution' in result['trace'].iloc[0].source_versions
