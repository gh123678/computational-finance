"""Consolidate existing field review claims without opening historical-use gates."""
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
import json
import re
import announcement_financial_audit as audit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/strategy_completion_20261012_r1'
BASE=ROOT/'output/off_checklist_revision_worklist_20261010/verification_round/results'
SOURCE_NAMES=[
 'output/financial_review_repair_20261011_r1/three_cases_visual_adjudication.json',
 'output/publication_scan_evidence_20261011_r1/manual_first_case.json',
 'output/publication_scan_evidence_20261011_r1/manual_middle_case.json',
 'output/publication_scan_evidence_20261011_r1/manual_last_case.json',
 'output/publication_manual_footers_20261012_r1/manual_financial_samples.json',
 'output/publication_footer_formats_20261012_r1/manual_financial_samples.json',
 'output/financial_review_repair_20261011_r1/corrected_report_field_review.json',
 'output/cross_period_review_20261011_r1/seven_key_adjudications.json']


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def claim(code,period,value,pdf,digest,page,role,source):
    """Hash verification protects the recorded review, not historical publication."""
    path=ROOT/pdf
    if audit.sha(path)!=digest:raise ValueError('Review source PDF hash changed: '+str(pdf))
    if not Decimal(value).is_finite():raise ValueError('Nonfinite review value')
    if not re.fullmatch(r'\d{8}',period):raise ValueError('Invalid target review period')
    return dict(ts_code=code,target_review_period=period,observed_review_value_cny=value,
        pdf=str(Path(pdf)),pdf_sha256=digest,pdf_page=page,source_review=source,
        role=role,evidence_status='existing_field_review_claim_pdf_hash_verified',
        selected_financial_value=None,verified_publication_day=None,usable_in_verified_history=False)


def summarize_claims(claims):
    versions=defaultdict(set)
    for c in claims:versions[(c['pdf_sha256'],c['target_review_period'])].add(Decimal(c['observed_review_value_cny']))
    conflict=any(len(values)>1 for values in versions.values())
    return dict(review_claim_count=len(claims),reviewed_pdf_versions=len(versions),
        intra_pdf_review_value_conflict=conflict,
        content_status='conflicting_review_claims' if conflict else 'review_claims_present' if claims else 'numeric_match_or_pending_only',
        selected_financial_value=None,verified_publication_day=None,usable_in_verified_history=False)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    inputs={str(p.relative_to(ROOT)):audit.sha(p) for p in sorted(BASE.glob('*.json'))}
    for name in SOURCE_NAMES:inputs[name]=audit.sha(ROOT/name)
    claims=[]
    for name in SOURCE_NAMES:
        data=read(ROOT/name)
        if name.endswith('corrected_report_field_review.json'):
            for r in data['target_year_field_reviews']:
                claims.append(claim(r['ts_code'],r['end_date'],r['observed_value_cny'],r['path'],r['pdf_sha256'],r['pdf_page'],'identified_updated_report',name))
            continue
        rows=data if isinstance(data,list) else [data]
        for r in rows:
            if 'original_profit_dedt_cny' in r:
                c=claim(r['ts_code'],r['end_date'],r['original_profit_dedt_cny'],r['source_pdf'],r['source_sha256'],r['pdf_page'],'original_annual_report',name)
            elif 'observed_annual_profit_dedt_cny' in r:
                e=r['annual_evidence']
                c=claim(r['ts_code'],r['end_date'],r['observed_annual_profit_dedt_cny'],e['path'],e['sha256'],e['pdf_page'],'original_annual_report',name)
            else:
                value=r.get('annual_direct_headline_dedt',r.get('annual_direct_dedt'))
                unit=r.get('annual_dedt_unit',r.get('annual_unit'))
                if value is None or unit not in ['元','人民币元']:continue
                stem=r.get('stem','').split('_')
                code=r.get('ts_code',stem[0] if stem else None)
                period=r.get('target_review_period',stem[1] if len(stem)>1 else None)
                c=claim(code,period,value,r['annual_pdf'],r['annual_pdf_sha256'],
                    r.get('annual_page',r.get('annual_visual_page')),'original_annual_report',name)
            claims.append(c)
    by_key=defaultdict(list)
    for c in claims:by_key[(c['ts_code'],c['target_review_period'])].append(c)
    keys=[]
    for p in sorted(BASE.glob('*.json')):
        r=read(p);key=(r['ts_code'],r['end_date']);own=by_key.get(key,[])
        row=dict(ts_code=key[0],target_review_period=key[1],vendor_ann_date=r['ann_date'],
            prior_machine_status=r.get('final_status',r.get('verdict')),
            numeric_match_is_not_field_review=True,claims=own,**summarize_claims(own),
            historical_release_identity='unverified',complete_historical_version_chain='unverified')
        keys.append(row)
    assert len(keys)==166
    assert set(by_key).issubset({(r['ts_code'],r['target_review_period']) for r in keys})
    for c in claims:inputs[c['pdf']]=c['pdf_sha256']
    assert all(audit.sha(ROOT/p)==h for p,h in inputs.items())
    audit.write_json(OUT/'field_review_claims.json',claims)
    audit.write_json(OUT/'financial_key_ledger.json',keys)
    audit.write_json(OUT/'input_sha256.json',inputs)
    result=dict(keys=166,claims=len(claims),keys_with_review_claims=len(by_key),
        claim_role_counts=dict(Counter(c['role'] for c in claims)),
        content_status_counts=dict(Counter(r['content_status'] for r in keys)),
        historical_approvals=0,selected_values=0,new_models=0,new_backtests=0,
        claims_are_prior_review_records_not_new_manual_certification=True)
    audit.write_json(OUT/'financial_ledger_summary.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
