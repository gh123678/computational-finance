"""Narrow, source-verified event corrections; never delete a security's history."""
import math
import pandas as pd

DEAO_SOURCE = 'https://static.cninfo.com.cn/finalpage/2020-09-19/1208460598.PDF'
LUTIANHUA_SOURCE = 'https://static.cninfo.com.cn/finalpage/2018-08-03/1205254635.PDF'
CHUANHUA_SOURCE = 'https://static.cninfo.com.cn/finalpage/2016-09-30/1202736702.PDF'
LONGPING_SOURCE = 'data/development_2018/{daily.csv,adj_factor.csv,dividend.csv}'
CMPO_SOURCE = 'https://www.szse.cn/disclosure/notice/general/t20191211_572534.html'
ZHONGJIAO_DESIGN_SOURCE = 'https://q.stock.sohu.com/cn/gg/2024/600720/58588651.shtml'
LINGLONG_2023_SOURCE = 'https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=10263255'
LINGLONG_2025Q1_SOURCE = 'https://www.linglong.cn/Upload/202606/20260617133932_6784.pdf'
WUXI_SOURCE = 'https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?stockid=603259&id=11108963'
SHUNFENG_SOURCE = 'https://paper.cnstock.com/html/2024-10/31/content_1988127.htm'
BAOFENG_SOURCE = 'https://stock.stockstar.com/notice/SN2024071700040373.shtml'
AOGU_SOURCE = 'http://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?stockid=000615&id=11866438'
HANMA_SOURCE = 'https://static.cninfo.com.cn/finalpage/2024-12-12/1221996706.PDF'
DONGYI_SOURCE = 'http://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?stockid=002713&id=11884801'
SANSHENG_SOURCE = 'https://paper.cnstock.com/html/2025-12/03/content_2153237.htm'


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
    shenhua = frame.ts_code.eq('601088.SH') & frame.ex_date.eq('20170710') & frame.div_proc.eq('实施')
    if shenhua.any():
        rows = frame.loc[shenhua]
        amounts = pd.to_numeric(rows.cash_div_tax, errors='raise')
        if (len(rows) != 2 or sorted(amounts.tolist()) != [2.51, 2.97] or
                not rows.record_date.eq('20170707').all() or
                not rows.pay_date.eq('20170710').all() or
                not pd.to_numeric(rows.stk_div).eq(0).all()):
            raise ValueError('Verified Shenhua dividend overlap no longer matches; review required')
        redundant = rows.index[amounts.eq(2.51)]
        excluded.loc[redundant] = True
        audit.append(dict(ts_code='601088.SH', ex_date='20170710',
                          action='exclude_special_dividend_already_in_total',
                          source='https://static.cninfo.com.cn/finalpage/2017-08-26/1203873127.PDF',
                          reason='Total 2.97 CNY includes ordinary 0.46 and special 2.51 CNY dividend.',
                          retained_cash_per_share=2.97, excluded_cash_per_share=2.51))
    shunfeng = frame.ts_code.eq('002352.SZ') & frame.ex_date.eq('20241107') & frame.div_proc.eq('实施')
    if shunfeng.any():
        rows = frame.loc[shunfeng]
        amounts = pd.to_numeric(rows.cash_div_tax, errors='raise')
        expected = {('20241011', '20241011', 1.0), ('20240630', '20240829', 0.4), ('20240630', '20241030', 1.4)}
        observed = {(r['end_date'], r['ann_date'], round(float(r['cash_div_tax']), 6)) for r in rows.to_dict('records')}
        if len(rows) != 3 or observed != expected:
            raise ValueError('Verified 002352.SZ combined payment no longer matches source rows; review required')
        component = rows.index[amounts.isin([1.0, 0.4])]
        excluded.loc[component] = True
        audit.append(dict(ts_code='002352.SZ', ex_date='20241107',
                          action='exclude_components_already_in_total',
                          source=SHUNFENG_SOURCE,
                          reason='Combined interim 0.4 and special 1.0 CNY are one 1.4 CNY/share payment; the 1.4 total row is retained.'),
                     )
    baofeng = frame.ts_code.eq('600989.SH') & frame.ex_date.eq('20240724') & frame.div_proc.eq('实施')
    if baofeng.any():
        rows = frame.loc[baofeng]
        amounts = pd.to_numeric(rows.cash_div_tax, errors='raise')
        if (len(rows) != 2 or not amounts.round(6).isin([0.3158, 0.265]).all() or
                not rows.record_date.eq('20240723').all() or not rows.pay_date.eq('20240724').all()):
            raise ValueError('Verified 600989.SH differentiated dividend no longer matches source rows; review required')
        major = rows.index[amounts.round(6).eq(0.265)]
        excluded.loc[major] = True
        audit.append(dict(ts_code='600989.SH', ex_date='20240724',
                          action='exclude_major_shareholder_dividend_leg',
                          source=BAOFENG_SOURCE,
                          reason='Differentiated dividend: minority holders receive 0.3158 CNY/share, major holders 0.2650; the research account is entitled to the minority rate.'),
                     )
    aogu = frame.ts_code.eq('000615.SZ') & frame.ex_date.eq('20251229') & frame.div_proc.eq('实施')
    if aogu.any():
        rows = frame.loc[aogu]
        ratios = pd.to_numeric(rows.stk_div, errors='raise')
        if (len(rows) != 2 or not ratios.round(6).isin([1.34278, 0.1]).all() or
                not rows.record_date.eq('20251226').all() or not rows.div_listdate.eq('20251229').all()):
            raise ValueError('Verified 000615.SZ restructuring capitalization no longer matches source rows; review required')
        estate = rows.index[ratios.round(6).eq(1.34278)]
        excluded.loc[estate] = True
        audit.append(dict(ts_code='000615.SZ', ex_date='20251229',
                          action='exclude_restructuring_shares_not_distributed',
                          source=AOGU_SOURCE,
                          reason='Restructuring capitalization: of 1.34278 shares per share, only 0.1 goes to existing shareholders; the rest goes to creditors and restructuring investors per the court-approved plan.'),
                     )
    for correction in [
        dict(code='600375.SH', ex='20241226', ratios=[1.45, 1.45], record='20241225',
             source=HANMA_SOURCE,
             reason='Restructuring capitalization shares are not distributed to existing shareholders; they go to restructuring investors and creditors per the court-approved plan.'),
        dict(code='002713.SZ', ex='20251230', ratios=[1.26775047, 1.26775047], record='20251229',
             source=DONGYI_SOURCE,
             reason='Restructuring capitalization shares are not distributed to existing shareholders; they go to restructuring investors and creditors per the court-approved plan.'),
        dict(code='002742.SZ', ex='20251210', ratios=[0.58356954, 0.58356954], record='20251209',
             source=SANSHENG_SOURCE,
             reason='Restructuring capitalization shares are not distributed to existing shareholders; they go to restructuring investors and creditors per the court-approved plan.'),
        dict(code='002309.SZ', ex='20241224', ratios=[2.45], record='20241223',
             source='https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?stockid=002309&id=10926625',
             reason='Restructuring capitalization shares are not distributed to existing shareholders; they go to restructuring investors and creditors per the court-approved plan.'),
    ]:
        mask = (frame.ts_code.eq(correction['code']) & frame.ex_date.eq(correction['ex']) &
                frame.div_proc.eq('实施'))
        if not mask.any():
            continue
        rows = frame.loc[mask]
        ratios = pd.to_numeric(rows.stk_div, errors='raise').round(8)
        if (len(rows) != len(correction['ratios']) or
                sorted(ratios.tolist()) != sorted(round(r, 8) for r in correction['ratios']) or
                not rows.record_date.eq(correction['record']).all()):
            raise ValueError(f"Verified {correction['code']} restructuring correction no longer matches source rows; review required")
        excluded.loc[rows.index] = True
        for row in rows.to_dict('records'):
            audit.append(dict(ts_code=row['ts_code'], ex_date=row['ex_date'],
                              action='exclude_non_shareholder_restructuring_capitalization',
                              source=correction['source'], reason=correction['reason'],
                              original={k: None if pd.isna(v) else v for k, v in row.items()}))
    combined = [
        dict(code='600720.SH', ex='20240613', record='20240612', pay='20240613', imp_ann='20240604',
             parts=[('20231231', '20240417', 0.257), ('20221231', '20240417', 0.1104), ('20221231', '20230322', 0.1104)],
             total=0.3674, source=ZHONGJIAO_DESIGN_SOURCE,
             reason='2022 and 2023 annual dividends were combined into one payment of 0.3674 CNY/share per the implementation announcement.'),
        dict(code='601966.SH', ex='20240614', record='20240613', pay='20240614', imp_ann='20240607',
             parts=[('20231231', '20240516', 0.286), ('20240331', '20240516', 0.091)],
             total=0.377, source=LINGLONG_2023_SOURCE,
             reason='2023 annual 0.286 and 2024 Q1 0.091 dividends were combined into one payment of 0.377 CNY/share.'),
        dict(code='601966.SH', ex='20250710', record='20250709', pay='20250710', imp_ann='20250516',
             parts=[('20241231', '20250516', 0.014), ('20250331', '20250516', 0.07)],
             total=0.084, source=LINGLONG_2025Q1_SOURCE,
             reason='2024 Q4 0.014 and 2025 Q1 0.07 dividends were combined into one payment of 0.084 CNY/share.'),
        dict(code='603259.SH', ex='20250521', record='20250520', pay='20250521', imp_ann='20250430',
             parts=[('20241231', '20250430', 0.98169), ('20241231', '20250318', 0.98169),
                    ('20250318', '20250430', 0.35), ('20250318', '20250318', 0.35)],
             total=1.33169, source=WUXI_SOURCE,
             reason='2024 annual 0.98169 and 2025 special 0.35 dividends were combined into one payment of 1.33169 CNY/share; each leg is duplicated by the vendor.'),
        dict(code='300760.SZ', ex='20250529', record='20250528', pay='20250529', imp_ann='20250520',
             parts=[('20241231', '20250520', 0.56), ('20250331', '20250520', 1.41)],
             total=1.97, source='https://q.stock.sohu.com/cn/300760/bw_5.shtml',
             reason='2024 annual 0.56 and 2025 first interim 1.41 dividends were combined into one payment of 1.97 CNY/share.'),
    ]
    merged_rows = []
    for spec in combined:
        mask = (frame.ts_code.eq(spec['code']) & frame.ex_date.eq(spec['ex']) & frame.div_proc.eq('实施'))
        if not mask.any():
            continue
        rows = frame.loc[mask]
        observed = {(r['end_date'], r['ann_date'], round(float(r['cash_div_tax']), 6)) for r in rows.to_dict('records')}
        expected = {(end, ann, round(cash, 6)) for end, ann, cash in spec['parts']}
        if observed != expected or not rows.record_date.eq(spec['record']).all() or not rows.pay_date.eq(spec['pay']).all():
            raise ValueError(f"Verified {spec['code']}/{spec['ex']} combined payment no longer matches source rows; review required")
        # Total = sum of distinct legs; duplicated legs (same end_date+ann_date+cash) count once.
        distinct = {round(cash, 6) for _, _, cash in spec['parts']}
        if not math.isclose(sum(distinct), spec['total']):
            raise ValueError(f"Verified {spec['code']}/{spec['ex']} combined total mismatch; review required")
        excluded.loc[rows.index] = True
        base = rows.iloc[0].to_dict()
        base.update(end_date=max(end for end, _, _ in spec['parts']), ann_date=max(ann for _, ann, _ in spec['parts']),
                    cash_div=f"{spec['total']:.6f}".rstrip('0').rstrip('.'), cash_div_tax=f"{spec['total']:.6f}".rstrip('0').rstrip('.'),
                    imp_ann_date=spec['imp_ann'])
        merged_rows.append(base)
        audit.append(dict(ts_code=spec['code'], ex_date=spec['ex'],
                          action='merge_same_day_payments_into_one_action',
                          source=spec['source'], reason=spec['reason'],
                          merged_cash_per_share=spec['total'], merged_parts=len(rows)))
    frame = pd.concat([frame.loc[~excluded], pd.DataFrame(merged_rows, columns=frame.columns)], ignore_index=True)
    return frame, audit


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
