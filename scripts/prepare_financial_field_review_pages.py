"""Render fixed-order candidate pages for human field review; no automatic approval."""
import argparse
from pathlib import Path
import json
import shutil
import fitz
import announcement_financial_audit as audit

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/off_checklist_revision_worklist_20261010/verification_round'
QUEUE=ROOT/'output/strategy_completion_20261012_r1/remaining_field_review_queue.json'
OUT=ROOT/'output/financial_field_visual_review_20261012_r1'


def main(start,count):
    queue=json.loads(QUEUE.read_text(encoding='utf-8'))
    assert len(queue)==140 and 0<=start<140 and 1<=count<=20
    for name in ['images','cases','source_snapshot']:(OUT/name).mkdir(exist_ok=True)
    protocol=dict(queue_sha256=audit.sha(QUEUE),source_sha256=audit.sha(Path(__file__)),render_zoom=2,
        max_initial_pages_per_key=2,max_batch_keys=20,historical_approvals=0)
    target=OUT/'protocol.json'
    if target.exists():assert json.loads(target.read_text(encoding='utf-8'))==protocol
    else:
        audit.write_json(target,protocol);shutil.copy2(__file__,OUT/'source_snapshot'/Path(__file__).name)
    for index,r in enumerate(queue[start:start+count],start):
        stem=r['ts_code']+'_'+r['target_review_period'];result_path=OUT/'cases'/(stem+'.json')
        if result_path.exists():continue
        source_path=BASE/'results'/(stem+'.json');source=json.loads(source_path.read_text(encoding='utf-8'))
        candidates=r['candidate_original_annual_documents']
        fallback=False
        if not candidates:
            candidates=[d for d in source['documents'] if '招股' in d['title']]
            fallback=bool(candidates)
        candidates=[d for d in candidates if d.get('hits',{}).get('flag0')]
        record=dict(queue_index=index,ts_code=r['ts_code'],target_review_period=r['target_review_period'],
            vendor_ann_date=source['ann_date'],flag0=source['val_flag0'],flag1=source['val_flag1'],
            source_key_record_sha256=audit.sha(source_path),
            selected_financial_value=None,verified_publication_day=None,usable_in_verified_history=False,
            status='no_candidate_with_original_value_hit',visual_review_pending=True)
        if candidates:
            d=candidates[0];path=BASE/d['file'];digest=audit.sha(path)
            hit=int(d['hits']['flag0'][0][0]);pages=list(dict.fromkeys([max(1,hit-1),hit]))
            if shutil.disk_usage(OUT).free<6*1024**3:raise RuntimeError('Disk free-space floor')
            images=[]
            with fitz.open(path) as pdf:
                for n in pages:
                    assert 1<=n<=len(pdf)
                    png=OUT/'images'/(stem+f'_p{n}.png')
                    pdf[n-1].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(png)
                    images.append(dict(page=n,path=str(png.relative_to(OUT)),sha256=audit.sha(png)))
            record.update(status='candidate_pages_rendered_only',pdf=str(path.relative_to(ROOT)),pdf_sha256=digest,
                title=d['title'],current_index_day=d['index_day'],document_role='preipo_prospectus_candidate' if fallback else 'annual_report_candidate',
                hit_page=hit,images=images,hit_is_not_field_confirmation=True)
            assert audit.sha(path)==digest
        audit.write_json(result_path,record)
        print(index,stem,record['status'],record.get('hit_page'),flush=True)
    assert audit.sha(QUEUE)==protocol['queue_sha256'] and audit.sha(Path(__file__))==protocol['source_sha256']


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--start',type=int,default=0);p.add_argument('--count',type=int,default=20)
    args=p.parse_args();main(args.start,args.count)
