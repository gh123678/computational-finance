"""As-of r5 event roles and source-admission audit; never fit or drop old keys."""
from copy import deepcopy
from decimal import Decimal
import json
import re

import pandas as pd

from alphaforge_r3_guard import day, decimal_price
from alphaforge_r5_evidence import ACTION_FIELDS, DATE_FIELDS


def _date(value):
    parsed = day(value)
    if pd.isna(parsed):
        return None
    return parsed.strftime('%Y-%m-%d')


def _known(known_date, as_of, timing):
    if timing not in ('preopen', 'close'):
        raise ValueError('Timing must be preopen or close')
    return bool(known_date and (known_date < as_of if timing == 'preopen' else known_date <= as_of))


def _original(action):
    return {f: _date(getattr(action,f)) if f in DATE_FIELDS else getattr(action,f)
            for f in ACTION_FIELDS}


def _binding(action, expected):
    actual = _original(action)
    for field in ACTION_FIELDS:
        valid = (actual[field] == expected[field] if field in DATE_FIELDS or field == 'code'
                 else Decimal(str(actual[field])) == Decimal(str(expected[field])))
        if not valid:
            raise ValueError('Revised source does not bind original action: ' + action.code + ':' + field)


def select_event_version(code, ex, as_of, evidence, *, timing='preopen'):
    """Latest published version; same-day date-only evidence is preopen-uncertain.

    Close-level research cutoffs retain the original conditional inclusive daily
    convention. Future versions and sources never enter the detached view.
    """
    as_of, ex = _date(as_of), _date(ex)
    if not as_of or not ex:
        raise ValueError('Valid as-of and ex dates required')
    _known(None, as_of, timing)
    matches = [v for v in evidence.get('event_versions', [])
               if v['code'] == code and v['ex'] == ex and v['known_date'] <= as_of]
    if not matches:
        return None
    selected = deepcopy(max(matches, key=lambda v:(v['known_date'],v['version'])))
    selected.update(as_of_date=as_of, pre_open_known=_known(selected['known_date'],as_of,'preopen'),
                    stage_usable=_known(selected['known_date'],as_of,timing), information_timing=timing)
    selected['sources'] = [s for s in selected['sources'] if s['known_date'] <= as_of]
    return selected


def distribution_view(action, as_of, evidence, *, timing='preopen'):
    """Project the immutable original Action into its currently known role."""
    base = _original(action)
    matching = [v for v in evidence.get('event_versions', [])
                if v['code'] == action.code and v['ex'] == base['ex']]
    for version in matching:
        _binding(action, version['original_action'])
    selected = select_event_version(action.code,action.ex,as_of,evidence,timing=timing)
    if selected is not None:
        return selected
    return dict(base, original_action=deepcopy(base), version=0, role='original_distribution',
                known_date=None, ordinary=True, apply_distribution=True, reference_explained=True,
                unsupported_special=False, pre_open_known=True, stage_usable=True,
                sources=[], as_of_date=_date(as_of), information_timing=timing)


