"""Independent G2 reference checks.  No producer or simulator is imported.

Raw event serialization may be shared, but date admission, event version choice,
economic arithmetic, universe, scores, targets and the ledger are rebuilt here.
The audit returns a verified research stop separately from an audit mismatch.
"""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd


def _day(value):
    if value is None or value is pd.NaT or (not isinstance(value, (dict, list)) and pd.isna(value)) or value == '':
        return None
    text = str(value)
    if re.fullmatch(r'\d{8}(\.0)?', text):
        text = text[:8]
        result = pd.Timestamp(year=int(text[:4]), month=int(text[4:6]), day=int(text[6:8]))
    else:
        result = pd.Timestamp(value)
    if result.tz is not None or result != result.normalize():
        raise ValueError('Date-only input required')
    return result.strftime('%Y-%m-%d')


def _get(row, *names, default=None):
    for name in names:
        value = row.get(name)
        if value is not None and value is not pd.NaT and not (isinstance(value, float) and math.isnan(value)) and value != '':
            return value
    return default


def _number(value, *, nonnegative=False):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or (result < 0 if nonnegative else result <= 0):
        return None
    return result


def _records(value):
    if value is None:
        return []
    return value.to_dict('records') if isinstance(value, pd.DataFrame) else list(value)


def _bool(value):
    return value is True or str(value).lower() in ('true', '1')


def _lex(row, field):
    return str(_get(row, field + '_text', field))


