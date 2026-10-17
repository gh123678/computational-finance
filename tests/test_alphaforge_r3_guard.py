import pandas as pd
import pytest

from alphaforge_r3_guard import audit_reference_guard, freeze_event_registry, lifecycle_state
from quant_research.accounting import Action
from quant_research.rights import RightsIssue


HASHES = {'dividend': 'a' * 64, 'rights': 'b' * 64}


def market(codes=('A',), start='2020-01-02', periods=6):
    full = pd.bdate_range(pd.Timestamp(start) - pd.Timedelta(days=8), periods=periods + 8)
    full = full.union(pd.bdate_range(start, periods=periods))
    dates = pd.bdate_range(start, periods=periods)
    previous = full[full < dates[0]][-1]
    rows = [dict(trade_date=d, ts_code=c, open=10., close=10., vol=100000., amount=30000.,
                 close_text='10.000', pre_close_text='10.000') for c in codes for d in dates]
    seed = pd.DataFrame([dict(trade_date=previous, ts_code=c, close_text='10.000', pre_close_text='10.000') for c in codes])
    universe = pd.DataFrame([dict(ts_code=c, list_date='20100101', delist_date=None) for c in codes])
    return dates, pd.DataFrame(rows), universe, seed, full


def audit(data, **kwargs):
    dates, bars, universe, seed, full = data
    return audit_reference_guard(bars, dates, universe, seed_bars=seed, full_calendar=full,
                                 source_hashes=HASHES, **kwargs)


def reasons(result):
    return set(result['failures'].reason)


def test_complete_exhaustive_scope_and_empty_delisting_are_valid():
    result = audit(market(('A', 'B')))
    assert result['summary']['passed']
    assert result['summary']['security_session_rows'] == 12
    assert not result['summary']['performance_computed']
    assert result['summary']['accounts_started'] == 0
    assert result['daily'].decision.eq('continuous_reference').all()


def test_decimal_original_text_rejects_sub_float_precision_difference():
    data = market()
    data[1].loc[2, 'pre_close_text'] = '10.00000000000000000001'
    result = audit(data)
    assert 'unexplained_reference_change' in reasons(result)
    assert len(result['failures']) == 1


def test_invented_numeric_reference_is_not_accepted_as_original_lexeme():
    data = market()
    data[1].loc[2, 'pre_close_text'] = 10.
    assert 'invalid_pre_close_text' in reasons(audit(data))


def test_all_security_failures_are_inventoried_not_only_a_first_or_holding():
    data = market(('A', 'B'))
    data[1].loc[data[1].trade_date.eq(data[0][2]), 'pre_close_text'] = '9'
    result = audit(data)
    assert set(result['failures'].ts_code) == {'A', 'B'}
    assert len(result['daily']) == 12


def test_missing_old_security_seed_cannot_be_misclassified_as_new_listing():
    data = list(market())
    data[3] = data[3].iloc[:0]
    result = audit(data)
    assert 'missing_initial_seed' in reasons(result)
    assert 'missing_prior_close_for_reference' in reasons(result)


def test_seed_requires_actual_preceding_exchange_session():
    data = list(market())
    data[3].trade_date -= pd.Timedelta(days=1)
    assert 'invalid_seed_session' in reasons(audit(data))
    result = audit_reference_guard(data[1], data[0], data[2], seed_bars=data[3])
    assert 'missing_preceding_exchange_calendar' in reasons(result)


def test_account_calendar_cannot_silently_omit_an_exchange_session():
    data = list(market())
    omitted = data[0][2]
    data[0] = data[0].drop(omitted)
    data[1] = data[1].loc[data[1].trade_date.ne(omitted)]
    assert 'account_calendar_omits_exchange_sessions' in reasons(audit(data))


def test_lifecycle_domain_is_explicit_and_never_inferred_from_quotes():
    data = list(market())
    dates, bars, universe, seed, full = data
    universe.loc[0, 'list_date'] = str(dates[1].date())
    universe.loc[0, 'delist_date'] = str(dates[-2].date())
    data[1] = bars.loc[bars.trade_date.between(dates[1], dates[-3])]
    data[3] = seed.iloc[:0]
    result = audit(data)
    assert result['summary']['passed']
    assert result['daily'].lifecycle.tolist() == ['pre_listing', 'listed', 'listed', 'listed', 'scheduled_delisting', 'post_delisting']
    assert result['daily'].iloc[1].decision == 'listing_initial_anchor'
    assert result['daily'].iloc[-2].decision == 'zero_recovery_write_off'


def test_domain_quote_conflicts_and_invalid_metadata_stop():
    data = list(market())
    data[2].loc[0, 'list_date'] = str(data[0][1].date())
    assert 'quote_outside_lifecycle' in reasons(audit(data))
    data[2].loc[0, 'list_date'] = None
    assert 'invalid_lifecycle_dates' in reasons(audit(data))


def test_seed_quote_before_listing_is_a_conflict_not_an_initial_anchor():
    data = list(market())
    data[2].loc[0, 'list_date'] = str(data[0][0].date())
    assert 'seed_quote_outside_lifecycle' in reasons(audit(data))


def test_missing_quote_needs_same_day_S_not_future_R():
    data = list(market())
    gap = data[0][2]
    data[1] = data[1].loc[data[1].trade_date.ne(gap)]
    suspensions = pd.DataFrame([dict(trade_date=gap, ts_code='A', suspend_type='R', suspend_timing='09:30')])
    assert 'missing_quote_without_daily_suspension' in reasons(audit(data, suspensions=suspensions))
    suspensions.loc[0, 'suspend_type'] = 'S'
    result = audit(data, suspensions=suspensions)
    assert result['summary']['passed']
    assert result['daily'].loc[result['daily'].date.eq(gap), 'decision'].iloc[0] == 'stale_mark_registered_suspension'
    assert result['daily'].loc[result['daily'].date.eq(gap), 'suspend_timing'].iloc[0] == '09:30'