def rights_stage(issue, as_of, evidence, stage='record', *, timing='preopen'):
    """Separate quota, market ex-reference, and later listing knowledge.

    Partial listing knowledge is representable here even though the immutable
    legacy RightsIssue dataclass requires all original terms together.
    """
    if stage not in ('record','subscription','listing'):
        raise ValueError('Unknown rights stage')
    as_of = _date(as_of)
    if as_of is None:
        raise ValueError('Valid rights as-of date required')
    _known(None,as_of,timing)
    record, ex = _date(issue.record), _date(issue.ex)
    matches = [s for s in evidence.get('rights_stages', [])
               if s['code'] == issue.code and s['record'] == record and s['ex'] == ex]
    if len(matches) > 1:
        raise ValueError('Duplicate staged rights source identity')
    subscribed = issue.price is not None or issue.ratio is not None
    base = dict(code=issue.code,record=record,ex=ex,price=None,quota_ratio=None,market_ex_ratio=None,
        list_date=None,terms_known_date=None,result_known_date=None,listing_known_date=None,
        stage=stage,stage_usable=True,reason='original_no_subscription',sources=[],
        personal_actual_allocation_certified=False, original_subscription_authorized=subscribed,
        as_of_date=as_of,information_timing=timing)
    if not matches:
        if re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)',issue.code) and subscribed:
            base.update(stage_usable=False,reason='missing_bound_rights_stage_source')
        elif subscribed:
            base.update(price=issue.price,quota_ratio=issue.ratio,list_date=_date(issue.list_date),
                        reason='original_generic_fixture_subscription')
        return base
    fact = matches[0]
    if subscribed and not fact['original_subscription_authorized']:
        raise ValueError('New source terms cannot authorize a previously absent subscription')
    if subscribed:
        original = fact.get('original_subscription_terms')
        if not original or (Decimal(str(issue.price)) != Decimal(str(original['price']))
                or Decimal(str(issue.ratio)) != Decimal(str(original['ratio']))
                or _date(issue.list_date) != original['list_date']):
            raise ValueError('Staged source does not bind original rights subscription terms')
    docs = fact['sources']
    for role, date_field in [('issuance','terms_known_date'),('actual_result','result_known_date'),('listing','listing_known_date')]:
        date = fact[date_field]
        matching_docs = [s for s in docs if s.get('role') == role]
        if date is not None and (not matching_docs or any(s['known_date'] != date for s in matching_docs)):
            raise ValueError('Rights phase source and publication date conflict: ' + role)
        if _known(date,as_of,timing):
            base[date_field] = date
            base['sources'].extend(deepcopy(matching_docs))
    if base['result_known_date']:
        base['market_ex_ratio'] = fact.get('market_ex_ratio')
    # Unsourced legacy no-terms events stay no-subscription even after the
    # archive yields full issuance facts; no new personal obligations are made.
    if not subscribed:
        return base
    if base['terms_known_date']:
        base.update(price=float(fact['price']),quota_ratio=float(fact['quota_ratio']),reason='known_prior_issuance_terms')
    if base['listing_known_date']:
        base['list_date'] = fact['list_date']
    usable = bool(base['listing_known_date'] and base['list_date']) if stage == 'listing' else bool(base['terms_known_date'])
    base['stage_usable'] = usable
    if not usable:
        base['reason'] = 'rights_listing_source_not_known_by_stage' if stage == 'listing' else 'rights_issuance_source_not_known_by_stage'
    return base


def _verified(value):
    return value is True or str(value).lower() == 'true'


