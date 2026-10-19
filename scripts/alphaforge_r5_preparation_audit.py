"""Independent reconstruction of every frozen reference edge, without r5 helpers.

This verifier does not call the producer, event projection, guard or simulator.
It verifies source admission rather than recomputing factors, labels or targets.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import json

import pandas as pd


def _day(value):
    if value is None or pd.isna(value) or value == '':
        return None
    result = pd.Timestamp(value)
    if result.tz is not None or result != result.normalize():
        raise AssertionError('Reference input must contain date-only values')
    return result.strftime('%Y-%m-%d')


def _true(value):
    return value is True or str(value).lower() == 'true'


def _price(value):
    if not isinstance(value, str):
        return None
    try:
        number = Decimal(value)
        return number if number.is_finite() and number > 0 else None
    except InvalidOperation:
        return None


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _clean_text(value):
    # Empty CSV cells round-trip as missing, including unknown quote text.
    return None if value is None or pd.isna(value) or value == '' else str(value)


def _canonical_trace(frame):
    result = {}
    for row in frame.to_dict('records'):
        key = (str(row['kind']), str(row['ts_code']), _day(row['formation_date']),
               _day(row.get('bridge_left')), _day(row.get('bridge_right')))
        assert key not in result, 'Duplicated source bridge trace'
        item = dict(cutoff=_day(row['cutoff']), reason=_clean_text(row.get('reason')) or '',
                    passed=_true(row['passed']), original_valid=_true(row.get('original_valid')))
        for field in ('previous_close_text', 'current_pre_close_text'):
            item[field] = _clean_text(row.get(field))
        for field in ('original_known_event_ids','effective_known_event_ids','source_versions'):
            value = row.get(field)
            item[field] = _json(json.loads(value)) if isinstance(value,str) and value else _json([])
        item['reference_changed'] = _true(row.get('reference_changed'))
        item['revised_event_in_interval'] = _true(row.get('revised_event_in_interval'))
        result[key] = item
    return result


def _canonical_coverage(frame):
    result = {}
    for row in frame.to_dict('records'):
        key = (str(row['kind']),str(row['ts_code']),_day(row['formation_date']))
        assert key not in result, 'Duplicated source bridge coverage'
        result[key] = (_true(row['original_valid']),int(row['internal_bridges']),
                       int(row['invalid_bridges']),int(row['revised_event_bridges']))
    return result


def audit_preparation_bridges(raw_bars, full_calendar, formation_rows, label_rows,
                             original_events, evidence, producer_summary,
                             producer_coverage, producer_failures, producer_trace):
    """Return a verified source stop as data, but reject misleading audit files."""
    calendar = [_day(x) for x in full_calendar]
    assert None not in calendar and calendar == sorted(set(calendar)), 'Invalid reference calendar'
    positions = {date:i for i,date in enumerate(calendar)}
    quotes = defaultdict(dict)
    for row in raw_bars[['ts_code','trade_date','close_text','pre_close_text']].itertuples(index=False):
        date = _day(row.trade_date)
        assert date is not None and date not in quotes[row.ts_code], 'Duplicate raw quote key'
        quotes[row.ts_code][date] = (row.close_text,row.pre_close_text)
    catalogue = defaultdict(list)
    ids = set()
    for row in original_events.to_dict('records'):
        assert row['event_id'] not in ids, 'Duplicate original event identity'
        ids.add(row['event_id'])
        row = dict(row,event_date=_day(row['event_date']),known_date=_day(row['known_date']))
        assert row['event_date'] is not None
        catalogue[row['code']].append(row)
    revisions = defaultdict(lambda:defaultdict(list))
    for fact in evidence.get('event_versions',[]):
        revisions[fact['code']][fact['ex']].append(fact)
        assert all(doc['known_date'] <= fact['known_date'] for doc in fact['sources']), 'Future source in event version'
    quota_results = [x for x in evidence.get('rights_stages',[]) if x['code']=='000977.SZ']
    coverage, failures, trace = [], [], []
    totals = dict(formation_keys=len(formation_rows),label_keys=len(label_rows),
                  formation_bridges=0,label_bridges=0,original_invalid_label_keys=0,
                  diagnostic_invalid_label_bridges=0)
    # Finite cache only of event-date metadata, not decisions shared with producer.
    def inspect(code,left,right,cutoff):
        prior = quotes.get(code,{}).get(left,(None,None))[0]
        reference = quotes.get(code,{}).get(right,(None,None))[1]
        original = [x for x in catalogue.get(code,[]) if left < x['event_date'] <= right]
        published = [x for x in original if _true(x['timing_verified']) and x['known_date'] and x['known_date'] <= cutoff]
        effective = [str(x['event_id']) for x in published]
        versions, special = [], False
        for ex, candidates in revisions.get(code,{}).items():
            if not left < ex <= right:
                continue
            available = [x for x in candidates if x['known_date'] <= cutoff]
            if not available:
                continue
            latest = sorted(available,key=lambda x:(x['known_date'],x['version']))[-1]
            removed = {str(x['event_id']) for x in original if x['event_date']==ex and
                       x.get('kind','distribution') in ('distribution','dividend','cash','stock','cash_and_stock')}
            removed.add(latest['event_id'])
            effective = [x for x in effective if x not in removed]
            versions.append(dict(event_id=latest['event_id'],version=latest['version'],role=latest['role'],
                known_date=latest['known_date'],ex=ex,sources=latest['sources']))
            if latest['unsupported_special']:
                special = True
            elif latest['reference_explained']:
                effective.append(latest['event_id'])
        if code == '000977.SZ':
            for fact in quota_results:
                if (left < fact['ex'] <= right and fact['result_known_date'] and fact['result_known_date'] <= cutoff):
                    effective = [x for x in effective if x not in {str(e['event_id']) for e in original
                        if e.get('kind')=='rights' and e['event_date']==fact['ex']}]
                    effective.append(fact['event_id'])
                    docs = [s for s in fact['sources'] if s.get('role')=='actual_result']
                    assert docs and all(s['known_date']==fact['result_known_date'] for s in docs)
                    versions.append(dict(event_id=fact['event_id'],version=1,role='rights_market_reference',
                        known_date=fact['result_known_date'],ex=fact['ex'],sources=docs))
        a,b = _price(prior),_price(reference)
        reason = ''
        if a is None or b is None:
            reason = 'unknown_reference'
        elif special:
            reason = 'unsupported_special_reorganization_reference_bridge'
        elif a != b and not effective:
            reason = 'unexplained_reference_change'
        elif any(_true(x.get('conflict',False)) for x in published):
            reason = 'known_action_conflict'
        return dict(ts_code=code,bridge_left=left,bridge_right=right,cutoff=cutoff,
            previous_close_text=prior,current_pre_close_text=reference,
            reference_changed=a is not None and b is not None and a!=b,
            original_known_event_ids=_json([str(x['event_id']) for x in published]),
            effective_known_event_ids=_json(effective),source_versions=_json(versions),
            revised_event_in_interval=bool(versions),reason=reason,passed=not reason)

    seen = set()
    def path(code,date,start,end,kind,valid):
        key = kind,code,date
        assert date is not None and key not in seen, 'Invalid or duplicated fixed key'
        seen.add(key)
        if start < 0 or end < start or end >= len(calendar):
            row = dict(kind=kind,ts_code=code,formation_date=date,bridge_left=None,bridge_right=None,
                cutoff=date,source_versions='[]',reason='original_reference_interval_outside_calendar',
                original_valid=valid,passed=False)
            trace.append(row)
            if valid: failures.append(row)
            coverage.append(dict(kind=kind,ts_code=code,formation_date=date,original_valid=valid,
                internal_bridges=0,invalid_bridges=1,revised_event_bridges=0))
            return
        invalid = revised = 0
        for index in range(start+1,end+1):
            row = inspect(code,calendar[index-1],calendar[index],date if kind=='formation' else calendar[index])
            row.update(kind=kind,formation_date=date,original_valid=valid)
            totals[kind+'_bridges'] += 1
            invalid += int(not row['passed']); revised += int(row['revised_event_in_interval'])
            if row['revised_event_in_interval'] or not row['passed']: trace.append(row)
            if not row['passed']:
                if valid: failures.append(row)
                else: totals['diagnostic_invalid_label_bridges'] += 1
        coverage.append(dict(kind=kind,ts_code=code,formation_date=date,original_valid=valid,
            internal_bridges=end-start,invalid_bridges=invalid,revised_event_bridges=revised))

    for row in formation_rows[['ts_code','trade_date']].itertuples(index=False):
        date = _day(row.trade_date); end = positions.get(date,-1)
        path(row.ts_code,date,end-20,end,'formation',True)
    for row in label_rows.to_dict('records'):
        date = _day(row['signal_date']); valid = _true(row['R_valid'])
        start = positions.get(_day(row['execution_date']),-1); end = positions.get(_day(row['R_end']),-1)
        if not valid: totals['original_invalid_label_keys'] += 1
        if not valid and (start<0 or end<start):
            key = 'label',row['ts_code'],date
            assert date is not None and key not in seen
            seen.add(key)
            coverage.append(dict(kind='label',ts_code=row['ts_code'],formation_date=date,
                original_valid=False,internal_bridges=0,invalid_bridges=0,revised_event_bridges=0))
        else:
            path(row['ts_code'],date,start,end,'label',valid)
    expected_summary = dict(totals,passed=not failures,failure_count=len(failures),
        original_formation_keys_preserved=True,original_labels_preserved=True,values_recomputed=False,
        accounts_started=0,information_cutoff='formation_signal_inclusive_and_label_each_endpoint_inclusive',
        publication_time_intraday_certified=False)
    assert producer_summary == expected_summary, 'Producer bridge summary differs from independent reconstruction'
    assert _canonical_coverage(producer_coverage)==_canonical_coverage(pd.DataFrame(coverage)), 'Fixed-key/internal-edge coverage differs'
    assert _canonical_trace(producer_failures)==_canonical_trace(pd.DataFrame(failures)), 'Source failures differ'
    assert _canonical_trace(producer_trace)==_canonical_trace(pd.DataFrame(trace)), 'Event/cutoff/price/source trace differs'
    return dict(status='passed' if not failures else 'source_gate_failed',
        conditional_account_attempt_allowed=not failures,source_bridge_passed=not failures,
        independent_source_bridge_reconstruction=True,**totals,
        source_failure_count=len(failures),source_trace_rows=len(trace),
        coverage_keys=len(coverage),producer_summary_exact=True,coverage_exact=True,
        source_failures_exact=True,source_trace_exact=True,
        publication_time_intraday_certified=False,values_recomputed=False,
        full_six_account_verification_passed=False,live_enablement=False)
