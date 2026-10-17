"""Independent r3 reference-method and account audit.

No new reference/guard constructor is imported here.  Reused r1 functions
only check diagnostics, deterministic selectors and cash/share ledgers.
"""
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import traceback

import numpy as np
import pandas as pd
from scipy.stats import rankdata

import verify_alphaforge_case as legacy
from quant_research.backtest import Config, summarize
from quant_research.factors import FACTORS
from quant_research.factors import weekly_schedule
from quant_research.corporate_corrections import correct_actions
from quant_research.accounting import normalize_actions
from quant_research.continuous import relevant_actions
from quant_research.rights import verified_rights
from retention_selector import select_retention

ROOT, DATA = legacy.ROOT, legacy.DATA
OUT = ROOT/'output/alphaforge_case_2018_2020_r3'
R2 = ROOT/'output/alphaforge_case_2018_2020_r2'
PATHS, PRIMARY = legacy.PATHS, legacy.PRIMARY
sha, read_json = legacy.sha, legacy.read_json
QUOTE_FIELDS = ('open','high','low','close','vol','amount')
COUNTS = ('bridge_count','valid_bridge_count','reference_change_count',
          'unknown_reference_count','unexplained_reference_change_count',
          'known_action_count','event_timing_unverified_count','known_conflict_count')


def flag(value, missing=False):
    if value is None or pd.isna(value) or str(value) == '':
        if missing:
            return None
        raise AssertionError('Missing Boolean flag')
    if isinstance(value,(bool,np.bool_)):
        return bool(value)
    assert str(value) in ('True','False','true','false','1','0'), repr(value)
    return str(value) in ('True','true','1')


def decimal_price(value):
    if value is None or pd.isna(value):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation,ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def numeric(value):
    if value is None or pd.isna(value) or str(value) == '':
        return np.nan
    try:
        return float(value)
    except (ValueError,TypeError,OverflowError):
        return np.nan


def price_number(value):
    result=numeric(decimal_price(value))
    return result if math.isfinite(result) and result>0 else np.nan


def check_fingerprints(protocol):
    for name,expected in protocol['inputs'].items():
        assert sha(ROOT/name) == expected, 'Frozen input changed: '+name
    for name,expected in protocol['external_inputs'].items():
        assert sha(Path(name)) == expected, 'External input changed: '+name
    assert {path.name:sha(path) for path in (ROOT/'quant_research').glob('*.py')} == protocol['source_sha256']
    manifests = protocol['prior_artifact_manifests']
    assert isinstance(manifests,list) and len({entry['path'] for entry in manifests}) == len(manifests)
    counts = {}
    for entry in manifests:
        path = Path(entry['path'])
        assert path.is_absolute() and sha(path) == entry['sha256'], str(path)
        contents = read_json(path)
        assert len(contents) == entry['count'], str(path)
        for name,expected in contents.items():
            assert sha(path.parent/name) == expected, 'Protected artifact changed: '+name
        counts[str(path)] = len(contents)
    assert sum(counts.values()) == 1924, 'Expected 1854 prior plus 70 decision artifacts'
    return counts


def event_index(events):
    result = defaultdict(list)
    assert not events.event_id.duplicated().any()
    for row in events.to_dict('records'):
        effective = pd.to_datetime(row['event_date'],errors='coerce')
        known = pd.to_datetime(row['known_date'],errors='coerce')
        assert pd.notna(effective)
        result[row['code']].append(dict(event_id=str(row['event_id']),effective=effective,
            known=known,verified=flag(row['timing_verified']),conflict=flag(row.get('conflict',False))))
    for values in result.values():
        values.sort(key=lambda row:(row['effective'],row['event_id']))
    return result


def independent_bridge(previous_close,current_reference,left,right,events,cutoff):
    """Independent Decimal comparison and literal open-to-open event interval."""
    a,b = decimal_price(previous_close),decimal_price(current_reference)
    matched = [row for row in events if left < row['effective'] <= right]
    known = [row for row in matched if row['verified'] and pd.notna(row['known']) and row['known'] <= cutoff]
    conflict = any(row['conflict'] for row in known)
    if a is None or b is None:
        reason = 'unknown_reference'
    elif conflict:
        reason = 'known_action_conflict'
    elif a != b and not known:
        reason = 'unexplained_reference_change'
    else:
        reason = 'valid'
    return dict(valid=reason == 'valid',reason=reason,changed=a is not None and b is not None and a != b,
                known_ids=[row['event_id'] for row in known],
                unverified_ids=[row['event_id'] for row in matched if row not in known],
                matched_ids=[row['event_id'] for row in matched])


def independent_chain(quotes,dates,events=(),cutoff=None,require_full_quotes=False):
    """Scalar float64 K/P*/O* reconstruction, retaining all internal bridges.

    First pre_close is intentionally unused. cutoff=None gives each bridge's
    own endpoint cutoff for outcome labels; a formation date gives past-only
    factor construction. No adj_factor is an argument or implicit input.
    """
    dates = pd.DatetimeIndex(dates)
    assert len(dates) == len(quotes) and len(dates) and dates.is_monotonic_increasing and not dates.has_duplicates
    quote_rows = quotes.to_dict('records')
    bridges = []
    failures = []
    counts = {name:0 for name in COUNTS}
    counts['bridge_count'] = len(dates)-1
    present = [bool(row.get('_present',not pd.isna(row.get('ts_code','present')))) for row in quote_rows]
    close_values = [price_number(row.get('close_text',row.get('close'))) for row in quote_rows]
    if not all(present):
        failures.append('missing_quote')
    if any(is_present and not math.isfinite(value) for is_present,value in zip(present,close_values)):
        failures.append('invalid_close')
    for index in range(1,len(dates)):
        previous,current = quote_rows[index-1],quote_rows[index]
        bridge = independent_bridge(previous.get('close_text',previous.get('close')),
            current.get('pre_close_text',current.get('pre_close')),dates[index-1],dates[index],events,
            dates[index] if cutoff is None else pd.Timestamp(cutoff))
        left = decimal_price(previous.get('close_text',previous.get('close')))
        right = decimal_price(current.get('pre_close_text',current.get('pre_close')))
        unknown = not present[index-1] or not present[index] or left is None or right is None or not (
            math.isfinite(numeric(left)) and math.isfinite(numeric(right)) and numeric(left)>0 and numeric(right)>0)
        conflict = sum(item['conflict'] for item in events if item['event_id'] in bridge['known_ids'])
        unexplained = bridge['changed'] and not bridge['known_ids']
        counts['known_action_count'] += len(bridge['known_ids'])
        counts['event_timing_unverified_count'] += len(bridge['unverified_ids'])
        counts['known_conflict_count'] += conflict
        counts['reference_change_count'] += int(bridge['changed'])
        counts['unknown_reference_count'] += int(unknown)
        counts['unexplained_reference_change_count'] += int(unexplained)
        counts['valid_bridge_count'] += int(not (unknown or conflict or unexplained))
        for failed,reason in [(unknown,'unknown_reference'),(conflict,'known_action_conflict'),(unexplained,'unexplained_reference_change')]:
            if failed and reason not in failures:
                failures.append(reason)
        bridges.append(bridge)
    if require_full_quotes:
        valid_quotes = [all(math.isfinite(numeric(row.get(name))) and numeric(row.get(name)) > 0
                            for name in QUOTE_FIELDS) for row in quote_rows]
    else:
        valid_quotes = [exists and math.isfinite(value) and value>0 for exists,value in zip(present,close_values)]
    valid = all(valid_quotes) and not failures
    scale = [1.]
    prices = [close_values[0]]
    openings = [numeric(quote_rows[0].get('open_text',quote_rows[0].get('open')))]
    if valid:
        for index in range(1,len(dates)):
            # Explicit multiply-then-divide, without algebraic cancellation.
            scale.append((scale[-1]*close_values[index-1])/numeric(decimal_price(quote_rows[index].get('pre_close_text',quote_rows[index].get('pre_close')))))
            prices.append(close_values[index]*scale[-1])
            openings.append(numeric(quote_rows[index].get('open_text',quote_rows[index].get('open')))*scale[-1])
        valid = all(math.isfinite(value) and value > 0 for value in scale+prices)
        if not valid:
            failures = ['nonfinite_reference_index']
    return dict(valid=bool(valid),bridges=bridges,valid_quote_count=sum(valid_quotes),counts=counts,
                failures=failures,reason=failures[0] if failures else 'valid',
                prices=prices if valid else [],openings=openings if valid else [],scale=scale if valid else [])


