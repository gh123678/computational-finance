"""Economic regression cases for the separately approved r5 account adapter."""
from copy import deepcopy
from dataclasses import asdict
import json
import math

import pandas as pd
import pytest

from alphaforge_r5_account import Ledger, simulate_exposure, AccountRunFailure
from alphaforge_r5_evidence import build_evidence
from alphaforge_r5_guard import prune_prices, share_price_scope
from quant_research.accounting import Action
from quant_research.backtest import Config, simulate
from quant_research.rights import RightsIssue


@pytest.fixture(scope='module')
def evidence():
    return build_evidence()


def case(code='A', start='2020-01-02', end='2020-01-17', price=10., initial=10000.):
    dates = pd.bdate_range(start, end)
    bars = pd.DataFrame(dict(trade_date=dates, ts_code=code, open=price, high=price,
        low=price, close=price, vol=100000., amount=30000., up_limit=100., down_limit=.01,
        close_text=str(price), pre_close_text=str(price)))
    targets = pd.DataFrame([dict(execution_date=dates[2],signal_date=dates[1],
                                ts_code=code,target_weight=.5)])
    return dict(bars=bars,calendar=dates,targets=targets,universe=pd.DataFrame([
        dict(ts_code=code,list_date='20100101',delist_date=None)]),full_calendar=dates,
        evidence=dict(ordinary_actions=[],status_events=[]),
        config=Config(initial_cash=initial,zero_trading_costs=True))


def run(item, **kwargs):
    return simulate_exposure(**dict(item, **kwargs))


def action_from(row):
    return Action(**{k:pd.NaT if v is None else pd.Timestamp(v) if k in
        ('record','ex','cash_pay','stock_pay') else float(v) if k.endswith('_per_share') else v
        for k,v in row.items()})


def corrected_case(evidence, code, ex):
    item = next(x for x in evidence['event_versions'] if x['code']==code and x['ex']==ex)
    return action_from(item['original_action'])


@pytest.mark.parametrize('bps',[0,10,30])
def test_original_cash_fees_capacity_and_target_execution_preserved(bps):
    data=case(); dates=data['calendar']
    data['targets'].loc[1]=[dates[5],dates[4],'A',.3]
    data['config']=Config(initial_cash=10000.,slippage_bps=bps,zero_trading_costs=bps==0)
    result=run(data)
    old=simulate(data['bars'].assign(adj_factor=1.),dates,data['targets'],config=data['config'])
    for name in ('nav','orders','holdings','corporate_events'):
        if not old[name].empty:
            pd.testing.assert_frame_equal(result[name][old[name].columns],old[name])


@pytest.mark.parametrize('quoted',[True,False])
def test_cancelled_plan_keeps_research_record_without_cash_pending_or_ex_mark(evidence, quoted):
    data=case('600781.SH','2019-07-15','2019-07-24');data['evidence']=evidence
    action=corrected_case(evidence,'600781.SH','2019-07-22')
    if not quoted:
        data['bars']=data['bars'].loc[data['bars'].trade_date.ne(action.ex)]
        data['suspensions']={(action.ex,action.code)}
    result=run(data,actions=[action])
    assert result['corporate_events'].event.tolist()==[
        'distribution_research_record','distribution_cancelled']
    record,cancel=result['corporate_events'].to_dict('records')
    assert record['date']==action.record and cancel['date']==action.ex
    assert record['entitled_shares']==500 and cancel['entitled_shares']==500
    assert not result['nav'].cash.eq(5000.).all()  # cash before entry remains initial
    assert result['nav'].iloc[-1].cash==5000. and result['nav'].receivable.eq(0).all()
    assert result['nav'].equity.eq(10000.).all()
    assert result['account_state']['pending']==[]
    assert result['account_state']['unapplied_distributions']==[]
    assert result['account_state']['scenario_entitlements'][0]['status']=='cancelled'
    ledger=Ledger(evidence=evidence);ledger.positions[action.code]=500;ledger.prices[action.code]=10.
    ledger.record(action.record,[action]);ledger.prepare_day(action.ex,[action],())
    ledger.morning(action.ex,[action])
    assert action not in ledger.applied and ledger.prices[action.code]==10.


def test_future_cancellation_never_rewrites_earlier_research_record(evidence):
    data=case('600781.SH','2019-07-15','2019-07-19');data['evidence']=evidence
    action=corrected_case(evidence,'600781.SH','2019-07-22')
    baseline=run(data,actions=[action])
    changed=deepcopy(evidence)
    version=next(v for v in changed['event_versions'] if v['role']=='cancelled')
    version['known_date']='2030-01-01';version['sources']=[]
    altered=run(dict(data,evidence=changed),actions=[action])
    pd.testing.assert_frame_equal(baseline['corporate_events'],altered['corporate_events'])
    assert baseline['account_state']==altered['account_state']
    assert baseline['account_state']['scenario_entitlements'][0]['status']=='planned'


