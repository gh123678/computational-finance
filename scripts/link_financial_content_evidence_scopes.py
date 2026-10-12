"""Link existing review scopes without promoting vendor dates to publication evidence."""
from pathlib import Path
from decimal import Decimal
from collections import defaultdict, Counter
import json
import pandas as pd
import announcement_financial_audit as audit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/financial_content_scope_link_20261012_r1'
CONTENT=ROOT/'output/financial_field_visual_review_20261012_r1'
AUDIT=audit.OUT
LATEST=ROOT/'output/latest_financial_report_coverage_20261012_r1'


def identity(row):
    # PDF identities and units cannot be merged just because the numbers agree.
    return (row['ts_code'],row['key_ann_date'],row['end_date'],row['pdf_sha256'],
        row['observed_document_unit'],str(Decimal(row['reported_value_cny']).normalize()),row['evidence_kind'])


def deduplicate(rows):
    result={}
    for row in rows:
        key=identity(row)
        if key not in result:
            result[key]=dict(row,source_references=[])
        result[key]['source_references'].append(row['source_reference'])
    return list(result.values())


def main():
    if OUT.exists():raise RuntimeError('Snapshot already exists; inspect, do not overwrite')
    OUT.mkdir()
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    paths=[CONTENT/'field_ledger_current_content_checkpoint07.json',CONTENT/'artifact_sha256.json',
        AUDIT/'evidence/field_checks.csv',AUDIT/'case_review_20261009/manual_adjudication_20261010.csv',
        AUDIT/'evidence/sinosoft_mirror_case.json',LATEST/'required_latest_report_keys.csv',
        LATEST/'signal_latest_report_evidence.csv.gz',LATEST/'artifact_sha256.json',Path(__file__)]
    inputs={str(p.relative_to(ROOT)):audit.sha(p) for p in paths}
    for base in [CONTENT,LATEST]:
        for p,h in read(base/'artifact_sha256.json').items():
            if audit.sha(base/p)!=h:raise ValueError('Frozen stage changed: '+p)
    old=audit.verify_old();rows=[]
    def add(code,ann,period,value,pdf,digest,unit,kind,ref,role):
        if digest:
            if audit.sha(ROOT/pdf)!=digest:raise ValueError('Reviewed PDF changed: '+pdf)
            inputs[pdf]=digest
        rows.append(dict(ts_code=code,key_ann_date=ann,end_date=period,
            reported_value_cny=value,pdf=pdf,pdf_sha256=digest,
            observed_document_unit=unit,evidence_kind=kind,document_role=role,
            source_reference=ref,key_ann_date_binding='vendor_or_review_key_only_not_independently_verified_publication',
            selected_financial_value=None,verified_publication_day=None,usable_in_verified_history=False))
    for r in read(paths[0]):
        for i,c in enumerate(r['claims']):
            add(r['ts_code'],r['vendor_ann_date'],r['target_review_period'],c['observed_review_value_cny'],c['pdf'],c['pdf_sha256'],
                'unverified_in_this_prior_claim_schema','prior_166_pdf_review_claim',c['source_review']+f' claim{i}',c['role'])
        c=r['current_visual_adjudication']
        if c:
            # A rounded display is retained as a display observation, never an exact value.
            value=c['scaled_display_value_cny']
            add(r['ts_code'],r['vendor_ann_date'],r['target_review_period'],value,c['pdf'],c['pdf_sha256'],c['observed_unit'],
                'exact_current_pdf_field_review' if c['original_exact_cny_value_confirmed'] else 'rounded_display_observation',
                str(paths[0].relative_to(ROOT))+f" queue_index{c['queue_index']}",c['original_document_role'])
    checks=pd.read_csv(paths[2],dtype=str,keep_default_na=False)
    for i,r in checks.loc[checks.api.eq('fina_indicator') & checks.field.eq('profit_dedt')].iterrows():
        pdf=str((AUDIT/'evidence'/r.pdf_file).relative_to(ROOT))
        add(r.ts_code,r.ann_date,r.end_date,r.original_value,pdf,r.pdf_sha256,r.original_document_unit,
            'early_field_check_record',str(paths[2].relative_to(ROOT))+f' row{i+2}','dated_original_claim_not_historical_approval')
    manual=pd.read_csv(paths[3],dtype=str,keep_default_na=False)
    assert len(manual)==32
    for i,r in manual.iterrows():
        add(r.ts_code,r.ann_date,r.end_date,r.original_value,None,None,'not_carried_in_adjudication_csv',
            'manual_32_adjudication_reference_unanchored_pdf',str(paths[3].relative_to(ROOT))+f' row{i+2}','manual_adjudication_'+r.adjudication)
    m=read(paths[4]);pdf=str((AUDIT/m['pdf_file']).relative_to(ROOT))
    add(m['ts_code'],m['ann_date'],m['end_date'],m['original_value'],pdf,m['pdf_sha256'],m['unit'],
        'mirror_identity_and_publication_unresolved',str(paths[4].relative_to(ROOT)),'company_old_security_code_mirror')
    claims=deduplicate(rows);by=defaultdict(list)
    for c in claims:by[(c['ts_code'],c['key_ann_date'],c['end_date'])].append(c)
    needed=pd.read_csv(paths[5],dtype=str,keep_default_na=False);signals=pd.read_csv(paths[6],dtype=str,keep_default_na=False)
    # Link metadata references; no inference that a report was available historically.
    for frame in [needed,signals]:
        groups=[by.get(tuple(k),[]) for k in frame[['ts_code','ann_date','end_date']].itertuples(index=False,name=None)]
        frame['any_existing_review_reference']=[bool(g) for g in groups]
        frame['has_hash_verified_pdf_review_claim']=[any(c['pdf_sha256'] for c in g) for g in groups]
        frame['has_manual_32_unanchored_reference']=[any(c['evidence_kind'].startswith('manual_32') for c in g) for g in groups]
        frame['historical_approval_from_this_link']=False
    needed.to_csv(OUT/'required_report_evidence_scope.csv',index=False)
    needed.loc[needed.same_day_profit_conflict.eq('True')].to_csv(OUT/'required_conflict_evidence_scope.csv',index=False)
    signals.to_csv(OUT/'signal_evidence_scope.csv.gz',index=False,compression='gzip')
    yearly=[]
    for year,g in signals.groupby('year'):
        yearly.append(dict(year=int(year),signal_rows=len(g),any_reference_rows=int(g.any_existing_review_reference.sum()),
            pdf_hash_claim_rows=int(g.has_hash_verified_pdf_review_claim.sum()),historical_approvals=0))
    audit.write_json(OUT/'claims.json',claims);audit.write_json(OUT/'yearly_summary.json',yearly)
    summary=dict(input_claim_rows=len(rows),deduplicated_claims=len(claims),distinct_vendor_dated_review_keys=len(by),
        required_dated_keys=len(needed),required_keys_with_any_reference=int(needed.any_existing_review_reference.sum()),
        required_keys_with_pdf_hash_claim=int(needed.has_hash_verified_pdf_review_claim.sum()),
        required_conflict_keys=int(needed.same_day_profit_conflict.eq('True').sum()),
        conflict_keys_without_any_reference=int((needed.same_day_profit_conflict.eq('True') & ~needed.any_existing_review_reference).sum()),
        signal_rows=len(signals),signal_rows_with_any_reference=int(signals.any_existing_review_reference.sum()),
        signal_rows_with_pdf_hash_claim=int(signals.has_hash_verified_pdf_review_claim.sum()),
        evidence_kind_counts=dict(Counter(c['evidence_kind'] for c in claims)),historical_approvals=0,new_models=0,new_backtests=0,
        limitations=['Key annotation is not original publication identity','Unanchored manual CSV references do not verify PDFs',
            'Scaled bank units and prospectus rounded values are not cent precision','Sources beyond listed scopes are not claimed absent'])
    for p,h in inputs.items():
        if audit.sha(ROOT/p)!=h:raise ValueError('Input changed: '+p)
    audit.write_json(OUT/'summary.json',summary);audit.write_json(OUT/'input_sha256.json',inputs)
    audit.write_json(OUT/'verification.json',dict(inputs_unchanged=True,old_experiments=old,all_history_gates_closed=True))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