def _display(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def _close(a, b, tolerance=1e-8):
    try:
        return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tolerance * max(1., abs(float(b)))
    except (ValueError, TypeError):
        return False


def _ledger_equal(a, b):
    try:
        return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= 1e-6
    except (ValueError, TypeError):
        return False


def _decimal(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except Exception:
        return None


def _bind_normalized_fact(fact, original, *, rights=False, registry=None, evidence=None, raw_dividends=()):
    """Independent canonical projection of the frozen source record."""
    evidence = evidence or {}
    errors = []
    code = str(_get(original, 'code', 'ts_code')).upper()
    dates = dict(record=_day(_get(original, 'record', 'record_date')), ex=_day(_get(original, 'ex', 'ex_date')),
                 cash_pay=None if rights else _day(_get(original, 'cash_pay', 'pay_date')),
                 stock_pay=None if rights else _day(_get(original, 'stock_pay', 'div_listdate')))
    public = _day(_get(original, 'terms_known_date', 'planned_known_date')) if rights else _day(original.get('known_date'))
    kind = 'unsupported' if rights else 'cancelled' if original.get('role') == 'cancelled' else 'unsupported' if _bool(original.get('unsupported_special')) else 'ordinary'
    amount_values = [None, None, None] if rights else [_get(original, *names) for names in
        (('cash_per_share', 'cash_div_tax'), ('stock_per_share', 'stk_div'), ('taxable_bonus_per_share', 'stk_bo_rate'))]
    conflicts = {tuple(x) for x in evidence.get('source_facts', {}).get('publication_chronology_conflict_keys', [])}
    if (code, dates['ex']) in conflicts:
        kind = 'conflict'
    if not rights:
        bound_original = original.get('original_action', original)
        for raw in raw_dividends:
            if str(raw.get('ts_code')) != code or _day(raw.get('ex_date')) != dates['ex'] or raw.get('div_proc') != '实施':
                continue
            bo = _get(raw, 'stk_bo_rate')
            if bo is None and (_decimal(raw.get('stk_div')) == Decimal(0) or _decimal(raw.get('stk_div')) is not None and _decimal(raw.get('stk_div')) == _decimal(raw.get('stk_co_rate'))):
                bo = 0
            original_values = [_get(bound_original, *names) for names in
                (('cash_per_share', 'cash_div_tax'), ('stock_per_share', 'stk_div'), ('taxable_bonus_per_share', 'stk_bo_rate'))]
            if any(not (actual is None and expected is not None or actual == expected) for actual, expected in ((_decimal(a), _decimal(b)) for a, b in zip((raw.get('cash_div_tax'), raw.get('stk_div'), bo), original_values))) or any(
                _day(raw.get(a)) != _day(_get(bound_original, b, a)) for a, b in
                (('record_date', 'record'), ('ex_date', 'ex'), ('pay_date', 'cash_pay'), ('div_listdate', 'stock_pay'))):
                kind = 'conflict'
    if registry is not None:
        registry_ex = _day(_get(registry, 'ex', 'ex_date'))
        registry_record = _day(_get(registry, 'record', 'record_date'))
        if registry_ex != dates['ex'] or registry_record != dates['record']:
            kind = 'conflict'
        # Canonical dates remain those of the registry; the phase announcement
        # only supplies its public time, never repairs a registry mismatch.
        dates['ex'], dates['record'] = registry_ex, registry_record
    for name in ('code', 'ts_code'):
        if name in fact and str(fact[name]) != code:
            errors.append(name)
    for canonical, aliases in dict(record=('record', 'record_date'), ex=('ex', 'ex_date'),
                                   cash_pay=('cash_pay', 'pay_date'), stock_pay=('stock_pay', 'div_listdate')).items():
        for name in aliases:
            if name in fact and _day(fact[name]) != dates[canonical]:
                errors.append(name)
    for names, expected in zip((('cash_per_share', 'cash_div_tax', 'D'), ('stock_per_share', 'stk_div', 's'),
                                ('taxable_bonus_per_share', 'stk_bo_rate', 'bonus')), amount_values):
        for name in names:
            if name in fact and _decimal(fact[name]) != _decimal(expected):
                errors.append(name)
    expected_id = ('rights:' + code + ':' + str(dates['record'])) if rights else ('distribution:' + code + ':' + str(dates['ex']))
    if fact.get('event_id') != expected_id:
        errors.append('event_id')
    if _day(fact.get('source_available_date')) != public:
        errors.append('source_available_date')
    if fact.get('kind') != kind:
        errors.append('kind')
    if fact.get('status') != ('cancelled' if kind == 'cancelled' else 'active'):
        errors.append('status')
    version = int(original.get('version', 1)) if not rights else 1
    if int(fact.get('version', 1)) != version or str(fact.get('version_id', version)) != str(version):
        errors.append('version')
    if not rights and fact.get('bound_fact_event_id') != original.get('event_id'):
        errors.append('bound_fact_event_id')
    if not rights and fact.get('explicit_revision') is not True:
        errors.append('explicit_revision')
    if rights and fact.get('role') != 'rights_issue':
        errors.append('role')
    if not rights and 'role' in original and fact.get('role') != original['role']:
        errors.append('role')
    sources = list(original.get('sources', []))
    if rights:
        sources = [x for x in sources if _day(x.get('known_date')) == public]
    if (code, dates['ex']) not in conflicts and json.dumps(fact.get('sources', []), sort_keys=True, default=str) != json.dumps(sources, sort_keys=True, default=str):
        errors.append('sources')
    tax_keys = {tuple(x) for x in evidence.get('source_facts', {}).get('unsupported_capitalization_keys', [])}
    expected_guard = 'capitalization_tax_origin_unknown' if (code, dates['ex']) in tax_keys else None
    if _get(fact, 'account_guard') != expected_guard:
        errors.append('account_guard')
    return errors


def _source_check(facts, calendar, raw_inputs):
    """Check public-date translation and frozen file bindings independently."""
    failures, cache = [], {}
    manifests = raw_inputs.get('input_hashes', {})
    verify_files = raw_inputs.get('verify_source_files', False)
    for fact in facts:
        event_id = str(_get(fact, 'event_id', default=''))
        public = _day(_get(fact, 'source_available_date', 'publication_date', 'imp_ann_date'))
        known = _day(_get(fact, 'known_date'))
        if public:
            expected = next((d for d in calendar if d > public), None)
            if known != expected:
                failures.append(dict(event_id=event_id, reason='publication_next_session_mismatch'))
        sources = _get(fact, 'sources', default=[])
        if isinstance(sources, str):
            sources = json.loads(sources)
        for source in sources:
            source_known = _day(_get(source, 'known_date'))
            # The serialized catalogue may include later documents.  Their
            # date admission is checked only on an actually consumed version;
            # merely attaching them cannot change a past pool or force a stop.
            path = _get(source, 'path')
            digest = _get(source, 'sha256')
            if path and digest:
                if str(path) in manifests and manifests[str(path)] != digest:
                    failures.append(dict(event_id=event_id, reason='source_manifest_binding_mismatch', path=str(path)))
                if verify_files:
                    if path not in cache:
                        target = Path(path)
                        cache[path] = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
                    if cache[path] != digest:
                        failures.append(dict(event_id=event_id, reason='source_file_binding_mismatch', path=str(path)))
    # Bind ordinary facts back to the original supplier rows when supplied.
    raw_rows = _records(raw_inputs.get('dividends'))
    if raw_rows:
        indexed = defaultdict(list)
        for row in raw_rows:
            indexed[(str(_get(row, 'ts_code', 'code')), _day(_get(row, 'ex_date', 'ex')))].append(row)
        for fact in facts:
            if _get(fact, 'raw_row_id') is None:
                continue
            key = str(_get(fact, 'ts_code', 'code')), _day(_get(fact, 'ex_date', 'ex'))
            candidates = indexed[key]
            values = (_get(fact, 'cash_per_share', 'cash_div_tax', 'D'), _get(fact, 'stock_per_share', 'stk_div', 's'), _get(fact, 'taxable_bonus_per_share', 'stk_bo_rate'))
            def binding(candidate):
                for value, name in zip(values, ('cash_div_tax', 'stk_div', 'stk_bo_rate')):
                    original = _get(candidate, name)
                    if value is None and original is None:
                        continue
                    if name == 'stk_bo_rate' and original is None and _close(value, 0):
                        total, capital = _get(candidate, 'stk_div'), _get(candidate, 'stk_co_rate')
                        if _close(total, 0) or _close(total, capital):
                            continue
                    if not _close(value, original):
                        return False
                for aliases in (('record_date', 'record'), ('ex_date', 'ex'), ('pay_date', 'cash_pay'), ('div_listdate', 'stock_pay')):
                    if _day(_get(fact, *aliases)) != _day(_get(candidate, *aliases)):
                        return False
                return _day(_get(fact, 'source_available_date')) == _day(_get(candidate, 'imp_ann_date'))
            bound = next((r for r in candidates if binding(r)), None)
            if bound is None:
                failures.append(dict(event_id=fact.get('event_id'), reason='raw_dividend_economics_binding_mismatch'))
            else:
                expected_bo = _get(bound, 'stk_bo_rate')
                if expected_bo is None and (_decimal(bound.get('stk_div')) == Decimal(0) or _decimal(bound.get('stk_div')) is not None and _decimal(bound.get('stk_div')) == _decimal(bound.get('stk_co_rate'))):
                    expected_bo = 0
                fields = []
                for aliases, expected in zip((('cash_per_share', 'cash_div_tax', 'D'), ('stock_per_share', 'stk_div', 's'), ('taxable_bonus_per_share', 'stk_bo_rate', 'bonus')),
                                             (bound.get('cash_div_tax'), bound.get('stk_div'), expected_bo)):
                    fields.extend(name for name in aliases if name in fact and _decimal(fact[name]) != _decimal(expected))
                fields.extend(name for name in ('code', 'ts_code') if name in fact and str(fact[name]) != str(bound['ts_code']))
                expected_kind = 'ordinary'
                if not _day(bound.get('ex_date')) or not _day(bound.get('imp_ann_date')):
                    expected_kind = 'unavailable'
                total, bo, capital = (_decimal(bound.get(k)) for k in ('stk_div', 'stk_bo_rate', 'stk_co_rate'))
                if all(x is not None for x in (total, bo, capital)) and total != bo + capital:
                    expected_kind = 'conflict'
                conflict_keys = {tuple(x) for x in raw_inputs.get('evidence', {}).get('source_facts', {}).get('publication_chronology_conflict_keys', [])}
                if (str(bound['ts_code']), _day(bound.get('ex_date'))) in conflict_keys:
                    expected_kind = 'conflict'
                if fact.get('kind') != expected_kind:
                    fields.append('kind')
                if int(fact.get('version', 1)) != 1 or str(fact.get('version_id', '1')) != '1':
                    fields.append('version')
                if fact.get('event_id') != 'distribution:' + str(bound['ts_code']) + ':' + str(_day(bound.get('ex_date'))):
                    fields.append('event_id')
                tax_keys = {tuple(x) for x in raw_inputs.get('evidence', {}).get('source_facts', {}).get('unsupported_capitalization_keys', [])}
                guard = 'capitalization_tax_origin_unknown' if (str(bound['ts_code']), _day(bound.get('ex_date'))) in tax_keys else None
                if _get(fact, 'account_guard') != guard:
                    fields.append('account_guard')
                if fields:
                    failures.append(dict(event_id=fact.get('event_id'), reason='normalized_cache_fields_not_bound', fields=fields))
            if _bool(fact.get('explicit_revision')):
                failures.append(dict(event_id=fact.get('event_id'), reason='cached_row_cannot_invent_explicit_revision'))
    evidence = raw_inputs.get('evidence')
    if evidence is not None:
        originals = [row for collection in ('ordinary_actions', 'event_versions', 'rights_stages', 'rights_overlay') for row in evidence.get(collection, [])]
        def clean(value):
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [clean(v) for v in value]
            if value is None or value is pd.NaT or isinstance(value, float) and math.isnan(value):
                return None
            if isinstance(value, (pd.Timestamp, np.datetime64)):
                return _day(value)
            return value
        canonical = lambda row: json.dumps(clean(row), sort_keys=True, ensure_ascii=False, default=str)
        identities = {canonical(row) for row in originals}
        for fact in facts:
            if fact.get('raw_source') != 'r5_bound_mapping':
                continue
            original = fact.get('raw_record')
            if canonical(original) not in identities:
                failures.append(dict(event_id=fact.get('event_id'), reason='raw_mapping_fact_binding_mismatch'))
                continue
            rights = fact.get('role') == 'rights_issue' or original in evidence.get('rights_stages', []) or original in evidence.get('rights_overlay', [])
            fields = _bind_normalized_fact(fact, original, rights=rights, evidence=evidence, raw_dividends=raw_rows)
            if fields:
                failures.append(dict(event_id=fact.get('event_id'), reason='normalized_mapping_fields_not_bound', fields=fields))
        registry_rows = _records(raw_inputs.get('rights_catalog'))
        phase_rows = [*evidence.get('rights_stages', []), *evidence.get('rights_overlay', [])]
        for fact in facts:
            if fact.get('raw_source') != 'verified_rights_registry':
                continue
            original = fact.get('raw_record') or {}
            code, record = str(_get(original, 'code', 'ts_code')), _day(_get(original, 'record', 'record_date'))
            registry = next((r for r in registry_rows if str(_get(r, 'code', 'ts_code')) == code and _day(_get(r, 'record', 'record_date')) == record), None)
            if registry is None or canonical(registry) != canonical(original):
                failures.append(dict(event_id=fact.get('event_id'), reason='raw_rights_registry_binding_mismatch'))
                continue
            phase = next((r for r in phase_rows if str(r.get('code')) == code and _day(r.get('record')) == record), None)
            phase = phase or dict(code=code, record=record, ex=_day(_get(registry, 'ex', 'ex_date')))
            fields = _bind_normalized_fact(fact, phase, rights=True, registry=registry, evidence=evidence)
            if fields:
                failures.append(dict(event_id=fact.get('event_id'), reason='normalized_registry_fields_not_bound', fields=fields))
    return failures


class _Reference:
    def __init__(self, raw):
        self.raw = raw
        cal = raw.get('full_calendar', raw.get('calendar'))
        if isinstance(cal, pd.DataFrame):
            if 'is_open' in cal:
                cal = cal.loc[cal.is_open.astype(str).eq('1') | cal.is_open.eq(1)]
            cal = cal['cal_date' if 'cal_date' in cal else 'trade_date']
        self.calendar = [_day(x) for x in cal]
        if None in self.calendar or self.calendar != sorted(set(self.calendar)):
            raise ValueError('Calendar identity conflict')
        self.pos = {date: i for i, date in enumerate(self.calendar)}
        self.universe = _records(raw.get('universe', raw.get('metadata')))
        self.names = defaultdict(list)
        self.industries = defaultdict(list)
        for item in _records(raw.get('name_history', raw.get('names'))):
            self.names[str(item['ts_code'])].append(item)
        for item in _records(raw.get('industries', raw.get('industry_history'))):
            self.industries[str(item['ts_code'])].append(item)
        self.quotes = defaultdict(dict)
        for row in _records(raw['bars']):
            code, date = str(row['ts_code']), _day(row['trade_date'])
            if date in self.quotes[code]:
                raise ValueError('Duplicate raw quote identity')
            self.quotes[code][date] = row
        self.facts = _records(raw.get('event_inventory', raw.get('events', [])))
        self.source_failures = _source_check(self.facts, self.calendar, raw)
        self.events = defaultdict(lambda: defaultdict(list))
        self.identities = set()
        for fact in self.facts:
            f = dict(fact)
            f['code'] = str(_get(f, 'ts_code', 'code'))
            f['known'] = _day(_get(f, 'known_date'))
            f['ex'] = _day(_get(f, 'ex_date', 'ex'))
            f['record'] = _day(_get(f, 'record_date', 'record'))
            f['pay'] = _day(_get(f, 'pay_date', 'cash_pay'))
            f['listing'] = _day(_get(f, 'div_listdate', 'stock_pay', 'list_date'))
            f['id'] = str(_get(f, 'event_id', default=f['code'] + ':' + str(f['ex'])))
            f['version'] = str(_get(f, 'version_id', 'version', default=1))
            f['version_order'] = int(_get(f, 'version', default=f['version'])) if str(_get(f, 'version', default=f['version'])).isdigit() else f['version']
            key = f['code'], f['id'], f['version'], f['known']
            if key in self.identities:
                existing = next(x for x in self.events[f['code']][f['id']] if (x['code'], x['id'], x['version'], x['known']) == key)
                comparable = ('record', 'ex', 'pay', 'listing', 'cash_per_share', 'stock_per_share', 'taxable_bonus_per_share', 'kind', 'status', 'role', 'sources', 'raw_source', 'source_available_date')
                if all(str(existing.get(k)) == str(f.get(k)) for k in comparable):
                    continue
            self.identities.add(key)
            f['D'] = _number(_get(f, 'cash_per_share', 'cash_div_tax', 'D'), nonnegative=True)
            f['s'] = _number(_get(f, 'stock_per_share', 'stk_div', 's'), nonnegative=True)
            f['bonus'] = _number(_get(f, 'taxable_bonus_per_share', 'stk_bo_rate'), nonnegative=True)
            self.events[f['code']][f['id']].append(f)
        self.bridge_cache = {}

    def versions(self, code, cutoff):
        result = []
        for event_id, versions in self.events.get(code, {}).items():
            known = [x for x in versions if x['known'] and x['known'] <= cutoff]
            if known:
                selected = dict(max(known, key=lambda x: (x['known'], x['version_order'])))
                same_stage = [x for x in known if (x['known'], x['version_order']) == (selected['known'], selected['version_order'])]
                economic = lambda x: (x['record'], x['ex'], x['pay'], x['listing'], x['D'], x['s'], x['bonus'], x.get('kind'), x.get('role'), x.get('reason'))
                unapproved = [x for x in known if not _bool(x.get('explicit_revision'))]
                source_stages = {(economic(x), _day(x.get('source_available_date'))) for x in unapproved}
                conflict = len({economic(x) for x in same_stage}) > 1 or (len({x['version_order'] for x in unapproved}) == 1 and len(source_stages) > 1)
                if conflict:
                    selected.update(kind='conflict', reason='unapproved_or_same_stage_economic_conflict')
                result.append(selected)
        return result

    @staticmethod
    def cancelled(fact):
        return str(_get(fact, 'status', 'role', default='')).lower() in ('cancelled', 'canceled', '取消', '终止') or str(fact.get('role', '')).lower() in ('cancelled', 'canceled')

    @staticmethod
    def unsupported(fact):
        role = str(_get(fact, 'role', default='ordinary')).lower()
        kind = str(_get(fact, 'kind', default='ordinary')).lower()
        return (_bool(fact.get('unsupported_special')) or _bool(fact.get('unsupported')) or _bool(fact.get('conflict')) or
                kind not in ('ordinary', 'distribution', 'dividend', 'cash', 'stock', 'cash_and_stock', 'cancelled') or
                role in ('special_reorganization', 'unknown', 'rights_market_reference', 'unsupported', 'ambiguous'))

    def exclusion(self, code, cutoff, start):
        for f in self.versions(code, cutoff):
            if self.cancelled(f):
                continue
            if self.unsupported(f) and (f['ex'] is None or f['ex'] >= start):
                return 'known_unsupported_action'
        return ''

    def bridge(self, code, index):
        key = code, index
        if key in self.bridge_cache:
            return self.bridge_cache[key]
        left, right = self.calendar[index - 1], self.calendar[index]
        prior, quote = self.quotes.get(code, {}).get(left), self.quotes.get(code, {}).get(right)
        row = dict(ts_code=code, bridge_left=left, bridge_right=right, D=0., s=0., factor=None,
                   valid=False, reason='', late_source_hard_error=False, event_ids=[])
        if prior is None or quote is None:
            row['reason'] = 'missing_quote'
        else:
            c0, c1, pre = _number(_get(prior, 'close')), _number(_get(quote, 'close')), _number(_get(quote, 'pre_close'))
            if c0 is None or c1 is None or pre is None:
                row['reason'] = 'invalid_price'
            else:
                on_date = [x for x in self.versions(code, right) if x['ex'] == right]
                row['event_ids'] = [x['id'] for x in on_date]
                row['event_versions'] = [x['version'] for x in on_date]
                row['source_known_dates'] = [x['known'] for x in on_date]
                row['previous_close_text'], row['current_pre_close_text'] = _lex(prior, 'close'), _lex(quote, 'pre_close')
                selected = [x for x in on_date if not self.cancelled(x)]
                # Two economically distinct active identities on one date cannot be summed.
                if len(selected) > 1:
                    signatures = {(x['D'], x['s'], x['record'], x['pay'], x['listing']) for x in selected}
                    if len(signatures) != 1:
                        row['reason'] = 'conflicting_event_identity'
                    selected = selected[:1]
                if selected and not row['reason']:
                    f = selected[0]
                    sources = _get(f, 'sources', default=[])
                    if isinstance(sources, str):
                        sources = json.loads(sources)
                    usable_sources = []
                    for source in sources:
                        public = _day(source.get('known_date'))
                        available = next((d for d in self.calendar if d > public), None) if public else None
                        if public is None or (available and available <= right):
                            usable_sources.append(source)
                    if self.unsupported(f):
                        row['reason'] = 'unsupported_economic_action'
                    elif f.get('raw_source') == 'r5_bound_mapping' and sources and not usable_sources:
                        row['reason'] = 'no_source_document_available_on_consumed_bridge'
                    elif (f['D'] is None or f['s'] is None or f['bonus'] is None or f['bonus'] > f['s'] or
                          f['record'] != left or f['known'] > left or
                          (f['D'] > 0 and (not f['pay'] or f['pay'] < right)) or
                          (f['s'] > 0 and (not f['listing'] or f['listing'] < right))):
                        row['reason'] = 'ordinary_action_contract'
                    else:
                        row['D'], row['s'] = f['D'], f['s']
                if not row['reason']:
                    theoretical = (Decimal(_lex(prior, 'close')) - Decimal(str(row['D']))) / (1 + Decimal(str(row['s'])))
                    row['theoretical_pre_close'] = str(theoretical.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
                    if theoretical <= 0 or _display(_lex(quote, 'pre_close')) != _display(theoretical):
                        row['reason'] = 'pre_close_display_mismatch'
                        future = [x for versions in self.events.get(code, {}).values() for x in versions
                                  if x['ex'] == right and (not x['known'] or x['known'] > right) and not self.cancelled(x)]
                        for f in future:
                            if f['D'] is None or f['s'] is None or self.unsupported(f):
                                continue
                            later = (Decimal(_lex(prior, 'close')) - Decimal(str(f['D']))) / (1 + Decimal(str(f['s'])))
                            if later > 0 and _display(later) == _display(_lex(quote, 'pre_close')):
                                row['late_source_hard_error'] = True
                    else:
                        row['factor'] = (c1 * (1 + row['s']) + row['D']) / c0
                        row['valid'] = _number(row['factor']) is not None
                        if not row['valid']:
                            row['reason'] = 'invalid_total_return_factor'
                future = [x for versions in self.events.get(code, {}).values() for x in versions
                          if x['ex'] == right and (not x['known'] or x['known'] > right)]
                if future and not [x for x in self.versions(code, right) if x['ex'] == right]:
                    row['late_source_hard_error'] = True
                known_ids = {x['id']: x for x in on_date}
                for later in future:
                    original = known_ids.get(later['id'])
                    if original is None:
                        row['late_source_hard_error'] = True
                    elif ((self.cancelled(original), self.unsupported(original), original['record'], original['ex'], original['D'], original['s']) !=
                          (self.cancelled(later), self.unsupported(later), later['record'], later['ex'], later['D'], later['s'])):
                        row['late_source_hard_error'] = True
        self.bridge_cache[key] = row
        return row


def _schedule(raw, ref):
    supplied = _records(raw.get('schedule'))
    if supplied:
        result = []
        for row in supplied:
            formation = _day(_get(row, 'formation_date', 'signal_date', 'trade_date'))
            execution = _day(row['execution_date'])
            result.append(dict(formation_date=formation, execution_date=execution))
        if len({x['formation_date'] for x in result}) != len(result):
            raise ValueError('Duplicate schedule identity')
        # Independently check full-calendar ISO-week construction.
        for row in result:
            f, e = row['formation_date'], row['execution_date']
            if f not in ref.pos or e not in ref.pos or ref.pos[e] != ref.pos[f] + 1 or pd.Timestamp(f).isocalendar()[:2] == pd.Timestamp(e).isocalendar()[:2]:
                raise ValueError('Schedule is not last-open to next-open ISO week')
        return sorted(result, key=lambda x: x['formation_date'])
    weeks = defaultdict(list)
    for date in ref.calendar:
        weeks[pd.Timestamp(date).isocalendar()[:2]].append(date)
    dates = sorted(weeks)
    return [dict(formation_date=weeks[a][-1], execution_date=weeks[b][0]) for a, b in zip(dates, dates[1:])
            if '2018-01-01' <= weeks[b][0] <= '2020-12-31']


def _eligible(raw, ref, formation):
    result, seen = {}, set()
    for row in ref.universe:
        code = str(row['ts_code'])
        if code in seen:
            raise ValueError('Duplicate universe identity')
        seen.add(code)
        listed, exited = _day(row.get('list_date')), _day(row.get('delist_date'))
        if not re.fullmatch(r'(60\d{4}\.SH|00\d{4}\.SZ)', code) or not listed or listed > formation or (exited and exited <= formation):
            continue
        age = ref.pos[formation] + 1 - int(np.searchsorted(ref.calendar, listed))
        if age < 120:
            continue
        risk = False
        for n in ref.names.get(code, ()):
            start, end, ann = _day(n.get('start_date')), _day(n.get('end_date')), _day(n.get('ann_date'))
            if start and start <= formation and (not end or end >= formation) and ann and ann < formation and re.search(r'ST|^PT', str(n.get('name', '')), re.I):
                risk = True
                break
        if risk:
            continue
        sectors = {str(_get(s, 'l1_code', 'industry')) for s in ref.industries.get(code, ()) if
                   _day(s.get('in_date')) and _day(s.get('in_date')) <= formation and
                   (not _day(s.get('out_date')) or _day(s.get('out_date')) > formation) and
                   str(_get(s, 'l1_code', 'industry', default='')).strip()}
        if len(sectors) == 1:
            result[code] = next(iter(sectors))
    return result


def reference_preparation(raw_inputs):
    """Independent raw reconstruction, also used to authenticate an early stop."""
    ref = _Reference(raw_inputs)
    schedule = _schedule(raw_inputs, ref)
    features, exclusions, coverage, hard = [], [], [], list(ref.source_failures)
    consumed = {}
    amount_multiplier = raw_inputs.get('amount_multiplier', 1000.)
    if amount_multiplier != 1000.:
        raise ValueError('G2 raw amount is thousand CNY; conversion is fixed at 1000')
    for item in schedule:
        date = item['formation_date']
        end = ref.pos[date]
        if end < 273:
            hard.append(dict(formation_date=date, reason='insufficient_full_calendar_274_points'))
            break
        eligible = _eligible(raw_inputs, ref, date)
        count, windows, bridges = 0, 0, 0
        for code, industry in eligible.items():
            reason, late = '', False
            start = end - 273
            if not reason:
                quotes = ref.quotes.get(code, {})
                points = [quotes.get(d) for d in ref.calendar[start:end + 1]]
                if any(q is None for q in points):
                    reason = 'missing_quote'
                elif any(_number(q.get(field)) is None for q in points for field in ('open', 'high', 'low', 'close', 'vol', 'amount')):
                    reason = 'invalid_six_field_quote'
                elif math.fsum(float(q['amount']) for q in points[-20:]) / 20 * 1000. < 20_000_000:
                    reason = 'adv20_below_20m'
                elif float(points[-1]['close']) * 100 > 49_000:
                    reason = 'formation_lot_above_slot'
                elif ref.exclusion(code, date, ref.calendar[start]):
                    reason = 'known_unsupported_action'
                else:
                    windows += 1
                    links = [ref.bridge(code, index) for index in range(start + 1, end + 1)]
                    bridges += len(links)
                    bad = [x for x in links if not x['valid']]
                    late = any(x['late_source_hard_error'] for x in links)
                    if bad:
                        reason = bad[0]['reason']
                    elif late:
                        consumed.update({(x['ts_code'], x['bridge_right']): x for x in links})
                        hard.append(dict(formation_date=date, ts_code=code, reason='late_source_needed_for_consumed_bridge'))
                        break
                    else:
                        adv = math.fsum(float(q['amount']) for q in points[-20:]) / 20 * 1000.
                        close = float(points[-1]['close'])
                        if adv < 20_000_000:
                            reason = 'adv20_below_20m'
                        elif close * 100 > 49_000:
                            reason = 'formation_lot_above_slot'
                        else:
                            # Exactly the first 252 of the 273 internal intervals.
                            momentum = math.prod(x['factor'] for x in links[:252]) - 1
                            features.append(dict(trade_date=date, ts_code=code, industry=industry,
                                                 momentum=momentum, adv20_cny=adv, formation_close=close,
                                                 window_start=ref.calendar[start], signal_end=ref.calendar[end - 21]))
                            consumed.update({(x['ts_code'], x['bridge_right']): x for x in links})
                            count += 1
            if reason:
                exclusions.append(dict(trade_date=date, ts_code=code, reason=reason, late_source_hard_error=late))
        if hard:
            break
        coverage.append(dict(formation_date=date, historical_pool=len(eligible), eligible_count=count,
                             consumed_windows=windows, consumed_internal_bridges=bridges, passed=count >= 200 and not hard))
        if hard or count < 200:
            if count < 200:
                hard.append(dict(formation_date=date, reason='common_pool_below_200', eligible_count=count))
            break
    return dict(status='passed' if not hard else 'preparation_stopped', passed=not hard,
                feature_rows=pd.DataFrame(features), coverage=pd.DataFrame(coverage),
                exclusions=pd.DataFrame(exclusions), daily_bridge_audit=pd.DataFrame(ref.bridge_cache.values()),
                consumed_daily_bridge_audit=pd.DataFrame(consumed.values()),
                failures=hard, schedule=schedule, source_bindings_checked=True)


def reference_targets(feature_rows, schedule):
    """Independent two-path selection; no production retention helper."""
    rows = _records(feature_rows)
    previous = dict(momentum=set(), control=set())
    result = dict(momentum=[], control=[])
    for plan in _records(schedule):
        date = _day(_get(plan, 'formation_date', 'trade_date', 'signal_date'))
        group = [dict(x) for x in rows if _day(x['trade_date']) == date]
        scores = pd.Series([float(x['momentum']) for x in group]).rank(method='average', pct=True).tolist()
        for row, score in zip(group, scores):
            row['score'] = score
        lookup = {x['ts_code']: x for x in group}
        for path in ('momentum', 'control'):
            if path == 'momentum':
                ordered = sorted(lookup, key=lambda c: (-lookup[c]['score'], c))
            else:
                ordered = sorted(lookup, key=lambda c: (hashlib.sha256(('CF2026_G2_MOM_CONTROL_V1|' + c).encode('utf-8')).hexdigest(), c))
            chosen, blocked, new = [], set(), set()
            def fits(codes):
                return max(Counter(lookup[c]['industry'] for c in codes).values(), default=0) <= 5
            for code in ordered:
                if code not in previous[path]:
                    continue
                if fits(chosen + [code]):
                    chosen.append(code)
                else:
                    blocked.add(code)
            for code in ordered:
                if len(chosen) >= 20:
                    break
                if code not in chosen and code not in blocked and fits(chosen + [code]):
                    chosen.append(code)
                    new.add(code)
            if path == 'momentum':
                for _ in range(5):
                    pair = None
                    for buyer in ordered:
                        if buyer in chosen or buyer in blocked:
                            continue
                        sellers = sorted((c for c in chosen if c not in new), key=lambda c: (lookup[c]['score'], c))
                        for seller in sellers:
                            if lookup[buyer]['score'] <= lookup[seller]['score'] + .05:
                                break
                            if fits([c for c in chosen if c != seller] + [buyer]):
                                pair = seller, buyer
                                break
                        if pair:
                            break
                    if not pair:
                        break
                    seller, buyer = pair
                    chosen.remove(seller)
                    chosen.append(buyer)
                    new.add(buyer)
                    blocked.add(seller)
            previous[path] = set(chosen)
            for code in chosen:
                result[path].append(dict(formation_date=date, execution_date=_day(plan['execution_date']),
                                         ts_code=code, target_weight=.049))
    return {path: pd.DataFrame(values, columns=['formation_date', 'execution_date', 'ts_code', 'target_weight']) for path, values in result.items()}


def _compare_table(expected, actual, keys, values, label, mismatches):
    e, a = {}, {}
    for source, sink in ((expected, e), (actual, a)):
        for row in _records(source):
            normal = dict(row)
            if 'formation_date' in keys and 'formation_date' not in normal:
                normal['formation_date'] = _get(normal, 'trade_date', 'signal_date')
            key = tuple(_day(normal.get(k)) if 'date' in k or k in ('bridge_left', 'bridge_right') else str(normal.get(k)) for k in keys)
            if key in sink:
                mismatches.append(dict(check=label, reason='duplicate_identity', key=key))
            sink[key] = normal
    if set(a) != set(e):
        mismatches.append(dict(check=label, reason='key_set_mismatch', expected_count=len(e), actual_count=len(a),
                               missing=list(sorted(set(e) - set(a)))[:5], extra=list(sorted(set(a) - set(e)))[:5]))
    for key in set(e) & set(a):
        for field in values:
            left, right = e[key].get(field), a[key].get(field)
            same = _close(left, right) if isinstance(left, (int, float, np.number)) and not isinstance(left, bool) else (str(left) == str(right))
            if not same:
                mismatches.append(dict(check=label, reason='value_mismatch', key=key, field=field, expected=left, actual=right))
                if len(mismatches) > 100:
                    return


def audit_preparation(raw_inputs, prepared, targets=None):
    """Recompute the prepared prefix and validate either success or real stop."""
    mismatches = []
    try:
        expected = reference_preparation(raw_inputs)
    except (ValueError, KeyError, ArithmeticError) as exc:
        return dict(status='audit_failed', passed=False, values_recomputed=False,
                    mismatches=[dict(check='raw_inputs', reason=str(exc))], accounts_allowed=False)
    _compare_table(expected['feature_rows'], prepared.get('feature_rows'), ['trade_date', 'ts_code'],
                   ['industry', 'momentum', 'adv20_cny', 'formation_close'], 'features', mismatches)
    # Coverage is independently asserted against every processed formation even
    # when the producer stops before writing any target or summary row.
    actual_coverage = prepared.get('coverage')
    if actual_coverage is not None:
        aliases = []
        for row in _records(actual_coverage):
            aliases.append(dict(row, formation_date=_get(row, 'formation_date', 'trade_date'),
                                eligible_count=_get(row, 'eligible_count', 'common_pool_count', 'common_pool', 'eligible', 'qualified_count')))
        _compare_table(expected['coverage'], aliases, ['formation_date'], ['eligible_count'], 'coverage', mismatches)
    else:
        mismatches.append(dict(check='coverage', reason='missing_producer_coverage'))
    if prepared.get('daily_bridge_audit') is not None:
        actual_bridges = []
        for row in _records(prepared['daily_bridge_audit']):
            actual_bridges.append(dict(row, theoretical_pre_close=row.get('theoretical_pre_close_text', row.get('theoretical_pre_close'))))
        _compare_table(expected['consumed_daily_bridge_audit'], actual_bridges, ['ts_code', 'bridge_left', 'bridge_right'],
                       ['D', 's', 'previous_close_text', 'current_pre_close_text', 'theoretical_pre_close', 'valid', 'late_source_hard_error'],
                       'consumed_daily_bridges', mismatches)
        actual_map = {(x['ts_code'], _day(x['bridge_right'])): x for x in actual_bridges}
        for row in _records(expected['consumed_daily_bridge_audit']):
            actual = actual_map.get((row['ts_code'], row['bridge_right']))
            if actual is None:
                continue
            for field in ('event_ids', 'event_versions', 'source_known_dates'):
                supplied = actual.get(field, [])
                if isinstance(supplied, str):
                    supplied = json.loads(supplied)
                if list(supplied) != row.get(field, []):
                    mismatches.append(dict(check='consumed_daily_bridges', reason='event_cutoff_or_version_mismatch',
                                           ts_code=row['ts_code'], bridge_right=row['bridge_right'], field=field))
    else:
        mismatches.append(dict(check='consumed_daily_bridges', reason='missing_producer_bridge_evidence'))
    summary = prepared.get('summary', prepared)
    producer_passed = _get(summary, 'passed', 'preparation_passed')
    if producer_passed is not None and _bool(producer_passed) != expected['passed']:
        mismatches.append(dict(check='stop', reason='producer_stop_disagrees_with_raw_reconstruction'))
    # A stopped producer must have an authentic failed date and cause, not just
    # a forged passed=False boolean.
    if not expected['passed']:
        producer_failures = _records(prepared.get('failures', []))
        producer_status = str(_get(summary, 'status', default=''))
        if not producer_failures and producer_status not in ('preparation_stopped', 'source_gate_failed', 'stopped', 'failed'):
            mismatches.append(dict(check='stop', reason='missing_stop_evidence'))
    target_verified = False
    if expected['passed'] and targets is not None:
        reference = reference_targets(expected['feature_rows'], expected['schedule'])
        for path in ('momentum', 'control'):
            supplied = targets.get(path, targets.get('main' if path == 'momentum' else path))
            _compare_table(reference[path], supplied, ['formation_date', 'execution_date', 'ts_code'], ['target_weight'], path + '_targets', mismatches)
        target_verified = not mismatches
    return dict(status='audit_failed' if mismatches else ('passed' if expected['passed'] else 'verified_preparation_stop'),
                passed=not mismatches and expected['passed'], audit_consistent=not mismatches,
                accounts_allowed=not mismatches and expected['passed'] and target_verified,
                values_recomputed=True, independent_event_admission=True, source_bindings_checked=True,
                target_verified=target_verified, mismatches=mismatches, independent_failures=expected['failures'],
                coverage=expected['coverage'].to_dict('records'), unique_daily_bridges=len(expected['daily_bridge_audit']),
                window_points=274, internal_intervals=273, momentum_intervals=252, skipped_intervals=21)


def _fee(notional, side, cost_bps):
    if not notional or cost_bps == 0:
        return 0.
    return round(max(5., .0003 * notional) + .00002 * notional + (.001 * notional if side == 'sell' else 0.), 2)


def _execution(side, requested, cash, reserve, held, sellable, quote, adv, cost_bps, suspended=False):
    """Independent one-shot fill arithmetic, including the cash reserve."""
    if suspended:
        return 0, 0., 0., 'suspended'
    if quote is None:
        return 0, 0., 0., 'missing_or_invalid_market_data'
    opening, upper, lower = (_number(quote.get(k)) for k in ('open', 'up_limit', 'down_limit'))
    if any(x is None for x in (opening, upper, lower, adv)):
        return 0, 0., 0., 'missing_or_invalid_market_data'
    if lower > upper or opening < lower - 1e-8 or opening > upper + 1e-8:
        return 0, 0., 0., 'inconsistent_price_limits'
    if (side == 'buy' and opening >= upper - 1e-8) or (side == 'sell' and opening <= lower + 1e-8):
        return 0, 0., 0., 'price_limit'
    raw = opening * (1 + cost_bps / 10000 * (1 if side == 'buy' else -1))
    price = float(Decimal(str(raw)).quantize(Decimal('.01'), rounding=ROUND_CEILING if side == 'buy' else ROUND_FLOOR))
    if price > upper + 1e-8 or price < lower - 1e-8 or price <= 0:
        return 0, 0., 0., 'slippage_outside_limits'
    qty = min(int(requested), int(.005 * adv / price))
    if side == 'buy':
        spending = round(max(0., cash - reserve), 2)
        qty = min(qty, int(spending / price)) // 100 * 100
        while qty > 0 and round(qty * price, 2) + _fee(qty * price, side, cost_bps) > spending + 1e-8:
            qty -= 100
    else:
        qty = min(qty, sellable)
        if qty != held:
            qty = qty // 100 * 100
    if qty <= 0:
        return 0, 0., 0., 'cash_capacity_lot_or_t1'
    notional = round(qty * price, 2)
    fee = _fee(notional, side, cost_bps)
    if side == 'sell' and round(cash + notional - fee, 2) < 0:
        return 0, 0., 0., 'insufficient_cash_for_fee'
    return qty, price, fee, ''


def _suspended(raw, code, date, quote, *, full_day=False, require_known=False):
    if quote is not None and _bool(quote.get('suspended')):
        return True
    for row in _records(raw.get('suspensions')):
        if isinstance(row, (tuple, list)) and len(row) == 2:
            if _day(row[0]) == date and str(row[1]) == code:
                return True
            continue
        if str(row.get('ts_code')) != code:
            continue
        start = _day(_get(row, 'suspend_date', 'trade_date', 'start_date'))
        end = _day(_get(row, 'resume_date', 'end_date'))
        if 'trade_date' in row:
            if str(row.get('suspend_type')) != 'S' or start != date:
                continue
            timing = _get(row, 'suspend_timing', default='')
            if not str(timing).strip():
                return True
            times = [int(h) * 60 + int(m) for h, m in re.findall(r'(\d{1,2}):(\d{2})', str(timing))]
            intervals = list(zip(times[::2], times[1::2]))
            if not intervals or len(times) % 2 or any(a >= b for a, b in intervals):
                if require_known:
                    raise ValueError('Unparseable suspension timing on actual planned/valuation consumption')
                continue
            if full_day:
                def covers(start, end):
                    reach = start
                    for a, b in sorted(intervals):
                        if a <= reach:
                            reach = max(reach, b)
                    return reach >= end
                if covers(570, 690) and covers(780, 900):
                    return True
            elif any(a <= 570 < b for a, b in intervals):
                return True
            continue
        if 'suspend_type' not in row and start and start <= date and end and date < end:
            return True
    return False


def audit_account(raw_inputs, result, targets, cost_bps=10):
    """Rebuild cash/H/U/receivables from raw actions and independently sized plans.

    Actual order records are observations to check, never ledger authority.  A
    missing fill, extra fill, changed fee, future resize or moved weekly plan is
    detected before its cash can influence the independent daily reconstruction.
    """
    if cost_bps not in (0, 10, 30):
        raise ValueError('Only the three approved cost scenarios are supported')
    mismatches, hard = [], []
    try:
        ref = _Reference(raw_inputs)
        schedule = _schedule(raw_inputs, ref)
    except (ValueError, KeyError) as exc:
        return dict(status='audit_failed', passed=False, mismatches=[dict(check='raw_inputs', reason=str(exc))])
    if ref.source_failures:
        return dict(status='audit_failed', passed=False, mismatches=ref.source_failures)
    target_rows = _records(targets)
    target_map = defaultdict(dict)
    for row in target_rows:
        formation = _day(_get(row, 'formation_date', 'signal_date', 'trade_date'))
        code = str(row['ts_code'])
        if code in target_map[formation]:
            raise ValueError('Duplicate target identity')
        weight = float(row['target_weight'])
        if weight not in (0., .049):
            raise ValueError('Nonregistered target weight')
        target_map[formation][code] = weight
    orders = defaultdict(list)
    for row in _records(result.get('orders')):
        orders[_day(_get(row, 'date', 'trade_date'))].append(row)
    actual_intents = defaultdict(list)
    for row in _records(result.get('intents')):
        actual_intents[_day(_get(row, 'formation_date', 'signal_date'))].append(row)
    nav_records = _records(result.get('nav'))
    actual_nav = {_day(_get(x, 'date', 'trade_date')): x for x in nav_records}
    if len(actual_nav) != len(nav_records):
        mismatches.append(dict(check='nav', reason='duplicate_daily_identity'))
    actual_holdings = defaultdict(dict)
    for row in _records(result.get('holdings')):
        date, code = _day(_get(row, 'date', 'trade_date')), str(row['ts_code'])
        if code in actual_holdings[date]:
            mismatches.append(dict(check='holdings', date=date, ts_code=code, reason='duplicate_identity'))
        actual_holdings[date][code] = row
    actual_obligations = defaultdict(list)
    for row in _records(result.get('obligations')):
        actual_obligations[_day(_get(row, 'date', 'trade_date'))].append(row)
    by_formation = {x['formation_date']: x for x in schedule}
    by_execution = {x['execution_date']: x for x in schedule}
    cash, held, prices, mark_dates = 1_000_000., defaultdict(int), {}, {}
    display_references = {}
    pending, entitlements, entitlement_terms, applied, plans = [], {}, {}, set(), {}
    reconstructed, expected_intents, expected_orders, expected_events = [], [], [], []
    position_history = {}
    episodes, active_episodes = [], {}
    initial_plan = None
    first_execution = min(by_execution) if by_execution else None
    prior_equity = 1_000_000.
    cumulative_fees = cumulative_slippage = 0.
    last_complete_state = dict(cash=1_000_000., positions={}, pending={})

    def fail(check, date, code='', **details):
        if len(mismatches) < 200:
            mismatches.append(dict(check=check, date=date, ts_code=code, **details))

    def unlisted(code):
        return sum(x['shares'] for x in pending if x['code'] == code)

    def ar():
        return math.fsum(x['cash'] for x in pending)

    def components():
        h = math.fsum(q * prices[c] for c, q in held.items() if q)
        u = math.fsum(x['shares'] * prices[x['code']] for x in pending if x['shares'])
        return dict(cash=cash, stock_value=h, bonus_value=u, receivable=ar(), equity=cash + h + u + ar())

    def freeze(date, equity):
        nonlocal initial_plan
        plan = by_formation[date]
        codes = set(target_map[date]) | {c for c, q in held.items() if q} | {x['code'] for x in pending if x['shares']}
        frozen = {}
        for code in sorted(codes):
            h, u = held[code], unlisted(code)
            weight = target_map[date].get(code, 0.)
            if not weight and not h + u:
                continue
            quote = ref.quotes.get(code, {}).get(date)
            close = (_number(quote.get('close')) if quote else None) if weight else prices.get(code)
            if close is None:
                hard.append(dict(date=date, ts_code=code, reason='formation_missing_reference_price'))
                continue
            total = 100 * math.floor(weight * equity / (100 * close)) if weight else 0
            difference = total - h - u
            side = 'buy' if difference > 0 else ('sell' if difference < 0 else 'none')
            requested = (int(difference) // 100 * 100 if difference > 0 else
                         h if total == 0 else min(h // 100 * 100, int(-difference) // 100 * 100)) if side != 'none' else 0
            index = ref.pos[date]
            trailing = [ref.quotes.get(code, {}).get(d) for d in ref.calendar[index - 19:index + 1]]
            adv = None if len(trailing) != 20 or any(q is None or _number(q.get('amount')) is None for q in trailing) else math.fsum(float(q['amount']) for q in trailing) / 20 * 1000.
            if adv is None:
                bad_dates = [d for d in ref.calendar[index - 19:index + 1]
                             if ref.quotes.get(code, {}).get(d) is None or _number(ref.quotes[code][d].get('amount')) is None]
                if len(trailing) != 20 or any(not _suspended(raw_inputs, code, d, ref.quotes.get(code, {}).get(d), full_day=True) for d in bad_dates):
                    hard.append(dict(date=date, ts_code=code, reason='unexplained_incomplete_formation_adv20'))
            conversion = 1.
            for f in ref.versions(code, date):
                if f['ex'] and date < f['ex'] <= plan['execution_date'] and not ref.cancelled(f):
                    if ref.unsupported(f) or f['s'] is None:
                        hard.append(dict(date=date, ts_code=code, reason='undefined_intent_unit_conversion'))
                    else:
                        conversion *= 1 + f['s']
            execute_request = int(math.floor(requested * conversion + 1e-8))
            if side == 'buy' or total > 0:
                execute_request = execute_request // 100 * 100
            record = dict(formation_date=date, execution_date=plan['execution_date'], ts_code=code,
                          formation_equity=equity, formation_close=close, held_shares=h, pending_shares=u,
                          target_shares=total, requested=requested, side=side, cash_reserve=.02 * equity,
                          adv20_cny=adv, conversion=conversion, execution_requested=execute_request,
                          target_weight=weight)
            frozen[code] = record
            expected_intents.append(record)
            if not weight and h + u > 0 and code not in active_episodes:
                episode = dict(ts_code=code, formation_date=date, execution_date=plan['execution_date'],
                               denominator_shares=h + u, formation_close=close, first_plan_sold=0.,
                               security_risk_closed_date=None, reversed=False, reversal_date=None)
                episodes.append(episode)
                active_episodes[code] = episode
            elif weight and code in active_episodes:
                active_episodes[code]['reversed'] = True
                if active_episodes[code]['reversal_date'] is None:
                    active_episodes[code]['reversal_date'] = date
        plans[plan['execution_date']] = frozen
        if initial_plan is None:
            initial_plan = frozen
        supplied = {str(x['ts_code']): x for x in actual_intents.get(date, [])}
        if len(supplied) != len(actual_intents.get(date, [])):
            fail('intents', date, reason='duplicate_formation_identity')
        # Zero-request intentions may be omitted; all positive requests are mandatory.
        for code, record in frozen.items():
            observed = supplied.get(code)
            if observed is None:
                if record['requested']:
                    fail('intents', date, code, reason='missing_formation_intent')
                continue
            aliases = dict(formation_equity=('formation_equity', 'equity_at_formation', 'equity', 'E'), formation_close=('formation_close', 'reference_price', 'C'),
                           held_shares=('held_shares', 'formation_listed_shares', 'held', 'H'), pending_shares=('pending_shares', 'formation_unlisted_shares', 'unlisted', 'U'),
                           target_shares=('target_shares', 'target_total_shares', 'target_total', 'T'), requested=('requested_formation_shares', 'requested', 'request', 'original_requested'),
                           cash_reserve=('cash_reserve', 'reserve'), adv20_cny=('adv20_cny',))
            for field, fields in aliases.items():
                value = _get(observed, *fields)
                if value is None and record[field] is not None:
                    fail('intents', date, code, reason='missing_formation_field', field=field)
                elif record[field] is not None and not _close(value, record[field]):
                    fail('intents', date, code, reason='formation_value_mismatch', field=field, expected=record[field], actual=value)
        for code in set(supplied) - set(frozen):
            fail('intents', date, code, reason='extra_formation_intent')

    # The baseline has an initial account state and can also be the first formation.
    baseline = '2017-12-29'
    if baseline in by_formation:
        freeze(baseline, 1_000_000.)
    if baseline in actual_nav:
        for field in ('cash', 'equity'):
            if not _close(actual_nav[baseline].get(field), 1_000_000.):
                fail('baseline', baseline, reason='initial_injection_mismatch', field=field)
    dates = [d for d in ref.calendar if '2018-01-01' <= d <= '2020-12-31']
    observed_last = max((d for d in actual_nav if d != baseline), default=None)
    terminal = result.get('terminal', result.get('summary', {}))
    producer_stopped = str(result.get('status', terminal.get('status', ''))).lower() in ('stopped', 'failed', 'account_stopped', 'data_failed')
    if producer_stopped:
        stop_date = _day(_get(terminal, 'failure_date', 'date', default=_get(result, 'failure_date', 'date')))
        if stop_date:
            dates = [d for d in dates if d <= stop_date]
        # When a partial result omits the failed session, include its next raw
        # session so a source stop is actually reproduced, rather than asserted.
        elif observed_last:
            next_index = ref.pos[observed_last] + 1
            stop_date = ref.calendar[next_index] if next_index < len(ref.calendar) else observed_last
            dates = [d for d in dates if d <= stop_date]
    for date in dates:
        sellable = dict(held)
        # Event eligibility comes from raw facts at this session, independently.
        all_known = [f for code in ref.events for f in ref.versions(code, date)]
        scope = {c for c, q in held.items() if q} | {x['code'] for x in pending if x['cash'] or x['shares']} | {c for (c, identity), q in entitlements.items() if q and (c, identity) not in applied}
        scope |= {c for c, intent in plans.get(date, {}).items() if intent['requested']}
        for code in scope:
            metadata = next((x for x in ref.universe if str(x['ts_code']) == code), None)
            if metadata is None or not _day(metadata.get('list_date')) or date <= _day(metadata['list_date']):
                hard.append(dict(date=date, ts_code=code, reason='unknown_or_prelisting_exposure'))
            elif _day(metadata.get('delist_date')) and date >= _day(metadata['delist_date']):
                hard.append(dict(date=date, ts_code=code, reason='unknown_delisting_recovery'))
            for f in (x for x in all_known if x['code'] == code and not ref.cancelled(x)):
                if ref.unsupported(f) and (not f['ex'] or f['ex'] >= date):
                    hard.append(dict(date=date, ts_code=code, reason='unsupported_exposed_future_plan'))
        active = [f for f in all_known if not ref.cancelled(f) and f['code'] in scope]
        for code in scope:
            known_ids = {f['id'] for f in all_known if f['code'] == code and f['ex'] == date}
            for versions in ref.events.get(code, {}).values():
                for f in versions:
                    if f['ex'] == date and f['id'] not in known_ids and (not f['known'] or f['known'] > date):
                        hard.append(dict(date=date, ts_code=code, reason='actual_exposure_requires_unavailable_event_terms'))
        for f in all_known:
            key = f['code'], f['id']
            if key not in entitlements or not entitlements[key] or key in applied:
                continue
            if ref.cancelled(f):
                entitlements[key] = 0
                expected_events.append(dict(date=date, ts_code=f['code'], event_id=f['id'], event='cancelled'))
            elif key in entitlement_terms and any(f[x] != entitlement_terms[key][x] for x in ('record', 'ex', 'D', 's', 'bonus')):
                hard.append(dict(date=date, ts_code=f['code'], reason='registered_economic_terms_changed'))
        for f in active:
            code = f['code']
            if f['ex'] != date:
                continue
            if ref.unsupported(f) and (held[code] or unlisted(code) or code in plans.get(date, {})):
                hard.append(dict(date=date, ts_code=code, reason='unsupported_exposed_economic_action'))
                continue
            if f['D'] is None or f['s'] is None or f['bonus'] is None:
                if held[code] or unlisted(code):
                    hard.append(dict(date=date, ts_code=code, reason='undefined_exposed_economic_amount'))
                continue
            if not _get(f, 'raw_source', 'source', 'sources'):
                hard.append(dict(date=date, ts_code=code, reason='ordinary_exposure_has_no_frozen_source'))
                continue
            if f['record'] != ref.calendar[ref.pos[date] - 1] or f['known'] > f['record'] or f['bonus'] > f['s']:
                hard.append(dict(date=date, ts_code=code, reason='ordinary_record_or_amount_contract'))
                continue
            key = code, f['id']
            day_intent = plans.get(date, {}).get(code)
            if day_intent and day_intent['requested'] and f['s']:
                frozen = next((v for v in ref.versions(code, day_intent['formation_date']) if v['id'] == f['id']), None)
                if frozen is None or any(frozen[x] != f[x] for x in ('record', 'ex', 'D', 's', 'bonus')):
                    hard.append(dict(date=date, ts_code=code, reason='execution_needs_share_units_unavailable_at_formation'))
                    continue
            if key not in entitlements and position_history.get(f['record'], {}).get(code, 0):
                hard.append(dict(date=date, ts_code=code, reason='past_held_registration_requires_unavailable_terms'))
                continue
            if key in applied:
                hard.append(dict(date=date, ts_code=code, reason='duplicate_ex_action'))
                continue
            applied.add(key)
            if code in prices:
                exact_previous = display_references.get(code, Decimal(str(prices[code])))
                prices[code] = (prices[code] - f['D']) / (1 + f['s'])
                display_references[code] = (exact_previous - Decimal(str(f['D']))) / (1 + Decimal(str(f['s'])))
            entitled = entitlements.get(key, 0)
            if entitled:
                gross = round(entitled * f['D'], 2)
                tax = round((gross + entitled * f['bonus']) * .20, 2)
                bonus = math.floor(entitled * f['s'] + 1e-8)
                payable = f['pay'] if gross else f['listing']
                if ((gross - tax) and not payable) or (payable and payable < date) or (f['listing'] and f['listing'] < date):
                    hard.append(dict(date=date, ts_code=code, reason='undefined_exposed_settlement_date'))
                else:
                    pending.append(dict(code=code, event_id=f['id'], cash=gross - tax, shares=bonus,
                                        cash_pay=payable, stock_pay=f['listing'], entitled_shares=entitled,
                                        frozen_D=f['D'], frozen_s=f['s'], frozen_bonus=f['bonus']))
                    expected_events.append(dict(date=date, ts_code=code, event_id=f['id'], event='ex',
                                                entitled_shares=entitled, gross_cash=gross, assumed_tax=tax, bonus_shares=bonus,
                                                cash_delta=0., positions_delta=0, pending_delta=bonus, receivable_delta=gross - tax))
        for item in pending:
            current = next((f for f in active if f['code'] == item['code'] and f['id'] == item['event_id']), None)
            if current is None or (current['D'], current['s'], current['bonus']) != (item['frozen_D'], item['frozen_s'], item['frozen_bonus']):
                hard.append(dict(date=date, ts_code=item['code'], reason='outstanding_economic_terms_changed_or_missing'))
                continue
            for pending_field, fact_field in (('stock_pay', 'listing'), ('cash_pay', 'pay')):
                if pending_field == 'cash_pay' and not current['D']:
                    continue
                old, new = item[pending_field], current[fact_field]
                if not old and new:
                    if new < date:
                        hard.append(dict(date=date, ts_code=item['code'], reason='settlement_date_learned_after_effective_date'))
                    else:
                        item[pending_field] = new
                        expected_events.append(dict(date=date, ts_code=item['code'], event_id=item['event_id'],
                                                    event=pending_field + '_known'))
                elif old and new and old != new:
                    hard.append(dict(date=date, ts_code=item['code'], reason='outstanding_settlement_date_changed'))
            if item['cash'] and item['cash_pay'] and item['cash_pay'] <= date:
                expected_events.append(dict(date=date, ts_code=item['code'], event_id=item['event_id'], event='cash_settlement',
                                            cash=item['cash'], cash_delta=item['cash'], positions_delta=0, pending_delta=0,
                                            receivable_delta=-item['cash']))
                cash = round(cash + item['cash'], 2)
                item['cash'] = 0.
            if item['shares'] and item['stock_pay'] and item['stock_pay'] <= date:
                expected_events.append(dict(date=date, ts_code=item['code'], event_id=item['event_id'], event='stock_settlement',
                                            shares=item['shares'], cash_delta=0., positions_delta=item['shares'], pending_delta=-item['shares'], receivable_delta=0.))
                held[item['code']] += item['shares']
                sellable[item['code']] = sellable.get(item['code'], 0) + item['shares']
                item['shares'] = 0
        pending = [x for x in pending if x['cash'] or x['shares']]
        if cash < -1e-8:
            hard.append(dict(date=date, reason='cash_insufficient_for_action_tax'))
        price_scope = {c for c, q in held.items() if q} | {x['code'] for x in pending if x['shares']}
        price_scope |= {c for c, intent in plans.get(date, {}).items() if intent['requested']}
        for code in price_scope:
            quote = ref.quotes.get(code, {}).get(date)
            reliable = _suspended(raw_inputs, code, date, quote)
            if quote is None:
                try:
                    full_suspension = _suspended(raw_inputs, code, date, quote, full_day=True, require_known=True)
                except ValueError as exc:
                    hard.append(dict(date=date, ts_code=code, reason=str(exc)))
                    full_suspension = False
                if not full_suspension or code not in prices:
                    hard.append(dict(date=date, ts_code=code, reason='unexplained_planned_or_exposed_quote_gap'))
                continue
            volume, amount = _number(quote.get('vol'), nonnegative=True), _number(quote.get('amount'), nonnegative=True)
            if any(_number(quote.get(k)) is None for k in ('open', 'close', 'pre_close')) or volume is None or amount is None:
                hard.append(dict(date=date, ts_code=code, reason='invalid_exposed_raw_quote'))
                continue
            if (volume == 0) != (amount == 0):
                hard.append(dict(date=date, ts_code=code, reason='daily_volume_amount_conflict'))
            if volume == 0 and (held[code] or unlisted(code)) and not reliable:
                hard.append(dict(date=date, ts_code=code, reason='held_zero_volume_without_suspension_source'))
            previous = display_references.get(code)
            if previous is None:
                previous_quote = ref.quotes.get(code, {}).get(ref.calendar[ref.pos[date] - 1])
                previous = Decimal(_lex(previous_quote, 'close')) if previous_quote and _number(previous_quote.get('close')) else None
                for f in active:
                    if f['code'] == code and f['ex'] == date and f['D'] is not None and f['s'] is not None:
                        previous = (previous - Decimal(str(f['D']))) / (1 + Decimal(str(f['s']))) if previous is not None else None
            if previous is None or _display(previous) != _display(_lex(quote, 'pre_close')):
                hard.append(dict(date=date, ts_code=code, reason='unexplained_exposed_preclose_bridge'))
            for f in active:
                if f['code'] == code and f['ex'] == date and f.get('account_guard') == 'capitalization_tax_origin_unknown' and (quote is None or volume == 0):
                    hard.append(dict(date=date, ts_code=code, reason='unknown_capitalization_source_missing_quote_exposure'))
        if hard:
            break
        day_fees = day_slippage = turnover = 0.
        frozen = plans.get(date, {})
        observed = orders.get(date, [])
        ordered = sorted((x for x in frozen.values() if x['requested']), key=lambda x: (0 if x['side'] == 'sell' else 1, x['ts_code']))
        observed_keys = [(str(x['side']), str(x['ts_code'])) for x in observed]
        if observed_keys != [(x['side'], x['ts_code']) for x in ordered]:
            fail('orders', date, reason='one_shot_order_identity_or_order_mismatch', expected=[(x['side'], x['ts_code']) for x in ordered], actual=observed_keys)
        observed_map = {(str(x['side']), str(x['ts_code'])): x for x in observed}
        for intent in ordered:
            code, side = intent['ts_code'], intent['side']
            quote = ref.quotes.get(code, {}).get(date)
            vol, amount = (_number(quote.get(k), nonnegative=True) if quote else None for k in ('vol', 'amount'))
            try:
                reliable = _suspended(raw_inputs, code, date, quote, require_known=True)
            except ValueError as exc:
                hard.append(dict(date=date, ts_code=code, reason=str(exc)))
                reliable = False
            if quote and ((vol == 0) != (amount == 0)):
                hard.append(dict(date=date, ts_code=code, reason='daily_volume_amount_conflict'))
            suspended = reliable or (vol == 0 and amount == 0)
            quantity, price, fee, reason = _execution(side, intent['execution_requested'], cash, intent['cash_reserve'],
                                                      held[code], sellable.get(code, 0), quote, intent['adv20_cny'], cost_bps, suspended)
            before = cash
            notional = round(quantity * price, 2)
            if quantity:
                cash = round(cash + (notional - fee if side == 'sell' else -notional - fee), 2)
                held[code] += quantity if side == 'buy' else -quantity
                if side == 'sell':
                    sellable[code] = sellable.get(code, 0) - quantity
                day_fees += fee
                opening = float(quote['open'])
                day_slippage += quantity * abs(price - opening)
                turnover += notional
                episode = active_episodes.get(code)
                if episode and side == 'sell' and episode['formation_date'] == intent['formation_date']:
                    episode['first_plan_sold'] += quantity / intent['conversion']
            observation = observed_map.get((side, code))
            expected_order = dict(date=date, formation_date=intent['formation_date'], ts_code=code, side=side,
                                  requested=intent['execution_requested'], shares=quantity, price=price, fee=fee,
                                  notional=notional, cash_before=before, cash_after=cash, reason=reason)
            expected_orders.append(expected_order)
            if observation:
                for field in ('shares', 'price', 'fee', 'notional', 'cash_before', 'cash_after'):
                    if not _ledger_equal(observation.get(field), expected_order[field]):
                        fail('orders', date, code, reason='fill_arithmetic_mismatch', field=field, expected=expected_order[field], actual=observation.get(field))
                if _day(observation.get('formation_date')) != intent['formation_date']:
                    fail('orders', date, code, reason='cross_week_plan_splice')
                if not _close(_get(observation, 'requested', 'request'), intent['execution_requested']):
                    fail('orders', date, code, reason='execution_resized_fixed_intent')
        # Day-end raw marking; stale marks need reliable suspension evidence.
        for code in set(held) | {x['code'] for x in pending if x['shares']}:
            if not held[code] and not unlisted(code):
                continue
            quote = ref.quotes.get(code, {}).get(date)
            close = _number(quote.get('close')) if quote else None
            vol = _number(quote.get('vol'), nonnegative=True) if quote else None
            if close and vol and vol > 0:
                prices[code], mark_dates[code] = close, date
                display_references[code] = Decimal(_lex(quote, 'close'))
            elif code not in prices or not _suspended(raw_inputs, code, date, quote, full_day=True):
                hard.append(dict(date=date, ts_code=code, reason='unexplained_exposed_quote_gap'))
        if hard:
            # Do not manufacture a daily equity when a real source guard stopped.
            break
        expected_nav = dict(date=date, **components())
        expected_nav.update(fees=day_fees, slippage_cost=day_slippage, turnover_value=turnover)
        expected_nav['stale_value'] = math.fsum((held[c] + unlisted(c)) * prices[c] for c in prices if (held[c] or unlisted(c)) and mark_dates.get(c) != date)
        cumulative_fees += day_fees
        cumulative_slippage += day_slippage
        reconstructed.append(expected_nav)
        if expected_nav['equity'] <= 0:
            hard.append(dict(date=date, reason='nonpositive_equity'))
            break
        observed_nav = actual_nav.get(date)
        if observed_nav is None:
            fail('nav', date, reason='missing_daily_nav')
        else:
            for field in ('cash', 'stock_value', 'bonus_value', 'receivable', 'equity', 'fees', 'slippage_cost', 'turnover_value', 'stale_value'):
                if not _ledger_equal(observed_nav.get(field), expected_nav[field]):
                    fail('nav', date, reason='daily_ledger_mismatch', field=field, expected=expected_nav[field], actual=observed_nav.get(field))
        exposed = {c for c, q in held.items() if q} | {x['code'] for x in pending if x['shares']}
        for code in exposed:
            row = actual_holdings[date].get(code)
            if row is None:
                fail('holdings', date, code, reason='missing_security_state')
                continue
            for field, value in (('shares', held[code]), ('pending_shares', unlisted(code)), ('mark', prices[code])):
                if not _close(row.get(field), value):
                    fail('holdings', date, code, reason='security_state_mismatch', field=field, expected=value, actual=row.get(field))
            if row.get('sellable') is not None and not _close(row['sellable'], sellable.get(code, 0)):
                fail('holdings', date, code, reason='sellable_state_mismatch')
        for code, row in actual_holdings[date].items():
            if code not in exposed and (float(row.get('shares', 0)) or float(row.get('pending_shares', 0))):
                fail('holdings', date, code, reason='invented_security_position')
        if pending or actual_obligations.get(date):
            observed_ar = math.fsum(float(x.get('cash', 0)) for x in actual_obligations[date])
            observed_u = sum(int(x.get('shares', 0)) for x in actual_obligations[date])
            if not _close(observed_ar, ar()) or observed_u != sum(x['shares'] for x in pending):
                fail('obligations', date, reason='pending_obligation_state_mismatch')
            expected_obligations = {x['event_id']: x for x in pending}
            observed_obligations = {str(x['event_id']): x for x in actual_obligations[date] if x.get('kind', 'pending') == 'pending'}
            if len(observed_obligations) != len([x for x in actual_obligations[date] if x.get('kind', 'pending') == 'pending']):
                fail('obligations', date, reason='duplicate_pending_identity')
            if set(expected_obligations) != set(observed_obligations):
                fail('obligations', date, reason='pending_obligation_identity_mismatch')
            for identity in set(expected_obligations) & set(observed_obligations):
                for field in ('cash', 'shares', 'entitled_shares'):
                    if not _ledger_equal(expected_obligations[identity][field], observed_obligations[identity].get(field)):
                        fail('obligations', date, expected_obligations[identity]['code'], reason='pending_obligation_value_mismatch', field=field)
        for f in (x for x in all_known if not ref.cancelled(x) and (held[x['code']] or unlisted(x['code']))):
            if f['record'] == date:
                if unlisted(f['code']):
                    hard.append(dict(date=date, ts_code=f['code'], reason='overlapping_unlisted_record_entitlement'))
                entitlements[(f['code'], f['id'])] = held[f['code']]
                entitlement_terms[(f['code'], f['id'])] = dict(f)
                expected_events.append(dict(date=date, ts_code=f['code'], event_id=f['id'], event='record', entitled_shares=held[f['code']]))
        position_history[date] = {code: shares for code, shares in held.items() if shares}
        for code, episode in list(active_episodes.items()):
            if held[code] + unlisted(code) == 0:
                episode['security_risk_closed_date'] = date
                del active_episodes[code]
        if date in by_formation:
            freeze(date, expected_nav['equity'])
        keep_prices = {c for c, q in held.items() if q} | {x['code'] for x in pending if x['shares']}
        keep_prices |= {c for (c, identity), q in entitlements.items() if q and (c, identity) not in applied}
        prices = {c: p for c, p in prices.items() if c in keep_prices}
        mark_dates = {c: d for c, d in mark_dates.items() if c in keep_prices}
        display_references = {c: p for c, p in display_references.items() if c in keep_prices}
        last_complete_state = dict(cash=cash, positions={c: n for c, n in held.items() if n},
                                   pending={x['event_id']: dict(x) for x in pending})
        prior_equity = expected_nav['equity']
    # Every initial and exit denominator is recomputed independently of summary.
    initial_planned = initial_filled = 0.
    if initial_plan:
        initial_planned = math.fsum(x['requested'] * x['formation_close'] for x in initial_plan.values() if x['side'] == 'buy')
        first_form = next(iter(initial_plan.values()))['formation_date'] if initial_plan else None
        for row in expected_orders:
            if row['formation_date'] == first_form and row['side'] == 'buy':
                intent = initial_plan[row['ts_code']]
                initial_filled += min(intent['requested'], row['shares'] / intent['conversion']) * intent['formation_close']
    observation_end = reconstructed[-1]['date'] if reconstructed else baseline
    for episode in episodes:
        episode['first_intent_completion'] = min(1., episode['first_plan_sold'] / episode['denominator_shares'])
        begin = ref.pos[episode['execution_date']]
        episode['complete_five_session_window'] = begin + 4 < len(ref.calendar) and ref.calendar[begin + 4] <= observation_end
        episode['product_verified'] = (episode['complete_five_session_window'] and episode['first_intent_completion'] >= .95 and
                                       episode['security_risk_closed_date'] is not None)
    if result.get('exit_episodes') is not None:
        observed_episodes = _records(result['exit_episodes'])
        if len(observed_episodes) != len(episodes):
            mismatches.append(dict(check='exit_episodes', reason='episode_count_mismatch', expected=len(episodes), actual=len(observed_episodes)))
        actual_episode_map = {(str(x['ts_code']), _day(x['formation_date'])): x for x in observed_episodes}
        for episode in episodes:
            observed = actual_episode_map.get((episode['ts_code'], episode['formation_date']))
            if observed:
                for field, aliases in (('denominator_shares', ('frozen_total_shares', 'denominator_shares')),
                                       ('first_plan_sold', ('first_intent_filled_equivalent', 'first_plan_sold')),
                                       ('first_intent_completion', ('first_intent_completion',))):
                    if not _close(_get(observed, *aliases), episode[field]):
                        mismatches.append(dict(check='exit_episodes', reason='episode_denominator_or_first_plan_mismatch',
                                               ts_code=episode['ts_code'], field=field, expected=episode[field], actual=_get(observed, *aliases)))
                for field, aliases in (('security_risk_closed_date', ('risk_closed_date', 'security_risk_closed_date')),
                                       ('reversal_date', ('reversal_date',)), ('execution_date', ('first_execution_date', 'execution_date'))):
                    if _day(_get(observed, *aliases)) != episode[field]:
                        mismatches.append(dict(check='exit_episodes', reason='episode_timing_mismatch', ts_code=episode['ts_code'], field=field))
                if _bool(observed.get('complete_five_session_window')) != episode['complete_five_session_window']:
                    mismatches.append(dict(check='exit_episodes', reason='five_session_window_mismatch', ts_code=episode['ts_code']))
                if _bool(observed.get('securities_risk_closed')) != (episode['security_risk_closed_date'] is not None):
                    mismatches.append(dict(check='exit_episodes', reason='risk_closure_claim_mismatch', ts_code=episode['ts_code']))
    # Match source-based corporate flows, so a forged event file is not excused
    # merely because its NAV happened to be left unchanged.
    actual_events = _records(result.get('corporate_events'))
    event_map = {(str(_get(x, 'ts_code', 'code')), _day(x['date']), str(x['event_id']), str(x['event'])): x for x in actual_events}
    if len(event_map) != len(actual_events):
        mismatches.append(dict(check='corporate_events', reason='duplicate_economic_flow_identity'))
    expected_event_map = {(x['ts_code'], x['date'], x['event_id'], x['event']): x for x in expected_events}
    if set(event_map) != set(expected_event_map):
        mismatches.append(dict(check='corporate_events', reason='economic_flow_identity_mismatch', expected=len(expected_event_map), actual=len(event_map)))
    for key in set(event_map) & set(expected_event_map):
        for field, value in expected_event_map[key].items():
            if isinstance(value, (int, float)) and not _close(event_map[key].get(field), value):
                mismatches.append(dict(check='corporate_events', reason='economic_flow_value_mismatch', key=key, field=field, expected=value, actual=event_map[key].get(field)))
    boundaries = []
    for year in (2018, 2019):
        before = [x for x in reconstructed if x['date'][:4] == str(year)]
        after = [x for x in reconstructed if x['date'][:4] == str(year + 1)]
        if before and after:
            boundaries.append(dict(previous_date=before[-1]['date'], next_date=after[0]['date'],
                                   previous_equity=before[-1]['equity'], next_equity=after[0]['equity'],
                                   cash_continuity_reconstructed=True, shares_continuity_reconstructed=True,
                                   receivables_continuity_reconstructed=True))
    annual, year_start = {}, 1_000_000.
    for year in (2018, 2019, 2020):
        part = [x for x in reconstructed if x['date'][:4] == str(year)]
        if part:
            annual[str(year)] = part[-1]['equity'] / year_start - 1
            year_start = part[-1]['equity']
    peak, drawdown = 1_000_000., 0.
    previous = 1_000_000.
    turnover_ratio = 0.
    for row in reconstructed:
        peak = max(peak, row['equity'])
        drawdown = max(drawdown, 1 - row['equity'] / peak)
        turnover_ratio += row['turnover_value'] / (2 * previous)
        previous = row['equity']
    summary = result.get('summary', {})
    for field, value in (('initial_completion', initial_filled / 980_000.), ('initial_unconditional_completion', initial_filled / 980_000.)):
        if field in summary and not _close(summary[field], value):
            mismatches.append(dict(check='product_denominator', reason='initial_980k_denominator_mismatch', field=field, expected=value, actual=summary[field]))
    for row in _records(result.get('deployment')):
        for field, value in (('denominator_cny', 980_000.), ('planned_cny', initial_planned), ('filled_formation_reference_cny', initial_filled),
                             ('unconditional_completion', initial_filled / 980_000.)):
            if not _close(row.get(field), value):
                mismatches.append(dict(check='deployment', reason='fixed_initial_denominator_mismatch', field=field, expected=value, actual=row.get(field)))
        if first_execution:
            final_position = ref.pos[first_execution] + 4
            complete_initial_window = final_position < len(ref.calendar) and ref.calendar[final_position] <= observation_end
            if _bool(row.get('complete_five_session_window')) != complete_initial_window:
                mismatches.append(dict(check='deployment', reason='initial_five_session_clock_mismatch'))
    state = result.get('account_state')
    if state is not None:
        if not _ledger_equal(state.get('cash'), last_complete_state['cash']):
            mismatches.append(dict(check='account_state', reason='terminal_cash_mismatch'))
        if {str(c): int(n) for c, n in state.get('positions', {}).items() if n} != last_complete_state['positions']:
            mismatches.append(dict(check='account_state', reason='terminal_positions_mismatch'))
        supplied_pending = state.get('pending', {})
        if not isinstance(supplied_pending, dict):
            supplied_pending = {str(x['event_id']): x for x in supplied_pending}
        if set(supplied_pending) != set(last_complete_state['pending']):
            mismatches.append(dict(check='account_state', reason='terminal_obligations_mismatch'))
        for identity in set(supplied_pending) & set(last_complete_state['pending']):
            for field in ('cash', 'shares', 'entitled_shares'):
                if not _ledger_equal(supplied_pending[identity].get(field), last_complete_state['pending'][identity][field]):
                    mismatches.append(dict(check='account_state', reason='terminal_obligation_value_mismatch', event_id=identity, field=field))
    if hard and not producer_stopped:
        mismatches.append(dict(check='stop', reason='required_account_stop_not_observed'))
    if producer_stopped and not hard:
        mismatches.append(dict(check='stop', reason='producer_stop_not_independently_reproduced'))
    complete = bool(reconstructed) and reconstructed[-1]['date'] == max(d for d in ref.calendar if d <= '2020-12-31') and not hard
    if not producer_stopped and not complete:
        mismatches.append(dict(check='coverage', reason='account_calendar_incomplete'))
    return dict(status='audit_failed' if mismatches else ('verified_account_stop' if hard else 'passed'),
                passed=not mismatches and complete, audit_consistent=not mismatches,
                independent_daily_ledger_reconstruction=True, summary_values_used_as_authority=False,
                daily_rows=len(reconstructed), intent_rows=len(expected_intents), order_rows=len(expected_orders),
                mismatches=mismatches, independent_failures=hard, annual_boundaries=boundaries, annual_boundary_count=len(boundaries),
                performance=dict(total_return=previous / 1_000_000. - 1, annual_returns=annual, maximum_drawdown=drawdown,
                                 fees=cumulative_fees, slippage_cost=cumulative_slippage,
                                 annualized_one_way_turnover=turnover_ratio * 252 / len(reconstructed) if reconstructed else None),
                initial_completion=dict(unconditional_denominator=980_000., planned_reference_amount=initial_planned,
                                        filled_reference_amount=initial_filled, unconditional_completion=initial_filled / 980_000.,
                                        whole_lot_plan_coverage=initial_planned / 980_000.,
                                        fill_of_plan=initial_filled / initial_planned if initial_planned else None),
                exit_episodes=episodes, product_exit_covered=bool(episodes),
                product_exit_verified=bool(episodes) and all(x['product_verified'] for x in episodes))