def test_cancelled_plan_cannot_explain_a_ghost_price_break(evidence):
    data=case('600781.SH','2019-07-15','2019-07-24');data['evidence']=evidence
    action=corrected_case(evidence,'600781.SH','2019-07-22')
    data['bars'].loc[data['bars'].trade_date.eq(action.ex),'pre_close_text']='9.9'
    with pytest.raises(AccountRunFailure,match='unexplained_reference_change') as failure:
        run(data,actions=[action])
    assert failure.value.partial['nav'].date.max()==action.record
    assert failure.value.partial['failure_state']['pending']==[]
    assert failure.value.partial['failure_day_corporate_events'].event.tolist()==['distribution_cancelled']


@pytest.mark.parametrize('quoted',[True,False])
def test_special_reorganization_account_stops_before_record_or_phantom_shares(evidence, quoted):
    data=case('601258.SH','2019-12-23','2019-12-31');data['evidence']=evidence
    action=corrected_case(evidence,'601258.SH','2019-12-30')
    if not quoted:
        data['bars']=data['bars'].loc[data['bars'].trade_date.ne(action.record)]
    with pytest.raises(AccountRunFailure,match='unsupported_special_reorganization_exposure_or_plan') as failure:
        run(data,actions=[action])
    assert failure.value.date==action.record
    partial=failure.value.partial
    assert partial['account_state']['positions']=={action.code:500}
    assert partial['account_state']['prices']=={action.code:10.}
    assert partial['account_state']['pending']==[]
    assert partial['corporate_events'].empty and partial['nav'].date.max()<action.record
    assert failure.value.original.row['has_quote']==quoted


def rights_case(evidence, price=20., initial=30000., end='2020-03-30'):
    data=case('000977.SZ','2020-03-04',end,price,initial);data['evidence']=evidence
    issue=RightsIssue('000977.SZ',pd.Timestamp('2020-03-10'),pd.Timestamp('2020-03-19'),
        'immutable original result provenance',price=12.92,ratio=.1177945,list_date=pd.Timestamp('2020-03-27'))
    return data,issue


def test_personal_quota_and_floor_use_issuance_without_future_market_or_listing_fact(evidence):
    data,issue=rights_case(evidence,end='2020-03-19')
    # A separately recorded small bonus produces an odd holding; floor remains
    # a research approximation, rather than a claim of certified custody shares.
    dates=data['calendar']; data['targets'].loc[0,['execution_date','signal_date']]=[dates[1],dates[0]]
    bonus=Action(issue.code,dates[1],dates[2],pd.NaT,dates[2],0.,.005,0.)
    result=run(data,rights=[issue],actions=[bonus])
    subscribed=result['corporate_events'].loc[result['corporate_events'].event.eq('rights_subscribed')].iloc[0]
    assert subscribed.entitled_shares==703
    assert subscribed.ratio==.12 and subscribed.allotted_shares==math.floor(703*.12)==84
    assert subscribed.allotted_shares!=math.floor(703*.1177945)
    assert pd.isna(subscribed.market_ex_ratio) and pd.isna(subscribed.list_date)
    assert subscribed.original_source==issue.source
    admitted=json.loads(subscribed.stage_sources)
    assert admitted and {source['role'] for source in admitted}=={'issuance'}
    assert all(source['known_date']<'2020-03-19' for source in admitted)
    assert subscribed.research_scenario=='ex_date_subscription_floor_not_custody'
    assert not subscribed.personal_actual_allocation_certified
    pending=result['account_state']['pending'][0]
    assert pending['stock_pay'] is None and pending['listing_known_date'] is None
    assert pending['market_ex_ratio'] is None and pending['quota_ratio']==.12
    assert result['nav'].iloc[-1].bonus_value==84*20.


