"""Approved four labels and explicit retrospective missing-data reasons."""
import numpy as np
import pandas as pd

VARIANTS=('A','B','C','D')


def asset_labels(group,calendar,schedule,benchmark,issues=()):
    if not calendar.is_monotonic_increasing or calendar.has_duplicates:
        raise ValueError('Unique ascending exchange calendar required')
    if group.trade_date.duplicated().any():raise ValueError('Duplicate quote')
    g=group.set_index('trade_date').reindex(calendar)
    fields=['open','high','low','close','adj_factor','vol','amount']
    present=pd.Series(calendar.isin(group.trade_date),index=calendar).to_numpy()
    values=g[fields].to_numpy(dtype=float)
    valid=np.isfinite(values).all(axis=1)&(values>0).all(axis=1)
    opened=(g.open*g.adj_factor).to_numpy()
    index_price=benchmark.reindex(calendar).to_numpy()
    pos=calendar.get_indexer(schedule.signal_date)
    if (pos<0).any():raise ValueError('Signal outside calendar')
    entry=calendar.get_indexer(schedule.execution_date)
    weekly_end=calendar.get_indexer(pd.DatetimeIndex(schedule.next_execution))
    twenty_end=pos+21
    unknown=np.zeros(len(calendar),dtype=bool)
    for d in issues:
        j=calendar.get_indexer([pd.Timestamp(d)])[0]
        if j>=0:unknown[j]=True
    prefix={name:np.r_[0,np.cumsum(mask.astype(int))] for name,mask in
            [('missing',~present),('invalid',present&~valid),('unknown',unknown)]}
    def interval_count(name,a,b):return int(prefix[name][b+1]-prefix[name][a]) if a<=b else 0
    rows=[]
    for i,d in enumerate(schedule.signal_date):
        for variant in VARIANTS:
            start=int(entry[i]);end=int(twenty_end[i] if variant in ('A','C') else weekly_end[i])
            outside=start<0 or end<0 or end>=len(calendar)
            endpoint_missing=endpoint_invalid=middle_missing=middle_invalid=unknown_event=benchmark_invalid=False
            dates_missing=[];dates_invalid=[]
            if not outside:
                endpoint_missing=not present[start] or not present[end]
                endpoint_invalid=(present[start] and not valid[start]) or (present[end] and not valid[end])
                middle_missing=interval_count('missing',start+1,end-1)>0
                middle_invalid=interval_count('invalid',start+1,end-1)>0
                unknown_event=interval_count('unknown',start,end)>0
                benchmark_invalid=not(np.isfinite(index_price[[start,end]]).all() and (index_price[[start,end]]>0).all())
                dates_missing=[x.strftime('%Y-%m-%d') for x in calendar[start:end+1][~present[start:end+1]]]
                dates_invalid=[x.strftime('%Y-%m-%d') for x in calendar[start:end+1][present[start:end+1]&~valid[start:end+1]]]
            full=variant in ('A','B')
            acceptable=not(outside or benchmark_invalid or unknown_event or endpoint_missing or endpoint_invalid or
                           (full and (middle_missing or middle_invalid)))
            if outside:reason='outside_period'
            elif benchmark_invalid:reason='benchmark_endpoint'
            elif unknown_event:reason='unknown_adjustment'
            elif endpoint_missing or endpoint_invalid:reason='stock_endpoint'
            elif full and (middle_missing or middle_invalid):reason='middle_window'
            else:reason='valid'
            label=float(opened[end]/opened[start]-1-(index_price[end]/index_price[start]-1)) if acceptable else np.nan
            ref_date=calendar[twenty_end[i]] if twenty_end[i]<len(calendar) else pd.NaT
            rows.append(dict(trade_date=d,variant=variant,label=label,label_valid=acceptable,
                entry_date=calendar[start] if start>=0 else pd.NaT,
                label_end=calendar[end] if 0<=end<len(calendar) else pd.NaT,reference_end=ref_date,
                sessions=end-start if not outside else np.nan,outside_period=outside,
                endpoint_missing=bool(endpoint_missing),endpoint_invalid=bool(endpoint_invalid),
                middle_missing=bool(middle_missing),middle_invalid=bool(middle_invalid),
                unknown_adjustment=bool(unknown_event),benchmark_invalid=bool(benchmark_invalid),reason=reason,
                missing_dates='|'.join(dates_missing),invalid_dates='|'.join(dates_invalid)))
    return pd.DataFrame(rows)


def training_samples(samples,variant,fit_date):
    result=samples.loc[samples[f'{variant}_valid']&samples.reference_end.lt(fit_date)&samples[f'{variant}_end'].lt(fit_date)].copy()
    result['label']=result[f'{variant}_label']
    result['label_end']=result[f'{variant}_end']
    result['sample_weight']=1/result.groupby('trade_date').ts_code.transform('size')
    return result
