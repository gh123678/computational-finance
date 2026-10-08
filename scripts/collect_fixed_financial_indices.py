"""Collect bounded official index queries for the pre-approved 48 fixed samples.

Metadata collection does not approve original versions or historical usability.
No credentials, Tushare requests, portfolio changes, or profit threshold searches.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import pandas as pd

OUT = audit.OUT/'fixed_sample_indices'
ENDPOINT = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'


def collect(code, day):
    date = pd.Timestamp(day).strftime('%Y-%m-%d')
    pages, metadata = [], []
    for page in range(1, 6):
        cache = OUT/'responses'/f'{code}_{day}_{page}.json'
        params = dict(pageNum=str(page),pageSize='30',tabName='fulltext',
            column='szse' if code.endswith('.SZ') else 'sse',isHLtitle='false',
            searchkey=code[:6],seDate=f'{date}~{date}')
        if not cache.exists():
            temp = cache.with_suffix('.download')
            errors=[]
            for attempt in range(2):
                command=['curl.exe','-4','--connect-timeout','10','--max-time','45',
                    '--fail','--silent','--show-error',ENDPOINT,'--header','User-Agent: Mozilla/5.0',
                    '--header','Referer: https://www.cninfo.com.cn/','--output',str(temp)]
                for key,value in params.items():command += ['--data-urlencode',f'{key}={value}']
                result=subprocess.run(command,capture_output=True,timeout=55)
                if result.returncode == 0:
                    try:
                        obj=json.loads(temp.read_text(encoding='utf-8'))
                        if not isinstance(obj,dict) or 'announcements' not in obj:raise ValueError('Index response schema missing announcements')
                        temp.replace(cache)
                        break
                    except (ValueError,UnicodeError) as exc:errors.append(str(exc))
                else:errors.append(result.stderr.decode('utf-8',errors='replace').strip())
                time.sleep(1.3)
            else:
                return dict(ts_code=code,ann_date=day,status='query_failed',errors=errors,request=params)
        obj=json.loads(cache.read_text(encoding='utf-8'))
        items=obj.get('announcements') or []
        if not isinstance(items,list):raise ValueError('Index announcements is not a list')
        pages.append(dict(file=str(cache.relative_to(audit.OUT)),sha256=audit.sha(cache),request=params))
        metadata.extend(items)
        if not obj.get('hasMore',False):break
        time.sleep(1.3)
    else:
        return dict(ts_code=code,ann_date=day,status='query_page_bound_hit',pages=pages,
                    limitation='At most five pages; no completeness claim')
    matches=[item for item in metadata if item.get('secCode')==code[:6]]
    # Different issuer codes may refer to a parent or a pre-IPO listing: preserve for manual review.
    return dict(ts_code=code,ann_date=day,
        status='index_candidates_only' if matches else 'successful_query_no_exact_code_match',
        pages=pages,exact_code_matches=matches,other_code_results=[a for a in metadata if a not in matches],
        usable_in_verified_history=False)


def main():
    audit.initialize()
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'responses').mkdir(exist_ok=True)
    lock=OUT/'collection.lock'
    descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(descriptor,str(os.getpid()).encode());os.close(descriptor)
    try:
        sample=pd.read_csv(audit.OUT/'fixed_original_samples.csv',dtype=str)
        assert len(sample)==48 and sample.ann_date.between('20130101','20201231').all()
        keys=sample[['ts_code','ann_date']].drop_duplicates().sort_values(['ts_code','ann_date'])
        sample_sha=audit.sha(audit.OUT/'fixed_original_samples.csv')
        results=[]
        for row in keys.itertuples(index=False):
            path=OUT/f'{row.ts_code}_{row.ann_date}.json'
            if path.exists():result=json.loads(path.read_text(encoding='utf-8'))
            else:
                try:result=collect(row.ts_code,row.ann_date)
                except Exception as exc:result=dict(ts_code=row.ts_code,ann_date=row.ann_date,status='query_failed',errors=[str(exc)])
                audit.write_json(path,result)
            results.append(result)
            audit.write_json(OUT/'status.json',dict(at=audit.now(),pid=os.getpid(),state='running',
                completed_keys=len(results),total_keys=len(keys),sample_sha256=sample_sha,
                failed_keys=sum(r['status'].startswith('query_') for r in results)))
            print(f'{len(results)}/{len(keys)} {row.ts_code} {row.ann_date}: {result["status"]}',flush=True)
            time.sleep(1.3)
        assert audit.sha(audit.OUT/'fixed_original_samples.csv')==sample_sha
        counts={status:sum(r['status']==status for r in results) for status in sorted({r['status'] for r in results})}
        audit.write_json(OUT/'status.json',dict(at=audit.now(),state='completed_index_collection_only',
            completed_keys=len(results),total_keys=len(keys),sample_sha256=sample_sha,
            source_sha256=audit.sha(Path(__file__)),status_counts=counts,verified_original_version_rows=0,
            limitation='Exact code matches are possible documents, not verified issuer period/type/version/publication proofs.'))
        print(json.dumps(counts),flush=True)
    finally:lock.unlink()


if __name__=='__main__':main()
