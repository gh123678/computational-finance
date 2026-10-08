"""Explain one-data-record revision; do not require or optimize improved returns."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'output/continuous_2016_2025'
NEW=ROOT/'output/continuous_2016_2025_dividend_r1'
EVENT=pd.Timestamp('2025-06-09')


def first_date(frame,column):
    return None if frame.empty else pd.to_datetime(frame[column]).min().strftime('%Y-%m-%d')


def main():
    a,b=(json.loads((folder/'summary.json').read_text(encoding='utf-8')) for folder in (OLD,NEW))
    verification=json.loads((NEW/'verification.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256((NEW/'summary.json').read_bytes()).hexdigest()
    assert verification['status']=='passed' and verification['summary_sha256']==digest
    assert len(a['experiments'])==len(b['experiments'])==12
    assert a['metadata_sha256']==b['metadata_sha256']
    differences=[key for key,value in a['source_sha256'].items() if value!=b['source_sha256'][key]]
    assert set(differences)=={'continuous.py','datasets.py'}
    for key,value in a['data_manifest']['files_sha256'].items():
        if key!='dividend.csv':
            assert value==b['data_manifest']['files_sha256'][key]
    before=pd.read_csv(OLD/'unexplained_adjustments.csv',dtype={'trade_date':str})
    after=pd.read_csv(NEW/'unexplained_adjustments.csv',dtype={'trade_date':str})
    expected=before.loc[~(before.ts_code.eq('001323.SZ')&before.trade_date.eq('2025-06-09'))]
    pd.testing.assert_frame_equal(expected.reset_index(drop=True),after.reset_index(drop=True))
    factor_changes=[]
    columns=['ts_code','trade_date','momentum20','reversal5','lowvol20','adv20_cny']
    left=pd.read_csv(OLD/'factors.csv',usecols=columns,chunksize=100000)
    right=pd.read_csv(NEW/'factors.csv',usecols=columns,chunksize=100000)
    import itertools
    for x,y in itertools.zip_longest(left,right):
        assert x is not None and y is not None and x.shape==y.shape
        pd.testing.assert_frame_equal(x[['ts_code','trade_date']],y[['ts_code','trade_date']])
        pd.testing.assert_series_equal(x.adv20_cny,y.adv20_cny)
        mask=pd.Series(False,index=x.index)
        for col in ['momentum20','reversal5','lowvol20']:
            mask |= ~((x[col]==y[col]) | (x[col].isna()&y[col].isna()))
        changed=y.loc[mask]
        assert changed.ts_code.eq('001323.SZ').all()
        assert x.loc[mask,['momentum20','reversal5','lowvol20']].isna().all().all()
        factor_changes.extend(changed.to_dict('records'))
    assert len(factor_changes)==a['quarantined_factor_rows']-b['quarantined_factor_rows']
    comparisons=[]
    for old in a['experiments']:
        label=old['strategy'];new=next(e for e in b['experiments'] if e['strategy']==label)
        assert old['config']==new['config']
        x=pd.read_csv(OLD/label/'historical_targets.csv',parse_dates=['signal_date','execution_date'])
        y=pd.read_csv(NEW/label/'historical_targets.csv',parse_dates=['signal_date','execution_date'])
        pd.testing.assert_frame_equal(x.loc[x.signal_date<EVENT].reset_index(drop=True),
                                     y.loc[y.signal_date<EVENT].reset_index(drop=True))
        keys=['signal_date','execution_date','ts_code']
        assert not x.duplicated(keys).any() and not y.duplicated(keys).any()
        joined=x[keys+['target_weight']].merge(y[keys+['target_weight']],on=keys,how='outer',suffixes=('_old','_new'),indicator=True)
        plan_changes=joined.loc[joined['_merge'].ne('both') | joined.target_weight_old.ne(joined.target_weight_new)]
        scored=x[keys+['score']].merge(y[keys+['score']],on=keys,how='inner',suffixes=('_old','_new'),validate='one_to_one')
        score_changes=scored.loc[~np.isclose(scored.score_old,scored.score_new,rtol=0,atol=1e-12)]
        ox=pd.read_csv(OLD/label/'orders.csv',parse_dates=['date'])
        oy=pd.read_csv(NEW/label/'orders.csv',parse_dates=['date'])
        pd.testing.assert_frame_equal(ox.loc[ox.date<EVENT].reset_index(drop=True),oy.loc[oy.date<EVENT].reset_index(drop=True))
        order_keys=['date','ts_code','side']
        assert not ox.duplicated(order_keys).any() and not oy.duplicated(order_keys).any()
        oj=ox.merge(oy,on=order_keys,how='outer',suffixes=('_old','_new'),indicator=True)
        changed=oj['_merge'].ne('both')
        for col in ['requested','shares','price','fee','status','reason']:
            aa,bb=oj[col+'_old'],oj[col+'_new']
            changed |= ~((aa==bb)|(aa.isna()&bb.isna()))
        order_changes=oj.loc[changed]
        nx=pd.read_csv(OLD/label/'nav.csv',parse_dates=['date'])
        ny=pd.read_csv(NEW/label/'nav.csv',parse_dates=['date'])
        assert nx.date.equals(ny.date)
        delta=(ny.equity-nx.equity).abs()
        nav_changes=ny.loc[delta>1e-6]
        assert (delta.loc[ny.date<EVENT]<1e-6).all()
        h=pd.read_csv(NEW/label/'holdings.csv',parse_dates=['date'])
        held=h.loc[h.date.eq(pd.Timestamp('20250606')) & h.ts_code.eq('001323.SZ')]
        assert held.empty or (held.shares.eq(0)&held.pending_shares.eq(0)).all()
        events=pd.read_csv(NEW/label/'corporate_events.csv',parse_dates=['date'])
        event=events.loc[events.code.eq('001323.SZ')&events.date.eq(EVENT)]
        assert event.empty, 'No holder entitlement on this event; investigate any cash payment'
        comparisons.append(dict(strategy=label,old_return=old['total_return'],new_return=new['total_return'],
                                old_drawdown=old['max_drawdown'],new_drawdown=new['max_drawdown'],
                                terminal_equity_difference=new['final_equity']-old['final_equity'],
                                first_target_membership_or_weight_change=first_date(plan_changes,'execution_date'),
                                changed_target_rows=len(plan_changes),first_order_change=first_date(order_changes,'date'),
                                changed_selected_score_rows=len(score_changes),
                                first_selected_score_change=first_date(score_changes,'signal_date'),
                                changed_order_rows=len(order_changes),first_nav_change=first_date(nav_changes,'date'),
                                maximum_nav_difference=float(delta.max())))
    result=dict(status='passed',summary_sha256=digest,core_changes=differences,
                remaining_unexplained=len(after),factor_rows_restored=factor_changes,
                comparisons=comparisons,scope='Only issuer-verified dividend; fixed parameters; no new holdout')
    (NEW/'revision_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 公告分红修订r1与旧连续账户对照','',
           '只新增001323.SZ 2025-06-09每股含税现金1元分红，其它原始表字节一致，十二组配置一致。'
           '原源码及输出保留；源码仅变更窗口注册与入口，账本、因子、交易执行和费用源码未改。','',
           f'未解释观测{len(before)}→{len(after)}，隔离股票日{a["quarantined_factor_rows"]}→{b["quarantined_factor_rows"]}。'
           f'恢复{len(factor_changes)}个股票日的价格因子，其它股票因子及全部流动性因子逐值一致。','',
           '所有组登记日均未持有，因此该分红没有直接现金入账；解除这一已解释事件的因子隔离仍可能改变后续截面排序。'
           '其它异常继续隔离。','',
           '| 实验 | 旧总收益 | 新总收益 | 期末权益差额 | 首次目标构成/权重差异 | 首次交易差异 |','|---|---:|---:|---:|---|---|']
    for row in comparisons:
        lines.append(f'| {row["strategy"]} | {row["old_return"]:.4%} | {row["new_return"]:.4%} | '
                     f'{row["terminal_equity_difference"]:,.2f}元 | {row["first_target_membership_or_weight_change"] or "无"} | {row["first_order_change"] or "无"} |')
    score_count=sum(r['changed_selected_score_rows'] for r in comparisons)
    first_scores=[r['first_selected_score_change'] for r in comparisons if r['first_selected_score_change']]
    if score_count:
        lines += ['',f'实测从{min(first_scores)}起，共{score_count}条已选股票截面得分发生变化。'
                  '这不等于选股构成或成交变化；上表和逐笔比较分别检验后两者。']
    lines+=['','目标构成比较只检查证券与权重，不把截面得分数值改变混同为证券变化；交易比较包含请求股数、成交股数、价格、费用、拒单状态和原因。'
            '净值差异阈值1e-6元，用于排除浮点加总差异。原事件前的目标、交易及净值一致性已检查。','',
            '已选股票的截面得分变化亦单列在revision_comparison.json；得分改变而构成不变时不能写成所有因子和排序完全不变。','',
            '这是已使用数据的公告纠错影响验证，不是新的封存测试，不据收益改变参数。首次小窗口数值守卫根因、历史ST及行业版本完整性等原限制仍保留。','']
    (NEW/'revision_comparison.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(comparisons,ensure_ascii=False))


if __name__=='__main__':
    main()