def independent_features(quotes,dates,events=(),cutoff=None):
    assert len(quotes) == len(dates) == 21
    chain = independent_chain(quotes,dates,events,cutoff,False)
    result = dict(reference_valid=chain['valid'])
    if chain['valid']:
        price = chain['prices']
        returns = [b/a-1 for a,b in zip(price[:-1],price[1:])]
        mean = sum(returns)/20
        variance = sum((value-mean)*(value-mean) for value in returns)/19
        result.update(momentum20=price[-1]/price[0]-1,reversal5=-(price[-1]/price[-6]-1),
                      lowvol20=-math.sqrt(variance))
        if not all(math.isfinite(result[name]) for name in FACTORS):
            result.update(reference_valid=False,**{name:np.nan for name in FACTORS})
            chain.update(valid=False,reason='nonfinite_factor',failures=['nonfinite_factor'])
    else:
        result.update({name:np.nan for name in FACTORS})
    return result,chain


def independent_label(quotes,dates,events,benchmark_values):
    chain = independent_chain(quotes,dates,events,None,False)
    failures = list(chain['failures'])
    opened = [numeric(decimal_price(row.get('open_text',row.get('open'))))
              for row in (quotes.iloc[0].to_dict(),quotes.iloc[-1].to_dict())]
    if not all(math.isfinite(value) and value>0 for value in opened):
        failures.insert(0,'stock_endpoint')
    if not all(math.isfinite(value) and value>0 for value in benchmark_values):
        failures.insert(0,'benchmark_endpoint')
    result = dict(R_valid=False,R_week=np.nan,R_reason=failures[0] if failures else 'valid',
                  stock_reference_return=np.nan,benchmark_return=np.nan,failures=failures)
    if not failures:
        stock = opened[1]*chain['scale'][-1]/opened[0]-1
        benchmark = benchmark_values[1]/benchmark_values[0]-1
        value = stock-benchmark
        if all(math.isfinite(x) for x in (stock,benchmark,value)):
            result.update(R_valid=True,R_week=value,stock_reference_return=stock,benchmark_return=benchmark)
        else:
            result.update(R_reason='nonfinite_label',failures=['nonfinite_label'])
    return result,chain


def close_enough(observed,expected,context):
    np.testing.assert_allclose(np.asarray(observed,dtype=float),np.asarray(expected,dtype=float),
                               rtol=1e-12,atol=1e-12,equal_nan=True,err_msg=str(context))


