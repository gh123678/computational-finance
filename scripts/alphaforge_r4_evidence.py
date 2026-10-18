"""Source-bound r4 overlays; no original rows or subscription terms are edited.

Publication dates are date-only observations from the frozen current official
index, not certified historical intraday feeds. A transition first published on
the queried day is explicitly unusable as pre-open missing-quote evidence.
"""
from copy import deepcopy
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_research.rights import RightsIssue


EVIDENCE_ROOT = Path('D:/QuantResearchEvidence/alphaforge_guard_evidence_20261017_r1')
EVIDENCE_MANIFEST_SHA256 = 'b95f68d53ac207de19ec54264b4a4337c0517c6f601ccfab5642168c0e7e2902'
ACTION_FIELDS = ('code', 'record', 'ex', 'cash_pay', 'stock_pay',
                 'cash_per_share', 'stock_per_share', 'taxable_bonus_per_share')
DATE_FIELDS = {'record', 'ex', 'cash_pay', 'stock_pay'}
NONTRADING_STATES = {'suspended_listing', 'suspended_trading', 'delisted'}


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _date(value):
    if value is None or pd.isna(value) or value == '':
        return None
    return pd.Timestamp(value).strftime('%Y-%m-%d')


def build_evidence(root=EVIDENCE_ROOT):
    """Return a JSON-serializable mapping, verifying every consumed old file.

    Only the three approved distributions are allowlisted across missing quotes.
    Later evidence remains a later event; no initial event receives a future end.
    """
    root = Path(root).resolve()
    manifest_path = root / 'output_sha256.json'
    if _sha(manifest_path) != EVIDENCE_MANIFEST_SHA256:
        raise ValueError('Frozen evidence manifest fingerprint changed')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    consumed = {}

    def bound(relative):
        relative = str(relative).replace('\\', '/')
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or relative not in manifest:
            raise ValueError('Source is outside the frozen evidence manifest: ' + relative)
        expected = manifest[relative]
        if _sha(path) != expected:
            raise ValueError('Frozen source fingerprint changed: ' + relative)
        consumed[relative] = expected
        return path

    def load(relative):
        return json.loads(bound(relative).read_text(encoding='utf-8-sig'))

    def source(directory, filename, expected_sha, url, known_date, **extra):
        relative = directory + '/' + filename
        path = bound(relative)
        if consumed[relative] != expected_sha:
            raise ValueError('PDF metadata fingerprint conflicts with frozen manifest: ' + relative)
        return dict(path=path.as_posix(), relative_path=relative, sha256=expected_sha,
                    url=url, known_date=known_date, publication_time_precision='date_only', **extra)

    queue_path = bound('P1_distributions_first3/event_evidence_queue.csv')
    with queue_path.open(encoding='utf-8-sig', newline='') as stream:
        distribution_rows = list(csv.DictReader(stream))
    if len(distribution_rows) != 3:
        raise ValueError('Approved ordinary-action source scope changed')
    # The sealed collector's old semantic question is resolved by this sealed
    # addendum: stock_pay is listing release, not certified custody arrival.
    bound('stock_date_semantics_addendum.md')
    expected_terms = {
        '000756.SZ': ('2018-01-25', '2018-01-26', '2018-01-26', None, '0.03', '0'),
        '600309.SH': ('2018-01-25', '2018-01-26', '2018-01-26', None, '1.5', '0'),
        '600226.SH': ('2018-03-23', '2018-03-26', None, '2018-03-27', '0', '0.3'),
    }
    ordinary = []
    for row in distribution_rows:
        code = row['ts_code']
        terms = (row['record'], row['ex'], row['cash_pay'] or None,
                 row['announced_unrestricted_new_share_listing_date'] or None,
                 row['gross_cash_per_share'] or '0',
                 row['capitalization_shares_per_existing_share'] or '0')
        if code not in expected_terms or terms != expected_terms[code]:
            raise ValueError('Approved ordinary action terms differ from the source: ' + code)
        record, ex, cash_pay, stock_pay, cash, stock = terms
        doc = source('P1_distributions_first3', row['implementation_pdf'],
                     row['implementation_sha256'], row['implementation_url'], row['cninfo_public_date'],
                     printed_date=row['body_signature_date'])
        ordinary.append(dict(code=code, event_id=row['event_id'], record=record, ex=ex,
            cash_pay=cash_pay, stock_pay=stock_pay, cash_per_share=cash,
            stock_per_share=stock, taxable_bonus_per_share='0', known_date=row['cninfo_public_date'],
            sources=[doc], ordinary=True, special_distribution=False,
            valuation_scenario='original_ledger_theoretical_stale_price_not_exchange_reference',
            stock_pay_semantics='listing_release_not_certified_custody_receipt',
            limitation=row['material_limit']))
    if {item['code'] for item in ordinary} != set(expected_terms):
        raise ValueError('Duplicate/missing approved ordinary action')

    status2017 = load('status_2017/status_evidence.json')
    downloads2017 = {item['id']: item for item in load('status_2017/download_records.json')}
    statuses = []

    def add_state(code, state, known, effective, doc, *, printed=None, received=None,
                  limitations=None, role='state_transition', date_conflict=None):
        statuses.append(dict(code=code, state=state, known_date=known, effective_date=effective,
            printed_date=printed, decision_received_date=received,
            source=doc, sources=[doc], role=role, end_date=None,
            publication_time_intraday_certified=False,
            daily_status_coverage_certified=False,
            limitations=limitations or '', date_conflict=date_conflict))

    for item in status2017['securities']:
        for kind, state, known_field, effective_field, printed_field in (
            ('suspension_source', 'suspended_listing', 'suspension_source_publication',
             'suspended_listing_effective', 'suspension_source_board_date'),
            ('restoration_source', 'listed', 'restoration_source_publication',
             'restoration_first_session', 'restoration_source_board_date')):
            record = downloads2017[item[kind]]
            known = item[known_field]
            doc = source('status_2017', record['path'], record['sha256'], record['url'], known)
            add_state(item['code'], state, known, item[effective_field], doc,
                      printed=item[printed_field], received=item.get('exchange_decision_received')
                      if kind == 'suspension_source' else item.get('restoration_decision_received'),
                      limitations=item['notes'])

    status2019 = load('status_2019_2020/status_evidence.json')
    documents = {item['label']: item for item in status2019['documents']}

    def later_doc(label):
        record = documents[label]
        known = record['url'].split('/finalpage/')[1].split('/')[0]
        return source('status_2019_2020', record['file'], record['sha256'], record['url'], known)

    for item in status2019['scope']:
        doc = later_doc(item['primary'])
        if doc['known_date'] != item['initial_publication_day']:
            raise ValueError('Official publication dates conflict: ' + item['code'])
        add_state(item['code'], 'suspended_listing', item['initial_publication_day'],
            item['pause_listing_effective'], doc, printed=item['printed_initial_day'],
            received=item['decision_received_day'], limitations=item['limitations'])

    # These originals describe earlier ordinary halts; knowledge begins on the
    # publication date, never on their retrospectively described starting date.
    for code, label, effective in (
        ('000760.SZ', '000760_prior_halt_20200619_complete_attempt2', '2020-06-04'),
        ('000792.SZ', '000792_prior_halt_20200519', '2020-04-30')):
        doc = later_doc(label)
        add_state(code, 'suspended_trading', doc['known_date'], effective, doc,
                  limitations='Earlier starting date is retrospective; no pre-publication backfill.')
    doc = later_doc('000792_resumption_20210810_complete_attempt2')
    add_state('000792.SZ', 'listed', doc['known_date'], '2021-08-10', doc,
              limitations='Same-day publication does not certify pre-open knowledge.')
    # The first available original for these 002680 endpoints is November 27.
    # Keep their different effective dates, but do not change October status.
    doc = later_doc('002680_delist_20191127_complete_attempt2')
    add_state('002680.SZ', 'delisting_board', doc['known_date'], '2019-10-16', doc,
              limitations='Delisting-board trading is not normal restoration; only known from this later original.')
    add_state('002680.SZ', 'delisted', doc['known_date'], '2019-11-27', doc,
              limitations='Termination decision 2019-10-08, delisting-board 2019-10-16, removal 2019-11-27 remain distinct.')
    for code, label, printed, conflict in (
        ('000760.SZ', '000760_yearend_20210106', '2020-01-05', status2019['date_conflicts'][0]),
        ('002359.SZ', '002359_progress_20210402', None, None),
        ('600614.SH', '600614_yearend_20210130_complete_attempt2', None, None)):
        doc = later_doc(label)
        add_state(code, 'suspended_listing', doc['known_date'], doc['known_date'], doc,
                  printed=printed, role='later_corroboration', date_conflict=conflict,
                  limitations='Later progress is not earlier availability or a retrospectively filled end date.')

    rights_facts = load('official_600480/reviewed_event_facts.json')
    rights_downloads = load('official_600480/download_manifest.json')
    rights_sources = []
    for record in rights_downloads:
        known = record['url'].split('/finalpage/')[1].split('/')[0]
        rights_sources.append(source('official_600480', record['filename'], record['sha256'], record['url'], known))
    if (rights_facts['code'], rights_facts['record_date'], rights_facts['ex_date']) != (
            '600480.SH', '2019-06-11', '2019-06-20'):
        raise ValueError('Approved date-only rights event changed')
    rights_overlay = [dict(code='600480.SH', record='2019-06-11', ex='2019-06-20',
        price=None, ratio=None, list_date=None, known_date='2019-06-20',
        planned_known_date='2019-06-06', actual_success_known_date='2019-06-20',
        sources=rights_sources, source=next(item['url'] for item in rights_sources
            if item['known_date'] == '2019-06-20'),
        scenario='original_no_subscription', usable_for_formation_eligibility=False)]
    return dict(schema_version=1, evidence_root=root.as_posix(),
        evidence_manifest_sha256=EVIDENCE_MANIFEST_SHA256,
        ordinary_actions=sorted(ordinary, key=lambda item: (item['ex'], item['code'])),
        status_events=sorted(statuses, key=lambda item: (item['known_date'], item['effective_date'], item['code'])),
        rights_overlay=rights_overlay,
        source_facts=dict(rights_600480=rights_facts, rights_600480_sources=rights_sources,
            status2017=status2017['securities'], status2019=status2019['scope'],
            date_conflicts=status2019['date_conflicts'],
            source_files=dict(sorted(consumed.items()))),
        limitations=[
            'Current official-index publication dates are not certified historical intraday snapshots.',
            'No original quote, S row, formation key, target, old source, or old output is edited.',
            'Only three exact ordinary actions are reviewed for cross-gap treatment; no blanket waiver.',
            'No personal rights entitlement is inferred from aggregate issuance or nominal ratio.',
            'Theoretical stale valuation and listing release do not certify custody settlement or exchange reference.',
            '000760 same-day initial publication is uncertain before opening; its later printed-year conflict remains unresolved.',
            '600677 period-end/termination original is unavailable; continuing known status is not full daily coverage certification.',
            '002680 October delisting-board trading is not backfilled from the November original.',
        ])


