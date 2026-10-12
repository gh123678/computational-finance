"""Bind fixed human observations to evidence scopes without historic value selection."""
from pathlib import Path
from collections import defaultdict
from decimal import Decimal
import json
import pandas as pd
import announcement_financial_audit as audit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/unanchored_conflict_pages_20261012_r1'
PREVIOUS=ROOT/'output/financial_content_scope_link_20261012_r1'
LATEST=ROOT/'output/latest_financial_report_coverage_20261012_r1'


def main():
    if (OUT/'summary.json').exists():raise RuntimeError('Followup already exists; do not overwrite')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    for base in [PREVIOUS,LATEST,ROOT/'output/financial_field_visual_review_20261012_r1']:
        for p,h in read(base/'artifact_sha256.json').items():
            assert audit.sha(base/p)==h,p
    claims=read(PREVIOUS/'claims_after_followup.json')
    observations=read(OUT/'visual_adjudications.json')
    queue=read(PREVIOUS/'unanchored_conflict_followup_queue.json')
    expected={(r['ts_code'],r['ann_date'],r['end_date']) for r in queue}
    assert len(observations)==11
    assert {(r['ts_code'],r['key_ann_date'],r['end_date']) for r in observations}==expected
    for r in observations:
        assert r['selected_financial_value'] is None and r['verified_publication_day'] is None
        assert not r['usable_in_verified_history'] and not r['historical_original_pdf_confirmed']
        assert audit.sha(ROOT/r['pdf'])==r['pdf_sha256']
        for image in r['images']:assert audit.sha(OUT/image['path'])==image['sha256']
        if r['value_derivation']:
            d=r['value_derivation']
            assert Decimal(d['parent_net_cny'])-Decimal(d['parent_nonrecurring_after_tax_cny'])==Decimal(r['reported_value_cny'])
    claims+=observations
    by=defaultdict(list)
    for r in claims:by[(r['ts_code'],r['key_ann_date'],r['end_date'])].append(r)
    frames=[]
    for file in ['required_latest_report_keys.csv','signal_latest_report_evidence.csv.gz']:
        frame=pd.read_csv(LATEST/file,dtype=str,keep_default_na=False)
        groups=[by.get(k,[]) for k in frame[['ts_code','ann_date','end_date']].itertuples(index=False,name=None)]
        frame['has_review_reference']=[bool(g) for g in groups]
        frame['has_pdf_hash_content_claim']=[any(c['pdf_sha256'] for c in g) for g in groups]
        frame['historical_approval']=False
        frames.append(frame)
    needed,signals=frames
    conflicts=needed.loc[needed.same_day_profit_conflict.eq('True')]
    assert len(conflicts)==61 and conflicts.has_pdf_hash_content_claim.all()
    needed.to_csv(OUT/'required_key_content_scope.csv',index=False)
    conflicts.to_csv(OUT/'conflict_key_content_scope.csv',index=False)
    signals.to_csv(OUT/'signal_content_scope.csv.gz',index=False,compression='gzip')
    audit.write_json(OUT/'claims_after_followup.json',claims)
    audit.write_json(OUT/'summary.json',dict(fixed_followup_keys=11,followup_pdf_identities=len({r['pdf_sha256'] for r in observations}),
        total_content_observations=len(claims),required_keys=len(needed),required_keys_with_pdf_claim=int(needed.has_pdf_hash_content_claim.sum()),
        signal_rows=len(signals),signal_rows_with_pdf_claim=int(signals.has_pdf_hash_content_claim.sum()),
        required_conflict_keys=61,conflict_keys_without_pdf_claim=0,historical_approvals=0,
        cancelled_or_later_comparative_observations=2,computed_audit_observations=1,quarterly_ytd_observations=1,
        historical_version_and_publication_gate_passed=False,new_models=0,new_backtests=0))
    audit.write_json(OUT/'verification.json',dict(prior_frozen_stages_unchanged=True,old_experiments=audit.verify_old(),
        source_sha256={str(p.relative_to(ROOT)):audit.sha(p) for p in [Path(__file__),ROOT/'scripts/prepare_unanchored_conflict_pages.py']},
        current_observation_sha256=audit.sha(OUT/'visual_adjudications.json'),all_historical_gates_closed=True))
    print((OUT/'summary.json').read_text(encoding='utf-8'))


if __name__=='__main__':main()