def verify_reference_data(common,windows,labels,raw,calendar,schedule,events,benchmark):
    keys = ['trade_date','ts_code']
    for frame in (common,windows):
        assert not frame.duplicated(keys).any()
    assert not labels.duplicated(['signal_date','ts_code']).any()
    expected_keys = set(common[keys].itertuples(index=False,name=None))
    assert expected_keys == set(windows[keys].itertuples(index=False,name=None))
    assert expected_keys == set(labels[['signal_date','ts_code']].itertuples(index=False,name=None))
    w = windows.set_index(keys)
    l = labels.set_index(['signal_date','ts_code'])
    c = common.set_index(keys)
    calendar = pd.DatetimeIndex(calendar)
    positions = {date:index for index,date in enumerate(calendar)}
    plans = schedule.set_index('signal_date')
    events_by_code = event_index(events)
    formed_count = label_count = valid_labels = bridges = label_bridges = 0
    reasons = Counter()
    for asset_number,(code,quoted) in enumerate(raw.groupby('ts_code',sort=True),1):
        days = common.loc[common.ts_code.eq(code),'trade_date'].sort_values()
        if not len(days):
            continue
        quoted = quoted.copy()
        quoted['_present'] = True
        q = quoted.set_index('trade_date').reindex(calendar)
        q['_present'] = q._present.fillna(False).astype(bool)
        asset_events = events_by_code.get(code,[])
        for date in days:
            key = (date,code)
            index = positions[date]
            assert index>=20
            expected,chain = independent_features(q.iloc[index-20:index+1],calendar[index-20:index+1],asset_events,date)
            saved = w.loc[key]
            assert flag(saved.reference_valid) == expected['reference_valid']
            assert expected['reference_valid'], ('Fixed key cannot be removed',key,chain['failures'])
            assert pd.Timestamp(saved.window_start) == calendar[index-20] and pd.Timestamp(saved.window_end) == date
            assert saved.reason == 'valid'
            assert int(saved.valid_quote_count_21) == chain['valid_quote_count'] == 21
            for name in COUNTS:
                assert int(saved[name]) == chain['counts'][name], (key,name)
            assert json.loads(saved.reference_failure_reasons) == chain['failures']
            for name in FACTORS:
                close_enough(saved[name],expected[name],(key,name))
                assert np.float64(c.loc[key,name]) == np.float64(saved[name]), (key,'common '+name)
            close_enough([saved.K_start,saved.K_end,saved.P_start,saved.P_end],
                         [1.,chain['scale'][-1],chain['prices'][0],chain['prices'][-1]],key)
            bridges += chain['counts']['bridge_count']
            formed_count += 1
            plan = plans.loc[date]
            observed = l.loc[key]
            assert pd.Timestamp(observed.execution_date) == plan.execution_date
            assert (pd.isna(observed.R_end) and pd.isna(plan.next_execution)) or observed.R_end == plan.next_execution
            if pd.isna(plan.next_execution):
                outcome = dict(R_valid=False,R_week=np.nan,R_reason='missing_next_execution',failures=['missing_next_execution'])
                expected_counts = {name:0 for name in COUNTS}
                label_chain = None
            elif plan.execution_date not in positions or plan.next_execution not in positions:
                outcome = dict(R_valid=False,R_week=np.nan,R_reason='outside_period',failures=['outside_period'])
                expected_counts = {name:0 for name in COUNTS}
                label_chain = None
            else:
                start,end = positions[plan.execution_date],positions[plan.next_execution]
                endpoint = [numeric(benchmark.get(d,np.nan)) for d in (plan.execution_date,plan.next_execution)]
                outcome,label_chain = independent_label(q.iloc[start:end+1],calendar[start:end+1],asset_events,endpoint)
                expected_counts = label_chain['counts']
            assert flag(observed.R_valid) == outcome['R_valid']
            assert observed.R_reason == outcome['R_reason'], (key,observed.R_reason,outcome['R_reason'])
            assert json.loads(observed.R_failure_reasons) == outcome['failures'], key
            close_enough(observed.R_week,outcome['R_week'],key)
            for name in COUNTS:
                assert int(observed[name]) == expected_counts[name], (key,name)
            for name in ('R_week','R_valid','R_end','R_reason'):
                a,b = c.loc[key,name],observed[name]
                if name == 'R_week':
                    assert (pd.isna(a) and pd.isna(b)) or np.float64(a) == np.float64(b), key
                elif name == 'R_valid':
                    assert flag(a) == flag(b)
                else:
                    assert (pd.isna(a) and pd.isna(b)) or a == b, (key,name)
            if outcome['R_valid']:
                valid_labels += 1
                close_enough([observed.K_start,observed.K_end,observed.stock_reference_return,observed.benchmark_return],
                    [1.,label_chain['scale'][-1],outcome['stock_reference_return'],outcome['benchmark_return']],key)
            else:
                assert pd.isna(observed.stock_reference_return) and pd.isna(observed.benchmark_return)
            reasons[outcome['R_reason']] += 1
            label_count += 1
            label_bridges += expected_counts['bridge_count']
        if asset_number % 250 == 0:
            print(f'Independent reference audit assets {asset_number}; formation rows {formed_count}; labels {label_count}',flush=True)
    assert formed_count == label_count == len(common)
    return dict(reference_formation_rows=formed_count,formation_internal_bridges=bridges,
                reference_label_rows=label_count,valid_reference_labels=valid_labels,
                label_internal_bridges=label_bridges,label_reasons=dict(reasons),
                independent_implementation=True,new_reference_modules_imported=False,
                label_event_cutoff='each bridge endpoint; formation cutoff for features',
                tolerance_for_independent_reference_math=dict(rtol=1e-12,atol=1e-12))


def verify_new_targets(common,schedule,out=OUT):
    out = Path(out)
    targets = {path:pd.read_csv(out/f'targets_{path}.csv',parse_dates=['trade_date','signal_date','execution_date'],
                               float_precision='round_trip') for path in PATHS}
    previous = {path:set() for path in PATHS}
    for row in schedule.itertuples(index=False):
        frame = common.loc[common.trade_date.eq(row.signal_date)]
        ranks = frame[list(FACTORS)].rank(method='average',pct=True)
        control = ranks.mean(axis=1)
        assert np.array_equal(frame.three_score.to_numpy(dtype=float),control.to_numpy(dtype=float))
        scores = {PRIMARY:frame.primary_score,PATHS[1]:control}
        for path in PATHS:
            score = frame[['trade_date','ts_code','industry']].copy()
            score['score'] = scores[path]
            selected,_ = select_retention(score,previous[path])
            previous[path] = set(selected.ts_code)
            saved = targets[path].loc[targets[path].signal_date.eq(row.signal_date)].sort_values('ts_code')
            chosen = selected.sort_values('ts_code')
            assert saved.ts_code.tolist() == chosen.ts_code.tolist()
            assert saved.execution_date.eq(row.execution_date).all()
            for name in ('target_weight','score'):
                assert np.array_equal(saved[name].to_numpy(dtype=float),chosen[name].to_numpy(dtype=float)), (path,row.signal_date,name)
            assert saved.industry.tolist() == chosen.industry.tolist()
    for path,target in targets.items():
        assert not target.duplicated(['execution_date','ts_code']).any()
        pairs = target[['signal_date','execution_date']].drop_duplicates().reset_index(drop=True)
        assert pairs.equals(schedule[['signal_date','execution_date']].reset_index(drop=True))
    return targets


def exact_primary_identity(common,old,targets=None,old_targets=None):
    keys = ['trade_date','ts_code']
    assert not common.duplicated(keys).any() and not old.duplicated(keys).any()
    left,right = common.set_index(keys).sort_index(),old.set_index(keys).sort_index()
    assert left.index.equals(right.index), 'Fixed r2 keys changed'
    assert left.industry.equals(right.industry), 'Frozen industry changed'
    for name in ('case_factor','case_signal'):
        assert np.array_equal(left[name].to_numpy(dtype=np.float64),right[name].to_numpy(dtype=np.float64)), 'Exact primary '+name+' changed'
    ranked = left.groupby(level='trade_date').case_signal.rank(method='average',pct=True)
    assert np.array_equal(left.primary_score.to_numpy(dtype=np.float64),ranked.to_numpy(dtype=np.float64)), 'Primary percentile changed'
    old_rank = right.groupby(level='trade_date').case_signal.rank(method='average',pct=True)
    assert np.array_equal(ranked.to_numpy(dtype=np.float64),old_rank.to_numpy(dtype=np.float64))
    if targets is not None:
        columns = ['signal_date','execution_date','ts_code']
        a,b = targets.sort_values(columns).reset_index(drop=True),old_targets.sort_values(columns).reset_index(drop=True)
        assert a[columns].equals(b[columns]), 'Primary target keys changed'
        for name in ('target_weight','score'):
            assert np.array_equal(a[name].to_numpy(dtype=np.float64),b[name].to_numpy(dtype=np.float64)), 'Exact primary target '+name+' changed'
        for name in ('industry',):
            assert a[name].equals(b[name]), 'Primary target industry changed'
    return dict(fixed_keys=len(left),exact_primary_formula=True,exact_primary_percentiles=True,
                exact_primary_targets=targets is not None,old_labels_or_control_scores_used_for_selection=False)