def validate_actions(actions, evidence, full_calendar):
    """Require all three original Actions to match approved terms exactly.

    Returns validation rows suitable for an audit file. Additional original
    actions remain registered, but this function never allowlists them.
    """
    actions = tuple(actions)
    approved_keys = {(item['code'], item['ex']) for item in evidence['ordinary_actions']}
    if len(evidence['ordinary_actions']) != 3 or len(approved_keys) != 3:
        raise ValueError('Exactly three distinct approved ordinary actions are required')
    calendar = pd.DatetimeIndex(full_calendar).normalize()
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Full exchange calendar must be sorted and unique')
    positions = {value.strftime('%Y-%m-%d'): index for index, value in enumerate(calendar)}
    result = []
    for approved in evidence['ordinary_actions']:
        matched = [action for action in actions if action.code == approved['code']
                   and _date(action.ex) == approved['ex']]
        if len(matched) != 1:
            raise ValueError('Approved action is missing or duplicated: ' + approved['code'])
        action = matched[0]
        for field in ACTION_FIELDS:
            original, expected = getattr(action, field), approved[field]
            equal = (_date(original) == expected if field in DATE_FIELDS else
                     str(original) == expected if field == 'code' else
                     Decimal(str(original)) == Decimal(str(expected)))
            if not equal:
                raise ValueError('Approved action conflicts with original field ' + approved['code'] + ':' + field)
        record, ex = approved['record'], approved['ex']
        if record not in positions or ex not in positions or positions[ex] != positions[record] + 1:
            raise ValueError('Approved ordinary action requires adjacent open record/ex sessions: ' + approved['code'])
        if approved['known_date'] >= record:
            raise ValueError('Date-only ordinary terms were not known before registration: ' + approved['code'])
        if (not approved.get('ordinary') or approved.get('special_distribution')
                or not approved.get('sources')):
            raise ValueError('Special or unsourced action is not approved for cross-gap treatment')
        for field, amount in (('cash_pay', 'cash_per_share'), ('stock_pay', 'stock_per_share')):
            if Decimal(str(approved[amount])) and approved[field] not in positions:
                raise ValueError('Approved settlement/listing is outside the full exchange calendar')
        result.append(dict(code=action.code, ex=approved['ex'], passed=True,
                           matched_fields=list(ACTION_FIELDS), record_ex_adjacent=True))
    if len(result) != 3:
        raise ValueError('Exactly three approved ordinary actions are required')
    return result


