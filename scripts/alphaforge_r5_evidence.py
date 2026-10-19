"""Frozen source mappings for the separately approved r5 experiment.

These facts are conditional research evidence, not custody or tax certification.
Original Actions, RightsIssues, quotes, eligibility keys and targets are immutable.
"""
from copy import deepcopy
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd

import alphaforge_r4_evidence as r4


EVIDENCE_ROOT = Path('D:/QuantResearchEvidence/alphaforge_potential_exposure_action_sources_20261019_r1')
EVIDENCE_MANIFEST_SHA256 = '99e7e34100c8e913d14dbf26f0bd0374a3883b5ac35998feb7c13813511d4847'
EXTERNAL_ROOT = Path('D:/QuantResearchEvidence/alphaforge_000426_distribution_201808_crosscheck_20261019_r1')
EXTERNAL_MANIFEST_SHA256 = 'cff4677d32dec9ba5a415a0c16541182b7857a3768ae4cdb4f57d3b22a9fa218'
ORIGIN_ROOT = Path('D:/QuantResearchEvidence/alphaforge_capitalization_origin_followup_20261019_r1')
ORIGIN_MANIFEST_SHA256 = '99b046a727fe701b99795de44c629f8419af5f20c350b581cbbc4b9c6d6a155d'
RIGHTS_600999_ROOT = Path('D:/QuantResearchEvidence/alphaforge_600999_rights_stage_source_20261019_r1')
RIGHTS_600999_MANIFEST_SHA256 = 'fb3f3efb6110561e17deac080cfd56bbe5f89113fc51fbf43921c57d3093a820'
ACTION_FIELDS = r4.ACTION_FIELDS
DATE_FIELDS = r4.DATE_FIELDS
known_state = r4.known_state
overlay_rights = r4.overlay_rights

APPROVED_CASH_KEYS = frozenset([
    ('002661.SZ', '2018-03-30'), ('603033.SH', '2018-05-21'),
    ('002729.SZ', '2018-05-24'), ('002637.SZ', '2018-05-30'),
    ('002431.SZ', '2018-06-11'), ('603939.SH', '2018-06-14'),
    ('002778.SZ', '2018-06-15'), ('002408.SZ', '2018-06-20'),
    ('002738.SZ', '2018-06-22'), ('600122.SH', '2018-06-25'),
    ('000967.SZ', '2018-06-29'), ('002573.SZ', '2018-07-11'),
    ('603315.SH', '2018-07-16'), ('002437.SZ', '2018-07-18'),
    ('601390.SH', '2018-07-18'), ('000426.SZ', '2018-08-16'),
    ('600282.SH', '2019-04-26'), ('603315.SH', '2019-06-27'),
    ('600483.SH', '2019-07-29'), ('600267.SH', '2020-07-15'),
])
OLD_APPROVED_KEYS = frozenset([
    ('000756.SZ', '2018-01-26'), ('600309.SH', '2018-01-26'),
    ('600226.SH', '2018-03-26'),
])
UNSUPPORTED_CAPITALIZATION_KEYS = frozenset([
    ('000711.SZ', '2018-05-28'), ('002301.SZ', '2018-05-28'),
    ('002647.SZ', '2018-06-01'), ('002485.SZ', '2018-06-12'),
    ('002856.SZ', '2018-06-20'), ('002668.SZ', '2018-07-06'),
    ('002602.SZ', '2018-10-31'),
])


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class _Batch:
    def __init__(self, root, digest, count, consumed):
        self.root = Path(root).resolve()
        path = self.root / 'output_sha256.json'
        if _sha(path) != digest:
            raise ValueError('Frozen evidence manifest fingerprint changed: ' + str(path))
        self.manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        if len(self.manifest) != count:
            raise ValueError('Frozen evidence manifest member count changed')
        self.consumed = consumed
        consumed[path.as_posix()] = digest

    def bound(self, relative):
        relative = str(relative).replace('\\', '/')
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or relative not in self.manifest:
            raise ValueError('Source is outside the frozen evidence manifest: ' + relative)
        digest = self.manifest[relative]
        if _sha(path) != digest:
            raise ValueError('Frozen source fingerprint changed: ' + relative)
        self.consumed[path.as_posix()] = digest
        return path

    def load(self, relative):
        return json.loads(self.bound(relative).read_text(encoding='utf-8-sig'))

    def source(self, relative, sha, url, known_date, **extra):
        path = self.bound(relative)
        if self.manifest[relative] != sha:
            raise ValueError('Source metadata fingerprint conflicts with frozen manifest: ' + relative)
        # Official path dates and source index dates must agree; a printed date
        # is separately retained and never silently promoted to publication.
        if '/finalpage/' in url and url.split('/finalpage/')[1].split('/')[0] != known_date:
            raise ValueError('Official source publication date conflict: ' + relative)
        return dict(path=path.as_posix(), relative_path=relative, sha256=sha, url=url,
                    known_date=known_date, publication_time_precision='date_only',
                    publication_time_intraday_certified=False, **extra)