def test_every_missing_open_day_requires_its_own_evidence():
    data = list(market())
    gaps = data[0][2:4]
    data[1] = data[1].loc[~data[1].trade_date.isin(gaps)]
    result = audit(data, suspensions={(gaps[0], 'A')})
    assert 'missing_quote_without_daily_suspension' in reasons(result)
    result = audit(data, suspensions={(d, 'A') for d in gaps})
    assert result['summary']['passed']


def test_resumed_quote_compares_with_last_actual_close():
    data = list(market())
    gap, resumed = data[0][2:4]
    data[1] = data[1].loc[data[1].trade_date.ne(gap)]
    data[1].loc[data[1].trade_date.eq(resumed), 'pre_close_text'] = '9.99'
    assert 'unexplained_reference_change' in reasons(audit(data, suspensions={(gap, 'A')}))


def test_registered_action_explains_reference_without_inventing_theoretical_rounding():
    data = market()
    ex = data[0][3]
    data[1].loc[data[1].trade_date.eq(ex), 'pre_close_text'] = '9.80'
    action = Action('A', data[0][2], ex, ex, pd.NaT, .2001741)
    result = audit(data, actions=[action])
    assert result['summary']['passed']
    row = result['daily'].loc[result['daily'].date.eq(ex)].iloc[0]
    assert row.decision == 'registered_action_reference' and not row.reference_equal
    assert result['event_registry'].source_sha256.iloc[0] == HASHES['dividend']


@pytest.mark.parametrize('field', ['record', 'ex', 'cash_pay', 'stock_pay', 'list_date'])
def test_all_equity_dates_in_a_missing_quote_interval_stop(field):
    data = list(market(periods=9))
    dates = data[0]
    if field == 'list_date':
        issue = RightsIssue('A', dates[0], dates[1], 'https://official.test/rights', 5., .3, dates[4])
        kwargs = dict(rights=[issue])
        gap = dates[4]
    else:
        if field == 'record':
            record, ex, cash, stock, gap = dates[3], dates[4], dates[5], dates[6], dates[3]
        elif field == 'ex':
            record, ex, cash, stock, gap = dates[2], dates[3], dates[4], dates[5], dates[3]
        elif field == 'cash_pay':
            record, ex, cash, stock, gap = dates[0], dates[1], dates[4], dates[5], dates[4]
        else:
            record, ex, cash, stock, gap = dates[0], dates[1], dates[3], dates[4], dates[4]
        action = Action('A', record, ex, cash, stock, .2, .1)
        kwargs = dict(actions=[action])
    data[1] = data[1].loc[data[1].trade_date.ne(gap)]
    result = audit(data, suspensions={(gap, 'A')}, **kwargs)
    assert 'equity_date_in_missing_quote_interval' in reasons(result)


def test_duplicate_conflict_zero_and_missing_source_registry_rules():
    data = market()
    action = Action('A', data[0][1], data[0][2], data[0][2], pd.NaT, .2)
    different = Action('A', data[0][1], data[0][2], data[0][2], pd.NaT, .3)
    assert 'duplicate_normalized_event' in reasons(audit(data, actions=[action, action]))
    assert 'conflicting_same_day_events' in reasons(audit(data, actions=[action, different]))
    registry, failures = freeze_event_registry([action], source_hashes={})
    assert failures.reason.eq('missing_event_source_hash').any()
    zero = Action('A', data[0][1], data[0][2], pd.NaT, pd.NaT)
    registry, failures = freeze_event_registry([zero], source_hashes=HASHES)
    assert registry.empty and failures.empty


def test_non_session_record_or_ex_never_auto_shifts():
    data = market()
    action = Action('A', pd.Timestamp('2020-01-04'), pd.Timestamp('2020-01-06'), pd.Timestamp('2020-01-06'), pd.NaT, .2)
    assert 'event_date_off_calendar' in reasons(audit(data, actions=[action]))


def test_historical_events_outside_account_domain_are_retained_not_mistaken_for_holidays():
    data = market()
    action = Action('A', pd.Timestamp('2016-01-05'), pd.Timestamp('2016-01-06'), pd.Timestamp('2016-01-06'), pd.NaT, .2)
    result = audit(data, actions=[action])
    assert result['summary']['passed']
    assert result['event_registry'].account_date_domain.iloc[0] == 'outside_account_calendar'


@pytest.mark.parametrize('bad', ['0', '-1', 'NaN', 'Infinity', ''])
def test_invalid_reference_lexemes_are_failures(bad):
    data = market()
    data[1].loc[2, 'pre_close_text'] = bad
    assert 'invalid_pre_close_text' in reasons(audit(data))


def test_adjustment_alert_never_changes_economic_qualification():
    data = market()
    baseline = audit(data)
    data[1]['adj_factor'] = [11.267, 11.267, 10.97, 10.97, float('nan'), 11.267]
    result = audit(data)
    assert result['summary']['passed']
    pd.testing.assert_frame_equal(result['daily'], baseline['daily'])
    assert not result['adjustment_alerts'].empty
    assert not result['adjustment_alerts'].economic_decision_affected.any()


def test_future_reference_perturbation_does_not_change_earlier_guard_rows():
    data = market()
    baseline = audit(data)
    data[1].loc[4, 'pre_close_text'] = '1'
    changed = audit(data)
    pd.testing.assert_frame_equal(baseline['daily'].iloc[:4].astype(object), changed['daily'].iloc[:4].astype(object))
    assert not changed['summary']['passed']
