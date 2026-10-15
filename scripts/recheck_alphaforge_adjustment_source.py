"""Six bounded read-only source checks after a stopped preparation; no repair."""
import json
from pathlib import Path
import traceback

import pandas as pd

from run_retention_development import ROOT, sha
from quant_research.data import TushareClient, load_token
from announcement_financial_audit import write_json

OUT=ROOT/'output/alphaforge_case_2018_2020_r1/provider_recheck'
DATES=['20180815','20180816','20180827','20180828']
CODES=['000005.SZ','600000.SH']
FIELDS='ts_code,trade_date,adj_factor'


def main():
    OUT.mkdir(exist_ok=False)
    # No credential, request body or decrypted value is written to evidence.
    client=TushareClient(load_token(),cache=OUT/'cache',interval=1.3)
    requests=[dict(trade_date=d) for d in DATES]+[
        dict(ts_code=c,start_date=DATES[0],end_date=DATES[-1]) for c in CODES]
    statuses=[];parts=[]
    for number,params in enumerate(requests):
        item=dict(number=number,api='adj_factor',params=params,fields=FIELDS)
        try:
            payload=client.query('adj_factor',params,FIELDS)
            frame=pd.DataFrame(payload['items'],columns=payload['fields'])
            if set(frame.columns)!=set(FIELDS.split(',')) or frame.duplicated(['ts_code','trade_date']).any():
                raise RuntimeError('Unexpected adjustment response schema or duplicate keys')
            frame['request_number']=number;parts.append(frame)
            item.update(state='completed',rows=len(frame))
            print('Read-only source check',number+1,'rows',len(frame),flush=True)
        except Exception as error:
            # Existing client already redacts credentials from API errors.
            item.update(state='failed',error=str(error))
            (OUT/f'failure_{number}.txt').write_text(traceback.format_exc(),encoding='utf-8')
        statuses.append(item);write_json(OUT/'status.json',statuses)
        if len(statuses)>=2 and all(s['state']=='failed' for s in statuses[-2:]):
            break
    if parts:
        fresh=pd.concat(parts,ignore_index=True)
        fresh.to_csv(OUT/'fresh_adj_factor.csv',index=False)
        prior=pd.read_csv(ROOT/'data/development_2018/adj_factor.csv',dtype={'ts_code':str,'trade_date':str},
                          float_precision='round_trip')
        day=fresh.loc[fresh.request_number.lt(4)].copy()
        joined=day.merge(prior,on=['ts_code','trade_date'],suffixes=('_fresh','_frozen'),how='left',validate='one_to_one')
        joined['difference']=joined.adj_factor_fresh-joined.adj_factor_frozen
        joined.to_csv(OUT/'fresh_vs_frozen.csv',index=False)
        by_stock=fresh.loc[fresh.request_number.ge(4)]
        equivalent=by_stock.merge(day,on=['ts_code','trade_date'],suffixes=('_stock','_day'),validate='one_to_one')
        equivalent['difference']=equivalent.adj_factor_stock-equivalent.adj_factor_day
        equivalent.to_csv(OUT/'stock_vs_day_queries.csv',index=False)
        write_json(OUT/'comparison_summary.json',dict(fresh_day_rows=len(day),joined_rows=len(joined),
            missing_frozen=int(joined.adj_factor_frozen.isna().sum()),
            changed_from_frozen=int(joined.difference.ne(0).sum()),
            stock_day_pairs=len(equivalent),stock_day_value_differences=int(equivalent.difference.ne(0).sum()),
            original_data_modified=False,new_factor_or_account_run=False))
    write_json(OUT/'manifest.json',{p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*')
                                   if p.is_file() and p.name!='manifest.json'})


if __name__=='__main__':main()
