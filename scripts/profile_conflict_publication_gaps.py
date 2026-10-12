"""Quantify diagnostic signal exposure to later PDF dates, not historical availability."""
from pathlib import Path
import json
import re
import pandas as pd
import announcement_financial_audit as audit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/conflict_publication_identity_20261012_r1'
RUN=OUT/'date_diagnostics_r2'


def earlier_signals(signals, candidate):
    # Signal dates are ISO, index candidates are compact dates; compare dates, not strings.
    signal_days=pd.to_datetime(signals.trade_date,format='%Y-%m-%d',errors='raise')
    candidate_day=pd.to_datetime(candidate,format='%Y%m%d',errors='raise')
    return signals.loc[signal_days.lt(candidate_day)]


def main():
    if RUN.exists():raise RuntimeError('Diagnostic snapshot exists')
    RUN.mkdir()
    events=json.loads((OUT/'events.json').read_text(encoding='utf-8'))
    source=ROOT/'output/latest_financial_report_coverage_20261012_r1/signal_latest_report_evidence.csv.gz'
    source_hash=audit.sha(source)
    frame=pd.read_csv(source,dtype=str,keep_default_na=False)
    rows=[];details=[]
    for e in events:
        own=frame.loc[frame.ts_code.eq(e['ts_code']) & frame.ann_date.eq(e['key_ann_date']) & frame.end_date.eq(e['end_date'])]
        candidate=e['candidate_available_day']
        before=earlier_signals(own,candidate) if candidate else own.iloc[:0]
        rows.append(dict(ts_code=e['ts_code'],ann_date=e['key_ann_date'],end_date=e['end_date'],
            linked_signal_rows=len(own),candidate_available_day=candidate,
            signal_rows_before_reviewed_pdf_candidate_date=len(before),
            candidate_date_unknown=candidate is None,current_title_cancelled=e['current_title_cancelled'],
            historical_approval=False))
        if len(before):
            d=before.copy();d['reviewed_pdf_sha256']=e['pdf_sha256'];d['reviewed_pdf_candidate_available_day']=candidate
            details.append(d)
    pd.DataFrame(rows).to_csv(RUN/'signal_date_gaps_by_key.csv',index=False)
    if details:pd.concat(details,ignore_index=True).to_csv(RUN/'signals_before_pdf_candidate_date.csv',index=False)
    # Named archive has no ID in filename: recover identity from hash-bound metadata only.
    metadata=ROOT/'output/announcement_financial_audit_20261007/evidence/000488_download.json'
    raw=json.loads(metadata.read_text(encoding='utf-8'))
    missing=[e for e in events if e['ts_code']=='000488.SZ']
    assert len(missing)==1 and raw['sha256']==missing[0]['pdf_sha256']
    assert audit.sha(ROOT/missing[0]['source_claims'][0]['pdf'])==raw['sha256']
    match=re.search(r'/finalpage/(\d{4}-\d{2}-\d{2})/(\d{10})\.PDF$',raw['url'])
    assert match
    audit.write_json(RUN/'named_pdf_identity_followup.json',dict(ts_code='000488.SZ',key_ann_date='20160331',end_date='20151231',
        announcement_id_from_hash_bound_download_metadata=match.group(2),source_url_date_only=match.group(1).replace('-',''),
        source_url=raw['url'],download_metadata=str(metadata.relative_to(ROOT)),download_metadata_sha256=audit.sha(metadata),
        pdf_sha256=raw['sha256'],current_official_index_still_not_matched=True,
        verified_publication_day=None,selected_financial_value=None,usable_in_verified_history=False))
    diagnostic=dict(conflict_keys=61,linked_signal_rows=sum(r['linked_signal_rows'] for r in rows),
        linked_signal_rows_before_pdf_candidate_day=sum(r['signal_rows_before_reviewed_pdf_candidate_date'] for r in rows),
        keys_with_signal_rows_before_pdf_candidate_day=sum(r['signal_rows_before_reviewed_pdf_candidate_date']>0 for r in rows),
        signal_rows_with_unknown_pdf_candidate_day=sum(r['linked_signal_rows'] for r in rows if r['candidate_date_unknown']),
        signal_rows_with_current_cancelled_pdf=sum(r['linked_signal_rows'] for r in rows if r['current_title_cancelled']),
        historical_approvals=0,source_sha256=source_hash,
        limitation='Hypothetical diagnostic for reviewed PDFs only; not a finding that frozen strategy consumed these financial values; candidate dates are not verified historical dates')
    assert audit.sha(source)==source_hash
    audit.write_json(RUN/'signal_date_diagnostics.json',diagnostic)
    print(json.dumps(diagnostic,ensure_ascii=False))


if __name__=='__main__':main()
