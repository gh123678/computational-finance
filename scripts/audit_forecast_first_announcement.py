"""Vendor-date and retained-version diagnostics; no historical-use approvals."""
from pathlib import Path
from decimal import Decimal, InvalidOperation
from collections import defaultdict, Counter
import json
import pandas as pd
import numpy as np
import announcement_financial_audit as audit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/forecast_first_day_integrity_20261012_r1'
FIELDS=['type','p_change_min','p_change_max','net_profit_min','net_profit_max','last_parent_net','summary','change_reason']
NUMERIC=set(FIELDS[1:6])


def content_identity(row):
    values=[]
    for field in FIELDS:
        value=row.get(field,'')
        if field in NUMERIC and value:
            try:value=str(Decimal(value).normalize())
            except InvalidOperation:value='invalid_numeric:'+value
        values.append(value)
    return tuple(values)


def exposure_dates(signals, first_day, current_day):
    # A row is not yet eligible on its current announcement day under strict-day policy.
    return signals[(signals>first_day)&(signals<=current_day)]


def main():
    if OUT.exists():raise RuntimeError('Snapshot already exists')
    OUT.mkdir()
    source=ROOT/'output/announcement_financial_audit_20261007/forecast_records.csv'
    signal=ROOT/'output/label_horizon_coverage_2018_2020_r1/common_samples.csv'
    inputs={str(p.relative_to(ROOT)):audit.sha(p) for p in [source,signal,Path(__file__)]}
    frame=pd.read_csv(source,dtype=str,keep_default_na=False)
    ann=pd.to_datetime(frame.ann_date,format='%Y%m%d',errors='coerce')
    first=pd.to_datetime(frame.first_ann_date,format='%Y%m%d',errors='coerce')
    in_window=ann.between(pd.Timestamp('2013-01-01'),pd.Timestamp('2020-12-31'))
    originals=defaultdict(list)
    for i,r in frame.iterrows():originals[(r.ts_code,r.ann_date,r.end_date)].append(i)
    samples=pd.read_csv(signal,usecols=['ts_code','trade_date'],dtype=str)
    samples['day']=pd.to_datetime(samples.trade_date,format='%Y-%m-%d',errors='raise')
    assert not samples.duplicated(['ts_code','day']).any()
    by_code={c:np.sort(g.day.to_numpy()) for c,g in samples.groupby('ts_code')}
    rows=[];exposures=set()
    for i,r in frame.loc[in_window].iterrows():
        a,f=ann.loc[i],first.loc[i]
        kind='missing_or_invalid_first_day' if pd.isna(f) else 'first_day_later_than_current_day' if f>a else 'first_day_equal_current_day' if f==a else 'first_day_earlier_than_current_day'
        matches=originals.get((r.ts_code,r.first_ann_date,r.end_date),[]) if kind=='first_day_earlier_than_current_day' else []
        earlier_in_window=bool(pd.notna(f) and pd.Timestamp('2013-01-01')<=f<=pd.Timestamp('2020-12-31'))
        identities={content_identity(frame.loc[j]) for j in matches}
        current=content_identity(r)
        version_state=('some_first_day_rows_match_payload' if current in identities else 'first_day_payload_differs') if matches else 'first_day_row_not_retained_in_current_cache'
        exposed=exposure_dates(by_code.get(r.ts_code,np.array([],dtype='datetime64[ns]')),f.to_datetime64(),a.to_datetime64()) if kind=='first_day_earlier_than_current_day' else []
        for day in exposed:exposures.add((r.ts_code,pd.Timestamp(day).strftime('%Y-%m-%d')))
        rows.append(dict(ts_code=r.ts_code,ann_date=r.ann_date,first_ann_date=r.first_ann_date,end_date=r.end_date,
            row_sha256=r.row_sha256,vendor_date_state=kind,first_day_in_approved_window=earlier_in_window,
            retained_first_day_row_count=len(matches),retained_first_day_distinct_payloads=len(identities),
            retained_version_comparison=version_state if kind=='first_day_earlier_than_current_day' else 'not_a_prior_date_comparison',
            hypothetical_early_signal_row_count=len(exposed),verified_publication_day=None,selected_financial_value=None,usable_in_verified_history=False))
    results=pd.DataFrame(rows);results.to_csv(OUT/'forecast_date_version_diagnostics.csv',index=False)
    results.loc[results.vendor_date_state.ne('first_day_equal_current_day')].to_csv(OUT/'non_equal_or_unknown_first_days.csv',index=False)
    pd.DataFrame(sorted(exposures),columns=['ts_code','trade_date']).to_csv(OUT/'hypothetical_early_signal_keys.csv',index=False)
    early=results.loc[results.vendor_date_state.eq('first_day_earlier_than_current_day')]
    summary=dict(raw_forecast_rows=len(frame),in_window_forecast_rows=len(results),vendor_date_states=dict(Counter(results.vendor_date_state)),
        earlier_day_code_periods=len(early[['ts_code','end_date']].drop_duplicates()),
        earlier_day_first_date_keys=len(early[['ts_code','first_ann_date','end_date']].drop_duplicates()),
        prior_date_row_comparisons=dict(Counter(early.retained_version_comparison)),
        earlier_rows_in_window_without_retained_first_day=int((early.first_day_in_approved_window & early.retained_first_day_row_count.eq(0)).sum()),
        earlier_rows_first_day_outside_window=int((~early.first_day_in_approved_window).sum()),
        summed_per_row_hypothetical_exposures=int(early.hypothetical_early_signal_row_count.sum()),
        unique_hypothetical_stock_signal_keys=len(exposures),historical_approvals=0,new_models=0,new_backtests=0,
        limitation='Vendor first_ann_date is not the release date of every revised payload; missing cached first-day rows do not establish absence of original announcements; exposure is hypothetical and not frozen-strategy financial consumption')
    for p,h in inputs.items():assert audit.sha(ROOT/p)==h,p
    audit.write_json(OUT/'summary.json',summary);audit.write_json(OUT/'input_sha256.json',inputs)
    audit.write_json(OUT/'verification.json',dict(inputs_unchanged=True,old_experiments=audit.verify_old(),all_history_gates_closed=True))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
