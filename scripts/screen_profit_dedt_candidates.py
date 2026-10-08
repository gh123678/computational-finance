"""Semi-automated profit_dedt screening against downloaded candidate texts.

For each queued fina_indicator row with downloaded candidate documents, locate
"扣除非经常性损益" net-profit lines in the extracted text, parse the first
(current-period) number with its unit, and compare against the API value.

Discipline: this screen produces field-level evidence only. It never sets
usable_in_verified_history; original-release/version-chain approval remains a
separate manual step. Outputs go to a new directory and never overwrite frozen
artifacts.
"""
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / 'output' / 'announcement_financial_audit_20261007'
OUT = AUDIT / 'auto_screen_20261008'
ROUNDS = [AUDIT / 'remaining_evidence_r1', AUDIT / 'remaining_evidence_r2_fixed_r1']

LABEL = re.compile(
    r'归属于(?:上市公司|母公司)股东的?扣除非经常性损益(?:后|的)(?:的)?净?利润'
    r'|扣除非经常性损益后(?:的)?归属于(?:上市公司|母公司)股东的?净利润'
    r'|(?<!每股)扣除非经常性损益(?:后|的)(?:的)?净利润(?!率)(?!及)')
UNIT = re.compile(r'(?:金额|货币)?单位[：:]?\s*(?:人民币)?(百万元|千元|万元|元)')
NUM = re.compile(r'[\(（]?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?[\)）]?|-?\d+\.\d+')
UNIT_INLINE = re.compile(r'[（(](?:人民币)?(百万元|千元|万元|元)[)）]')
UNIT_MULT = {'元': 1, '千元': 1e3, '万元': 1e4, '百万元': 1e6}
WINDOW = 160
PERIOD_PATTERNS = [
    (re.compile(r'(\d{4})年(?:年度|年末)报告'), lambda y: f'{y}1231'),
    (re.compile(r'(\d{4})年第一季度报告'), lambda y: f'{y}0331'),
    (re.compile(r'(\d{4})年(?:半年度|中期)报告'), lambda y: f'{y}0630'),
    (re.compile(r'(\d{4})年第三季度报告'), lambda y: f'{y}0930'),
]


def document_period(title):
    """Infer reporting period from the announcement title; None if unknown."""
    if not title:
        return None, 'no_title'
    if '招股' in title:
        return None, 'prospectus_multi_period'
    for pattern, make in PERIOD_PATTERNS:
        m = pattern.search(title)
        if m:
            return make(m.group(1)), 'title'
    return None, 'title_period_unidentified'


