"""Independent counterexamples; no real-data preparation/account is run."""
from copy import deepcopy
import math

import numpy as np
import pandas as pd
import pytest

import momentum_g2_audit as audit


def pool_case(count=200):
    calendar = pd.bdate_range(end='2018-01-05', periods=280)
    formation = pd.Timestamp('2017-12-29')
    start = calendar.get_loc(formation) - 273
    assert start >= 0
    codes = [f'{n:06d}.SZ' for n in range(1, count + 1)]
    bars = []
    for n, code in enumerate(codes):
        prices = np.full(len(calendar), 10.)
        prices[calendar.get_loc(formation) - 21:] = 10. + n / 100.
        for i, date in enumerate(calendar):
            bars.append(dict(ts_code=code, trade_date=date, open=prices[i], high=prices[i], low=prices[i],
                             close=prices[i], close_text=str(prices[i]), pre_close=prices[max(0, i - 1)],
                             pre_close_text=str(prices[max(0, i - 1)]), vol=1000000., amount=30000.,
                             up_limit=100., down_limit=.01))
    return dict(bars=pd.DataFrame(bars), full_calendar=calendar,
                schedule=pd.DataFrame([dict(formation_date=formation, execution_date='2018-01-01')]),
                universe=pd.DataFrame([dict(ts_code=c, list_date='20100101', delist_date=None) for c in codes]),
                names=pd.DataFrame(columns=['ts_code', 'name', 'start_date', 'end_date', 'ann_date']),
                industries=pd.DataFrame([dict(ts_code=c, in_date='20100101', out_date=None, l1_code=str(i // 5)) for i, c in enumerate(codes)]),
                event_inventory=pd.DataFrame())


def producer_shape(reference):
    return dict(feature_rows=reference['feature_rows'].copy(), coverage=reference['coverage'].copy(),
                daily_bridge_audit=reference['consumed_daily_bridge_audit'].copy(),
                summary=dict(passed=reference['passed'], status=reference['status']),
                failures=deepcopy(reference['failures']))


def test_274_points_252_intervals_and_21_skip_recomputed_without_producer():
    raw = pool_case()
    reference = audit.reference_preparation(raw)
    row = reference['feature_rows'].iloc[-1]
    assert reference['passed'] and row.momentum == pytest.approx(.199)
    assert len(reference['daily_bridge_audit']) == 200 * 273
    targets = audit.reference_targets(reference['feature_rows'], reference['schedule'])
    verified = audit.audit_preparation(raw, producer_shape(reference), targets)
    assert verified['passed'] and verified['accounts_allowed'] and verified['values_recomputed']
    # A large movement confined to the skipped tail cannot change momentum.
    changed = deepcopy(raw)
    code = row.ts_code
    final = changed['bars'].ts_code.eq(code) & changed['bars'].trade_date.eq(pd.Timestamp('2017-12-29'))
    changed['bars'].loc[final, ['open', 'high', 'low', 'close']] = 400.
    changed['bars'].loc[final, 'close_text'] = '400'
    other = audit.reference_preparation(changed)
    assert other['feature_rows'].iloc[-1].momentum == row.momentum


def test_wrong_price_return_and_wrong_252_denominator_are_rejected():
    raw = pool_case()
    reference = audit.reference_preparation(raw)
    forged = producer_shape(reference)
    forged['feature_rows'].loc[0, 'momentum'] = .1
    result = audit.audit_preparation(raw, forged)
    assert not result['audit_consistent']
    assert any(x.get('field') == 'momentum' for x in result['mismatches'])


def test_decimal_half_cent_preclose_guard_and_no_275th_consumption():
    raw = pool_case()
    code = raw['universe'].ts_code.iloc[0]
    frame = raw['bars']
    # All closes are 10.005 and represented previous close is half-up 10.01.
    mask = frame.ts_code.eq(code)
    frame.loc[mask, ['open', 'high', 'low', 'close']] = 10.005
    frame.loc[mask, 'close_text'] = '10.005'
    frame.loc[mask, 'pre_close'] = 10.01
    frame.loc[mask, 'pre_close_text'] = '10.01'
    formation = pd.Timestamp('2017-12-29')
    first = raw['full_calendar'][raw['full_calendar'].get_loc(formation) - 273]
    frame.loc[mask & frame.trade_date.eq(first), 'pre_close_text'] = '999'
    assert audit.reference_preparation(raw)['passed']
    # One internally consumed half-cent display error removes only this name.
    frame.loc[mask & frame.trade_date.eq(formation), 'pre_close_text'] = '10.00'
    stopped = audit.reference_preparation(raw)
    assert not stopped['passed'] and stopped['coverage'].eligible_count.iloc[0] == 199
    assert audit.audit_preparation(raw, producer_shape(stopped))['status'] == 'verified_preparation_stop'


def test_cash_and_stock_economic_return_uses_gross_not_vendor_adjustment():
    raw = pool_case()
    code = raw['universe'].ts_code.iloc[0]
    dates = raw['full_calendar']
    ex = dates[30]
    D, s = 1., .1
    mask = raw['bars'].ts_code.eq(code) & raw['bars'].trade_date.ge(ex)
    price = (10. - D) / (1 + s)
    raw['bars'].loc[mask, ['open', 'high', 'low', 'close']] = price
    raw['bars'].loc[mask, 'close_text'] = str(price)
    raw['bars'].loc[mask, 'pre_close'] = round(price, 2)
    raw['bars'].loc[mask, 'pre_close_text'] = str(round(price, 2))
    raw['bars']['adj_factor'] = np.nan
    raw['event_inventory'] = pd.DataFrame([dict(code=code, event_id='one', version=1,
        known_date=dates[20], ex=ex, record=dates[29], cash_pay=dates[31], stock_pay=dates[31],
        cash_per_share=D, stock_per_share=s, taxable_bonus_per_share=0., kind='ordinary')])
    reference = audit.reference_preparation(raw)
    assert reference['passed'] and reference['feature_rows'].iloc[0].momentum == pytest.approx(0.)
    forged = producer_shape(reference)
    forged['feature_rows'].loc[0, 'momentum'] = price / 10 - 1
    assert not audit.audit_preparation(raw, forged)['audit_consistent']


def test_later_explanation_does_not_turn_visible_ineligibility_into_hard_stop():
    raw = pool_case(201)
    dates = raw['full_calendar']
    code = raw['universe'].ts_code.iloc[0]
    ex = dates[30]
    raw['bars'].loc[raw['bars'].ts_code.eq(code) & raw['bars'].trade_date.eq(ex), ['pre_close', 'pre_close_text']] = [9., '9']
    raw['event_inventory'] = pd.DataFrame([dict(code=code, event_id='later', version=1, known_date=dates[40],
        ex=ex, record=dates[29], cash_pay=dates[41], cash_per_share=1., stock_per_share=0., taxable_bonus_per_share=0., kind='ordinary')])
    reference = audit.reference_preparation(raw)
    assert reference['passed'] and reference['coverage'].eligible_count.iloc[0] == 200
    assert not reference['failures']


def test_hidden_late_small_cash_action_on_otherwise_consumable_bridge_hard_stops():
    raw = pool_case(201)
    dates = raw['full_calendar']
    code = raw['universe'].ts_code.iloc[0]
    raw['event_inventory'] = pd.DataFrame([dict(code=code, event_id='later', version=1, known_date=dates[40],
        ex=dates[30], record=dates[29], cash_pay=dates[41], cash_per_share=.001, stock_per_share=0., taxable_bonus_per_share=0., kind='ordinary')])
    reference = audit.reference_preparation(raw)
    assert not reference['passed'] and reference['failures'][0]['reason'] == 'late_source_needed_for_consumed_bridge'
    assert reference['coverage'].empty and reference['feature_rows'].empty
    assert audit.audit_preparation(raw, producer_shape(reference))['status'] == 'verified_preparation_stop'


def test_late_economic_revision_cannot_hide_inside_same_cent_but_listing_metadata_can():
    raw = pool_case()
    dates = raw['full_calendar']
    code = raw['universe'].ts_code.iloc[0]
    base = dict(code=code, event_id='revised', version=1, known_date=dates[20],
        ex=dates[30], record=dates[29], cash_pay=dates[31], stock_pay=None,
        cash_per_share=.001, stock_per_share=0., taxable_bonus_per_share=0., kind='ordinary')
    revision = dict(base, version=2, known_date=dates[40], cash_per_share=.002)
    raw['event_inventory'] = [base, revision]
    stopped = audit.reference_preparation(raw)
    assert not stopped['passed'] and stopped['failures'][0]['reason'] == 'late_source_needed_for_consumed_bridge'
    raw['event_inventory'][1] = dict(base, version=2, known_date=dates[40], stock_pay=dates[50])
    assert audit.reference_preparation(raw)['passed']


def test_missing_ordinary_amount_is_never_invented_as_zero():
    raw = pool_case(201)
    dates = raw['full_calendar']
    raw['event_inventory'] = [dict(code='000001.SZ', event_id='unknown-D', version=1, known_date=dates[20],
        ex=dates[30], record=dates[29], cash_pay=dates[31], stock_pay=None,
        cash_per_share=None, stock_per_share=0., taxable_bonus_per_share=0., kind='ordinary')]
    rebuilt = audit.reference_preparation(raw)
    assert rebuilt['passed'] and rebuilt['coverage'].eligible_count.iloc[0] == 200


def mapped_fixture():
    raw, _ = account_case()
    original = dict(code='000001.SZ', event_id='original-bound-id', version=1,
        record='2018-01-03', ex='2018-01-04', cash_pay='2018-01-10', stock_pay=None,
        cash_per_share='1', stock_per_share='0', taxable_bonus_per_share='0', known_date='2017-12-20', sources=[])
    fact = dict(original, event_id='distribution:000001.SZ:2018-01-04', ts_code='000001.SZ',
        version_id='1', kind='ordinary', status='active', role='ordinary_distribution',
        source_available_date='2017-12-20', known_date='2017-12-21', explicit_revision=True,
        raw_source='r5_bound_mapping', raw_record=deepcopy(original), bound_fact_event_id=original['event_id'],
        record_date='2018-01-03', ex_date='2018-01-04', pay_date='2018-01-10', div_listdate=None,
        cash_div_tax='1', stk_div='0', stk_bo_rate='0', D='1', s='0', bonus='0')
    raw['evidence'] = dict(ordinary_actions=[original])
    raw['event_inventory'] = [fact]
    return raw


@pytest.mark.parametrize('field,value', [('cash_per_share', '2'), ('D', '.999'), ('record', '2018-01-02'),
    ('source_available_date', '2017-12-19'), ('kind', 'cancelled'), ('version_id', '2'),
    ('bound_fact_event_id', 'other-id'), ('explicit_revision', False)])
def test_normalized_mapping_fact_must_bind_every_economic_date_role_and_version_field(field, value):
    raw = mapped_fixture()
    calendar = [audit._day(x) for x in raw['full_calendar']]
    assert not audit._source_check(raw['event_inventory'], calendar, raw)
    raw['event_inventory'][0][field] = value
    errors = audit._source_check(raw['event_inventory'], calendar, raw)
    assert errors and any(x['reason'] == 'normalized_mapping_fields_not_bound' for x in errors)


def test_rights_registry_raw_record_and_canonical_phase_are_independently_bound():
    raw, _ = account_case()
    registry = dict(code='000001.SZ', record='2018-01-03', ex='2018-01-04', price=7., ratio=.2,
                    list_date='2018-01-10', source='frozen-registry')
    phase = dict(code='000001.SZ', record='2018-01-03', ex='2018-01-04', terms_known_date='2017-12-20', sources=[])
    fact = dict(code='000001.SZ', ts_code='000001.SZ', event_id='rights:000001.SZ:2018-01-03', version=1,
        version_id='1', kind='unsupported', status='active', role='rights_issue', source_available_date='2017-12-20',
        known_date='2017-12-21', record='2018-01-03', ex='2018-01-04', cash_pay=None, stock_pay=None,
        cash_per_share=None, stock_per_share=None, taxable_bonus_per_share=None, sources=[],
        raw_source='verified_rights_registry', raw_record=deepcopy(registry))
    raw.update(rights_catalog=[registry], evidence=dict(rights_stages=[phase]), event_inventory=[fact])
    calendar = [audit._day(x) for x in raw['full_calendar']]
    assert not audit._source_check([fact], calendar, raw)
    fact['raw_record']['price'] = 8.
    assert any(x['reason'] == 'raw_rights_registry_binding_mismatch' for x in audit._source_check([fact], calendar, raw))
    fact['raw_record'] = deepcopy(registry)
    fact['ex'] = '2018-01-05'
    assert any(x['reason'] == 'normalized_registry_fields_not_bound' for x in audit._source_check([fact], calendar, raw))


def test_unapproved_duplicate_versions_become_conflict_only_when_both_are_known():
    raw, _ = account_case()
    first = dict(code='000001.SZ', event_id='duplicate', version=1, known_date='2017-12-20',
        record='2018-01-03', ex='2018-01-04', cash_pay='2018-01-10', cash_per_share=1., stock_per_share=0.,
        taxable_bonus_per_share=0., kind='ordinary', status='active')
    other = dict(first, known_date='2017-12-22', cash_per_share=2.)
    raw['event_inventory'] = [first, other]
    reference = audit._Reference(raw)
    assert reference.versions('000001.SZ', '2017-12-21')[0]['kind'] == 'ordinary'
    assert reference.versions('000001.SZ', '2017-12-22')[0]['kind'] == 'conflict'
    raw['event_inventory'][1]['known_date'] = '2017-12-20'
    assert audit._Reference(raw).versions('000001.SZ', '2017-12-20')[0]['kind'] == 'conflict'


def test_cached_alias_and_guard_cannot_be_changed_while_preserving_raw_row():
    raw, _ = account_case()
    original = dict(ts_code='000001.SZ', div_proc='实施', record_date='20180103', ex_date='20180104',
        pay_date='20180110', div_listdate=None, cash_div_tax='1', stk_div='0', stk_bo_rate='0',
        stk_co_rate='0', imp_ann_date='20171220')
    fact = dict(code='000001.SZ', ts_code='000001.SZ', event_id='distribution:000001.SZ:2018-01-04',
        version=1, version_id='1', record='2018-01-03', record_date='2018-01-03', ex='2018-01-04', ex_date='2018-01-04',
        cash_pay='2018-01-10', pay_date='2018-01-10', stock_pay=None, div_listdate=None,
        cash_per_share='1', cash_div_tax='1', D='1', stock_per_share='0', stk_div='0', s='0',
        taxable_bonus_per_share='0', stk_bo_rate='0', bonus='0', source_available_date='2017-12-20', known_date='2017-12-21',
        kind='ordinary', status='active', role='cached_implemented_ordinary', sources=[], raw_source='dividend.csv', raw_row_id=0,
        raw_record=deepcopy(original))
    raw['dividends'] = pd.DataFrame([original])
    dates = [audit._day(x) for x in raw['full_calendar']]
    assert not audit._source_check([fact], dates, raw)
    fact['D'] = '2'
    assert any(x['reason'] == 'normalized_cache_fields_not_bound' for x in audit._source_check([fact], dates, raw))
    fact['D'] = '1'
    fact['account_guard'] = 'capitalization_tax_origin_unknown'
    assert any(x['reason'] == 'normalized_cache_fields_not_bound' for x in audit._source_check([fact], dates, raw))


def test_future_unsupported_event_cannot_exclude_past_and_same_day_publication_is_not_known():
    raw = pool_case()
    f = pd.Timestamp('2017-12-29')
    raw['event_inventory'] = pd.DataFrame([dict(code='000001.SZ', event_id='future', version=1,
        source_available_date=f, known_date='2018-01-01', ex='2018-01-04', kind='rights')])
    assert audit.reference_preparation(raw)['passed']
    raw['event_inventory'].loc[0, 'known_date'] = f
    result = audit.audit_preparation(raw, {})
    assert not result['passed'] and any(x['reason'] == 'publication_next_session_mismatch' for x in result['independent_failures'])


def test_target_identity_hash_seed_and_memory_are_independently_checked():
    raw = pool_case()
    reference = audit.reference_preparation(raw)
    targets = audit.reference_targets(reference['feature_rows'], reference['schedule'])
    original = audit.audit_preparation(raw, producer_shape(reference), targets)
    assert original['passed']
    targets['control'].loc[0, 'ts_code'] = '009999.SZ'
    assert not audit.audit_preparation(raw, producer_shape(reference), targets)['audit_consistent']


def test_production_serialization_is_checked_without_calling_any_production_decisions(monkeypatch):
    import momentum_g2_events
    import momentum_g2_prepare
    from momentum_g2_selection import build_targets
    raw = pool_case()
    raw['schedule'] = raw['schedule'].rename(columns={'formation_date': 'signal_date'})
    raw['schedule']['execution_date'] = pd.to_datetime(raw['schedule'].execution_date)
    book = momentum_g2_events.EventBook(raw['full_calendar'])
    produced = momentum_g2_prepare.prepare(raw['bars'], raw['full_calendar'], raw['schedule'], raw['universe'],
                                             raw['names'], raw['industries'], book)
    targets = build_targets(produced['feature_rows'], raw['schedule'])['targets']
    monkeypatch.setattr(momentum_g2_prepare, 'prepare', lambda *a, **k: pytest.fail('production prepare called'))
    monkeypatch.setattr(momentum_g2_events, 'bridge_terms', lambda *a, **k: pytest.fail('production bridge called'))
    result = audit.audit_preparation(raw, produced, targets)
    assert result['passed'], result['mismatches']
    produced['daily_bridge_audit'].loc[0, 'source_known_dates'] = '["2099-01-01"]'
    assert not audit.audit_preparation(raw, produced, targets)['audit_consistent']


def account_case(end='2018-01-12'):
    dates = pd.bdate_range('2017-11-20', end)
    bars = pd.DataFrame(dict(trade_date=dates, ts_code='000001.SZ', open=10., high=10., low=10.,
                             close=10., pre_close=10., vol=1_000_000., amount=100_000., up_limit=11., down_limit=9.))
    schedule = pd.DataFrame([dict(signal_date='2017-12-29', execution_date='2018-01-01')])
    return dict(bars=bars, full_calendar=dates, schedule=schedule, event_inventory=[],
                universe=pd.DataFrame([dict(ts_code='000001.SZ', list_date='20100101', delist_date=None)])), schedule.assign(ts_code='000001.SZ', target_weight=.049)


def run_synthetic_account(raw, targets, cost=0):
    # Integration fixture only. The auditor itself never imports these modules.
    from momentum_g2_account import simulate_account
    from momentum_g2_events import EventBook
    return simulate_account(raw['bars'], raw['full_calendar'], raw['schedule'], targets,
                            EventBook(raw['full_calendar'], raw['event_inventory']), raw['universe'],
                            raw.get('suspensions'), cost_bps=cost)


@pytest.mark.parametrize('cost', [0, 10, 30])
def test_daily_ledger_rebuild_and_fixed_initial_denominator(cost):
    raw, targets = account_case()
    observed = run_synthetic_account(raw, targets, cost)
    verified = audit.audit_account(raw, observed, targets, cost)
    assert verified['passed'], verified['mismatches']
    assert verified['initial_completion']['unconditional_denominator'] == 980000.
    assert verified['initial_completion']['whole_lot_plan_coverage'] == .05
    assert not verified['product_exit_covered']


@pytest.mark.parametrize('table,field,delta', [('nav', 'cash', 1.), ('holdings', 'shares', 100),
                                             ('orders', 'fee', 1.), ('intents', 'target_total_shares', 100),
                                             ('deployment', 'denominator_cny', -931000.)])
def test_cash_share_fee_fixed_intent_and_denominator_tampering_are_detected(table, field, delta):
    raw, targets = account_case()
    observed = run_synthetic_account(raw, targets)
    observed[table].loc[observed[table].index[-1], field] += delta
    verified = audit.audit_account(raw, observed, targets, 0)
    assert not verified['passed'] and verified['mismatches']


def test_new_week_fill_cannot_repair_old_plan_completion_or_splice_formation():
    raw, targets = account_case()
    raw['bars'].loc[raw['bars'].trade_date.eq(pd.Timestamp('2018-01-01')), 'open'] = 11.
    second = dict(signal_date='2018-01-05', execution_date='2018-01-08')
    raw['schedule'] = pd.concat([raw['schedule'], pd.DataFrame([second])], ignore_index=True)
    targets = pd.concat([targets, pd.DataFrame([dict(second, ts_code='000001.SZ', target_weight=.049)])], ignore_index=True)
    observed = run_synthetic_account(raw, targets)
    verified = audit.audit_account(raw, observed, targets)
    assert verified['initial_completion']['unconditional_completion'] == 0
    observed['orders'].loc[1, 'formation_date'] = pd.Timestamp('2017-12-29')
    forged = audit.audit_account(raw, observed, targets)
    assert any(x.get('reason') == 'cross_week_plan_splice' for x in forged['mismatches'])


def test_auditor_does_not_call_production_simulator_or_event_view(monkeypatch):
    raw, targets = account_case()
    observed = run_synthetic_account(raw, targets)
    import momentum_g2_account
    import momentum_g2_events
    monkeypatch.setattr(momentum_g2_account, 'simulate_account', lambda *a, **k: pytest.fail('producer simulator called'))
    monkeypatch.setattr(momentum_g2_events.EventBook, 'view', lambda *a, **k: pytest.fail('producer event view called'))
    assert audit.audit_account(raw, observed, targets, 0)['passed']


def with_distribution(raw):
    raw['event_inventory'] = [dict(code='000001.SZ', event_id='cash-stock', version=1,
        known_date='2017-12-20', record='2018-01-03', ex='2018-01-04', cash_pay='2018-01-10',
        stock_pay='2018-01-10', cash_per_share=1., stock_per_share=.1, taxable_bonus_per_share=.05,
        kind='ordinary', sources=[dict(role='synthetic_bound_fact')])]
    new = 9 / 1.1
    mask = raw['bars'].trade_date.ge(pd.Timestamp('2018-01-04'))
    raw['bars'].loc[mask, ['open', 'high', 'low', 'close']] = new
    raw['bars'].loc[mask, 'pre_close'] = round(new, 2)
    raw['bars'].loc[mask, 'up_limit'] = 9.
    raw['bars'].loc[mask, 'down_limit'] = 7.
    return raw


def test_independent_cash_tax_unlisted_and_receivable_reconstruction_catches_flow_forgery():
    raw, targets = account_case()
    with_distribution(raw)
    observed = run_synthetic_account(raw, targets)
    verified = audit.audit_account(raw, observed, targets, 0)
    assert verified['passed'], verified['mismatches']
    event = observed['corporate_events'].event.eq('ex')
    observed['corporate_events'].loc[event, 'assumed_tax'] += .01
    forged = audit.audit_account(raw, observed, targets, 0)
    assert any(x.get('check') == 'corporate_events' and x.get('field') == 'assumed_tax' for x in forged['mismatches'])


def test_exit_denominator_includes_unlisted_and_later_week_cannot_complete_first_intent():
    raw, targets = account_case('2018-01-19')
    with_distribution(raw)
    for formation, execution in [('2018-01-05', '2018-01-08'), ('2018-01-12', '2018-01-15')]:
        plan = dict(signal_date=formation, execution_date=execution)
        raw['schedule'] = pd.concat([raw['schedule'], pd.DataFrame([plan])], ignore_index=True)
        targets = pd.concat([targets, pd.DataFrame([dict(plan, ts_code='000001.SZ', target_weight=0.)])], ignore_index=True)
    observed = run_synthetic_account(raw, targets)
    verified = audit.audit_account(raw, observed, targets, 0)
    assert verified['passed'], verified['mismatches']
    episode = verified['exit_episodes'][0]
    assert episode['denominator_shares'] == 5390
    assert episode['first_intent_completion'] == pytest.approx(4900 / 5390)
    assert episode['security_risk_closed_date'] == '2018-01-15'
    assert not verified['product_exit_verified']
    observed['exit_episodes'].loc[0, 'frozen_total_shares'] = 4900
    assert not audit.audit_account(raw, observed, targets, 0)['passed']


def test_three_year_ledger_rebuild_preserves_both_year_boundaries():
    raw, targets = account_case('2020-12-31')
    observed = run_synthetic_account(raw, targets)
    verified = audit.audit_account(raw, observed, targets, 0)
    assert verified['passed'], verified['mismatches']
    assert len(verified['annual_boundaries']) == 2
    assert verified['performance']['annual_returns'] == {'2018': 0., '2019': 0., '2020': 0.}
    observed['nav'].loc[observed['nav'].date.eq(pd.Timestamp('2019-01-01')), 'cash'] += 1_000_000.
    assert not audit.audit_account(raw, observed, targets, 0)['passed']


def test_daily_suspension_is_not_carried_into_resume_day_and_afternoon_does_not_veto_open():
    raw, targets = account_case()
    raw['suspensions'] = pd.DataFrame([
        dict(ts_code='000001.SZ', trade_date='2018-01-01', suspend_type='S', suspend_timing=''),
        dict(ts_code='000001.SZ', trade_date='2018-01-02', suspend_type='R', suspend_timing=''),
        dict(ts_code='000001.SZ', trade_date='2018-01-03', suspend_type='S', suspend_timing='14:00-15:00'),
        dict(ts_code='000001.SZ', trade_date='2018-01-04', suspend_type='S', suspend_timing='09:30-10:30'),
        dict(ts_code='000001.SZ', trade_date='2018-01-05', suspend_type='S', suspend_timing='09:00-09:30')])
    assert audit._suspended(raw, '000001.SZ', '2018-01-01', None)
    assert not audit._suspended(raw, '000001.SZ', '2018-01-02', None)
    assert not audit._suspended(raw, '000001.SZ', '2018-01-03', None)
    assert audit._suspended(raw, '000001.SZ', '2018-01-04', None)
    assert not audit._suspended(raw, '000001.SZ', '2018-01-04', None, full_day=True)
    assert not audit._suspended(raw, '000001.SZ', '2018-01-05', None)


def test_later_listing_stage_updates_unlisted_right_without_future_replaying_registration():
    raw, targets = account_case()
    with_distribution(raw)
    base = dict(raw['event_inventory'][0], stock_pay=None)
    listing = dict(base, version=2, known_date='2018-01-09', stock_pay='2018-01-10')
    raw['event_inventory'] = [base, listing]
    observed = run_synthetic_account(raw, targets)
    verified = audit.audit_account(raw, observed, targets, 0)
    assert verified['passed'], verified['mismatches']
    assert observed['corporate_events'].event.eq('stock_pay_known').sum() == 1


def test_known_share_conversion_is_not_invalidated_by_later_listing_metadata():
    raw, targets = account_case()
    second_code = '000002.SZ'
    raw['bars'] = pd.concat([raw['bars'], raw['bars'].assign(ts_code=second_code)], ignore_index=True)
    raw['universe'] = pd.concat([raw['universe'], raw['universe'].assign(ts_code=second_code)], ignore_index=True)
    plan = dict(signal_date='2018-01-05', execution_date='2018-01-08')
    raw['schedule'] = pd.concat([raw['schedule'], pd.DataFrame([plan])], ignore_index=True)
    targets = pd.concat([targets, pd.DataFrame([dict(plan, ts_code='000001.SZ', target_weight=0.),
                                                dict(plan, ts_code=second_code, target_weight=.049)])], ignore_index=True)
    base = dict(code=second_code, event_id='split-next-open', version=1, known_date='2018-01-04',
        record='2018-01-05', ex='2018-01-08', cash_pay=None, stock_pay=None,
        cash_per_share=0., stock_per_share=.1, taxable_bonus_per_share=0., kind='ordinary',
        sources=[dict(role='synthetic_source')])
    raw['event_inventory'] = [base, dict(base, version=2, known_date='2018-01-09', stock_pay='2018-01-10')]
    mask = raw['bars'].ts_code.eq(second_code) & raw['bars'].trade_date.ge(pd.Timestamp('2018-01-08'))
    raw['bars'].loc[mask, ['open', 'high', 'low', 'close']] = 10 / 1.1
    raw['bars'].loc[mask, ['pre_close', 'up_limit', 'down_limit']] = [9.09, 10., 8.]
    observed = run_synthetic_account(raw, targets)
    verified = audit.audit_account(raw, observed, targets, 0)
    assert verified['passed'], verified['mismatches']
    buy = observed['orders'].loc[lambda x: x.ts_code.eq(second_code)].iloc[0]
    assert buy.requested == 5300


def test_verified_account_stop_is_reconstructed_from_raw_data_not_status_boolean():
    from momentum_g2_account import AccountFailure
    raw, targets = account_case()
    raw['universe'].loc[0, 'delist_date'] = '20180103'
    with pytest.raises(AccountFailure) as stopped:
        run_synthetic_account(raw, targets)
    observed = stopped.value.partial_result
    observed['terminal'] = dict(status='stopped', date=stopped.value.date)
    verified = audit.audit_account(raw, observed, targets, 0)
    assert verified['status'] == 'verified_account_stop', verified['mismatches']
    assert not verified['passed'] and verified['audit_consistent']
    assert any(x['reason'] == 'unknown_delisting_recovery' for x in verified['independent_failures'])
    raw['universe'].loc[0, 'delist_date'] = None
    forged = audit.audit_account(raw, observed, targets, 0)
    assert not forged['audit_consistent']


def test_six_independently_rebuilt_accounts_supply_all_twelve_year_crossings():
    raw, targets = account_case('2020-12-31')
    reports = []
    for path in ('momentum', 'control'):
        for cost in (0, 10, 30):
            observed = run_synthetic_account(raw, targets, cost)
            verified = audit.audit_account(raw, observed, targets, cost)
            assert verified['passed'], (path, cost, verified['mismatches'])
            reports.append(verified)
    assert sum(x['annual_boundary_count'] for x in reports) == 12