def known_state(code, date, evidence):
    """Latest already-published and effective state; never apply a future end.

    Callers must stop on ``usable_for_missing_quote=False`` uncertainty for an
    actual exposure. A date-only same-day publication is not pre-open proof.
    The returned object is detached, so consumers cannot mutate frozen mapping.
    """
    date = _date(date)
    candidates = [item for item in evidence['status_events'] if item['code'] == code
                  and item['known_date'] <= date and item['effective_date'] <= date]
    if not candidates:
        return None
    # A newly known retrospective transition must not override a later effective
    # transition described in the same document (e.g. 002680 on November 27).
    event = deepcopy(max(candidates, key=lambda item: (item['known_date'], item['effective_date'])))
    ambiguous = (event['known_date'] == date
                 and not event.get('publication_time_intraday_certified', False))
    event.update(as_of_date=date, certainty='publication_time_uncertain' if ambiguous else 'known_by_prior_date',
                 usable_for_missing_quote=not ambiguous and event['state'] in NONTRADING_STATES,
                 pre_open_known=not ambiguous, end_date=None)
    return event


def overlay_rights(rights, evidence):
    """Add a detached date-only RightsIssue, preserving all existing objects.

    No source fact, nominal ratio, aggregate ratio or later listing date is
    promoted into original subscription terms. A conflicting existing item stops.
    """
    result = list(rights)
    for item in evidence['rights_overlay']:
        if any(item.get(field) is not None for field in ('price', 'ratio', 'list_date')):
            raise ValueError('r4 date-only rights overlay cannot inject subscription terms')
        matches = [issue for issue in result if issue.code == item['code']
                   and (_date(issue.record) == item['record'] or _date(issue.ex) == item['ex'])]
        if matches:
            if len(matches) != 1 or (_date(matches[0].record), _date(matches[0].ex)) != (item['record'], item['ex']):
                raise ValueError('Rights overlay conflicts with original dates')
            if any(getattr(matches[0], field) is not None for field in ('price', 'ratio', 'list_date')):
                raise ValueError('Original subscription terms conflict with approved no-subscription overlay')
            continue
        result.append(RightsIssue(item['code'], pd.Timestamp(item['record']),
                                  pd.Timestamp(item['ex']), item['source']))
    return result
