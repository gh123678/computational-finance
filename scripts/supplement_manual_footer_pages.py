"""Read-only bounded OCR pages located by separately saved visual footer evidence."""
from pathlib import Path
from collections import Counter
import os
import shutil
import fitz
import announcement_financial_audit as audit
import recover_large_publication_pdfs as recovery
import ocr_recovered_financial_candidates as scan
import refine_scan_page_locations as refine

ROOT=scan.ROOT
OUT=ROOT/'output/publication_manual_footers_20261012_r1'
OLD=ROOT/'output/publication_scan_evidence_20261011_r1'
PREV=ROOT/'output/publication_scan_locations_20261012_r2'


def verify_old():
    for directory in [OLD,PREV]:
        for name,digest in recovery.read(directory/'artifact_sha256.json').items():
            assert audit.sha(directory/name)==digest
    recovery.verify(recovery.read(OLD/'input_sha256.json'))


def main():
    verify_old()
    for name in ['pages','images','results','source_snapshot']:(OUT/name).mkdir(exist_ok=True)
    reviews=recovery.read(OUT/'manual_footer_reviews.json')
    protocol=dict(source_sha256=audit.sha(Path(__file__)),manual_review_sha256=audit.sha(OUT/'manual_footer_reviews.json'),
        old_manifest_sha256=audit.sha(OLD/'artifact_sha256.json'),previous_manifest_sha256=audit.sha(PREV/'artifact_sha256.json'),
        max_new_pages_per_document=3,engine_sha256=recovery.read(OLD/'protocol.json')['engine_sha256'],historical_approvals=0)
    if (OUT/'protocol.json').exists():assert recovery.read(OUT/'protocol.json')==protocol
    else:
        audit.write_json(OUT/'protocol.json',protocol);shutil.copy2(__file__,OUT/'source_snapshot'/Path(__file__).name)
    lock=OUT/'supplement.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    scan.OUT=OUT;records=[]
    try:
        engine=scan.engine()
        for item in recovery.read(OUT/'footer_candidates.json'):
            review=next(r for r in reviews if r['stem']==item['stem'])
            source=recovery.read(OLD/'results'/(item['stem']+'.json'))
            target=OUT/'results'/(item['stem']+'.json')
            if target.exists():result=recovery.read(target)
            else:
                try:
                    assert audit.sha(ROOT/item['pdf'])==review['pdf_sha256']
                    assert audit.sha(OUT/review['sheet'])==review['sheet_sha256']
                    known=set()
                    for directory in [OLD,PREV]:
                        for p in (directory/'pages').glob(item['stem']+'_p*.json'):known.add(recovery.read(p)['page'])
                    with fitz.open(ROOT/item['pdf']) as pdf:
                        pages=refine.planned_pages(item['printed_targets'],review['notes_offset'],len(pdf),known)[:3]
                        evidence=[scan.read_page(engine,pdf,source,n) for n in pages]
                        result=scan.evidence_record(source,status='manual_located_pages_only' if pages else 'no_safe_new_pages',
                            manual_review_status=review['review_status'],extra_pages=pages,
                            supplemental_candidate_rows=sum(len(p['candidates']) for p in evidence),
                            full_financial_field_verified=False,whole_document_numbering_verified=False)
                except Exception as exc:
                    result=scan.evidence_record(source,status='supplement_failed',error_type=type(exc).__name__,error=str(exc))
                audit.write_json(target,result)
            records.append(result)
            status=dict(state='running',pid=os.getpid(),processed=len(records),total=38,
                status_counts=dict(Counter(r['status'] for r in records)),
                extra_pages=sum(len(r.get('extra_pages',[])) for r in records),historical_approvals=0)
            audit.write_json(OUT/'status.json',status)
            print(item['stem'],result['status'],result.get('extra_pages',[]),flush=True)
        verify_old()
        assert audit.sha(Path(__file__))==protocol['source_sha256']
        assert audit.sha(OUT/'manual_footer_reviews.json')==protocol['manual_review_sha256']
        assert all(audit.sha(ROOT/p)==h for p,h in protocol['engine_sha256'].items())
        audit.write_json(OUT/'verification.json',dict(old_ocr_artifacts=1450,previous_supplement_artifacts=93,old_inputs=1502,
            old_experiments=audit.verify_old(),source_unchanged=True,engine_unchanged=True,historical_approvals=0))
        status['state']='completed';audit.write_json(OUT/'status.json',status)
    finally:lock.unlink(missing_ok=True)


if __name__=='__main__':main()
