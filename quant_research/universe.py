"""Point-in-time historical eligibility for the investable universe."""
import pandas as pd


def historical_universe(date, metadata, names, industries, calendar):
    date = pd.Timestamp(date)
    stamp = date.strftime('%Y%m%d')
    listed = metadata.loc[metadata.ts_code.str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ)$') &
                          (metadata.list_date <= stamp) &
                          (metadata.delist_date.isna() | (metadata.delist_date > stamp))].copy()
    listed_dates = pd.to_datetime(listed.list_date, format='%Y%m%d')
    ages = calendar.searchsorted(date, side='right') - calendar.searchsorted(listed_dates)
    listed = listed.loc[ages >= 120]
    # Tushare ``namechange`` is an event/interval table, not a complete daily
    # security-name master.  A missing active ordinary-name row therefore does
    # not mean that the security's status is unknown.  Use announced ST/PT
    # intervals as an exclusion ledger instead of requiring every stock to
    # have an active name row.
    active_names = names.loc[
        (names.start_date <= stamp) &
        (names.end_date.isna() | (names.end_date >= stamp)) &
        names.ann_date.notna() &
        (names.ann_date <= stamp)
    ]
    risk_codes = active_names.loc[
        active_names.name.str.contains('ST|^PT', case=False, na=False), 'ts_code'
    ].unique()
    listed = listed.loc[~listed.ts_code.isin(risk_codes)]
    sector = industries.loc[(industries.in_date <= stamp) &
                             (industries.out_date.isna() | (industries.out_date > stamp))].copy()
    counts = sector.groupby('ts_code').l1_code.nunique()
    sector = sector.loc[sector.ts_code.isin(counts[counts == 1].index)].drop_duplicates('ts_code')
    selected = listed.merge(
        sector[['ts_code', 'l1_code']].rename(columns={'l1_code': 'industry'}), on='ts_code', validate='one_to_one')
    return selected
