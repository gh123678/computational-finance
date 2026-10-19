"""As-of, quoted/unquoted and actual-exposure r5 guard boundary cases."""
from copy import deepcopy

import pandas as pd
import pytest

from alphaforge_r5_account import simulate_exposure
from alphaforge_r5_evidence import build_evidence
from alphaforge_r5_guard import ExposureGuard, AccountDataFailure
from quant_research.accounting import Action, Ledger
from quant_research.backtest import Config
from quant_research.rights import RightsIssue


@pytest.fixture(scope='module')
def evidence():
    return build_evidence()


def action_from(row):
    return Action(**{k:pd.NaT if v is None else pd.Timestamp(v) if k in
        ('record','ex','cash_pay','stock_pay') else float(v) if k.endswith('_per_share') else v
        for k,v in row.items() if k in ('code','record','ex','cash_pay','stock_pay',
            'cash_per_share','stock_per_share','taxable_bonus_per_share')})


def bars_for(code, dates, price=10.):
    return pd.DataFrame(dict(trade_date=dates,ts_code=code,open=price,high=price,
        low=price,close=price,vol=10000.,amount=10000.,close_text=str(price),pre_close_text=str(price),
        up_limit=100.,down_limit=.01))


def guard_for(code, bars, dates, evidence, actions=(), rights=(), suspensions=None):
    meta=pd.DataFrame([dict(ts_code=code,list_date='20100101',delist_date=None)])
    return ExposureGuard(bars,dates,dates,meta,actions,rights,suspensions,evidence)


def holding(code):
    ledger=Ledger(10000.);ledger.positions[code]=100;ledger.prices[code]=10.
    return ledger


@pytest.mark.parametrize('quoted',[True,False])
@pytest.mark.parametrize('exposure',['held','pending_stock','pending_cash','unapplied_distribution','rights_entitlement','planned'])
def test_special_reorganization_stops_all_exposure_and_planned_bridges(evidence, quoted, exposure):
    code='601258.SH';dates=pd.bdate_range('2019-12-23','2019-12-31')
    action=action_from(next(v['original_action'] for v in evidence['event_versions'] if v['code']==code))
    bars=bars_for(code,dates)
    if not quoted:bars=bars.loc[bars.trade_date.ne(action.record)]
    guard=guard_for(code,bars,dates,evidence,[action])
    ledger=Ledger(10000.);rights={};signal=None
    if exposure=='held':ledger=holding(code)
    elif exposure=='pending_stock':
        ledger.prices[code]=10.
        ledger.pending.append(dict(code=code,cash=0.,shares=30,cash_pay=pd.NaT,stock_pay=dates[-1]))
    elif exposure=='pending_cash':
        ledger.pending.append(dict(code=code,cash=80.,shares=0,cash_pay=dates[-1],stock_pay=pd.NaT))
    elif exposure=='unapplied_distribution':ledger.entitlements[action]=100
    elif exposure=='rights_entitlement':
        rights[RightsIssue(code,dates[1],dates[-1],'prior source')]=100
    else:signal=dates[3]
    with pytest.raises(AccountDataFailure,match='unsupported_special_reorganization_exposure_or_plan') as failure:
        guard.check_day(code,action.record,ledger,planned_signal=signal,rights_entitlements=rights)
    assert failure.value.row['decision']=='stop'
    assert not ledger.pending_shares(code) if exposure not in ('pending_stock',) else ledger.pending_shares(code)==30
    assert action not in ledger.applied


def test_special_event_is_not_a_blacklist_or_an_ordinary_price_adjustment(evidence):
    code='601258.SH';dates=pd.bdate_range('2019-12-23','2020-01-03')
    action=action_from(next(v['original_action'] for v in evidence['event_versions'] if v['code']==code))
    bars=bars_for(code,dates);guard=guard_for(code,bars,dates,evidence,[action])
    assert guard.check_day(code,dates[-1],Ledger(10000.),planned_signal=dates[-2])
    empty_targets=pd.DataFrame(columns=['execution_date','signal_date','ts_code','target_weight'])
    result=simulate_exposure(bars,dates,empty_targets,actions=[action],
        universe=pd.DataFrame([dict(ts_code=code,list_date='20100101',delist_date=None)]),
        full_calendar=dates,evidence=evidence,config=Config(initial_cash=10000.,zero_trading_costs=True))
    assert result['corporate_events'].empty and result['holdings'].empty
    assert result['account_state']['prices']=={} and result['nav'].equity.eq(10000.).all()


