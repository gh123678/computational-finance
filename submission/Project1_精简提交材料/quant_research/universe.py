"""Historical eligibility using explicit intervals, with unknowns excluded."""
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
    known = names.loc[(names.start_date <= stamp) & (names.end_date.isna() | (names.end_date >= stamp)) &
                      names.ann_date.notna() & (names.ann_date <= stamp)].copy()
    counts = known.groupby('ts_code').name.nunique()
    known = known.loc[known.ts_code.isin(counts[counts == 1].index)]
    known = known.loc[~known.name.str.contains('ST|^PT', case=False, na=True)].drop_duplicates('ts_code')
    sector = industries.loc[(industries.in_date <= stamp) &
                             (industries.out_date.isna() | (industries.out_date > stamp))].copy()
    counts = sector.groupby('ts_code').l1_code.nunique()
    sector = sector.loc[sector.ts_code.isin(counts[counts == 1].index)].drop_duplicates('ts_code')
    selected = listed.loc[listed.ts_code.isin(known.ts_code)].merge(
        sector[['ts_code', 'l1_code']].rename(columns={'l1_code': 'industry'}), on='ts_code', validate='one_to_one')
    return selected
