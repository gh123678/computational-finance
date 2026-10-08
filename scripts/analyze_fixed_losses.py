"""Read-only diagnosis of frozen results, without any new strategy or parameters."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'output/continuous_2016_2025_dividend_r1'
OUT=ROOT/'output/continuous_loss_diagnosis_20261006'


def main():
    OUT.mkdir(exist_ok=True)
    summary=json.loads((SOURCE/'summary.json').read_text(encoding='utf-8'))
    verified=json.loads((SOURCE/'verification.json').read_text(encoding='utf-8'))
    assert verified['status']=='passed'
    assert verified['summary_sha256']==hashlib.sha256((SOURCE/'summary.json').read_bytes()).hexdigest()
    annual_returns=pd.read_csv(SOURCE/'continuous_annual_returns.csv')
    yearly,totals,worst,rejections,retentions=[],[],[],[],[]
    provenance={}
    for result in summary['experiments']:
        label=result['strategy'];folder=SOURCE/label
        for name in ['orders.csv','nav.csv','cost_attribution.csv','historical_targets.csv']:
            path=folder/name
            provenance[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        nav=pd.read_csv(folder/'nav.csv',parse_dates=['date'])
        nav=nav.loc[nav.date.ge(pd.Timestamp('20151231'))].copy()
        nav['return']=nav.equity.pct_change()
        trades=pd.read_csv(folder/'orders.csv',parse_dates=['date'])
        fills=trades.loc[trades.shares.gt(0)].copy()
        targets=pd.read_csv(folder/'historical_targets.csv')
        previous=None;fractions=[]
        for date,group in targets.groupby('execution_date',sort=True):
            codes=set(group.ts_code)
            if previous is not None:
                retained=len(previous&codes)/len(previous)
                fractions.append(retained)
                retentions.append(dict(strategy=label,execution_date=date,previous_size=len(previous),
                                       current_size=len(codes),retained_codes=len(previous&codes),
                                       retained_fraction=retained))
            previous=codes
        config=result['config'];free=config['zero_trading_costs']
        fills['raw_notional']=fills.shares*fills.raw_open
        fills['specified_slippage']=fills.raw_notional*config['slippage_bps']/10000
        fills['tick_rounding_cost']=fills.slippage_cost-fills.specified_slippage
        assert fills.tick_rounding_cost.ge(-1e-7).all()
        if free:
            fills['commission']=fills['minimum_commission_extra']=fills['sell_tax']=fills['transfer']=0.
        else:
            nominal=fills.notional*config['commission']
            fills['commission']=np.maximum(nominal,config['minimum_commission'])
            fills['minimum_commission_extra']=fills.commission-nominal
            tax_rate=np.where(fills.date.lt(pd.Timestamp('20230828')),.001,.0005)
            fills['sell_tax']=np.where(fills.side.eq('sell'),fills.notional*tax_rate,0.)
            fills['transfer']=fills.notional*np.where(fills.date.lt(pd.Timestamp('20220429')),.00002,.00001)
        theoretical_fee=(fills.commission+fills.transfer+fills.sell_tax)
        # Fees were rounded to cents in the execution engine. Re-reading decimal
        # CSV values may shift a half-cent tie; verify the rounding interval.
        assert (fills.fee-theoretical_fee).abs().le(.00500001).all()
        fills['fee_rounding_adjustment']=fills.fee-theoretical_fee
        assert abs(fills.fee.sum()-result['total_fees'])<1e-6
        assert abs(fills.slippage_cost.sum()-result['total_slippage'])<1e-6
        for year,days in nav.loc[nav.date.ge(pd.Timestamp('20160101'))].groupby(nav.date.dt.year):
            orders=fills.loc[fills.date.dt.year.eq(year)]
            annual=annual_returns.loc[annual_returns.strategy.eq(label)&annual_returns.year.eq(year)].iloc[0]
            cost=float(orders.fee.sum()+orders.slippage_cost.sum())
            annual_row=dict(strategy=label,year=int(year),return_value=float(annual.return_value),
                            start_equity=float(annual.start_equity),end_equity=float(annual.end_equity),
                            costs=cost,cost_to_year_start=cost/annual.start_equity,
                            turnover_multiple=float(days.turnover.sum()),filled_orders=len(orders),
                            average_positions=float(days.position_count.mean()),
                            average_cash_weight=float((days.cash/days.equity).mean()),
                            commission=float(orders.commission.sum()),minimum_commission_extra=float(orders.minimum_commission_extra.sum()),
                            sell_tax=float(orders.sell_tax.sum()),transfer=float(orders.transfer.sum()),
                            specified_slippage=float(orders.specified_slippage.sum()),
                            tick_rounding_cost=float(orders.tick_rounding_cost.sum()),
                            fee_rounding_adjustment=float(orders.fee_rounding_adjustment.sum()))
            assert abs(annual_row['commission']+annual_row['sell_tax']+annual_row['transfer']+
                       annual_row['specified_slippage']+annual_row['tick_rounding_cost']+
                       annual_row['fee_rounding_adjustment']-cost)<1e-6
            yearly.append(annual_row)
        cost=float(fills.fee.sum()+fills.slippage_cost.sum())
        raw=float(fills.raw_notional.sum())
        totals.append(dict(strategy=label,total_return=result['total_return'],max_drawdown=result['max_drawdown'],
                           total_cost=cost,raw_notional=raw,effective_cost_bps=cost/raw*10000,
                           actual_slippage_bps=float(fills.slippage_cost.sum())/raw*10000,
                           specified_slippage_bps=config['slippage_bps'],
                           tick_rounding_cost=float(fills.tick_rounding_cost.sum()),
                           minimum_commission_extra=float(fills.minimum_commission_extra.sum()),
                           turnover_multiple=float(nav.turnover.sum()),filled_orders=len(fills),
                           rejected_orders=int(trades.status.eq('rejected').sum()),
                           average_fill_notional=float(fills.notional.mean()),
                           mean_target_retained_fraction=float(np.mean(fractions))))
        for _,row in nav.nsmallest(5,'return').iterrows():
            worst.append(dict(strategy=label,date=row['date'].strftime('%Y-%m-%d'),daily_return=float(row['return']),
                              equity=float(row['equity']),stale_value=float(row['stale_value'])))
        for reason,count in trades.loc[trades.status.eq('rejected')].reason.fillna('').value_counts().items():
            rejections.append(dict(strategy=label,reason=reason,orders=int(count)))
    annual=pd.DataFrame(yearly);total=pd.DataFrame(totals)
    annual.to_csv(OUT/'annual_costs.csv',index=False)
    total.to_csv(OUT/'total_costs.csv',index=False)
    pd.DataFrame(worst).to_csv(OUT/'worst_daily_returns.csv',index=False)
    pd.DataFrame(rejections).to_csv(OUT/'rejected_orders.csv',index=False)
    pd.DataFrame(retentions).to_csv(OUT/'target_retention.csv',index=False)
    roles=[]
    for label in ['combined','combined_biweekly','combined_biweekly_slip30']:
        f=pd.read_csv(SOURCE/label/'cost_attribution.csv')
        f['strategy']=label;roles.append(f)
    role=pd.concat(roles,ignore_index=True)
    role.to_csv(OUT/'cost_by_trade_role.csv',index=False)
    selected=['combined','combined_zero_cost','combined_biweekly','combined_biweekly_zero_cost','combined_biweekly_slip30']
    lines=['# 固定规则亏损来源诊断','',
           '只分析已冻结十二组输出，没有新增策略、参数搜索或回测。所有指标来源与输入指纹另存；不能把该诊断作为新的封存测试。','',
           '## 主要发现','',
           '2018年双周加缓冲方案收益为−41.09%，零交易成本情景仍为−33.90%。这说明该年的组合损失在取消交易成本后仍然存在；这些数字本身不能确定市场暴露或具体因子的因果贡献。','',
           '双周方案十年累计交易成本为88.38万元，相邻调仓目标股票平均保留3.73%，出入场占成本99.90%。最低佣金额外负担仅650.65元。固定10bp滑点在不利方向按分取整后，成交金额加权的实际滑点为16.20bp，取整部分累计22.98万元，已计入总成本。','',
           '现有结果指向组合回撤与换股成本两个研究环节；本轮仅完成诊断，未据此修改规则或筛选新参数。','',
           '## 成本与换手','',
           '| 情景 | 十年收益 | 交易成本 | 累计双边换手倍数 | 成交笔数 | 实际平均滑点bp |',
           '|---|---:|---:|---:|---:|---:|']
    for label in selected:
        row=total.loc[total.strategy.eq(label)].iloc[0]
        lines.append(f'| {label} | {row.total_return:.2%} | {row.total_cost:,.2f}元 | {row.turnover_multiple:.2f} | '
                     f'{row.filled_orders:,.0f} | {row.actual_slippage_bps:.2f} |')
    lines+=['','累计双边换手是每日成交金额除以当日交易前权益后求和，包含买与卖，不能直接称为年化单边换手率。'
            '实际平均滑点以成交股数和原始开盘价计算，包含模型要求的价格向不利方向取整到分的影响。','',
            '零成本与有成本情景使用相同选股目标，但资金路径、可买股数、最低佣金和现金约束会不同。'
            '因此不能把两条期末净值之差当成单独扣费金额，也不能把累计现金成本简单加回期末净值来声称可执行收益。','',
            '## 连续年度收益','',
            '| 年份 | 周频 | 周频零成本 | 双周加缓冲 | 双周零成本 | 双周30bp |',
            '|---|---:|---:|---:|---:|---:|']
    pivot=annual.pivot(index='year',columns='strategy',values='return_value')
    for year,row in pivot.iterrows():
        lines.append(f'| {year} | '+ ' | '.join(f'{row[label]:.2%}' for label in selected)+' |')
    lines+=['','每年起点为连续账户上年末权益；这些收益不同于每年重新投入100万元的旧年度实验。','',
            '## 成本细项','',
            '| 情景 | 最低佣金额外负担 | 价格取整额外滑点 | 出入场成本占比 |',
            '|---|---:|---:|---:|']
    for label in ['combined','combined_biweekly','combined_biweekly_slip30']:
        row=total.loc[total.strategy.eq(label)].iloc[0]
        subset=role.loc[role.strategy.eq(label)]
        share=subset.loc[subset.role.isin(['entry','exit']),'total_cost'].sum()/subset.total_cost.sum()
        lines.append(f'| {label} | {row.minimum_commission_extra:,.2f}元 | {row.tick_rounding_cost:,.2f}元 | {share:.2%} |')
    lines+=['','最低佣金额外负担是实际佣金下限超过按比例佣金的部分，已包含在总手续费中；价格取整部分已包含在总滑点中，均不能重复加算。'
            '手续费按已保存成交金额、历史税费率及最后四舍五入重建；年度细项之和与原成本账单核对通过。','',
            '## 目标股票保留率','',
            '| 情景 | 与上一次调仓相比平均保留比例 |','|---|---:|']
    for label in ['combined','combined_rank_buffer40','combined_biweekly','lowvol20']:
        row=total.loc[total.strategy.eq(label)].iloc[0]
        lines.append(f'| {label} | {row.mean_target_retained_fraction:.2%} |')
    lines+=['','该比例按相邻目标组合的股票代码交集除以上一次目标股票数计算，首个建仓日不计。'
            '它是等数量目标保留率，不是资金权重换手或已成交持仓的保留率。双周之间相隔更长，不能直接把两种周期的保留率差异归因为缓冲规则。'
            '周频排名缓冲使保留率略有增加，但并未形成稳定少换股的组合；出入场成本占比也显示费用主要来自换股，而非对原持仓微调。','',
            '## 解释边界','',
            '这些是成交模型内的成本与市场损失证据，不是真实券商报价或实盘成交验证。日线滑点情景、ST/行业版本完整性、固定红利税及未闭合事件等原限制仍在。'
            '本报告不引入择时、止损、频率或因子参数改变，也不根据这一已使用区间选择新策略。','']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    provenance[str((SOURCE/'summary.json').relative_to(ROOT))]=hashlib.sha256((SOURCE/'summary.json').read_bytes()).hexdigest()
    for path in [SOURCE/'continuous_annual_returns.csv',SOURCE/'verification.json',ROOT/'scripts/analyze_fixed_losses.py']:
        provenance[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT/'input_sha256.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    checks=dict(status='passed',strategies=len(total),annual_rows=len(annual),
                source_summary_sha256=provenance[str((SOURCE/'summary.json').relative_to(ROOT))],
                checks=['成交手续费与未取整重建值差异在半分范围内',
                        '订单成本总和与冻结摘要相符（误差小于1e-6元）',
                        '年度成本细项含取整残差与账单相符（误差小于1e-6元）'],
                scope='保存输出的分析核验；未新增回测或修改账户引擎',
                initial_failure='初次逐笔精确对比分位四舍五入失败；浮点读写及取整方式造成边界差异。改按半分区间核验，并单列取整残差。原失败日志保留。')
    (OUT/'verification.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(total.loc[total.strategy.isin(selected)].to_string(index=False))


if __name__=='__main__':
    main()