def calendar_inputs():
    source = pd.read_csv(DATA/'calendar.csv',dtype={'cal_date':str})
    full = pd.DatetimeIndex(pd.to_datetime(source.loc[source.is_open.eq(1),'cal_date'],format='%Y%m%d')).sort_values()
    calendar = full[(full>='2015-11-01')&(full<='2020-12-31')]
    plan = weekly_schedule(full[full>='2015-11-01'])
    plan['next_execution'] = plan.execution_date.shift(-1)
    plan = plan.loc[plan.execution_date.between('2018-01-01','2020-12-31')].reset_index(drop=True)
    assert len(plan)==154
    return full,calendar,calendar[calendar>='2017-10-01'],plan


def prepared_hashes(out,name):
    entries = read_json(out/name)
    for relative,expected in entries.items():
        assert sha(out/relative)==expected, 'Stage artifact changed: '+relative
    return sha(out/name)


def load_prepared(out):
    bars = pd.read_csv(out/'raw_bars.csv',parse_dates=['trade_date'],
        converters={'close_text':str,'pre_close_text':str},float_precision='round_trip')
    assert 'adj_factor' not in bars and 'orig_adj_factor' not in bars
    assert not bars.duplicated(['trade_date','ts_code']).any()
    return bars


def verify_raw_source(raw,codes):
    """Read frozen daily once, preserving the r2 numeric parser and lexemes."""
    fields = ['ts_code','trade_date','open','high','low','close','pre_close','vol','amount']
    saved = raw.set_index(['ts_code','trade_date']).sort_index()
    count=0
    for chunk in pd.read_csv(DATA/'daily.csv',usecols=fields,dtype={'ts_code':str,'trade_date':str},
            converters={'close':str,'pre_close':str},chunksize=150000):
        part=chunk.loc[chunk.ts_code.isin(codes)&chunk.trade_date.between('20151101','20201231')].copy()
        if part.empty:continue
        part['trade_date']=pd.to_datetime(part.trade_date,format='%Y%m%d')
        original=part.set_index(['ts_code','trade_date']).sort_index()
        observed=saved.loc[original.index]
        for name in ('close','pre_close'):
            assert original[name].tolist()==observed[name+'_text'].tolist(), 'Raw lexemes differ: '+name
            values=pd.to_numeric(original[name],errors='coerce').to_numpy(dtype=float)
            assert np.array_equal(values,observed[name].to_numpy(dtype=float),equal_nan=True), name
        for name in ('open','high','low','vol','amount'):
            assert np.array_equal(original[name].to_numpy(dtype=float),observed[name].to_numpy(dtype=float),equal_nan=True),name
        count+=len(part)
    assert count==len(raw), 'Raw saved quote keys differ from fixed source range'
    return count


def verify_primary_formula(common,raw,calendar):
    saved=common.set_index(['trade_date','ts_code']);count=guarded=0;maximum=0.
    for number,(code,quotes) in enumerate(raw.groupby('ts_code',sort=True),1):
        frame=quotes.set_index('trade_date').reindex(calendar)
        for date in common.loc[common.ts_code.eq(code),'trade_date']:
            pos=calendar.get_loc(date);window=frame.iloc[pos-9:pos+1]
            assert len(window)==10
            values=window[['close','vol']].to_numpy(dtype=float)
            assert np.isfinite(values).all() and (values>0).all()
            calculated=legacy.scalar_formula(values[:,0],values[:,1]);row=saved.loc[(date,code)]
            assert flag(row.case_guard)==calculated['case_guard']
            for name in ('case_factor','case_signal','case_rho'):
                difference=abs(float(row[name])-calculated[name]);maximum=max(maximum,difference)
                assert difference<=1e-10, ((date,code),name)
            for name in ('case_nlvar','case_nrvar'):
                assert math.isclose(float(row[name]),calculated[name],rel_tol=2e-12,abs_tol=1e-10)
            assert row.case_signal == -row.case_factor
            guarded+=int(calculated['case_guard']);count+=1
        if number%250==0:print(f'Independent primary audit assets {number}; rows {count}',flush=True)
    assert count==len(common)
    return dict(raw_formula_rows=count,source_epsilon_guard_rows=guarded,maximum_scalar_formula_error=maximum,
                price_unit='raw CNY',volume_unit='raw lots times 100 shares',scalar_formula_tolerance=1e-10)


