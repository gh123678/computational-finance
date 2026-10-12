"""Link two explicitly adjudicated PDF observations; never approve historical use."""
from pathlib import Path
from collections import defaultdict
import json
import pandas as pd
import announcement_financial_audit as audit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/financial_content_scope_link_20261012_r1'
LATEST = ROOT / 'output/latest_financial_report_coverage_20261012_r1'


def main():
    target = OUT / 'summary_after_followup.json'
    if target.exists():
        raise RuntimeError('Followup snapshot already exists; do not overwrite')
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    claims = read(OUT / 'claims.json')
    manual = read(OUT / 'two_remaining_conflict_adjudications.json')
    assert len(manual) == 2
    for row in manual:
        assert row['usable_in_verified_history'] is False
        assert row['selected_financial_value'] is None
        assert row['verified_publication_day'] is None
        assert audit.sha(ROOT / row['pdf']) == row['pdf_sha256']
        assert audit.sha(OUT / row['viewed_image']) == row['viewed_image_sha256']
        claims.append(row)
    by = defaultdict(list)
    for row in claims:
        by[(row['ts_code'], row['key_ann_date'], row['end_date'])].append(row)
    frames = []
    for name in ['required_latest_report_keys.csv', 'signal_latest_report_evidence.csv.gz']:
        frame = pd.read_csv(LATEST / name, dtype=str, keep_default_na=False)
        groups = [by.get(k, []) for k in frame[['ts_code', 'ann_date', 'end_date']].itertuples(index=False, name=None)]
        frame['any_existing_review_reference'] = [bool(g) for g in groups]
        frame['has_hash_verified_pdf_review_claim'] = [any(c['pdf_sha256'] for c in g) for g in groups]
        frame['historical_approval_from_this_link'] = False
        frames.append(frame)
    needed, signals = frames
    conflicts = needed.loc[needed.same_day_profit_conflict.eq('True')]
    assert len(conflicts) == 61 and conflicts.any_existing_review_reference.all()
    summary = dict(deduplicated_claims=len(claims), distinct_vendor_dated_review_keys=len(by),
        required_dated_keys=len(needed), required_keys_with_any_reference=int(needed.any_existing_review_reference.sum()),
        required_keys_with_pdf_hash_claim=int(needed.has_hash_verified_pdf_review_claim.sum()),
        required_conflict_keys=len(conflicts), conflict_keys_without_any_reference=0,
        conflict_keys_without_pdf_hash_claim=int((~conflicts.has_hash_verified_pdf_review_claim).sum()),
        signal_rows=len(signals), signal_rows_with_any_reference=int(signals.any_existing_review_reference.sum()),
        signal_rows_with_pdf_hash_claim=int(signals.has_hash_verified_pdf_review_claim.sum()),
        historical_approvals=0, new_models=0, new_backtests=0,
        limitations=read(OUT / 'summary.json')['limitations'])
    needed.to_csv(OUT / 'required_report_evidence_scope_after_followup.csv', index=False)
    conflicts.to_csv(OUT / 'required_conflict_evidence_scope_after_followup.csv', index=False)
    signals.to_csv(OUT / 'signal_evidence_scope_after_followup.csv.gz', index=False, compression='gzip')
    audit.write_json(OUT / 'claims_after_followup.json', claims)
    audit.write_json(target, summary)
    for p, h in read(OUT / 'input_sha256.json').items():
        assert audit.sha(ROOT / p) == h, p
    for base in [ROOT / 'output/financial_field_visual_review_20261012_r1', LATEST]:
        for p, h in read(base / 'artifact_sha256.json').items():
            assert audit.sha(base / p) == h, p
    audit.write_json(OUT / 'verification_after_followup.json', dict(
        frozen_stages_unchanged=True, original_inputs_unchanged=True, old_experiments=audit.verify_old(),
        source_sha256={str(p.relative_to(ROOT)): audit.sha(p) for p in [Path(__file__), ROOT / 'scripts/link_financial_content_evidence_scopes.py', ROOT / 'tests/test_financial_content_scope_link.py']},
        all_history_gates_closed=True))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
