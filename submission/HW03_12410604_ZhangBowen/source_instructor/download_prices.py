"""Optional data-acquisition helper; not an implementation of A1's analysis.
Attempts a Yahoo Finance chart download. The endpoint is not a guaranteed public API.
On access failure, use a lawfully obtained provider CSV and preserve its provenance.
Never silently substitute synthetic data. This helper was NOT network-validated here.
"""
from pathlib import Path
import argparse, csv, datetime as dt, hashlib, json, urllib.request, urllib.parse


def download(symbol: str, start: str, end: str, output: str):
    a=dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc)
    b=dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc)
    if a>=b:raise ValueError('start must precede end (end date is inclusive)')
    params={'period1':int(a.timestamp()),'period2':int((b+dt.timedelta(days=1)).timestamp()),'interval':'1d','events':'div,splits'}
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(symbol,safe='')+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req,timeout=30) as response:payload=json.load(response)
        result=payload['chart']['result'][0]
        rows=result['indicators']['adjclose'][0]['adjclose']
        stamps=result['timestamp']
        if not rows or len(rows)!=len(stamps):raise ValueError('Invalid or empty response')
        if any(x is None or x<=0 for x in rows):raise ValueError('Missing/nonpositive adjusted prices; audit the provider data')
    except Exception as exc:
        raise RuntimeError('Price acquisition failed; no data were synthesized. Obtain a legal CSV from your provider and record its source.') from exc
    target=Path(output);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['Date','Price'])
        for t,v in zip(stamps,rows):w.writerow([dt.datetime.fromtimestamp(t,dt.timezone.utc).date().isoformat(),v])
    manifest={'symbol':symbol,'start':start,'end_inclusive':end,'source_url':url,
              'field':'Yahoo adjclose: split/dividend adjusted; not unadjusted exchange price',
              'retrieved_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'rights':'Provider terms apply; no redistribution permission is asserted by this script.'}
    target.with_suffix('.provenance.json').write_text(json.dumps(manifest,indent=2))
    print(f'Saved {len(rows)} observations to {target}')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',default='MSFT');parser.add_argument('--start',default='2021-10-14')
    parser.add_argument('--end',default='2026-10-14');parser.add_argument('--out',default='data/prices.csv')
    args=parser.parse_args();download(args.symbol,args.start,args.end,args.out)