def _ordinary(code, event_id, terms, sources):
    result = dict(code=code, event_id=event_id, **{f: terms[f] for f in ACTION_FIELDS if f != 'code'},
        known_date=terms['known_date'], sources=sources, ordinary=True, special_distribution=False,
        valuation_scenario='original_ledger_theoretical_stale_price_not_exchange_reference',
        stock_pay_semantics='listing_release_not_certified_custody_receipt',
        limitation='Exact cash action only; not complete gap, custody, actual tax or exchange-reference certification.')
    if (Decimal(result['cash_per_share']) <= 0 or Decimal(result['stock_per_share']) != 0
            or Decimal(result['taxable_bonus_per_share']) != 0 or result['stock_pay'] is not None):
        raise ValueError('Approved added ordinary action must be unsplit pure cash: ' + code)
    return result


def build_evidence(root=EVIDENCE_ROOT, external_root=EXTERNAL_ROOT, origin_root=ORIGIN_ROOT,
                   rights_600999_root=RIGHTS_600999_ROOT):
    """Build the exact 23-action allowlist and detached staged event facts."""
    old = r4.build_evidence()
    consumed = {(Path(old['evidence_root']) / name).resolve().as_posix(): sha
                for name, sha in old['source_facts']['source_files'].items()}
    consumed[(Path(old['evidence_root']) / 'output_sha256.json').resolve().as_posix()] = r4.EVIDENCE_MANIFEST_SHA256
    batch = _Batch(root, EVIDENCE_MANIFEST_SHA256, 646, consumed)
    external = _Batch(external_root, EXTERNAL_MANIFEST_SHA256, 78, consumed)
    origin = _Batch(origin_root, ORIGIN_MANIFEST_SHA256, 115, consumed)
    rights999 = _Batch(rights_600999_root, RIGHTS_600999_MANIFEST_SHA256, 35, consumed)
    for directory, count in [('distributions_early', 125), ('distributions_late', 203), ('rights', 297)]:
        sub = batch.load(directory + '/output_sha256.json')
        if len(sub) != count or any(batch.manifest.get(directory + '/' + name) != sha for name, sha in sub.items()):
            raise ValueError('Frozen child manifest conflicts with parent: ' + directory)
    batch.bound('audit_protocol.json')
    with batch.bound('case_audit_summary.csv').open(encoding='utf-8-sig', newline='') as stream:
        queue = list(csv.DictReader(stream))
    if len(queue) != 39 or len({r['event_id'] for r in queue}) != 39:
        raise ValueError('Frozen 39-case source identities changed')
    queue = {(r['code'], r['ex']): r for r in queue}
    early = batch.load('distributions_early/source_facts.json')['cases']
    late = batch.load('distributions_late/source_facts.json')['cases']
    rights = batch.load('rights/source_facts.json')['cases']
    origin_summary = origin.load('merged_case_facts.json')
    ordinary = deepcopy(old['ordinary_actions'])
    for case in early:
        terms = case['implementation_terms']
        key = (case['code'], terms['ex'])
        if key not in APPROVED_CASH_KEYS:
            continue
        if (not case['old_cache_comparison']['all_numeric_and_operational_dates_match']
                or case['special_reorganization_or_grant_exception_stated_in_this_notice']
                or not terms['all_registered_ordinary_shareholders_eligible']):
            raise ValueError('Cash source has unsupported recipient or term conflict')
        source = case['source']
        doc = batch.source('distributions_early/' + source['file'], source['sha256'],
            source['official_url'], source['current_cninfo_public_day'], printed_date=source['printed_day'])
        row = dict(record=terms['record'], ex=terms['ex'], cash_pay=terms['cash_pay'],
            stock_pay=terms['unrestricted_new_stock_listing_day'],
            cash_per_share=terms['cash_per_share_pretax'],
            stock_per_share=str(Decimal(terms['capitalization_shares_per_share']) + Decimal(terms['stock_bonus_profit_shares_per_share'])),
            taxable_bonus_per_share=case['tax']['taxable_bonus_per_share_certified'], known_date=doc['known_date'])
        if case['event_id'] != queue[key]['event_id']:
            raise ValueError('Cash source event identity conflict')
        ordinary.append(_ordinary(case['code'], case['event_id'], row, [doc]))

    def late_sources(case):
        return [batch.source('distributions_late/' + item['file'], item['sha256'], item['url'],
            item['current_public_date'], role=item['role']) for item in case['sources']]

    versions = []
    for case in late:
        key = (case['code'], case['ex'])
        if case['event_id'] != queue[key]['event_id']:
            raise ValueError('Distribution source event identity conflict')
        terms = case['reviewed_terms']
        if key in APPROVED_CASH_KEYS:
            if not case['old_terms_match']:
                raise ValueError('Cash source terms conflict with frozen original')
            row = {f: terms[f] for f in ACTION_FIELDS if f != 'code'}
            row['known_date'] = terms['current_public_date']
            ordinary.append(_ordinary(case['code'], case['event_id'], row, late_sources(case)))
        if case['code'] not in ('600781.SH', '601258.SH'):
            continue
        original = {f: (case['original_terms'][f] or None) if f in DATE_FIELDS else case['original_terms'][f]
                    for f in ACTION_FIELDS}
        base = dict(original, event_id=case['event_id'], original_action=original,
                    publication_time_intraday_certified=False)
        docs = late_sources(case)
        if case['code'] == '600781.SH':
            if (original['record'], original['ex'], original['cash_pay'], original['cash_per_share']) != ('2019-07-19', '2019-07-22', '2019-07-22', '0.1'):
                raise ValueError('Cancelled planned action identity changed')
            for version, role, known, printed, apply, source_role in [
                (1, 'planned_distribution', '2019-07-16', '2019-07-16', True, 'primary_implementation_original'),
                (2, 'cancelled', '2019-07-20', '2019-07-19', False, 'cancellation_supersedes_initial_schedule')]:
                doc = [d for d in docs if d['role'] == source_role]
                if len(doc) != 1 or doc[0]['known_date'] != known:
                    raise ValueError('Cancelled source version chronology changed')
                versions.append(dict(base, version=version, role=role, known_date=known, printed_date=printed,
                    ordinary=apply, apply_distribution=apply, reference_explained=apply,
                    unsupported_special=False, sources=doc, actual_custody_receipt_certified=False))
        else:
            if (original['record'], original['ex'], original['stock_pay'], original['stock_per_share']) != ('2019-12-27', '2019-12-30', '2019-12-31', '0.5641598'):
                raise ValueError('Special action identity changed')
            versions.append(dict(base, version=1, role='special_reorganization', known_date='2019-12-24',
                printed_date='2019-12-23', ordinary=False, apply_distribution=False,
                reference_explained=False, unsupported_special=True, sources=docs,
                cash_per_share='0', stock_per_share='0', taxable_bonus_per_share='0',
                company_total_expansion_per_old_total_share=terms['company_total_expansion_per_old_total_share'],
                actual_recipient=terms['actual_recipient']))
    facts426 = external.load('source_facts.json')
    original426 = facts426['official_implementation']
    record426 = next(x for x in external.load('official_sources.json') if x['announcement_id'] == '1205273340')
    doc426 = external.source(record426['local_pdf'], record426['sha256'], record426['official_url'],
        record426['api_path_public_day'], printed_date=original426['printed_day'])
    key426 = ('000426.SZ', original426['ex_day'])
    row426 = dict(record=original426['record_day'], ex=original426['ex_day'], cash_pay=original426['cash_pay_day'],
        stock_pay=None, cash_per_share=facts426['cash_terms']['effective_pretax_cash_per_share'],
        stock_per_share=str(Decimal(original426['bonus_shares_per_share']) + Decimal(original426['capitalization_shares_per_share'])),
        taxable_bonus_per_share='0', known_date=original426['public_day'])
    ordinary.append(_ordinary('000426.SZ', queue[key426]['event_id'], row426, [doc426]))
    keys = [(row['code'], row['ex']) for row in ordinary]
    if len(keys) != 23 or set(keys) != APPROVED_CASH_KEYS | OLD_APPROVED_KEYS:
        raise ValueError('Exactly 23 distinct approved ordinary source keys are required')
    stages = []
    for case in rights:
        key = (case['code'], case['ex'])
        if case['event_id'] != queue[key]['event_id'] or not case['queue_dates_match']:
            raise ValueError('Rights source event identity or date conflict')
        docs = [batch.source('rights/' + source['pdf'], source['sha256'], source['url'],
                    source['current_index_publication_day'], role=source['role'],
                    printed_date=source['printed_body_date']) for source in case['source_pdfs']]
        issuance = [d for d in docs if d['role'] == 'issuance']
        stages.append(dict(code=case['code'], record=case['record'], ex=case['ex'],
            event_id=case['event_id'], terms_known_date=issuance[0]['known_date'] if len(issuance) == 1 else None,
            result_known_date=case['actual_result_known_date'], listing_known_date=case['listing_known_date'],
            price=case['subscription_price_cny'], quota_ratio=case['nominal_individual_eligibility_ratio'],
            market_ex_ratio=case.get('published_reference_ratio_per_old_share'), list_date=case['listing_date'],
            original_subscription_authorized=case['code'] == '000977.SZ', sources=docs,
            original_subscription_terms=(dict(price='12.92',ratio='0.1177945',list_date='2020-03-27')
                                         if case['code']=='000977.SZ' else None),
            personal_actual_allocation_certified=False, actual_result_intraday_certified=False))
    issue977 = next(s for s in stages if s['code'] == '000977.SZ')
    if tuple(str(issue977[f]) for f in ('record','ex','price','quota_ratio','market_ex_ratio','terms_known_date','result_known_date','listing_known_date','list_date')) != (
            '2020-03-10','2020-03-19','12.92','.12','.1177945','2020-03-06','2020-03-19','2020-03-26','2020-03-27'):
        raise ValueError('Approved individual quota versus market-reference mapping changed')
    facts999 = rights999.load('source_facts.json')
    if tuple(facts999[f] for f in ('code','record','ex','list_date','price','personal_quota_ratio')) != (
            '600999.SH','2020-07-09','2020-07-20','2020-07-31','7.46','0.3'):
        raise ValueError('Unchanged 600999 original subscription terms conflict')
    if not facts999['original_terms_unchanged'] or facts999['market_reference_ratio'] is not None:
        raise ValueError('600999 personal quota cannot become an aggregate market ratio')
    docs999 = [rights999.source(s['file'],s['sha256'],s['url'],s['known_date'],
            printed_date=s['printed_date'],role='actual_result' if role=='result' else role)
               for role,s in facts999['stages'].items()]
    stages.append(dict(code='600999.SH',record=facts999['record'],ex=facts999['ex'],
        event_id='rights:600999.SH:2020-07-09:unchanged_original_terms',
        terms_known_date=facts999['stages']['issuance']['known_date'],
        result_known_date=facts999['stages']['result']['known_date'],
        listing_known_date=facts999['stages']['listing']['known_date'],
        price=facts999['price'],quota_ratio=facts999['personal_quota_ratio'],market_ex_ratio=None,
        list_date=facts999['list_date'],original_subscription_authorized=True,sources=docs999,
        original_subscription_terms=dict(price='7.46',ratio='0.3',list_date='2020-07-31'),
        personal_actual_allocation_certified=False,actual_result_intraday_certified=False,
        issuance_actual_success_not_established_by_plan=True,
        research_exdate_payment_differs_actual_payment_window=True))
    result = deepcopy(old)
    result.update(schema_version=5, evidence_root=batch.root.as_posix(), evidence_manifest_sha256=EVIDENCE_MANIFEST_SHA256,
        ordinary_actions=sorted(ordinary, key=lambda r: (r['ex'],r['code'])),
        event_versions=versions, rights_stages=stages, consumed_source_files=dict(sorted(consumed.items())))
    result['source_facts'].update(r5_parent_manifest_count=646, ordinary_cash_added_count=20,
        unsupported_capitalization_keys=[list(k) for k in sorted(UNSUPPORTED_CAPITALIZATION_KEYS)],
        capitalization_origin_followup=origin_summary, capitalization_origin_remains_unknown=True,
        publication_chronology_conflict_keys=[['002470.SZ','2018-06-19']],
        distribution_000426=facts426,rights_600999=facts999, old_r4_evidence_root=old['evidence_root'])
    result['limitations'] = [s for s in result['limitations'] if not s.startswith('Only three exact')]
    result['limitations'] += [
        'Exactly three prior ordinary actions and twenty approved pure-cash actions receive conditional cross-gap treatment.',
        'Seven capitalization tax origins and 002470 publication chronology remain unresolved; original r4 boundary applies.',
        'Cancelled plans preserve earlier research registration without certifying custody or payment.',
        'Special reorganization is unsupported on actual/planned stage contact regardless of quoted prices.',
        '000977 quota 0.12 is a floor research approximation; 0.1177945 is market-reference only.',
        '600999 original terms remain; July 7 issuance, July 20 result and July 28 listing source dates stay separate.',
    ]
    return result