def verify_preparation(out=OUT):
    out=Path(out)
    if (out/'preparation_audit.json').exists():raise RuntimeError('Existing preparation audit; do not overwrite')
    protocol=read_json(out/'frozen_protocol.json');counts=check_fingerprints(protocol)
    assert read_json(out/'preparation_status.json')['state']=='completed'
    digest=prepared_hashes(out,'preparation_sha256.json')
    _,calendar,_,plan=calendar_inputs()
    schedule=pd.read_csv(out/'schedule.csv',parse_dates=['signal_date','execution_date','next_execution'])
    pd.testing.assert_frame_equal(schedule,plan,check_exact=True)
    common=pd.read_csv(out/'common_samples.csv',parse_dates=['trade_date','R_end'],float_precision='round_trip')
    assert not any(name.startswith('D_') for name in common), 'Old-label columns must not persist in r3'
    assert len(common)==273794 and common.trade_date.nunique()==154
    assert set(common.trade_date)==set(schedule.signal_date) and common.groupby('trade_date').size().min()>=200
    old=pd.read_csv(R2/'common_samples.csv',usecols=['trade_date','ts_code','industry','case_factor','case_signal'],
                    parse_dates=['trade_date'],float_precision='round_trip')
    raw=load_prepared(out);codes=set(common.ts_code)
    assert len(codes)==2806 and set(raw.ts_code)==codes
    raw_count=verify_raw_source(raw,codes)
    formula=verify_primary_formula(common,raw,calendar)
    windows=pd.read_csv(out/'reference_windows.csv',parse_dates=['trade_date','window_start','window_end'],float_precision='round_trip')
    labels=pd.read_csv(out/'reference_labels.csv',parse_dates=['signal_date','execution_date','R_end'],float_precision='round_trip')
    events=pd.read_csv(out/'events.csv',parse_dates=['event_date','known_date'])
    old_events=pd.read_csv(R2/'events.csv',parse_dates=['event_date','known_date'])
    pd.testing.assert_frame_equal(events.drop(columns='conflict'),old_events,check_exact=True)
    assert not events.conflict.map(flag).any()
    benchmark=pd.read_csv(DATA/'benchmark.csv',dtype={'trade_date':str},float_precision='round_trip')
    benchmark.index=pd.to_datetime(benchmark.trade_date,format='%Y%m%d')
    reference=verify_reference_data(common,windows,labels,raw,calendar,schedule,events,benchmark.open)
    targets=verify_new_targets(common,schedule,out)
    old_target=pd.read_csv(R2/f'targets_{PRIMARY}.csv',parse_dates=['trade_date','signal_date','execution_date'],float_precision='round_trip')
    identity=exact_primary_identity(common,old,targets[PRIMARY],old_target)
    legacy.verify_diagnostics(common.rename(columns={'R_week':'D_label','R_valid':'D_valid'}),schedule,out)
    for name in ('factor_ic.csv','factor_groups.csv'):
        frame=pd.read_csv(out/name,usecols=['label_definition']);assert frame.label_definition.eq('R_week').all()
    assert check_fingerprints(protocol)==counts
    assert prepared_hashes(out,'preparation_sha256.json')==digest
    result=dict(status='passed',raw_quote_rows=raw_count,**formula,**identity,**reference,
        old_artifacts=counts,preparation_manifest_sha256=digest,verifier_sha256=sha(Path(__file__)),
        label_definition='R_week conditional reference opening return minus benchmark opening return',
        legacy_diagnostic_reuse='Independent r1 diagnostic checker with in-memory R aliases; no old labels read',
        account_verification_performed=False,live_enablement=False,
        legacy_pool_indirect_adjustment_dependency=True,economic_terms_certified=False)
    write_json_exclusive(out/'preparation_audit.json',result)
    return result


def strict_day(value):
    if value is None or pd.isna(value) or value=='':return pd.NaT
    if isinstance(value,str) and not re.fullmatch(r'(\d{8}|\d{4}-\d{2}-\d{2})',value):return pd.NaT
    if isinstance(value,(int,float,np.number)):return pd.NaT
    parsed=pd.to_datetime(value,errors='coerce')
    return parsed if pd.notna(parsed) and parsed.tzinfo is None and parsed==parsed.normalize() else pd.NaT


def lifecycle(date,listing,delisting=pd.NaT):
    if pd.isna(listing) or pd.notna(delisting) and delisting<listing:return 'invalid_lifecycle'
    if date<listing:return 'pre_listing'
    if pd.isna(delisting) or date<delisting:return 'listed'
    return 'scheduled_delisting' if date==delisting else 'post_delisting'


def action_inputs(raw):
    corrected,_=correct_actions(pd.read_csv(DATA/'dividend.csv',dtype=str))
    corrected,_=relevant_actions(corrected,raw)
    corrected=corrected.loc[pd.to_datetime(corrected.ex_date).le(pd.Timestamp('20201231'))]
    codes=set(raw.ts_code)
    return normalize_actions(corrected,codes),[r for r in verified_rights() if r.code in codes and r.ex<=pd.Timestamp('20201231')]


def independent_registry(actions,rights,hashes):
    """Canonical immutable accounting terms, not raw announcement preferences."""
    rows=[];errors=[];seen={}
    for kind,items in (('distribution',actions),('rights',rights)):
        for item in items:
            if kind=='distribution' and not (item.cash_per_share or item.stock_per_share):continue
            fields=dict(event_id='',code=item.code,kind=kind,record=strict_day(item.record),ex=strict_day(item.ex),
                cash_pay=pd.NaT,stock_pay=pd.NaT,list_date=pd.NaT,cash_per_share=0.,stock_per_share=0.,
                taxable_bonus_per_share=0.,price=None,ratio=None,
                source='frozen_correct_actions_then_normalize_actions' if kind=='distribution' else item.source,
                source_sha256=hashes['dividend' if kind=='distribution' else 'rights'])
            names=('cash_pay','stock_pay','cash_per_share','stock_per_share','taxable_bonus_per_share') if kind=='distribution' else ('price','ratio','list_date')
            for name in names:
                value=getattr(item,name);fields[name]=strict_day(value) if name in ('cash_pay','stock_pay','list_date') else value
            identity={name:(None if pd.isna(value) else value.strftime('%Y-%m-%d')) if name in ('record','ex','cash_pay','stock_pay','list_date') else value
                      for name,value in fields.items() if name!='event_id'}
            fields['event_id']=kind+':'+hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str).encode()).hexdigest()
            key=(fields['code'],fields['ex'])
            if key in seen:
                reason='duplicate_normalized_event' if seen[key]==fields['event_id'] else 'conflicting_same_day_events'
                errors.append(dict(date=fields['ex'],ts_code=item.code,reason=reason,detail=fields['event_id']))
            seen[key]=fields['event_id']
            if not re.fullmatch('[0-9a-fA-F]{64}',fields['source_sha256']):
                errors.append(dict(date=fields['ex'],ts_code=item.code,reason='missing_event_source_hash',detail='dividend' if kind=='distribution' else 'rights'))
            if pd.isna(fields['record']) or pd.isna(fields['ex']) or fields['record']>=fields['ex'] or not fields['source']:
                errors.append(dict(date=fields['ex'],ts_code=item.code,reason='invalid_event_terms',detail=fields['event_id']))
            rows.append(fields)
    return pd.DataFrame(rows),errors


