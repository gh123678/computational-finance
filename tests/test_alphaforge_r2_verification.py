"""Small adversarial data cases; never runs the historical r2 experiment."""
from pathlib import Path
import json
import math
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from verify_alphaforge_r2 import (boolean, event_index, independent_window,
                                 verify_events, verify_formation, verify_pool_comparison)


CODE = '000001.SZ'


def market():
    dates = pd.bdate_range('2018-08-06', periods=10)
    frame = pd.DataFrame(dict(trade_date=dates, ts_code=CODE,
                              close=[str(i) for i in range(10,20)],
                              pre_close=['999']+[str(i) for i in range(10,19)],
                              vol=[str(i) for i in range(1,11)], adj_factor=1.))
    return dates, frame


def event(effective, known, verified=True, identifier='E'):
    return dict(code=CODE, event_date=effective, known_date=known,
                timing_verified=verified, event_id=identifier)


def test_raw_formula_units_epsilon_and_ignored_first_reference():
    dates, frame = market()
    frame.loc[0, 'pre_close'] = ''
    result, transitions = independent_window(CODE, dates, frame)
    assert result['case_valid'] and result['reason'] == 'valid'
    assert result['case_rho'] == pytest.approx(1.)
    assert result['case_factor'] == pytest.approx(math.log(2))
    assert result['case_signal'] == -result['case_factor']
    assert result['case_nlvar'] == pytest.approx(82.5)
    assert result['case_nrvar'] == pytest.approx(825000.)
    assert result['volume_scale'] == 100 and not result['case_guard']
    assert len(transitions) == 9
    assert transitions[0]['previous_date'] == dates[0] and transitions[-1]['current_date'] == dates[-1]
    # Keep the source's small-variance denominator=1 branch, not default corr.
    frame['close'] = [repr(10+i*1e-7) for i in range(10)]
    frame['pre_close'] = ['']+frame.close.iloc[:-1].tolist()
    result, _ = independent_window(CODE, dates, frame)
    assert result['case_guard'] and result['case_valid']
    assert result['case_rho'] == pytest.approx(100*1e-7*82.5, rel=1e-7)


def test_decimal_reference_detects_difference_lost_by_float_and_no_tolerance():
    dates, frame = market()
    frame.loc[0, 'close'] = '10.00000000000000001'
    frame.loc[1, 'pre_close'] = '10.00000000000000002'
    assert float(frame.close.iloc[0]) == float(frame.pre_close.iloc[1])
    result, transitions = independent_window(CODE, dates, frame)
    assert not result['case_valid'] and result['reason'] == 'raw_reference_change'
    assert result['reference_change_count'] == 1
    assert transitions[0]['reference_status'] == 'raw_reference_change'


def test_adjustment_factor_change_is_audit_only_not_qualification():
    dates, frame = market()
    frame.loc[4:6, 'adj_factor'] = 1.0004
    result, transitions = independent_window(CODE, dates, frame)
    assert result['case_valid'] and result['adj_factor_change_count'] == 2
    assert result['isolated_factor_change_no_observed_reference_break']
    assert sum(row['isolated_factor_change_no_observed_reference_break'] for row in transitions) == 2
    assert result['case_factor'] == pytest.approx(math.log(2))


@pytest.mark.parametrize('field,bad,reason', [('pre_close', '', 'unknown_reference'),
                                             ('pre_close', 'NaN', 'unknown_reference'),
                                             ('pre_close', '-1', 'unknown_reference'),
                                             ('vol', '0', 'invalid_quote'),
                                             ('adj_factor', np.inf, 'invalid_quote')])
def test_missing_reference_and_bad_numeric_quotes_exclude(field,bad,reason):
    dates, frame = market()
    frame.loc[5, field] = bad
    result, _ = independent_window(CODE, dates, frame)
    assert not result['case_valid'] and result['reason'] == reason
    assert all(np.isnan(result[name]) for name in ['case_factor','case_signal','case_rho'])


def test_action_interval_start_exclusive_end_inclusive_and_future_not_consumed():
    dates, frame = market()
    excluded = pd.DataFrame([event(dates[0], dates[0], identifier='start'),
                             event(dates[-1]+pd.Timedelta(days=1), dates[0], identifier='future')])
    result, _ = independent_window(CODE, dates, frame, event_index(excluded))
    assert result['case_valid'] and result['known_action_count'] == 0
    included = pd.DataFrame([event(dates[-1],dates[-1],identifier='end')])
    result, transitions = independent_window(CODE,dates,frame,event_index(included))
    assert not result['case_valid'] and result['reason'] == 'known_action'
    assert result['known_action_count'] == 1 and transitions[-1]['known_action_ids'] == ['end']