def audit_internal_reference_bridges(raw_bars, full_calendar, formation_rows, label_rows,
                                    original_events, evidence):
    """Audit every original internal bridge without recomputing any value.

    Formation uses its fixed signal cutoff. Labels use each bridge rear date.
    Previously invalid label rows remain diagnostics; they are never deleted or
    promoted. Failures identify a fixed key and the actual offending bridge.
    """
    calendar = pd.DatetimeIndex(full_calendar)
    if (calendar.hasnans or calendar.has_duplicates or not calendar.is_monotonic_increasing
            or calendar.tz is not None or not calendar.equals(calendar.normalize())):
        raise ValueError('Full reference calendar must be sorted and unique')
    required = {'trade_date','ts_code','close_text','pre_close_text'}
    if not required.issubset(raw_bars):
        raise ValueError('Original raw lexical reference columns required')
    raw = raw_bars[list(required)].copy()
    raw['trade_date'] = raw.trade_date.map(day)
    if raw.trade_date.isna().any() or raw.duplicated(['ts_code','trade_date']).any():
        raise ValueError('Duplicate or invalid original raw reference keys')
    forms = formation_rows.copy()
    forms['trade_date'] = forms.trade_date.map(day)
    if forms.trade_date.isna().any() or forms.duplicated(['ts_code','trade_date']).any():
        raise ValueError('Original formation keys are invalid or duplicated')
    labels = label_rows.copy()
    labels['signal_date'] = labels.signal_date.map(day)
    if labels.signal_date.isna().any() or labels.duplicated(['ts_code','signal_date']).any():
        raise ValueError('Original label keys are invalid or duplicated')
    events = pd.DataFrame(original_events).copy()
    needed = {'code','event_id','event_date','known_date','timing_verified'}
    if not needed.issubset(events):
        raise ValueError('Frozen original event catalogue required')
    events['event_date'] = events.event_date.map(day)
    events['known_date'] = events.known_date.map(day)
    if events.event_date.isna().any() or events.event_id.duplicated().any():
        raise ValueError('Frozen event catalogue date or identity invalid')
    quote_groups = {c:{r.trade_date:(r.close_text,r.pre_close_text)
                      for r in g[['trade_date','close_text','pre_close_text']].itertuples(index=False)}
                    for c,g in raw.groupby('ts_code',sort=False)}
    event_groups = {c:g.to_dict('records') for c,g in events.groupby('code',sort=False)}
    version_groups, rights_groups = {}, {}
    for v in evidence.get('event_versions',[]):
        version_groups.setdefault(v['code'],{}).setdefault(v['ex'],[]).append(v)
    for fact in evidence.get('rights_stages',[]):
        rights_groups.setdefault(fact['code'],[]).append(fact)
    failures, trace, coverage = [], [], []
    totals = dict(formation_keys=len(forms),label_keys=len(labels),formation_bridges=0,label_bridges=0,
                  original_invalid_label_keys=0,diagnostic_invalid_label_bridges=0)
    def bridge(code,left,right,cutoff):
        quotes = quote_groups.get(code,{})
        a,b = quotes.get(left,(None,None)),quotes.get(right,(None,None))
        close,ref = decimal_price(a[0]),decimal_price(b[1])
        original = [e for e in event_groups.get(code,[]) if left < e['event_date'] <= right]
        known = [e for e in original if _verified(e['timing_verified']) and pd.notna(e['known_date']) and e['known_date'] <= cutoff]
        current_ids = [str(e['event_id']) for e in known]
        corrected, unsupported, revised = [], [], False
        cutoff_text = _date(cutoff)
        for ex, versions in version_groups.get(code,{}).items():
            if not (left < pd.Timestamp(ex) <= right):
                continue
            published = [v for v in versions if v['known_date'] <= cutoff_text]
            if not published:
                continue
            selected = max(published,key=lambda v:(v['known_date'],v['version']))
            revised = True
            # Bind by the source's immutable original event ID, or by its
            # original code/ex identity when the old selection catalogue used
            # a different event-ID digest. Never remove other same-day events.
            original_ids = {str(e['event_id']) for e in original
                            if e['event_date'] == pd.Timestamp(ex) and e.get('kind','distribution') in
                            ('distribution','dividend','cash','stock','cash_and_stock')}
            original_ids.add(selected['event_id'])
            current_ids = [identity for identity in current_ids if identity not in original_ids]
            corrected.append(dict(event_id=selected['event_id'],version=selected['version'],role=selected['role'],
                known_date=selected['known_date'],ex=ex,sources=deepcopy(selected['sources'])))
            if selected['unsupported_special']:
                unsupported.append(selected['event_id'])
            elif selected['reference_explained']:
                current_ids.append(selected['event_id'])
        for fact in rights_groups.get(code,[]) if code == '000977.SZ' else ():
            if not (left < pd.Timestamp(fact['ex']) <= right):
                continue
            if fact['result_known_date'] and fact['result_known_date'] <= cutoff_text:
                revised = True
                current_ids = [identity for identity in current_ids if identity not in {
                    str(e['event_id']) for e in original if e.get('kind') == 'rights' and e['event_date'] == pd.Timestamp(fact['ex'])}]
                current_ids.append(fact['event_id'])
                corrected.append(dict(event_id=fact['event_id'],version=1,role='rights_market_reference',
                    known_date=fact['result_known_date'],ex=fact['ex'],
                    sources=deepcopy([s for s in fact['sources'] if s.get('role') == 'actual_result'])))
        reason = ('unknown_reference' if close is None or ref is None else
                  'unsupported_special_reorganization_reference_bridge' if unsupported else
                  'unexplained_reference_change' if close != ref and not current_ids else
                  'known_action_conflict' if any(_verified(e.get('conflict',False)) for e in known) else '')
        row = dict(ts_code=code,bridge_left=left,bridge_right=right,cutoff=cutoff,
            previous_close_text=a[0],current_pre_close_text=b[1],
            reference_changed=close is not None and ref is not None and close != ref,
            original_known_event_ids=json.dumps([str(e['event_id']) for e in known]),
            effective_known_event_ids=json.dumps(current_ids),source_versions=json.dumps(corrected,ensure_ascii=False,sort_keys=True),
            revised_event_in_interval=revised,reason=reason,passed=not reason)
        return row

    def check_path(code,key_date,start,end,kind,original_valid):
        if start < 0 or end < start or end >= len(calendar):
            row = dict(kind=kind,ts_code=code,formation_date=key_date,bridge_left=pd.NaT,bridge_right=pd.NaT,
                       cutoff=key_date,source_versions='[]',reason='original_reference_interval_outside_calendar',
                       original_valid=original_valid,passed=False)
            trace.append(row)
            if original_valid: failures.append(row)
            coverage.append(dict(kind=kind,ts_code=code,formation_date=key_date,original_valid=original_valid,
                internal_bridges=0,invalid_bridges=1,revised_event_bridges=0))
            return
        invalid, changed = 0, 0
        for p in range(start+1,end+1):
            cutoff = key_date if kind == 'formation' else calendar[p]
            row = dict(bridge(code,calendar[p-1],calendar[p],cutoff),kind=kind,formation_date=key_date,
                       original_valid=original_valid)
            totals[kind+'_bridges'] += 1
            invalid += int(not row['passed'])
            changed += int(row['revised_event_in_interval'])
            if row['revised_event_in_interval'] or not row['passed']:
                trace.append(row)
            if not row['passed']:
                if original_valid:
                    failures.append(row)
                else:
                    totals['diagnostic_invalid_label_bridges'] += 1
        coverage.append(dict(kind=kind,ts_code=code,formation_date=key_date,original_valid=original_valid,
            internal_bridges=end-start,invalid_bridges=invalid,revised_event_bridges=changed))

    for row in forms[['trade_date','ts_code']].itertuples(index=False):
        position = calendar.get_indexer([row.trade_date])[0]
        check_path(row.ts_code,row.trade_date,position-20,position,'formation',True)
    for row in labels.to_dict('records'):
        valid = _verified(row['R_valid'])
        if not valid:
            totals['original_invalid_label_keys'] += 1
        start,end = calendar.get_indexer([day(row['execution_date']),day(row['R_end'])])
        if not valid and (start < 0 or end < start):
            coverage.append(dict(kind='label',ts_code=row['ts_code'],formation_date=row['signal_date'],
                original_valid=False,internal_bridges=0,invalid_bridges=0,revised_event_bridges=0))
            continue
        check_path(row['ts_code'],row['signal_date'],start,end,'label',valid)
    summary = dict(totals,passed=not failures,failure_count=len(failures),
        original_formation_keys_preserved=True,original_labels_preserved=True,values_recomputed=False,
        accounts_started=0,information_cutoff='formation_signal_inclusive_and_label_each_endpoint_inclusive',
        publication_time_intraday_certified=False)
    return dict(summary=summary,failures=pd.DataFrame(failures),trace=pd.DataFrame(trace),coverage=pd.DataFrame(coverage))
