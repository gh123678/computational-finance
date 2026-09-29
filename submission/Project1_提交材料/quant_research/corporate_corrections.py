"""Narrow, source-verified event corrections; never delete a security's history."""
import math
import pandas as pd

DEAO_SOURCE = 'https://static.cninfo.com.cn/finalpage/2020-09-19/1208460598.PDF'
LUTIANHUA_SOURCE = 'https://static.cninfo.com.cn/finalpage/2018-08-03/1205254635.PDF'
CHUANHUA_SOURCE = 'https://static.cninfo.com.cn/finalpage/2016-09-30/1202736702.PDF'
LONGPING_SOURCE = 'data/development_2018/{daily.csv,adj_factor.csv,dividend.csv}'
CMPO_SOURCE = 'https://www.szse.cn/disclosure/notice/general/t20191211_572534.html'


def correct_actions(frame):
    frame = frame.copy()
    audit = []
    corrections = [
        dict(code='002260.SZ', ex='20200925', record='20200924', announcement='20200919',
             ratio=1.1, source=DEAO_SOURCE,
             reason='Restructuring shares go to investors, not existing shareholders; announcement specifies no ex-price adjustment.'),
        dict(code='000912.SZ', ex='20180730', record='20180727', announcement='20180724',
             ratio=1.6803419, source=LUTIANHUA_SOURCE,
             reason='Restructuring shares were registered to the bankruptcy estate for debt repayment, investors and disposal; existing shareholders received no shares.'),
        dict(code='000155.SZ', ex='20161214', record='20161213', announcement='20161210',
             ratio=1.7021276, source=CHUANHUA_SOURCE,
             reason='Restructuring shares were transferred to restructuring investors; proceeds paid restructuring expenses and creditors, so existing shareholders received no shares.'),
    ]
    excluded = pd.Series(False, index=frame.index)
    for correction in corrections:
        mask = (frame.ts_code.eq(correction['code']) & frame.ex_date.eq(correction['ex']) &
                frame.div_proc.eq('实施'))
        excluded |= mask
        for row in frame.loc[mask].to_dict('records'):
            def amount(field):
                value = row.get(field)
                return 0. if pd.isna(value) else float(value)
            if (row.get('record_date') != correction['record'] or
                    row.get('imp_ann_date') != correction['announcement'] or
                    not math.isclose(amount('stk_div'), correction['ratio']) or
                    not math.isclose(amount('stk_co_rate'), correction['ratio']) or
                    any(amount(f) != 0 for f in ['cash_div', 'cash_div_tax', 'stk_bo_rate'])):
                raise ValueError(f"Verified {correction['code']} correction no longer matches source row; review required")
            audit.append(dict(ts_code=row['ts_code'], ex_date=row['ex_date'],
                              action='exclude_non_shareholder_distribution', source=correction['source'],
                              reason=correction['reason'],
                              original={k: None if pd.isna(v) else v for k, v in row.items()}))
    return frame.loc[~excluded].copy(), audit


def correct_adjustments(frame):
    """Repair exact, bounded vendor factor reversals after verifying raw-price continuity."""
    frame = frame.copy()
    audit = []
    if (frame.empty or frame.trade_date.min() > pd.Timestamp('2018-08-15') or
            frame.trade_date.max() < pd.Timestamp('2018-08-28')):
        return frame, audit
    mask = (frame.ts_code.eq('000998.SZ') &
            frame.trade_date.between(pd.Timestamp('2018-08-16'), pd.Timestamp('2018-08-27')))
    observed = frame.loc[mask, ['trade_date', 'adj_factor']].sort_values('trade_date')
    expected_dates = pd.to_datetime(['2018-08-23', '2018-08-24', '2018-08-27'])
    if frame.ts_code.eq('000998.SZ').any():
        if (not observed.trade_date.reset_index(drop=True).equals(pd.Series(expected_dates)) or
                not observed.adj_factor.map(lambda value: math.isclose(float(value), 10.8142)).all()):
            raise ValueError('Verified 000998.SZ adjustment correction no longer matches source rows; review required')
        before = frame.loc[(frame.ts_code.eq('000998.SZ')) &
                           (frame.trade_date.eq(pd.Timestamp('2018-08-15'))), 'adj_factor']
        after = frame.loc[(frame.ts_code.eq('000998.SZ')) &
                          (frame.trade_date.eq(pd.Timestamp('2018-08-28'))), 'adj_factor']
        if len(before) != 1 or len(after) != 1 or not math.isclose(float(before.iloc[0]), 11.1070) or not math.isclose(float(after.iloc[0]), 11.1070):
            raise ValueError('Verified 000998.SZ adjustment boundaries changed; review required')
        frame.loc[mask, 'adj_factor'] = 11.1070
        audit.append(dict(
            ts_code='000998.SZ', start_date='2018-08-16', end_date='2018-08-27',
            action='replace_transient_vendor_adjustment_factor', source=LONGPING_SOURCE,
            reason=('The factor fell 2.6362% and then returned exactly to its prior value; '
                    'raw pre_close remained continuous and the dividend table contains no event.'),
            original_factor=10.8142, corrected_factor=11.1070,
            corrected_quote_dates=[date.strftime('%Y%m%d') for date in expected_dates]))
    return frame, audit


def correct_limit_code_aliases(frame):
    """Copy execution limits across an exchange-confirmed security-code change."""
    frame = frame.copy()
    cutoff = pd.Timestamp('2019-12-16')
    old = frame.ts_code.eq('000043.SZ') & frame.trade_date.lt(cutoff)
    if not old.any():
        return frame, []
    mapped = frame.loc[old].copy()
    mapped['ts_code'] = '001914.SZ'
    existing = set(frame[['trade_date', 'ts_code']].itertuples(index=False, name=None))
    collisions = set(mapped[['trade_date', 'ts_code']].itertuples(index=False, name=None)) & existing
    if collisions:
        raise ValueError('000043.SZ to 001914.SZ limit alias collides with existing rows; review required')
    audit = [dict(
        ts_code='001914.SZ', start_date=mapped.trade_date.min().strftime('%Y%m%d'),
        end_date=mapped.trade_date.max().strftime('%Y%m%d'),
        action='copy_pre_change_price_limits_from_000043.SZ', source=CMPO_SOURCE,
        reason=('SZSE confirms that 000043 changed to 001914 on 2019-12-16; '
                'the provider backfills daily prices under the new code but retains historical limits under the old code.'),
        corrected_rows=len(mapped))]
    return pd.concat([frame, mapped], ignore_index=True), audit