def test_non_open_day_event_remains_original_day_in_internal_interval():
    dates, frame = market()
    saturday = pd.Timestamp('2018-08-11')
    events = pd.DataFrame([event(saturday, pd.Timestamp('2018-08-10'))])
    result, transitions = independent_window(CODE,dates,frame,event_index(events))
    assert not result['case_valid'] and result['known_action_count'] == 1
    matched = [row for row in transitions if row['known_action_count']]
    assert len(matched) == 1 and matched[0]['current_date'] == pd.Timestamp('2018-08-13')
    assert matched[0]['event_effective_dates'] == {'E':'2018-08-11'}


@pytest.mark.parametrize('known,verified', [(pd.NaT,False), ('2018-08-30',False),
                                          ('2018-08-30',True), ('2018-08-08',False)])
def test_unknown_unverified_and_late_known_dates_only_record_risk(known,verified):
    dates,frame = market()
    events = pd.DataFrame([event(dates[5],known,verified)])
    result, _ = independent_window(CODE,dates,frame,event_index(events))
    assert result['case_valid'] and result['known_action_count'] == 0
    assert result['event_timing_unverified_count'] == 1


def formation_fixture():
    dates,bars = market()
    date = dates[-1]
    base = pd.DataFrame(dict(trade_date=[date],ts_code=[CODE],industry=['I']))
    coverage = base.assign(window_start=dates[0], window_end=date, case_valid=True,
                           reason='valid', valid_quote_count_10=10,volume_scale=100.,
                           reference_change_count=0,unknown_reference_count=0,known_action_count=0,
                           event_timing_unverified_count=0,adj_factor_change_count=0,
                           isolated_factor_change_no_observed_reference_break=False,
                           case_factor=math.log(2),case_signal=-math.log(2),case_rho=1.,
                           case_nlvar=82.5,case_nrvar=825000.,case_guard=False)
    r1=coverage[['trade_date','ts_code','case_valid','case_factor','case_signal','case_rho']].copy()
    events=pd.DataFrame(columns=['code','event_date','known_date','timing_verified','event_id'])
    return dates,bars,base,coverage,r1,events


def test_full_formation_audit_checks_pool_math_and_old_valid_intersection():
    dates,bars,base,coverage,r1,events=formation_fixture()
    record=verify_formation(coverage.copy(),base,dates,bars,events,coverage,r1,minimum_pool=1)
    assert record['original_formation_rows'] == record['feature_rows_checked'] == 1
    assert record['reference_transition_rows_checked'] == 9
    assert record['r1_common_valid_intersection_rows'] == 1
    assert record['r1_intersection_formula_unchanged']
    assert not record['future_label_used_for_formation']


@pytest.mark.parametrize('fault',['math','old_math','eligibility','count','extra_common','missing_common'])
def test_distinct_formation_corruption_is_rejected(fault):
    dates,bars,base,coverage,r1,events=formation_fixture()
    common=coverage.copy()
    if fault=='math':coverage['case_factor'] += .001
    elif fault=='old_math':r1['case_factor'] += .001
    elif fault=='eligibility':coverage['case_valid']=False
    elif fault=='count':coverage['adj_factor_change_count']=1
    elif fault=='extra_common':
        extra=common.copy();extra['ts_code']='OTHER';common=pd.concat([common,extra])
    else:common=common.iloc[:0]
    with pytest.raises(AssertionError):
        verify_formation(common,base,dates,bars,events,coverage,r1,minimum_pool=1)


def test_reference_transition_stream_checks_original_text_and_json_event_fields():
    dates,bars,base,coverage,r1,events=formation_fixture()
    rows=[]
    for i in range(1,10):
        rows.append(dict(signal_date=str(dates[-1].date()),ts_code=CODE,
                         window_start=str(dates[0].date()),window_end=str(dates[-1].date()),
                         previous_date=str(dates[i-1].date()),current_date=str(dates[i].date()),
                         previous_close_text=str(9+i),current_pre_close_text=str(9+i),
                         reference_status='continuous',adj_factor_changed='False',matched_event_ids='[]',
                         known_action_ids='[]',unverified_event_ids='[]',event_known_dates='{}',event_effective_dates='{}',
                         known_action_count='0',event_timing_unverified_count='0',
                         isolated_factor_change_no_observed_reference_break='False'))
    verify_formation(coverage,base,dates,bars,events,coverage,r1,iter(rows),minimum_pool=1)
    rows[3]['previous_close_text']='13.000000000001'
    with pytest.raises(AssertionError):
        verify_formation(coverage,base,dates,bars,events,coverage,r1,iter(rows),minimum_pool=1)


def dividend():
    return dict(ts_code=CODE,end_date='20171231',ann_date='20180301',div_proc='实施',
                cash_div='0.1',cash_div_tax='0.1',stk_div='0',stk_bo_rate='0',stk_co_rate='0',
                ex_date='20180823',imp_ann_date='20180820',record_date='20180822')