def source_inputs(evidence):
    """Every consumed absolute file, including manifests, for runner freezing."""
    result = dict(evidence['consumed_source_files'])
    for path, expected in result.items():
        if not Path(path).is_absolute() or _sha(path) != expected:
            raise ValueError('Consumed source fingerprint changed: ' + path)
    return result


def validate_actions(actions, evidence, full_calendar):
    """Match all eight original fields for precisely the approved 23 keys."""
    actions = tuple(actions)
    approved = evidence['ordinary_actions']
    keys = [(r['code'],r['ex']) for r in approved]
    if len(keys) != 23 or set(keys) != APPROVED_CASH_KEYS | OLD_APPROVED_KEYS:
        raise ValueError('Exactly 23 distinct approved ordinary actions are required')
    calendar = pd.DatetimeIndex(full_calendar).normalize()
    if calendar.hasnans or calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Full exchange calendar must be sorted and unique')
    positions = {d.strftime('%Y-%m-%d'):i for i,d in enumerate(calendar)}
    rows = []
    for expected in approved:
        matches = [a for a in actions if a.code == expected['code'] and r4._date(a.ex) == expected['ex']]
        if len(matches) != 1:
            raise ValueError('Approved action is missing or duplicated: ' + expected['code'])
        for field in ACTION_FIELDS:
            actual, wanted = getattr(matches[0],field), expected[field]
            okay = (r4._date(actual) == wanted if field in DATE_FIELDS else str(actual) == wanted if field == 'code'
                    else Decimal(str(actual)) == Decimal(str(wanted)))
            if not okay:
                raise ValueError('Approved action conflicts with original field ' + expected['code'] + ':' + field)
        if expected['record'] not in positions or expected['ex'] not in positions or positions[expected['ex']] != positions[expected['record']] + 1:
            raise ValueError('Approved ordinary action requires adjacent open record/ex sessions: ' + expected['code'])
        if expected['known_date'] >= expected['record']:
            raise ValueError('Date-only terms not known before registration')
        if not expected.get('ordinary') or expected.get('special_distribution') or not expected.get('sources'):
            raise ValueError('Special or unsourced action is not approved')
        for field, amount in [('cash_pay','cash_per_share'),('stock_pay','stock_per_share')]:
            if Decimal(str(expected[amount])) and expected[field] not in positions:
                raise ValueError('Approved settlement/listing outside exchange calendar')
        rows.append(dict(code=expected['code'],ex=expected['ex'],passed=True,matched_fields=list(ACTION_FIELDS),record_ex_adjacent=True))
    return rows