def independent_guard(raw,calendar,full,universe,registry,initial_errors,suspensions,observed_daily):
    """Replay every security/session independently; no guard module imports."""
    codes=sorted(set(raw.ts_code));calendar=pd.DatetimeIndex(calendar);full=pd.DatetimeIndex(full)
    previous_session=full[full<calendar[0]][-1]
    assert calendar.equals(full[(full>=calendar[0])&(full<=calendar[-1])])
    metadata=universe.set_index('ts_code');errors=list(initial_errors);life_counts=Counter();decision_counts=Counter()
    evidence=defaultdict(list)
    for row in suspensions.itertuples(index=False):
        evidence[(strict_day(row.trade_date),row.ts_code)].append((str(row.suspend_type),'' if pd.isna(row.suspend_timing) else str(row.suspend_timing)))
    initial_bad={(row['ts_code'],row['date']) for row in initial_errors}
    reg=registry.copy();reg['allowed']=[(row.code,row.ex) not in initial_bad for row in reg.itertuples()]
    date_fields=('record','ex','cash_pay','stock_pay','list_date')
    reg['account_date_domain']=['overlaps_account_calendar' if any(pd.notna(row[name]) and calendar[0]<=row[name]<=calendar[-1] for name in date_fields) else 'outside_account_calendar' for row in reg.to_dict('records')]
    groups={code:g.set_index('trade_date') for code,g in raw.groupby('ts_code')}
    recorded={code:g for code,g in observed_daily.groupby('ts_code',sort=False)}
    assert set(recorded)==set(codes) and len(observed_daily)==len(codes)*len(calendar)
    checked=0
    def add(date,code,reason,detail=''):errors.append(dict(date=date,ts_code=code,reason=reason,detail=detail))
    for number,code in enumerate(codes,1):
        quoted=groups[code];listing=delisting=pd.NaT
        if code not in metadata.index:add(calendar[0],code,'missing_universe_security')
        else:
            meta=metadata.loc[code];listing=strict_day(meta.list_date);delisting=strict_day(meta.delist_date)
            if pd.isna(listing) or (pd.notna(meta.delist_date) and meta.delist_date!='' and pd.isna(delisting)) or pd.notna(delisting) and delisting<listing:
                add(calendar[0],code,'invalid_lifecycle_dates',str(meta.to_dict()));listing=pd.NaT
        previous_date=pd.NaT;previous_close=None;previous_text='';gap=False
        seed=quoted.loc[previous_session] if previous_session in quoted.index else None
        if seed is not None and pd.notna(listing) and lifecycle(previous_session,listing,delisting)!='listed':add(previous_session,code,'seed_quote_outside_lifecycle')
        if pd.notna(listing) and listing<calendar[0]:
            if seed is not None:
                previous_close=decimal_price(seed.close_text)
                if lifecycle(previous_session,listing,delisting)!='listed' or previous_close is None:
                    add(previous_session,code,'invalid_initial_seed',str(seed.close_text));previous_close=None
                else:previous_date=previous_session;previous_text=str(seed.close_text)
            elif pd.isna(delisting) or delisting>=calendar[0]:add(calendar[0],code,'missing_initial_seed',previous_session.strftime('%Y-%m-%d'))
        local=reg.loc[reg.code.eq(code)].to_dict('records');explanations=defaultdict(list);equity=[]
        for event in local:
            permitted=event['allowed']
            for field in ('record','ex'):
                d=event[field]
                if pd.isna(d):continue
                if calendar[0]<=d<=calendar[-1] and d not in full:
                    add(d,code,'event_date_off_calendar',event['event_id']+':'+field);permitted=False
                if pd.notna(listing) and calendar[0]<=d<=calendar[-1] and lifecycle(d,listing,delisting)!='listed':
                    add(d,code,'event_outside_listed_lifecycle',event['event_id']+':'+field);permitted=False
            equity.extend((event[name],event['event_id'],name) for name in date_fields if pd.notna(event[name]))
            if permitted:explanations[event['ex']].append(event['event_id'])
            else:reg.loc[reg.event_id.eq(event['event_id']),'allowed']=False
        actual=recorded[code].set_index('date');assert pd.DatetimeIndex(actual.index).equals(calendar)
        for date in calendar:
            state=lifecycle(date,listing,delisting);quote=quoted.loc[date] if date in quoted.index else None
            present=quote is not None;reasons=[];equal=None;identities=[];old_date,old_text=previous_date,previous_text
            suspended=evidence.get((date,code),[]);types='|'.join(x[0] for x in suspended);times='|'.join(x[1] for x in suspended)
            def stop(reason,detail=''):reasons.append(reason);add(date,code,reason,detail)
            reference_text='' if quote is None else quote.pre_close_text
            if state=='invalid_lifecycle':stop('invalid_lifecycle');decision='stop'
            elif state in ('pre_listing','post_delisting'):
                if present:stop('quote_outside_lifecycle',state)
                decision='stop' if reasons else 'outside_lifecycle'
            elif state=='scheduled_delisting':
                if any(item[0]==date for item in equity):stop('delisting_equity_date_conflict')
                decision='stop' if reasons else 'zero_recovery_write_off'
            elif not present:
                if not any(x[0]=='S' for x in suspended):stop('missing_quote_without_daily_suspension')
                if previous_close is None:stop('missing_prior_close_for_stale_mark')
                crossed=[(d,identity,field) for d,identity,field in equity if (pd.isna(previous_date) or previous_date<d) and d<=date]
                if crossed:stop('equity_date_in_missing_quote_interval','|'.join(identity+':'+field for _,identity,field in crossed))
                gap=True;decision='stop' if reasons else 'stale_mark_registered_suspension'
            else:
                close=decimal_price(quote.close_text);reference=decimal_price(reference_text)
                if close is None:stop('invalid_close_text')
                if reference is None:stop('invalid_pre_close_text')
                for name in ('open','close','vol','amount'):
                    value=numeric(quote[name]);valid=math.isfinite(value) and (value>0 if name in ('open','close') else value>=0)
                    if name=='close' and close is not None:valid=valid and value==numeric(close)
                    if not valid:stop('invalid_quote_'+name)
                if gap:
                    crossed=[(d,identity,field) for d,identity,field in equity if (pd.isna(previous_date) or previous_date<d) and d<=date]
                    if crossed:stop('equity_date_in_missing_quote_interval','|'.join(identity+':'+field for _,identity,field in crossed))
                if previous_close is None:
                    if date==listing and close is not None:decision='listing_initial_anchor'
                    else:stop('missing_prior_close_for_reference');decision='stop'
                else:
                    equal=reference==previous_close if reference is not None else None;identities=explanations.get(date,[])
                    if reference is not None and not equal and not identities:stop('unexplained_reference_change')
                    decision='registered_action_reference' if identities else 'continuous_reference'
                if reasons:decision='stop'
                if close is not None:previous_date=date;previous_close=close;previous_text=str(quote.close_text)
                gap=False
            expected=dict(lifecycle=state,has_quote=present,prior_quote_date=old_date,prior_close_text=old_text,
                pre_close_text=reference_text,reference_equal=equal,event_ids='|'.join(identities),decision=decision,
                reason='|'.join(reasons),suspend_type=types,suspend_timing=times)
            observed=actual.loc[date]
            for name,value in expected.items():
                got=observed[name]
                if name in ('has_quote','reference_equal'):assert flag(got,missing=True)==value,(code,date,name,got,value)
                elif name=='prior_quote_date':assert (pd.isna(got) and pd.isna(value)) or got==value,(code,date,name)
                else:assert ('' if pd.isna(got) else str(got))==('' if pd.isna(value) else str(value)),(code,date,name,got,value)
            life_counts[state]+=1;decision_counts[decision]+=1;checked+=1
        if number%250==0:print(f'Independent guard audit assets {number}; daily rows {checked}; failures {len(errors)}',flush=True)
    return dict(rows=checked,lifecycle_counts=dict(life_counts),decision_counts=dict(decision_counts)),reg,errors


