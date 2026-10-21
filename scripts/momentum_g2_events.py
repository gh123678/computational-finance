"""Date-causal ordinary distribution facts for the approved momentum G2.

No vendor adjustment factor or legacy correction function is used.  Publication
dates and available session dates are deliberately separate fields.  The small
r5 mapping is a source supplement, never the ordinary distribution catalogue.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
import re

import pandas as pd


DATE_ALIASES = {'record_date': 'record', 'ex_date': 'ex', 'pay_date': 'cash_pay',
                'div_listdate': 'stock_pay'}
AMOUNT_ALIASES = {'cash_div_tax': 'cash_per_share', 'stk_div': 'stock_per_share',
                  'stk_bo_rate': 'taxable_bonus_per_share'}
ECONOMIC_FIELDS = ('record', 'ex', 'cash_pay', 'stock_pay', 'cash_per_share',
                   'stock_per_share', 'taxable_bonus_per_share')


def day(value):
    if value is None or pd.isna(value) or str(value).strip() == '':
        return None
    if isinstance(value, str) and re.fullmatch(r'\d{8}', value):
        parsed = pd.to_datetime(value, format='%Y%m%d', errors='coerce')
    else:
        try:
            parsed = pd.Timestamp(value)
        except (TypeError, ValueError):
            return None
    if pd.isna(parsed) or parsed.tzinfo is not None or parsed != parsed.normalize():
        return None
    return parsed.strftime('%Y-%m-%d')


def validate_calendar(calendar):
    c = pd.DatetimeIndex(calendar)
    if (c.empty or c.has_duplicates or c.hasnans or not c.is_monotonic_increasing
            or c.tz is not None or not c.equals(c.normalize())):
        raise ValueError('calendar must contain sorted unique whole exchange sessions')
    return c


def next_session(publication_date, calendar):
    d = day(publication_date)
    if d is None:
        return None
    pos = calendar.searchsorted(pd.Timestamp(d), side='right')
    return calendar[pos].strftime('%Y-%m-%d') if pos < len(calendar) else None


def number(value):
    if value is None or pd.isna(value) or isinstance(value, bool):
        return None
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return n if n.is_finite() and n >= 0 else None


def _code(value):
    result = str(value).upper()
    if not re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)', result):
        raise ValueError('invalid event security identity: ' + result)
    return result


def _signature(row):
    return tuple(row.get(f) for f in (*ECONOMIC_FIELDS, 'kind', 'role', 'reason'))


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (pd.Timestamp, Decimal)):
        return day(value) if isinstance(value, pd.Timestamp) else str(value)
    if value is None or not isinstance(value, (dict, list, tuple)) and pd.isna(value):
        return None
    return value


def _normalize(row, calendar):
    r = deepcopy(row)
    r['code'] = r['ts_code'] = _code(r.get('code', r.get('ts_code')))
    for alias, canonical in DATE_ALIASES.items():
        r[canonical] = day(r.get(canonical, r.get(alias)))
        r[alias] = r[canonical]
    for alias, canonical in AMOUNT_ALIASES.items():
        n = number(r.get(canonical, r.get(alias)))
        r[canonical] = str(n) if n is not None else None
        r[alias] = r[canonical]
    r['D'], r['s'], r['bonus'] = (r[k] for k in AMOUNT_ALIASES)
    r['event_id'] = str(r.get('event_id') or ('distribution:' + r['code'] + ':' + str(r['ex'])))
    r['version_id'] = str(r.get('version_id', r.get('version', 1)))
    r['version'] = int(r.get('version', 1))
    # Direct canonical fixtures can supply an already available known_date.
    # Production source adapters ALWAYS supply source_available_date.
    if day(r.get('source_available_date')) is not None:
        r['source_available_date'] = day(r['source_available_date'])
        r['known_date'] = next_session(r['source_available_date'], calendar)
    else:
        r['known_date'] = day(r.get('known_date'))
        r['source_available_date'] = None
    r.setdefault('kind', 'ordinary')
    r.setdefault('status', 'cancelled' if r['kind'] == 'cancelled' else 'active')
    r.setdefault('role', 'ordinary_distribution')
    r.setdefault('reason', '')
    r.setdefault('sources', [])
    r.setdefault('raw_source', None)
    r.setdefault('raw_row_id', None)
    r['ordinary'] = r['kind'] == 'ordinary'
    r['apply_distribution'] = r['ordinary'] and r['status'] == 'active'
    return r


class EventBook:
    """Immutable event versions; methods return detached date-causal views."""
    def __init__(self, calendar, versions=()):
        self.calendar = validate_calendar(calendar)
        self.versions = tuple(_normalize(r, self.calendar) for r in versions)
        grouped = defaultdict(list)
        for r in self.versions:
            grouped[(r['code'], r['event_id'])].append(r)
        self._groups = dict(grouped)
        self._by_code = defaultdict(list)
        self._by_ex = defaultdict(set)
        for key in self._groups:
            self._by_code[key[0]].append(key)
            for r in self._groups[key]:
                self._by_ex[(key[0], r['ex'])].add(key)

    def _selected(self, code, asof, keys=None):
        cutoff = day(asof)
        if cutoff is None:
            raise ValueError('event view needs a valid whole-day cutoff')
        rows = []
        for key in self._by_code.get(code, ()) if keys is None else keys:
            known = [r for r in self._groups[key] if r['known_date'] and r['known_date'] <= cutoff]
            if not known:
                continue
            last = max(r['known_date'] for r in known)
            same = [r for r in known if r['known_date'] == last]
            rank = max(r['version'] for r in same)
            same = [r for r in same if r['version'] == rank]
            selected = deepcopy(same[0])
            unapproved = [r for r in known if not r.get('explicit_revision')]
            unapproved_conflict = (len(unapproved) > 1 and len({r['version'] for r in unapproved}) == 1
                and len({(tuple(r.get(f) for f in ECONOMIC_FIELDS), r['source_available_date'], r['kind'])
                         for r in unapproved}) > 1)
            if len({_signature(r) for r in same}) > 1 or unapproved_conflict:
                selected.update(kind='conflict', ordinary=False, apply_distribution=False,
                                reason='conflicting_same_stage_versions')
                selected['conflicting_versions'] = deepcopy(same)
            # A source may be listed in the final mapping but never enter a
            # historical detached view before its own date-level availability.
            selected['sources'] = [deepcopy(s) for s in selected['sources']
                if not s.get('known_date') or next_session(s['known_date'], self.calendar)
                and next_session(s['known_date'], self.calendar) <= cutoff]
            rows.append(selected)
        return sorted(rows, key=lambda r: (r['ex'] or '9999', r['event_id']))

    def view(self, asof):
        return [r for c in sorted(self._by_code) for r in self._selected(c, asof)]

    def known_for_code(self, code, asof):
        return self._selected(_code(code), asof)

    def events_on(self, date, asof=None, code=None):
        date = day(date)
        rows = (self.view(asof or date) if code is None else
                self._selected(code, asof or date, self._by_ex.get((code, date), ())))
        return [r for r in rows if r['ex'] == date]

    def exposure_issues(self, code, asof, window_start=None):
        cutoff, start = day(asof), day(window_start)
        return [r for r in self.known_for_code(code, cutoff)
            if r['kind'] not in ('ordinary', 'cancelled') and r['status'] != 'cancelled'
            and (r['ex'] is None or r['ex'] > cutoff or start is None or r['ex'] >= start)]

    def inventory(self):
        return pd.DataFrame(deepcopy(self.versions))

    def to_inventory(self):
        return _jsonable(list(self.versions))

    @classmethod
    def from_inventory(cls, calendar, inventory):
        return cls(calendar, inventory.to_dict('records') if isinstance(inventory, pd.DataFrame) else inventory)

    def unknown_effective(self, code, ex):
        """Diagnostic only.  Never use these future rows to remove a past name."""
        ex = day(ex)
        return [deepcopy(r) for key in self._by_ex.get((code, ex), ()) for r in self._groups[key]
                if r['ex'] == ex and (r['known_date'] is None or r['known_date'] > ex)]


def ordinary_reason(row, calendar):
    """Validate ordinary old-shareholder terms including the prior session."""
    if row['kind'] != 'ordinary' or row['status'] != 'active':
        return row.get('reason') or row['kind']
    d, s, b = (number(row.get(k)) for k in ('cash_div_tax', 'stk_div', 'stk_bo_rate'))
    if d is None or s is None or b is None or b > s:
        return 'missing_or_invalid_ordinary_amount'
    ex, rec = row.get('ex'), row.get('record')
    pos = calendar.get_indexer([pd.Timestamp(ex)])[0] if ex else -1
    if pos <= 0 or rec != calendar[pos - 1].strftime('%Y-%m-%d'):
        return 'ordinary_record_not_previous_exchange_session'
    if not row.get('known_date') or row['known_date'] > rec:
        return 'ordinary_terms_unavailable_by_record'
    if d > 0 and (not row.get('cash_pay') or row['cash_pay'] < ex):
        return 'missing_or_invalid_cash_payment_date'
    if s > 0 and (not row.get('stock_pay') or row['stock_pay'] < ex):
        return 'missing_or_invalid_stock_listing_date'
    return ''


def bridge_terms(book, code, right):
    rows = book.events_on(right, right, code)
    active = [r for r in rows if r['kind'] != 'cancelled' and r['status'] != 'cancelled']
    if not active:
        return Decimal(0), Decimal(0), rows, ''
    if len(active) != 1:
        return None, None, rows, 'multiple_events_on_economic_bridge'
    row = active[0]
    reason = ordinary_reason(row, book.calendar)
    if reason:
        return None, None, rows, reason
    return number(row['cash_div_tax']), number(row['stk_div']), rows, ''


def display_price(value):
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not n.is_finite() or n <= 0:
        return None
    return n.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def _binding(raw, fact):
    for field in ECONOMIC_FIELDS:
        expected = fact.get(field)
        if field in ('record', 'ex', 'cash_pay', 'stock_pay'):
            equal = day(raw.get(field)) == day(expected)
        else:
            actual, exp = number(raw.get(field)), number(expected)
            # An explicitly frozen primary source may fill a missing cache
            # field.  It may never overwrite a contradictory numeric value.
            equal = actual is None and exp is not None or actual == exp
        if not equal:
            return False
    return True


def build_event_book(dividends, calendar, evidence=None, rights=(), *,
                     dividend_source='dividend.csv'):
    """Build all ordinary cached rows plus explicitly bound r5 stage facts.

    Raw missing implementation dates stay unavailable; ann_date is not used as
    a replacement implementation publication date.  No raw economic duplicate
    is summed, averaged, or silently selected by row order.
    """
    calendar = validate_calendar(calendar)
    evidence = evidence or {}
    rows = []
    for index, raw in zip(dividends.index, dividends.to_dict('records')):
        if raw.get('div_proc') != '实施':
            continue
        ex = day(raw.get('ex_date'))
        # Only this approved date range is admitted to any feature or account.
        if ex and not (calendar[0] <= pd.Timestamp(ex) <= calendar[-1]):
            continue
        r = dict(code=raw['ts_code'], event_id='distribution:' + raw['ts_code'] + ':' + str(ex),
                 source_available_date=raw.get('imp_ann_date'), version=1,
                 raw_source=dividend_source, raw_row_id=index, raw_record=deepcopy(raw),
                 sources=[], role='cached_implemented_ordinary', **{k: raw.get(k) for k in DATE_ALIASES},
                 **{k: raw.get(k) for k in AMOUNT_ALIASES})
        # A zero total distribution necessarily has a zero taxable bonus.
        # For a pure capital transfer an explicit component equality gives 0.
        if number(r.get('stk_bo_rate')) is None:
            s, co = number(raw.get('stk_div')), number(raw.get('stk_co_rate'))
            if s == 0 or (s is not None and s == co):
                r['stk_bo_rate'] = '0'
        r = _normalize(r, calendar)
        if ex is None or r['known_date'] is None:
            r.update(kind='unavailable', reason='missing_implementation_publication_or_effective_date')
        s, bo, co = (number(raw.get(k)) for k in ('stk_div', 'stk_bo_rate', 'stk_co_rate'))
        if s is not None and bo is not None and co is not None and s != bo + co:
            r.update(kind='conflict', reason='stock_total_component_conflict')
        rows.append(r)

    def replace_bound(fact, kind='ordinary', version=1, original=None):
        code, ex = fact['code'], day(fact.get('ex'))
        candidates = [r for r in rows if r['code'] == code and r['ex'] == ex
                      and r.get('raw_source') == dividend_source]
        expected = original or fact
        conflict = bool(candidates) and not all(_binding(r, expected) for r in candidates)
        # Explicit fact versions replace only the bound original identity.
        if not conflict:
            rows[:] = [r for r in rows if r not in candidates]
        item = dict(fact, source_available_date=fact.get('known_date'), kind='conflict' if conflict else kind,
                    version=version, explicit_revision=True, raw_source='r5_bound_mapping',
                    raw_record=deepcopy(fact))
        item['bound_fact_event_id'] = fact.get('event_id')
        item['event_id'] = 'distribution:' + code + ':' + str(ex)
        if conflict:
            item['reason'] = 'r5_source_does_not_bind_cached_original_action'
        rows.append(_normalize(item, calendar))

    for fact in evidence.get('ordinary_actions', ()):
        replace_bound(fact)
    grouped_versions = defaultdict(list)
    for fact in evidence.get('event_versions', ()):
        grouped_versions[(fact['code'], day(fact['ex']))].append(fact)
    for group in grouped_versions.values():
        for fact in sorted(group, key=lambda r: r['version']):
            kind = ('cancelled' if fact.get('role') == 'cancelled' else 'unsupported'
                    if fact.get('unsupported_special') else 'ordinary')
            replace_bound(fact, kind, fact['version'], fact.get('original_action'))

    # Known chronology conflict is an economic-source conflict, with its own
    # original implementation publication availability, never a current date.
    conflict_keys = {tuple(k) for k in evidence.get('source_facts', {}).get('publication_chronology_conflict_keys', ())}
    tax_keys = {tuple(k) for k in evidence.get('source_facts', {}).get('unsupported_capitalization_keys', ())}
    for r in rows:
        if (r['code'], r['ex']) in conflict_keys:
            r.update(kind='conflict', reason='bound_publication_chronology_conflict')
            r['sources'] = [dict(path=p, sha256=h, known_date=r['source_available_date'],
                                 role='bound_chronology_conflict_source')
                for p, h in evidence.get('consumed_source_files', {}).items()
                if Path(p).name.startswith(r['code'][:6] + '_') and p.lower().endswith('.pdf')]
        if (r['code'], r['ex']) in tax_keys:
            r['account_guard'] = 'capitalization_tax_origin_unknown'

    staged = {f['code'] + ':' + f['record']: f for f in evidence.get('rights_stages', ())}
    overlays = {f['code'] + ':' + f['record']: f for f in evidence.get('rights_overlay', ())}
    for issue in rights:
        item = vars(issue) if not isinstance(issue, dict) else issue
        code, record, ex = item['code'], day(item.get('record')), day(item.get('ex'))
        if ex is None or not (calendar[0] <= pd.Timestamp(ex) <= calendar[-1]):
            continue
        identity = code + ':' + str(record)
        fact = staged.pop(identity, None) or overlays.pop(identity, None)
        pub = (fact.get('terms_known_date', fact.get('planned_known_date')) if fact else None)
        conflict = bool(fact and (day(fact['ex']) != ex or day(fact['record']) != record))
        rows.append(dict(code=code, event_id='rights:' + identity, kind='conflict' if conflict else 'unsupported', role='rights_issue',
            status='active', record=record, ex=ex, source_available_date=pub,
            reason='rights_source_does_not_bind_registry' if conflict else 'rights_economics_not_supported',
            raw_source='verified_rights_registry', raw_record=deepcopy(item),
            sources=[s for s in fact.get('sources', ()) if s.get('known_date') == pub] if fact else []))
    # r5 includes the documented missing registry issue 600480.
    for identity, fact in {**staged, **overlays}.items():
        pub = fact.get('terms_known_date', fact.get('planned_known_date'))
        rows.append(dict(code=fact['code'], event_id='rights:' + identity, kind='unsupported', role='rights_issue',
            record=fact['record'], ex=fact['ex'], source_available_date=pub, status='active',
            reason='rights_economics_not_supported', raw_source='r5_bound_mapping', raw_record=deepcopy(fact),
            sources=[s for s in fact.get('sources', ()) if s.get('known_date') == pub]))
    normalized = [_normalize(r, calendar) for r in rows]
    # Only semantically identical records with identical source can collapse.
    unique, duplicates = {}, defaultdict(int)
    for r in normalized:
        key = json.dumps({k: r.get(k) for k in ('code', 'event_id', 'known_date', 'version',
              *ECONOMIC_FIELDS, 'kind', 'role', 'reason', 'raw_source', 'sources')}, sort_keys=True, default=str)
        duplicates[key] += 1
        unique.setdefault(key, r)
    for key, r in unique.items():
        r['equivalent_duplicate_count'] = duplicates[key]
    return EventBook(calendar, unique.values())


def bound_source_inputs(evidence, mapping_path=None):
    """Return only used binding sources and necessary ancestor manifests.

    Hash verification is the runner's freeze responsibility; this helper avoids
    importing or executing the former full-preservation source builder.
    """
    consumed = evidence.get('consumed_source_files', {})
    paths = {}
    for collection in ('ordinary_actions', 'event_versions', 'rights_stages', 'rights_overlay', 'status_events'):
        for r in evidence.get(collection, ()):
            if collection == 'status_events' and str(r.get('known_date', '9999')) > '2020-12-31':
                continue
            for s in r.get('sources', ()):
                paths[str(Path(s['path']))] = s['sha256']
    guard_codes = {k[0][:6] for name in ('unsupported_capitalization_keys', 'publication_chronology_conflict_keys')
                   for k in evidence.get('source_facts', {}).get(name, ())}
    for path, digest in consumed.items():
        if path.endswith('output_sha256.json') or Path(path).name[:6] in guard_codes and path.lower().endswith('.pdf'):
            paths[str(Path(path))] = digest
    if mapping_path is not None:
        p = Path(mapping_path)
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        paths[str(p)] = actual
        # Bind just the consumed mapping through its two necessary old parent
        # manifests.  Do not hash or demand preservation of unrelated outputs.
        prep, parent = p.parent / 'preparation_sha256.json', p.parent / 'output_sha256.json'
        if not prep.exists() or not parent.exists():
            raise ValueError('necessary old mapping parent manifest is absent')
        if prep.exists() and parent.exists():
            prep_data = json.loads(prep.read_text(encoding='utf-8'))
            parent_data = json.loads(parent.read_text(encoding='utf-8'))
            prep_sha = hashlib.sha256(prep.read_bytes()).hexdigest()
            if (prep_data.get(p.name) != actual or parent_data.get(p.name) != actual
                    or parent_data.get(prep.name) != prep_sha):
                raise ValueError('old frozen mapping does not bind its necessary parent manifests')
            paths[str(prep)] = prep_sha
            paths[str(parent)] = hashlib.sha256(parent.read_bytes()).hexdigest()
    return paths
