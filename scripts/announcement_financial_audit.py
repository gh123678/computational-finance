"""Separate read-only financial-data audit; never creates trading signals."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from quant_research.data import TushareClient, load_token, DataError

DATA = ROOT/'data/announcement_financial_audit_2013_2020_r1'
OUT = ROOT/'output/announcement_financial_audit_20261007'
SOURCE = ROOT/'output/label_horizon_coverage_2018_2020_r1'
SPEC = ROOT/'docs/superpowers/specs/2026-10-07-announcement-financial-audit-design.md'
APIS = ['forecast', 'fina_indicator', 'fina_audit']
CAPS = {'forecast':3500, 'fina_indicator':100, 'fina_audit':1000}
FIELDS = {
    'forecast':'ts_code,ann_date,end_date,type,p_change_min,p_change_max,net_profit_min,net_profit_max,last_parent_net,first_ann_date,summary,change_reason,update_flag',
    'fina_indicator':'ts_code,ann_date,end_date,profit_dedt,roe,debt_to_assets,ocf_to_debt,update_flag',
    'fina_audit':'ts_code,ann_date,end_date,audit_result,audit_fees,audit_agency,audit_sign',
}

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576), b''):digest.update(block)
    return digest.hexdigest()

def write_json(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+f'.{os.getpid()}.{time.time_ns()}.tmp')
    temp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
    # Windows readers may temporarily hold the destination without delete sharing.
    for attempt in range(8):
        try:
            temp.replace(path)
            break
        except PermissionError:
            if attempt==7:raise
            time.sleep(.05*(attempt+1))

def now():return datetime.now(timezone.utc).isoformat()

def verify_old():
    counts={}
    for base in [SOURCE,ROOT/'output/open_source_ml_risk_2018_2020_r1']:
        files=json.loads((base/'output_sha256.json').read_text(encoding='utf-8'))
        for name,h in files.items():
            if sha(base/name)!=h:raise DataError('Frozen artifact changed: '+name)
        counts[base.name]=len(files)
    return counts

def initialize():
    OUT.mkdir(parents=True,exist_ok=True);DATA.mkdir(parents=True,exist_ok=True)
    file=OUT/'protocol.json'
    inputs={'spec':sha(SPEC),'common_samples':sha(SOURCE/'common_samples.csv'),
            'calendar':sha(ROOT/'data/continuous_2016_2025_dividend_r1/calendar.csv'),
            'runner':sha(__file__),'client':sha(ROOT/'quant_research/data.py')}
    core={p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}
    original=json.loads((ROOT/'output/open_source_ml_risk_2018_2020_r1/frozen_protocol.json').read_text(encoding='utf-8'))
    if core!=original['source_sha256']:raise DataError('Core differs from frozen research source')
    if file.exists():
        protocol=json.loads(file.read_text(encoding='utf-8'))
        if protocol['inputs']!=inputs or protocol['core_sha256']!=core:
            raise DataError('Audit inputs/source changed; do not mix versions')
    else:
        codes=sorted(pd.read_csv(SOURCE/'common_samples.csv',usecols=['ts_code']).ts_code.unique())
        pd.DataFrame({'ts_code':codes}).to_csv(DATA/'universe.csv',index=False)
        protocol={'created_at':now(),'inputs':inputs,'core_sha256':core,'codes':codes,
                  'universe_sha256':sha(DATA/'universe.csv'),'apis':APIS,'fields':FIELDS,
                  'announcement_window':['20130101','20201231'],
                  'indicator_report_window':['20121231','20201231'],
                  'interval_seconds':1.3,'old_artifacts':verify_old(),
                  'rule':'All records remain unverified until original-version publication evidence is checked.'}
        write_json(file,protocol)
    if sha(DATA/'universe.csv')!=protocol['universe_sha256']:raise DataError('Universe changed')
    return protocol

def partitioned_query(client, api, code, start, end):
    """Date partition when at endpoint cap; no unsupported offset pagination."""
    params={'ts_code':code,'start_date':start,'end_date':end}
    data=client.query(api,params,FIELDS[api])
    fields=data['fields']; rows=data['items']
    if not {'ts_code','ann_date','end_date'}.issubset(fields):raise DataError(api+': missing date/code schema')
    dimension='end_date' if api=='fina_indicator' else 'ann_date'
    ci=fields.index('ts_code');di=fields.index(dimension)
    for row in rows:
        date=str(row[di])
        if row[ci]!=code or len(date)!=8 or not date.isdigit() or not start<=date<=end:
            raise DataError(api+': response violates stock/date query scope')
    public={'api_name':api,'params':params,'fields':FIELDS[api]}
    key=hashlib.sha256(json.dumps(public,sort_keys=True).encode()).hexdigest()
    path=client.cache/api/(key+'.json')
    reference={'path':str(path.relative_to(DATA)),'sha256':sha(path)}
    if len(rows)>=CAPS[api] or data.get('has_more') is True:
        left=datetime.strptime(start,'%Y%m%d');right=datetime.strptime(end,'%Y%m%d')
        if left==right:raise DataError(api+': endpoint cap at single date; cannot prove completeness')
        middle=left+(right-left)//2
        a=partitioned_query(client,api,code,start,middle.strftime('%Y%m%d'))
        b=partitioned_query(client,api,code,(middle+timedelta(days=1)).strftime('%Y%m%d'),end)
        return a+b
    return [reference]

def safe_error(exc, token=''):
    # No traceback/request body is persisted. Existing client errors already redact token.
    message=str(exc)
    if token:message=message.replace(token,'[REDACTED]')
    return {'error_type':type(exc).__name__,'error':message}

def download(protocol):
    lock=OUT/'download.lock'
    try:
        with lock.open('x',encoding='utf-8') as stream:json.dump({'pid':os.getpid(),'started_at':now()},stream)
    except FileExistsError:raise DataError('Existing audit lock; inspect process rather than duplicate')
    done=0;failed=0;consecutive=0;total=len(protocol['codes'])*len(APIS)
    try:
        try:token=load_token()
        except Exception as exc:
            write_json(OUT/('credential_failure_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json'),safe_error(exc))
            raise
        client=TushareClient(token,cache=DATA/'raw',interval=protocol['interval_seconds'])
        for code in protocol['codes']:
            for api in APIS:
                result=DATA/'completed'/api/(code+'.json')
                if result.exists():
                    old=json.loads(result.read_text(encoding='utf-8'))
                    for leaf in old['leaves']:
                        if sha(DATA/leaf['path'])!=leaf['sha256']:raise DataError('Completed raw response changed')
                    done+=1;continue
                try:
                    start='20121231' if api=='fina_indicator' else '20130101'
                    leaves=partitioned_query(client,api,code,start,'20201231')
                    write_json(result,{'api':api,'ts_code':code,'completed_at':now(),'leaves':leaves})
                    done+=1;consecutive=0
                except Exception as exc:
                    failed+=1;consecutive+=1
                    error=dict(api=api,ts_code=code,at=now(),**safe_error(exc,token))
                    failure=OUT/'failures'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
                    write_json(failure,error)
                    print(json.dumps(error,ensure_ascii=False),flush=True)
                    # Avoid a useless failure storm or continued requests after authentication loss.
                    if 'code=2002' in error['error'] or consecutive>=3:raise DataError('Requests stopped after authorization loss or three consecutive failures')
                write_json(OUT/'download_status.json',{'at':now(),'pid':os.getpid(),'completed_units':done,
                    'total_units':total,'failed_units_this_run':failed,'last_code':code,'last_api':api,'state':'running'})
                if (done+failed)%30==0:print(f'{done}/{total} stock/API units complete; {failed} failures',flush=True)
        write_json(OUT/'download_status.json',{'at':now(),'completed_units':done,'total_units':total,
            'failed_units_this_run':failed,'state':'completed' if done==total else 'incomplete'})
    except Exception as exc:
        write_json(OUT/'download_status.json',{'at':now(),'completed_units':done,'total_units':total,
            'failed_units_this_run':failed,'state':'stopped',**safe_error(exc,locals().get('token',''))})
        raise
    finally:
        lock.unlink()

def annotate(frame, api, calendar):
    """API dates produce candidates, never evidence of original publication."""
    f=frame.copy()
    for col in ['ann_date','end_date']:
        f[col+'_parsed']=pd.to_datetime(f[col].astype('string'),format='%Y%m%d',errors='coerce')
    ann=f.ann_date_parsed;period=f.end_date_parsed
    f['within_ann_window']=ann.between('20130101','20201231')
    valid=ann.notna()&period.notna()&f.within_ann_window
    if api!='forecast':valid &= period.le(ann)
    positions=calendar.searchsorted(ann.fillna(pd.Timestamp('21000101')),side='right')
    f['candidate_available_date']=[calendar[i] if ok and i<len(calendar) else pd.NaT for ok,i in zip(valid,positions)]
    f['publication_evidence_status']='unverified_original_version'
    f['usable_in_verified_history']=False
    f['api']=api
    f['row_sha256']=[hashlib.sha256(json.dumps(r,sort_keys=True,default=str).encode()).hexdigest() for r in frame.to_dict('records')]
    content=frame.drop(columns=['raw_path','raw_sha256','retrieved_at','update_flag'],errors='ignore')
    f['content_sha256']=[hashlib.sha256(json.dumps(r,sort_keys=True,default=str).encode()).hexdigest() for r in content.to_dict('records')]
    # Forecast monetary fields are officially in 10,000 CNY; preserve originals.
    if api=='forecast':
        for col in ['net_profit_min','net_profit_max','last_parent_net']:
            if col in f:f[col+'_cny']=pd.to_numeric(f[col],errors='coerce')*10000
    f['source_url']='';f['verified_publication_date']=pd.NaT
    return f

def analyze(protocol):
    frames=[];units=[]
    calendar_file=ROOT/'data/continuous_2016_2025_dividend_r1/calendar.csv'
    cal=pd.read_csv(calendar_file,dtype={'cal_date':str})
    calendar=pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1),'cal_date'])).sort_values().unique()
    calendar=calendar[calendar<=pd.Timestamp('20201231')]
    for api in APIS:
        collected=[]
        for code in protocol['codes']:
            file=DATA/'completed'/api/(code+'.json')
            if not file.exists():
                units.append({'api':api,'ts_code':code,'status':'not_completed','rows':None});continue
            obj=json.loads(file.read_text(encoding='utf-8'));count=0
            for leaf in obj['leaves']:
                path=DATA/leaf['path']
                if sha(path)!=leaf['sha256']:raise DataError('Raw cache hash changed')
                response=json.loads(path.read_text(encoding='utf-8'))
                f=pd.DataFrame(response['data']['items'],columns=response['data']['fields'])
                count+=len(f)
                f['raw_path']=leaf['path'];f['raw_sha256']=leaf['sha256'];f['retrieved_at']=response['retrieved_at']
                collected.append(f)
            units.append({'api':api,'ts_code':code,'status':'success_empty' if count==0 else 'success_nonempty','rows':count})
        if not collected:continue
        f=annotate(pd.concat(collected,ignore_index=True),api,calendar)
        f.to_csv(OUT/(api+'_records.csv'),index=False)
        frames.append(f)
    pd.DataFrame(units).to_csv(OUT/'stock_api_coverage.csv',index=False)
    if not frames:
        write_json(OUT/'analysis_status.json',{'at':now(),'state':'no_completed_data','old_artifacts':verify_old()});return
    all_rows=pd.concat(frames,ignore_index=True)
    # Same report/publication key, multiple distinct content/version rows: investigation queue.
    group=['api','ts_code','end_date','ann_date']
    unique=all_rows.groupby(group,dropna=False).content_sha256.transform('nunique')
    conflict=all_rows.loc[unique.gt(1)].copy()
    conflict.to_csv(OUT/'same_date_version_conflicts.csv',index=False)
    eligible=all_rows.loc[all_rows.candidate_available_date.notna()].copy()
    eligible['year']=eligible.ann_date_parsed.dt.year
    sample=[]
    for (api,year),g in eligible.groupby(['api','year']):
        g=g.sort_values(['ts_code','end_date','ann_date','row_sha256'])
        sample.extend([g.iloc[0],g.iloc[-1]])
    sample=pd.DataFrame(sample).drop_duplicates('row_sha256') if sample else all_rows.iloc[:0]
    loss=pd.read_csv(ROOT/'output/pretrade_risk_diagnosis_20261007/top_losses_pretrade.csv').ts_code
    queue=pd.concat([sample,conflict,eligible.loc[eligible.ts_code.isin(loss)]],ignore_index=True).drop_duplicates(['api','row_sha256'])
    queue.to_csv(OUT/'original_document_check_queue.csv',index=False)
    # Candidate API coverage only, not verified coverage. Never turn absence into safe status.
    signal=pd.read_csv(SOURCE/'common_samples.csv',usecols=['trade_date','ts_code'],parse_dates=['trade_date'])
    coverage=[]
    for api,g in eligible.groupby('api'):
        first=g.groupby('ts_code').candidate_available_date.min()
        s=signal.copy();s['first_candidate_date']=s.ts_code.map(first)
        s['api_candidate_available']=s.first_candidate_date.le(s.trade_date)
        for year,h in s.groupby(s.trade_date.dt.year):coverage.append({'api':api,'year':int(year),
            'stock_signal_rows':len(h),'api_candidate_rows':int(h.api_candidate_available.sum()),
            'verified_original_version_rows':0,'not_verified_rows':len(h)})
    pd.DataFrame(coverage).to_csv(OUT/'signal_candidate_coverage.csv',index=False)
    status={'at':now(),'state':'api_candidate_analysis_only','completed_units':sum(u['status']!='not_completed' for u in units),
        'total_units':len(units),'raw_rows':len(all_rows),'ann_window_rows':int(all_rows.within_ann_window.sum()),
        'outside_or_invalid_ann_rows':int((~all_rows.within_ann_window).sum()),'same_date_conflict_rows':len(conflict),
        'document_queue_rows':len(queue),'verified_original_version_rows':0,'old_artifacts':verify_old()}
    write_json(OUT/'analysis_status.json',status)
    print(json.dumps(status,ensure_ascii=False),flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['initialize','download','analyze']);args=parser.parse_args()
    protocol=initialize()
    if args.stage=='initialize':print(f"Frozen universe: {len(protocol['codes'])} stocks, {len(protocol['codes'])*3} units",flush=True)
    elif args.stage=='download':download(protocol);analyze(protocol)
    else:analyze(protocol)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Audit stopped: '+str(exc),file=sys.stderr);sys.exit(1)
