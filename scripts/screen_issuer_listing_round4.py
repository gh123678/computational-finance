"""Screen the 67 no-candidate update_flag conflict keys against the round-4
issuer-listing documents (issuer_listing_evidence_20261009/results).

Row filter is the final_status == 'no_candidate_document_unverified' subset of
update_flag_conflict_all204.csv. Extraction/comparison rules are imported
unchanged from screen_profit_dedt_candidates. Evidence only:
usable_in_verified_history is never set. Outputs go to auto_screen_20261009_issuer_listing/.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import screen_profit_dedt_candidates as scr

AUDIT_OUT = audit.OUT
OUT = AUDIT_OUT / 'auto_screen_20261009_issuer_listing'
KEYS_CSV = AUDIT_OUT / 'case_review_20261009' / 'update_flag_conflict_all204.csv'
R4 = AUDIT_OUT / 'issuer_listing_evidence_20261009'


def load_inputs():
    keys = pd.read_csv(KEYS_CSV, dtype=str, encoding='utf-8-sig')
    keys = keys[keys['final_status'] == 'no_candidate_document_unverified']
    assert len(keys) == 67, f'expected 67 keys, got {len(keys)}'
    key_set = set(zip(keys['ts_code'], keys['ann_date'], keys['end_date']))
    records = pd.read_csv(AUDIT_OUT / 'fina_indicator_records.csv', dtype=str, encoding='utf-8')
    mask = [(t, a, e) in key_set for t, a, e in
            zip(records['ts_code'], records['ann_date'], records['end_date'])]
    rows = records[mask]
    by_pair = {}
    for (code, day), grp in rows.groupby(['ts_code', 'ann_date']):
        by_pair[(code, day)] = [dict(row_sha256=r['row_sha256'], end_date=r['end_date'],
                                     update_flag=r['update_flag'], profit_dedt=r['profit_dedt'])
                                for _, r in grp.iterrows()]
    return key_set, by_pair


def screen_document(result, round_dir, round_name, row, key_set, out_rows, docs_seen):
    if (result['ts_code'], result['ann_date'], row['end_date']) not in key_set:
        return
    raw = row.get('profit_dedt')
    api_value = float(raw) if raw and raw == raw else None
    for doc in result.get('documents', []):
        text_rel = doc.get('text_file')
        if not text_rel:
            continue
        text_path = round_dir / text_rel
        if not text_path.is_file():
            continue
        docs_seen.add(f"{round_name}:{doc['file']}")
        doc_period, period_source = scr.document_period(doc.get('title'))
        period_note = None
        if '已取消' in (doc.get('title') or ''):
            period_note = 'document_title_marked_cancelled'
        elif any(k in (doc.get('title') or '') for k in ('更正', '修订', '更新')):
            period_note = 'document_title_marked_revised'
        base = dict(ts_code=result['ts_code'], api='fina_indicator',
            ann_date=result['ann_date'], end_date=row['end_date'],
            row_sha256=row['row_sha256'], update_flag=row['update_flag'],
            field='profit_dedt', unit='CNY', api_value=api_value,
            pdf_file=Path(doc['file']).name, pdf_sha256=doc.get('sha256'),
            text_sha256=doc.get('text_sha256'), source_url=doc.get('url'),
            document_title=doc.get('title'), round=round_name,
            document_period=doc_period, period_source=period_source,
            version_note=period_note,
            index_day=doc.get('index_day'),
            ann_date_deviation_days=doc.get('ann_date_deviation_days'),
            usable_in_verified_history=False)
        if doc_period and row['end_date'] and doc_period != row['end_date']:
            out_rows.append(dict(base, original_value=None, original_document_unit=None,
                candidate_count=0, strong_context=None, match_position=None,
                status='document_period_mismatch_excluded', context=None))
            continue
        text = text_path.read_text(encoding='utf-8', errors='replace')
        cands = scr.extract_candidates(text)
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
                    best, match_pos, _ = found
                    status = ('value_matches_dated_original'
                              if match_pos == 1 and best['strong_context']
                              else 'value_matches_needs_manual_confirm')
                else:
                    status = 'value_differs_from_dated_original'
                    best = min(valued, key=lambda c: min(
                        abs(v - api_value) for v in c['values_cny'] if v is not None))
            else:
                status = 'api_value_missing'
        out_rows.append(dict(base,
            original_value=(best['values_cny'][0] if best and best['values_cny'] else None),
            original_document_unit=best['unit'] if best else None,
            candidate_count=len(cands),
            strong_context=best['strong_context'] if best else None,
            match_position=match_pos, status=status,
            context=(best['context'][:220] if best else None)))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    key_set, by_pair = load_inputs()
    out_rows, docs_seen = [], set()
    pairs_done = set()
    for round_dir, round_name in [(R4, R4.name)]:
        for result_file in sorted((round_dir / 'results').glob('*.json')):
            result = json.loads(result_file.read_text(encoding='utf-8'))
            pair = (result['ts_code'], result['ann_date'])
            if pair not in by_pair or pair in pairs_done:
                continue
            pairs_done.add(pair)
            for row in by_pair[pair]:
                screen_document(result, round_dir, round_name, row, key_set, out_rows, docs_seen)
    frame = pd.DataFrame(out_rows)
    frame.to_csv(OUT / 'profit_dedt_screen.csv', index=False, encoding='utf-8-sig')
    summary = dict(
        conflict_keys_targeted=67,
        pairs_with_documents=len(pairs_done),
        document_checks=int(len(frame)),
        keys_with_any_row=len(set(zip(frame['ts_code'], frame['ann_date'], frame['end_date']))) if len(frame) else 0,
        status_counts=frame.status.value_counts().to_dict() if len(frame) else {},
        distinct_documents=int(frame.pdf_sha256.nunique()) if len(frame) else 0,
        usable_in_verified_history_rows=0,
        limitation='Machine screen only; matches require manual spot-check before any usability decision.',
    )
    (OUT / 'screen_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    protocol = dict(script=Path(__file__).name, script_sha256=audit.sha(Path(__file__)),
        keys_csv_sha256=audit.sha(KEYS_CSV),
        rules='Extraction/comparison rules imported unchanged from screen_profit_dedt_candidates.py',
        inputs=['issuer_listing_evidence_20261009/results',
                'fina_indicator_records.csv', str(KEYS_CSV.name)],
        note='Round-4 screen of issuer-listing documents for 67 no-candidate keys; evidence only.')
    (OUT / 'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