def parse_number(token):
    neg = token.startswith(('(', '（')) or token.endswith((')', '）'))
    val = float(token.strip('()（）').replace(',', ''))
    return -val if neg else val


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract_candidates(text):
    """Return list of dicts: value_cny, unit, context, for the label occurrences."""
    flat = re.sub(r'\s+', '', text)
    results = []
    seen = set()
    for m in LABEL.finditer(flat):
        if m.start() in seen:
            continue
        seen.add(m.start())
        tail = flat[m.end():m.end() + WINDOW]
        if '每股' in flat[max(0, m.start() - 12):m.start()]:
            continue
        nums = NUM.findall(tail)
        if not nums:
            continue
        before = flat[max(0, m.start() - 1000):m.start()]
        inline = UNIT_INLINE.search(flat[m.end():m.end() + 30])
        if inline and not NUM.match(flat[m.end():]):
            # e.g. 净利润（元）13,385,220 — unit sits between label and numbers
            unit = inline.group(1)
        else:
            unit_hits = UNIT.findall(before) + UNIT.findall(flat[m.end():m.end() + 300])
            unit = unit_hits[0] if unit_hits else None
        mult = UNIT_MULT.get(unit)
        values = [parse_number(tok) for tok in nums[:4]]
        results.append(dict(
            values=values,
            strong_context='归属于上市公司股东的净利润' in flat[max(0, m.start() - 120):m.start()],
            unit=unit,
            values_cny=[v * mult if mult else None for v in values],
            context=flat[max(0, m.start() - 60):m.end() + 100]))
    # Prefer the main accounting-data table occurrence (preceded by the plain
    # net-profit row); otherwise keep document order.
    results.sort(key=lambda c: not c['strong_context'])
    return results


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = pd.read_csv(AUDIT / 'fina_indicator_records.csv', dtype=str)
    api_by_hash = {r['row_sha256']: r for _, r in records.iterrows()}

    queue = pd.read_csv(ROUNDS[0] / 'remaining_review_rows.csv', dtype=str)
    queued = set(queue.loc[queue.api.eq('fina_indicator'), 'row_sha256'])

    out_rows = []
    docs_seen = set()
    for round_dir in ROUNDS:
        results_dir = round_dir / 'results'
        if not results_dir.is_dir():
            continue
        for result_file in sorted(results_dir.glob('*.json')):
            result = json.loads(result_file.read_text(encoding='utf-8'))
            for key in result.get('row_keys', []):
                if key.get('api') != 'fina_indicator' or key['row_sha256'] not in queued:
                    continue
                api_row = api_by_hash.get(key['row_sha256'])
                if api_row is None:
                    continue
                api_value = api_row.get('profit_dedt')
                api_value = float(api_value) if api_value and api_value == api_value else None
                for doc in result.get('documents', []):
                    text_rel = doc.get('text_file')
                    if not text_rel:
                        continue
                    text_path = round_dir / text_rel
                    if not text_path.is_file():
                        continue
                    docs_seen.add(f"{round_dir.name}:{doc['file']}")
                    doc_period, period_source = document_period(doc.get('title'))
                    period_note = None
                    if '已取消' in (doc.get('title') or ''):
                        period_note = 'document_title_marked_cancelled'
                    elif any(k in (doc.get('title') or '') for k in ('更正', '修订', '更新')):
                        period_note = 'document_title_marked_revised'
                    if doc_period and key.get('end_date') and doc_period != key['end_date']:
                        out_rows.append(dict(
                            ts_code=result['ts_code'], api='fina_indicator',
                            ann_date=result['ann_date'], end_date=key.get('end_date'),
                            row_sha256=key['row_sha256'], field='profit_dedt',
                            unit='CNY', api_value=api_value, original_value=None,
                            original_document_unit=None, candidate_count=0,
                            status='document_period_mismatch_excluded',
                            pdf_file=Path(doc['file']).name,
                            pdf_sha256=doc.get('sha256'),
                            text_sha256=doc.get('text_sha256'),
                            source_url=doc.get('url'),
                            document_title=doc.get('title'), round=round_dir.name,
                            context=None, document_period=doc_period,
                            period_source=period_source, version_note=period_note,
                            usable_in_verified_history=False))
                        continue
                    text = text_path.read_text(encoding='utf-8', errors='replace')
                    cands = extract_candidates(text)
                    status, best, match_pos = 'not_found_in_candidate_text', None, None
                    if cands:
                        best = cands[0]
                        valued = [c for c in cands if any(v is not None for v in c['values_cny'])]
                        if not valued:
                            status = 'unit_unconfirmed_in_candidate_text'
                        elif api_value is not None:
                            found = None
                            for c in valued:
                                for pos, v in enumerate(c['values_cny'], 1):
                                    if v is not None and abs(v - api_value) < 0.5:
                                        found = (c, pos, v)
                                        break
                                if found:
                                    break
                            if found:
                                best, match_pos, matched_value = found
                                status = ('value_matches_dated_original'
                                          if match_pos == 1 and best['strong_context']
                                          else 'value_matches_needs_manual_confirm')
                            else:
                                status = 'value_differs_from_dated_original'
                                best = min(valued, key=lambda c: min(
                                    abs(v - api_value) for v in c['values_cny']
                                    if v is not None))
                        else:
                            status = 'api_value_missing'
                    out_rows.append(dict(
                        ts_code=result['ts_code'], api='fina_indicator',
                        ann_date=result['ann_date'], end_date=key.get('end_date'),
                        row_sha256=key['row_sha256'],
                        field='profit_dedt', unit='CNY', api_value=api_value,
                        original_value=(best['values_cny'][0]
                                        if best and best['values_cny'] else None),
                        original_document_unit=best['unit'] if best else None,
                        candidate_count=len(cands),
                        strong_context=best['strong_context'] if best else None,
                        match_position=match_pos,
                        status=status,
                        pdf_file=Path(doc['file']).name, pdf_sha256=doc.get('sha256'),
                        text_sha256=doc.get('text_sha256'),
                        source_url=doc.get('url'), document_title=doc.get('title'),
                        round=round_dir.name,
                        context=(best['context'][:220] if best else None),
                        document_period=doc_period, period_source=period_source,
                        version_note=period_note,
                        usable_in_verified_history=False))

    frame = pd.DataFrame(out_rows)
    frame.to_csv(OUT / 'profit_dedt_screen.csv', index=False)
    summary = dict(
        rows_screened=int(frame.row_sha256.nunique()) if len(frame) else 0,
        document_checks=int(len(frame)),
        status_counts=frame.status.value_counts().to_dict() if len(frame) else {},
        distinct_documents=int(frame.pdf_sha256.nunique()) if len(frame) else 0,
    )
    (OUT / 'screen_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    protocol = dict(
        script=Path(__file__).name,
        script_sha256=sha256(Path(__file__).resolve()),
        inputs=['remaining_review_rows.csv', 'fina_indicator_records.csv',
                'remaining_evidence_r1/results', 'remaining_evidence_r1/documents',
                'remaining_evidence_r2_fixed_r1/results',
                'remaining_evidence_r2_fixed_r1/documents'],
        rules='First numeric token after the deduced-profit label is taken as the '
              'current-period value; unit from nearest declaration; parenthesised '
              'numbers are negative; exact match within 0.5 CNY. Evidence only: '
              'usable_in_verified_history is never set by this screen.',
        limitation='PDF text extraction can scramble table columns; all matches '
                   'require manual spot-check before any usability decision.')
    (OUT / 'protocol.json').write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