@pytest.mark.parametrize('code',['000711.SZ','002470.SZ'])
def test_existing_unknown_tax_and_chronology_boundaries_do_not_add_quoted_gate(evidence, code):
    dates=pd.bdate_range('2018-05-23',periods=5)
    action=Action(code,dates[1],dates[2],dates[2],dates[2],.1,.5,0.)
    quoted=guard_for(code,bars_for(code,dates),dates,evidence,[action])
    assert quoted.check_day(code,action.ex,holding(code))
    bars=bars_for(code,dates).loc[lambda f:f.trade_date.ne(action.ex)]
    paused=guard_for(code,bars,dates,evidence,[action],suspensions={(action.ex,code)})
    with pytest.raises(AccountDataFailure,match='unreviewed_distribution_across_quote_gap'):
        paused.check_day(code,action.ex,holding(code))


def test_all_23_exact_ordinary_source_keys_match_and_tiny_mismatch_still_stops(evidence):
    assert len(evidence['ordinary_actions'])==23
    for row in evidence['ordinary_actions']:
        action=action_from(row)
        dates=pd.DatetimeIndex([action.record-pd.offsets.BDay(1),action.record,action.ex])
        bars=bars_for(action.code,dates[:1])
        ledger=holding(action.code);ledger.record(action.record,[action])
        guard=guard_for(action.code,bars,dates,evidence,[action],
                        suspensions={(d,action.code) for d in dates[1:]})
        assert guard.check_day(action.code,action.ex,ledger)
    row=next(v for v in evidence['ordinary_actions'] if v['code']=='000426.SZ')
    action=action_from(row)
    changed=Action(action.code,action.record,action.ex,action.cash_pay,action.stock_pay,
                   action.cash_per_share+1e-12,action.stock_per_share,action.taxable_bonus_per_share)
    dates=pd.DatetimeIndex([action.record-pd.offsets.BDay(1),action.record,action.ex])
    guard=guard_for(action.code,bars_for(action.code,dates[:1]),dates,evidence,[changed],
                    suspensions={(d,action.code) for d in dates[1:]})
    with pytest.raises(AccountDataFailure,match='distribution_source_terms_conflict'):
        guard.check_day(action.code,action.ex,holding(action.code))


def test_original_same_day_official_state_uncertainty_and_unexplained_price_break_preserved(evidence):
    code='000950.SZ';dates=pd.DatetimeIndex(['2018-08-27','2018-08-28'])
    guard=guard_for(code,bars_for(code,dates),dates,evidence)
    with pytest.raises(AccountDataFailure,match='uncertain'):
        guard.check_day(code,dates[-1],holding(code))
    dates=pd.bdate_range('2020-01-02',periods=3);bars=bars_for('A',dates)
    bars.loc[1,'pre_close_text']='9.99'
    guard=guard_for('A',bars,dates,dict(ordinary_actions=[],status_events=[]))
    with pytest.raises(AccountDataFailure,match='unexplained_reference_change'):
        guard.check_day('A',dates[1],holding('A'))


def test_same_day_cancellation_cannot_silently_cancel_preopen(evidence):
    changed=deepcopy(evidence)
    cancellation=next(v for v in changed['event_versions'] if v['role']=='cancelled')
    cancellation['known_date']='2019-07-22'
    action=action_from(cancellation['original_action'])
    dates=pd.bdate_range('2019-07-18','2019-07-22')
    guard=guard_for(action.code,bars_for(action.code,dates),dates,changed,[action])
    with pytest.raises(AccountDataFailure,match='distribution_source_not_usable_preopen'):
        guard.check_day(action.code,action.ex,holding(action.code))


def test_subscription_uses_prior_phase_sources_and_fail_closed_if_not_known(evidence):
    code='000977.SZ';dates=pd.bdate_range('2020-03-09','2020-03-19')
    issue=RightsIssue(code,pd.Timestamp('2020-03-10'),pd.Timestamp('2020-03-19'),'original',
        price=12.92,ratio=.1177945,list_date=pd.Timestamp('2020-03-27'))
    changed=deepcopy(evidence);fact=next(v for v in changed['rights_stages'] if v['code']==code)
    fact['terms_known_date']='2020-03-19'
    for doc in fact['sources']:
        if doc['role']=='issuance':doc['known_date']='2020-03-19'
    guard=guard_for(code,bars_for(code,dates),dates,changed,rights=[issue])
    with pytest.raises(AccountDataFailure,match='rights_subscription_source_not_usable_asof'):
        guard.require_rights_stage(issue,issue.ex,holding(code),'subscription')