def test_pending_listing_is_unknown_until_publication_and_t_plus_one_lock_is_retained(evidence):
    data,issue=rights_case(evidence)
    data['targets'].loc[1]=[pd.Timestamp('2020-03-27'),pd.Timestamp('2020-03-26'),issue.code,0.]
    data['targets'].loc[2]=[pd.Timestamp('2020-03-30'),pd.Timestamp('2020-03-27'),issue.code,0.]
    result=run(data,rights=[issue])
    updated=result['corporate_events'].loc[result['corporate_events'].event.eq('rights_listing_date_known')].iloc[0]
    assert updated.date==pd.Timestamp('2020-03-27') and updated.listing_known_date=='2020-03-26'
    assert updated.list_date=='2020-03-27'
    release=result['corporate_events'].loc[result['corporate_events'].event.eq('stock_settlement')].iloc[0]
    assert release.date==pd.Timestamp('2020-03-27')
    listed=result['holdings'].loc[result['holdings'].date.eq(release.date)].iloc[0]
    assert listed.shares==84 and listed.pending_shares==0
    assert result['account_state']['positions']=={}


def test_future_listing_perturbation_does_not_prefill_earlier_pending(evidence):
    data,issue=rights_case(evidence,end='2020-03-26');baseline=run(data,rights=[issue])
    changed=deepcopy(evidence)
    stage=next(v for v in changed['rights_stages'] if v['code']==issue.code)
    stage['list_date']='2020-03-26'
    altered=run(dict(data,evidence=changed),rights=[issue])
    assert baseline['account_state']==altered['account_state']
    pd.testing.assert_frame_equal(baseline['corporate_events'],altered['corporate_events'])
    assert baseline['account_state']['pending'][0]['stock_pay'] is None


def test_insufficient_cash_rejects_the_whole_original_subscription_scenario(evidence):
    data,issue=rights_case(evidence,price=5.,initial=10000.)
    data['targets'].loc[0,'target_weight']=.9
    result=run(data,rights=[issue])
    event=result['corporate_events'].loc[result['corporate_events'].event.eq('rights_not_subscribed')].iloc[0]
    assert event.reason=='insufficient_cash'
    assert result['account_state']['pending']==[]
    assert 'rights_subscribed' not in set(result['corporate_events'].event)


def test_other_newly_sourced_rights_keep_the_original_no_subscription_scenario(evidence):
    data=case('601162.SH','2020-03-04','2020-03-30');data['evidence']=evidence
    issue=RightsIssue('601162.SH',pd.Timestamp('2020-03-10'),pd.Timestamp('2020-03-19'),'original')
    result=run(data,rights=[issue])
    event=result['corporate_events'].iloc[0]
    assert event.event=='rights_not_subscribed'
    assert result['account_state']['pending']==[]
    assert result['account_state']['positions']=={issue.code:500}
    assert result['nav'].iloc[-1].cash==5000.


def test_unbound_full_terms_stage_stops_without_future_source_substitution():
    data=case('600999.SH','2020-07-06','2020-07-24')
    issue=RightsIssue('600999.SH',pd.Timestamp('2020-07-09'),pd.Timestamp('2020-07-20'),'unbound future listing',
        price=7.46,ratio=.3,list_date=pd.Timestamp('2020-07-31'))
    with pytest.raises(AccountRunFailure,match='rights_record_source_not_usable_asof') as failure:
        run(data,rights=[issue])
    assert failure.value.date==issue.record
    assert failure.value.partial['account_state']['pending']==[]
    assert failure.value.original.row['stage_reason']=='missing_bound_rights_stage_source'


def test_receivable_survives_sale_and_cache_contains_only_share_exposure():
    data=case();dates=data['calendar'];action=Action('A',dates[3],dates[4],dates[8],pd.NaT,1.)
    data['targets'].loc[1]=[dates[4],dates[3],'A',0.]
    mask=data['bars'].trade_date.ge(action.ex)
    data['bars'].loc[mask,['open','high','low','close']]=9.
    data['bars'].loc[mask,['close_text','pre_close_text']]='9.0'
    result=run(data,actions=[action])
    ex=result['nav'].loc[result['nav'].date.eq(action.ex)].iloc[0]
    assert ex.stock_value==0 and ex.receivable==400.
    assert result['account_state']['prices']=={} and result['nav'].iloc[-1].receivable==0.
    ledger=Ledger(evidence=data['evidence']);ledger.positions['A']=500;ledger.prices['A']=10.
    bonus=Action('A',dates[3],dates[4],pd.NaT,dates[8],0.,.3)
    ledger.record(bonus.record,[bonus]);ledger.positions['A']=0
    prune_prices(ledger,[bonus]);assert share_price_scope(ledger,[bonus])=={'A'}
    assert ledger.prices['A']==10.


def test_empty_account_does_not_cache_unowned_or_invalid_quote():
    data=case();data['targets']=data['targets'].iloc[:0]
    data['bars'].loc[0,'pre_close_text']='INVALID'
    result=run(data)
    assert result['nav'].equity.eq(10000).all()
    assert result['holdings'].empty and result['account_state']['prices']=={}
