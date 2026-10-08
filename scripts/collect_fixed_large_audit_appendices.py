"""Bounded two-document access revision; preserve original 20MB failures."""
import json,os,shutil,subprocess,sys,time
from pathlib import Path
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parent))
import announcement_financial_audit as a
import collect_remaining_financial_evidence as original

OUT=a.OUT/'fixed_large_appendices_r1'
TARGETS=[('603998.SH','20141114','1200392012'),('605288.SH','20200518','1207821156')]
MAX_BYTES=64*1024**2

def main():
    for name in ['source_snapshot','documents','results']:(OUT/name).mkdir(parents=True,exist_ok=True)
    protocol=dict(targets=TARGETS,max_pdf_bytes=MAX_BYTES,total_storage_budget=256*1024**2,
        free_space_floor=6*1024**3,max_attempts=2,request_max_seconds=90,
        source_sha256=a.sha(Path(__file__)),design_sha256=a.sha(a.SPEC),
        queue_sha256=a.sha(original.QUEUE),reason='Two fixed appendices exceed previous 20MB ceiling; existing failures retained')
    protocol=json.loads(json.dumps(protocol));path=OUT/'protocol.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==protocol,'Frozen revision changed'
    else:
        a.write_json(path,protocol);shutil.copy2(__file__,OUT/'source_snapshot'/Path(__file__).name)
    lock=OUT/'collection.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    results=[]
    try:
        a.initialize();a.verify_old()
        for code,day,identifier in TARGETS:
            result_path=OUT/'results'/f'{code}_{day}.json'
            if result_path.exists():results.append(json.loads(result_path.read_text(encoding='utf-8')));continue
            source=a.OUT/'remaining_evidence_r2_fixed_r1/results'/result_path.name
            cached=json.loads(source.read_text(encoding='utf-8'))
            candidates=[i for i in original.matched_items(cached['query']['items'],code,day) if i['announcementId']==identifier]
            assert len(candidates)==1
            item=candidates[0];url=original.safe_url(item,day)
            assert item['adjunctSize']*1024<=MAX_BYTES,'Known size exceeds revision ceiling'
            result=dict(ts_code=code,ann_date=day,announcement_id=identifier,source_url=url,title=item['announcementTitle'],
                index_file=str(source.relative_to(a.OUT)),index_sha256=a.sha(source),listed_size_kb=item['adjunctSize'],
                attempts=[],usable_in_verified_history=False)
            for attempt in [1,2]:
                if shutil.disk_usage(OUT).free<protocol['free_space_floor'] or sum(p.stat().st_size for p in (OUT/'documents').glob('*'))>=protocol['total_storage_budget']:
                    result['status']='storage_limit';break
                partial=OUT/'documents'/f'{identifier}_attempt{attempt}.partial'
                if partial.exists():raise RuntimeError('Existing unrecorded attempt; preserve for inspection')
                try:
                    response=subprocess.run(['curl.exe','-4','--fail','--silent','--show-error','--connect-timeout','10',
                        '--max-time','90','--max-filesize',str(MAX_BYTES),url,'--output',str(partial)],capture_output=True,timeout=105)
                    attempt_info=dict(at=a.now(),attempt=attempt,exit_code=response.returncode,error=response.stderr.decode('utf-8',errors='replace').strip(),bytes=partial.stat().st_size if partial.exists() else 0)
                    result['attempts'].append(attempt_info)
                    if response.returncode:
                        result['status']='transport_failed';time.sleep(1.3);continue
                    assert partial.stat().st_size<=MAX_BYTES
                    with fitz.open(partial) as doc:
                        assert doc.is_pdf and len(doc)>0
                        pages=len(doc);text='\n'.join(f'\n[PDF PAGE {i+1}]\n'+p.get_text() for i,p in enumerate(doc))
                    pdf=partial.with_name(f'{code}_{day}_{identifier}.pdf');partial.replace(pdf)
                    extracted=pdf.with_suffix('.txt');extracted.write_text(text,encoding='utf-8')
                    result.update(status='downloaded_readable_appendix_only',pdf_file=str(pdf.relative_to(OUT)),
                        pdf_sha256=a.sha(pdf),pages=pages,bytes=pdf.stat().st_size,text_file=str(extracted.relative_to(OUT)),text_sha256=a.sha(extracted),retrieved_at=a.now())
                    break
                except subprocess.TimeoutExpired:
                    result['attempts'].append(dict(at=a.now(),attempt=attempt,error='bounded subprocess timeout'))
                    result['status']='transport_failed';time.sleep(1.3)
            a.write_json(result_path,result);results.append(result)
            a.write_json(OUT/'status.json',dict(at=a.now(),pid=os.getpid(),state='running',completed=len(results),total=2,historical_approvals=0))
            print(json.dumps({k:result.get(k) for k in ['ts_code','status','pages','bytes']}),flush=True)
        a.verify_old()
        assert a.sha(original.QUEUE)==protocol['queue_sha256']
        a.write_json(OUT/'status.json',dict(at=a.now(),pid=os.getpid(),state='completed_access_only',completed=len(results),total=2,
            readable=sum(r['status']=='downloaded_readable_appendix_only' for r in results),historical_approvals=0))
    except Exception as exc:
        a.write_json(OUT/'status.json',dict(at=a.now(),pid=os.getpid(),state='failed',error=str(exc),historical_approvals=0));raise
    finally:lock.unlink()

if __name__=='__main__':main()