def saved_dividend_event():
    return dict(code=CODE,event_date='2018-08-23',known_date='2018-08-20',timing_verified='True',
                event_id='independent-id',kind='cash',source='dividend_frame_after_existing_correct_actions',
                known_date_field='imp_ann_date',timing_reason='valid_cached_implementation_day_not_after_event')


def test_event_catalog_independently_checks_cached_implementation_day_and_versions():
    raw=pd.DataFrame([dividend(),dividend()])
    first=saved_dividend_event();second=dict(first,event_id='second-version')
    saved=pd.DataFrame([first,second])
    calendar=pd.bdate_range('2018-01-01','2018-12-31')
    audit=verify_events(saved,raw,calendar,rights=[])
    assert audit['event_rows']==2 and audit['timing_verified_rows']==2
    assert not audit['original_version_identity_certified']
    with pytest.raises(AssertionError):
        verify_events(saved.iloc[:1],raw,calendar,rights=[])
    saved.loc[0,'known_date']='2018-03-01'
    with pytest.raises(AssertionError):
        verify_events(saved,raw,calendar,rights=[])


def test_pool_comparison_cannot_hide_newly_eligible_and_removed_records():
    _,_,_,coverage,r1,_=formation_fixture()
    comparison=coverage[['trade_date','ts_code','case_valid','case_factor','reason']].merge(
        r1[['trade_date','ts_code','case_valid','case_factor']],on=['trade_date','ts_code'],suffixes=('_r2','_r1'))
    result=verify_pool_comparison(coverage,r1,comparison)
    assert result['common_valid']==1 and result['newly_valid']==result['no_longer_valid']==0
    comparison['case_valid_r1']=False
    with pytest.raises(AssertionError):verify_pool_comparison(coverage,r1,comparison)


def test_boolean_flags_are_explicit_and_missing_is_not_true():
    assert boolean('False') is False and boolean('True') is True
    assert boolean('',missing=True) is None
    with pytest.raises(AssertionError):boolean('nan')


def test_small_production_output_contract_passes_independent_raw_text_audit():
    # This integration fixture exercises the producer/verifier boundary. The
    # verifier itself never imports or invokes the producer.
    import csv
    import io
    from alphaforge_case_r2_features import compute_asset
    dates=pd.bdate_range('2018-08-06',periods=20)
    signals=dates[[9,14]]
    raw_frames=[];base_frames=[];coverage_frames=[];transition_frames=[]
    events=pd.DataFrame([event(dates[6],dates[5],identifier='cash_known'),
                         event(dates[11],pd.NaT,False,identifier='cash_unknown')])
    for code in [CODE,'000002.SZ','000003.SZ']:
        raw=pd.DataFrame(dict(trade_date=dates,ts_code=code,
                              close=[str(10+i) for i in range(20)],
                              pre_close=['']+[str(10+i) for i in range(19)],
                              vol=[str(20+i) for i in range(20)],adj_factor=1.))
        numeric=raw.copy()
        numeric['close_text']=numeric.close
        numeric['pre_close_text']=numeric.pre_close
        numeric['close']=pd.to_numeric(numeric.close)
        numeric['pre_close']=pd.to_numeric(numeric.pre_close,errors='coerce')
        numeric['vol']=pd.to_numeric(numeric.vol)
        if code=='000002.SZ':
            raw.loc[4:7,'adj_factor']=numeric.loc[4:7,'adj_factor']=1.0004
        features,transitions=compute_asset(numeric,dates,signals,events)
        features=features.rename(columns=dict(factor='case_factor',signal='case_signal',rho='case_rho',
                                               nlvar='case_nlvar',nrvar='case_nrvar',guard='case_guard'))
        features['ts_code']=code
        base=pd.DataFrame(dict(trade_date=signals,ts_code=code,industry='I'))
        coverage_frames.append(base.merge(features,on=['trade_date','ts_code']))
        base_frames.append(base);raw_frames.append(raw);transition_frames.append(transitions)
    coverage=pd.concat(coverage_frames,ignore_index=True)
    common=coverage.loc[coverage.case_valid].copy()
    base=pd.concat(base_frames,ignore_index=True)
    raw=pd.concat(raw_frames,ignore_index=True)
    old=coverage[['trade_date','ts_code','case_valid','case_factor','case_signal','case_rho']].copy()
    old.loc[old.ts_code.eq('000002.SZ'),'case_valid']=False
    transition_csv=pd.concat(transition_frames,ignore_index=True).to_csv(index=False)
    result=verify_formation(common,base,dates,raw,events,coverage,old,
                            csv.DictReader(io.StringIO(transition_csv)),minimum_pool=1)
    assert result['original_formation_rows']==6 and result['reference_transition_rows_checked']==54
    assert result['feature_rows_checked']==4