def write_json_exclusive(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,default=str)


def verify_guard(out=OUT):
    out=Path(out)
    if (out/'guard_audit.json').exists():raise RuntimeError('Existing guard audit; do not overwrite')
    protocol=read_json(out/'frozen_protocol.json');old_counts=check_fingerprints(protocol)
    assert read_json(out/'preparation_audit.json')['status']=='passed'
    prep_digest=prepared_hashes(out,'preparation_sha256.json');guard_digest=prepared_hashes(out,'guard_sha256.json')
    full,_,calendar,_=calendar_inputs();raw=load_prepared(out)
    universe=pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    assert not universe.loc[universe.ts_code.isin(set(raw.ts_code))].ts_code.duplicated().any()
    actions,rights=action_inputs(raw)
    registry,initial=independent_registry(actions,rights,{'dividend':sha(DATA/'dividend.csv'),'rights':sha(ROOT/'quant_research/rights.py')})
    suspension=pd.read_csv(DATA/'suspend_d.csv',dtype=str)
    daily=pd.read_csv(out/'guard_daily.csv',dtype=str,keep_default_na=False)
    daily['date']=pd.to_datetime(daily.date,format='%Y-%m-%d')
    daily['prior_quote_date']=pd.to_datetime(daily.prior_quote_date,format='%Y-%m-%d',errors='coerce')
    assert not daily.duplicated(['date','ts_code']).any()
    audited,expected_registry,errors=independent_guard(raw,calendar,full,universe,registry,initial,suspension,daily)
    observed_registry=pd.read_csv(out/'event_registry.csv',float_precision='round_trip')
    date_names=['record','ex','cash_pay','stock_pay','list_date']
    for name in date_names:observed_registry[name]=pd.to_datetime(observed_registry[name],errors='coerce')
    observed_registry['allowed']=observed_registry.allowed.map(flag)
    expected_registry=expected_registry.sort_values('event_id').reset_index(drop=True)
    observed_registry=observed_registry.sort_values('event_id').reset_index(drop=True)
    pd.testing.assert_frame_equal(observed_registry,expected_registry[observed_registry.columns],check_dtype=False,check_exact=True)
    expected_failures=pd.DataFrame(errors,columns=['date','ts_code','reason','detail'])
    actual_failures=pd.read_csv(out/'guard_failures.csv',dtype=str,keep_default_na=False)
    def canonical_failure(frame):
        values=[]
        for row in frame.to_dict('records'):
            date=pd.to_datetime(row['date'],errors='coerce')
            values.append((None if pd.isna(date) else date.strftime('%Y-%m-%d'),str(row['ts_code']),str(row['reason']),'' if pd.isna(row['detail']) else str(row['detail'])))
        return Counter(values)
    assert canonical_failure(actual_failures)==canonical_failure(expected_failures),'Independent guard failure inventory differs'
    summary=read_json(out/'guard_summary.json');passed=len(errors)==0
    assert summary['passed']==passed and summary['failure_count']==len(errors)
    assert summary['fixed_security_count']==len(set(raw.ts_code))==2806
    assert summary['account_sessions']==len(calendar)
    assert summary['security_session_rows']==audited['rows']==len(calendar)*2806
    for name in ('lifecycle_counts','decision_counts'):assert summary[name]==audited[name],name
    assert summary['failure_reason_counts']==dict(Counter(item['reason'] for item in errors))
    assert summary['event_count']==len(expected_registry)
    assert summary['calendar_start']==calendar[0].strftime('%Y-%m-%d') and summary['calendar_end']==calendar[-1].strftime('%Y-%m-%d')
    assert summary['seed_session']==full[full<calendar[0]][-1].strftime('%Y-%m-%d')
    assert summary['accounts_started']==0 and summary['performance_computed'] is False
    assert summary['economic_terms_certified'] is False
    assert summary['enable_status']=='blocked_by_unverified_data_and_forward_validation'
    assert re.fullmatch('[0-9a-f]{64}',summary['input_fingerprint'])
    alerts=pd.read_csv(out/'guard_adjustment_alerts.csv')
    assert alerts.empty,'Runner supplies raw prices without adjustment-factor diagnostic series'
    stage=read_json(out/'experiment_stage.json')
    assert stage['state']==('precheck_passed' if passed else 'blocked_guard') and stage['accounts_started']==0
    if not passed:
        forbidden=['status.json','summary.json','experiment_protocol.json','verification.json']
        assert not any((out/name).exists() for name in forbidden),'Failed exhaustive guard must start no accounts'
        assert not any((out/f'{path}_{cost}bp').exists() for path in PATHS for cost in (0,10,30))
    assert check_fingerprints(protocol)==old_counts
    assert prepared_hashes(out,'preparation_sha256.json')==prep_digest
    assert prepared_hashes(out,'guard_sha256.json')==guard_digest
    result=dict(status='passed',guard_passed=passed,guard_failure_count=len(errors),
        independently_verified_security_session_rows=audited['rows'],fixed_security_count=2806,
        account_sessions=len(calendar),lifecycle_counts=audited['lifecycle_counts'],
        decision_counts=audited['decision_counts'],failure_reason_counts=summary['failure_reason_counts'],
        normalized_events_checked=len(expected_registry),accounts_started=0,
        stopped_before_accounts=not passed,full_six_account_verification_passed=False,
        research_gates_assessable=False,research_gate_passed=False,economic_terms_certified=False,
        guard_input_fingerprint=summary['input_fingerprint'],guard_manifest_sha256=guard_digest,
        preparation_manifest_sha256=prep_digest,old_artifacts=old_counts,
        independent_implementation=True,new_guard_module_imported=False,
        action_normalization_reuse='Original immutable correct_actions/relevant_actions/normalize_actions and verified_rights; independent canonical identity and date decisions',
        adjustment_factor_controls_economic_decisions=False,
        enable_status='blocked_by_unverified_data_and_forward_validation',verifier_sha256=sha(Path(__file__)))
    write_json_exclusive(out/'guard_audit.json',result)
    return result


def assert_six_completed(summary,statuses):
    expected={f'{path}_{cost}bp' for path in PATHS for cost in (0,10,30)}
    assert len(statuses)==6 and {item['strategy'] for item in statuses}==expected
    assert statuses==summary['experiment_statuses']
    assert all(item['status']=='completed' for item in statuses),'Incomplete or failed accounts cannot pass full verification'
    assert len(summary['experiments'])==6 and {item['strategy'] for item in summary['experiments']}==expected


