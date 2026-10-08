"""Past-only twelve price/volume features and matured twenty-session labels."""
import numpy as np
import pandas as pd

FEATURES=['ret5','ret20','ret60','vol20','vol60','ma20_gap','ma60_gap',
          'amount5_20','log_adv20','range20','intraday5','return_amount_corr20']


def compute_asset(group,calendar,signal_dates,benchmark_open,issue_dates=()):
    if group.trade_date.duplicated().any():
        raise ValueError('Duplicate asset/date')
    g=group.set_index('trade_date').reindex(calendar)
    valid=(g[['open','high','low','close','adj_factor']].gt(0).all(axis=1)&g.vol.gt(0)&g.amount.gt(0))
    raw=g[['open','high','low','close']].where(valid,axis=0)
    adjusted=raw.mul(g.adj_factor,axis=0)
    close=adjusted.close
    returns=close.pct_change(fill_method=None)
    amount=(g.amount*1000).where(valid)
    result=pd.DataFrame(index=calendar)
    for n in (5,20,60):
        result[f'ret{n}']=close/close.shift(n)-1
    for n in (20,60):
        result[f'vol{n}']=returns.rolling(n,min_periods=n).std(ddof=1)
        result[f'ma{n}_gap']=close/close.rolling(n,min_periods=n).mean()-1
    result['amount5_20']=amount.rolling(5,min_periods=5).mean()/amount.rolling(20,min_periods=20).mean()-1
    result['log_adv20']=np.log1p(amount.rolling(20,min_periods=20).mean())
    result['range20']=((raw.high-raw.low)/raw.close).rolling(20,min_periods=20).mean()
    result['intraday5']=((raw.close-raw.open)/raw.open).rolling(5,min_periods=5).mean()
    result['return_amount_corr20']=returns.rolling(20,min_periods=20).corr(np.log1p(amount))
    complete=valid.astype(int).rolling(61,min_periods=61).sum().eq(61)
    quarantine=pd.Series(False,index=calendar)
    for date in issue_dates:
        pos=calendar.get_indexer([pd.Timestamp(date)])[0]
        if pos>=0:
            # Include the event plus the following 60 exchange sessions.
            quarantine.iloc[pos:pos+61]=True
    result.loc[~complete|quarantine,FEATURES]=np.nan
    result['feature_valid']=complete&~quarantine&np.isfinite(result[FEATURES]).all(axis=1)
    label=adjusted.open.shift(-21)/adjusted.open.shift(-1)-1
    benchmark=benchmark_open.reindex(calendar)
    label-=benchmark.shift(-21)/benchmark.shift(-1)-1
    full_future=pd.Series(True,index=calendar)
    for step in range(1,22):
        full_future &= valid.shift(-step,fill_value=False)
    index=pd.Series(calendar,index=calendar)
    result['entry_date']=index.shift(-1)
    result['label_end']=index.shift(-21)
    label_valid=full_future&label.notna()&np.isfinite(label)
    for date in issue_dates:
        label_valid &= ~((result.entry_date<=pd.Timestamp(date))&(result.label_end>=pd.Timestamp(date)))
    result['label']=label.where(label_valid)
    result['label_valid']=label_valid
    result['long_quarantined']=quarantine
    result['trade_date']=calendar
    return result.loc[result.index.isin(signal_dates)].reset_index(drop=True),returns


def matured_training(samples,fit_date):
    result=samples.loc[samples.feature_valid&samples.label_valid&samples.label_end.lt(pd.Timestamp(fit_date))].copy()
    assert result.label_end.lt(pd.Timestamp(fit_date)).all()
    result['sample_weight']=1/result.groupby('trade_date').ts_code.transform('size')
    return result