def verify_accounts(out=OUT):
    out=Path(out)
    if (out/'verification.json').exists():raise RuntimeError('Existing full verification; do not overwrite')
    protocol=read_json(out/'frozen_protocol.json');old_counts=check_fingerprints(protocol)
    preparation=read_json(out/'preparation_audit.json');guard=read_json(out/'guard_audit.json')
    assert preparation['status']=='passed' and guard['status']=='passed' and guard['guard_passed']
    assert read_json(out/'guard_summary.json')['passed']
    prep_digest=prepared_hashes(out,'preparation_sha256.json');guard_digest=prepared_hashes(out,'guard_sha256.json')
    assert read_json(out/'experiment_stage.json')['state']=='completed'
    experiment=read_json(out/'experiment_protocol.json')
    assert experiment['runner_sha256']==sha(ROOT/'scripts/run_alphaforge_r3.py')
    assert experiment['paths']==list(PATHS) and experiment['costs']==[0,10,30] and experiment['live_enablement'] is False
    summary=read_json(out/'summary.json');statuses=read_json(out/'status.json');assert_six_completed(summary,statuses)
    _,_,calendar,schedule=calendar_inputs()
    common=pd.read_csv(out/'common_samples.csv',parse_dates=['trade_date','R_end'],float_precision='round_trip')
    ic=legacy.verify_diagnostics(common.rename(columns={'R_week':'D_label','R_valid':'D_valid'}),schedule,out)
    records=[];annual=[];boundaries=[];operations=[]
    for item in summary['experiments']:
        folder=out/item['strategy'];cost=int(item['strategy'].rsplit('_',1)[1][:-2])
        assert item['path'] in PATHS and item['strategy']==item['path']+f'_{cost}bp'
        assert item['config']==asdict(Config(slippage_bps=cost,zero_trading_costs=cost==0))
        assert sha(folder/'historical_targets.csv')==sha(out/f'targets_{item["path"]}.csv')
        nav=pd.read_csv(folder/'nav.csv',parse_dates=['date'],float_precision='round_trip')
        orders=pd.read_csv(folder/'orders.csv',parse_dates=['date'],float_precision='round_trip')
        events=pd.read_csv(folder/'corporate_events.csv',parse_dates=['date'],float_precision='round_trip')
        holdings=pd.read_csv(folder/'holdings.csv',parse_dates=['date'],float_precision='round_trip')
        assert pd.DatetimeIndex(nav.date).equals(calendar)
        assert nav.loc[nav.date.eq(pd.Timestamp('20171229')),'equity'].iloc[0]==1000000
        assert orders.date.isin(schedule.execution_date).all()
        if cost==0:assert orders[['fee','slippage_cost']].eq(0).all().all()
        record,edges=legacy.reconstruct_account(nav,orders,events,holdings)
        assert len(edges)==2
        records.append(dict(strategy=item['strategy'],**record))
        boundaries.extend(dict(strategy=item['strategy'],**edge) for edge in edges)
        operations.append(dict(strategy=item['strategy'],**legacy.summarize_operations(nav,orders)))
        calculated=summarize(nav,orders,schedule.execution_date.iloc[0],pd.Timestamp('20180101'))
        for name,value in calculated.items():
            if isinstance(value,(float,int)):assert np.isclose(value,item[name],rtol=0,atol=1e-6),(item['strategy'],name)
        assert abs(float(orders.fee.sum())-item['total_fees'])<1e-6
        assert abs(float(orders.slippage_cost.sum())-item['total_slippage'])<1e-6
        previous=1000000.
        for year,group in nav.loc[nav.date>='20180101'].groupby(nav.date.dt.year):
            ending=float(group.equity.iloc[-1]);annual.append(dict(strategy=item['strategy'],year=int(year),start_equity=previous,end_equity=ending,return_value=ending/previous-1));previous=ending
        print('Independent actual account reconstructed',item['strategy'],flush=True)
    assert len(records)==6 and len(boundaries)==12
    years=pd.DataFrame(annual);stats=pd.DataFrame(summary['experiments']).set_index('strategy')
    gates,mean_ic,yearly_ic=legacy.strategy_gates(stats,years,ic,schedule)
    assert check_fingerprints(protocol)==old_counts
    assert prepared_hashes(out,'preparation_sha256.json')==prep_digest and prepared_hashes(out,'guard_sha256.json')==guard_digest
    for name,frame in [('annual_returns.csv',years),('account_operations.csv',pd.DataFrame(operations)),
            ('comparison.csv',stats.reset_index().drop(columns=['config'])),('year_boundary_audit.csv',pd.DataFrame(boundaries))]:
        assert not (out/name).exists(),'Existing audit output: '+name
        frame.to_csv(out/name,index=False)
    result=dict(status='passed',engineering_verification_passed=True,full_six_account_verification_passed=True,
        completed_accounts_verified=6,accounts=records,year_boundaries=12,
        mean_rankIC=mean_ic,yearly_rankIC={int(k):float(v) for k,v in yearly_ic.items()},
        gates=gates,research_gates_passed=all(gates.values()),research_gates_assessable=True,
        label_definition='R_week',old_artifacts=old_counts,
        legacy_ledger_verifier_reuse='Frozen r1 independent cash/share/pending/receivable reconstruction and cost calculations; account simulation not reused',
        economic_terms_certified=False,legacy_pool_indirect_adjustment_dependency=True,
        enable_status='blocked_by_unverified_data_and_forward_validation',live_enablement=False,
        broker_connected=False,verifier_sha256=sha(Path(__file__)),summary_sha256=sha(out/'summary.json'),
        scope='Conditional retrospective reference-price study; no independent holdout or corrected supplier adjustment series')
    write_json_exclusive(out/'verification.json',result)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['preparation','guard','accounts'],required=True)
    parser.add_argument('--out',type=Path,default=OUT);args=parser.parse_args()
    try:
        result={'preparation':verify_preparation,'guard':verify_guard,'accounts':verify_accounts}[args.stage](args.out)
        print(json.dumps({name:result[name] for name in ('status','guard_passed','guard_failure_count','research_gates_passed') if name in result},ensure_ascii=False),flush=True)
    except Exception:
        path=args.out/f'verification_failure_{args.stage}_{pd.Timestamp.now():%Y%m%dT%H%M%S%f}.txt'
        with path.open('x',encoding='utf-8') as stream:stream.write(traceback.format_exc())
        raise


if __name__=='__main__':main()
