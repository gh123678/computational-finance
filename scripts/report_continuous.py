"""Report observed continuous outcomes including failed pre-registered groups."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def main(small=False,revision=False):
    if small and revision:
        raise ValueError('Revision uses full study')
    name='continuous_2016_2025_dividend_r1' if revision else 'continuous_2016_2025'
    out=ROOT/'output'/('continuous_2016_2017_check' if small else name)
    summary_path=out/'summary.json'
    summary=json.loads(summary_path.read_text(encoding='utf-8'))
    verification=json.loads((out/'verification.json').read_text(encoding='utf-8'))
    assert verification['summary_sha256']==hashlib.sha256(summary_path.read_bytes()).hexdigest()
    observed={e['strategy']:e for e in summary['experiments']}
    lines=['# 跨年连续账户固定规则研究','',
           '每组实验各自只投入一次 100 万元，跨年保留现金、股数和未到账权益；12 组是独立策略情景，不能相加。'
           '数据已经查看过，属于工程与账户连续性验证，不是新的封存测试。','',
           f"区间：2016-01-01 至 {summary['until'] or '2025-12-31'}；预热从 2015-11-01 开始。"
           '不在年末清仓或重新充值；双周相位从统一预热窗口起算。','',
           '| 实验 | 状态 | 总收益 | 期末净值 | 最大回撤 | 费用及滑点 |','|---|---|---:|---:|---:|---:|']
    for status in summary['experiment_statuses']:
        label=status['strategy']
        if label in observed:
            e=observed[label]
            lines.append(f"| {label} | 完成并核验 | {e['total_return']:.2%} | {e['final_equity']:,.2f} 元 | "
                         f"{e['max_drawdown']:.2%} | {e['total_fees']+e['total_slippage']:,.2f} 元 |")
        else:
            lines.append(f"| {label} | {status['status']} | — | — | — | — |")
    lines+=['','## 完整性与失败记录','',
            f"核验状态：{verification['status']}；已核验完成组 {len(verification['checks'])}/12。"
            '失败组不生成伪完整收益，也不因结果好坏删除。','']
    reproduction_path=out/'reproduction_comparison.json'
    if reproduction_path.exists():
        reproduction=json.loads(reproduction_path.read_text(encoding='utf-8'))
        assert reproduction['status']=='passed'
        assert reproduction['summary_sha256']==verification['summary_sha256']
        lines += ['独立进程重复执行同一冻结矩阵，12 组的目标、订单、持仓、公司行动、净值、月收益与成本表共 84 项比较通过。'
                  '持仓按日期与股票唯一键对齐；其余表保留原始行次序。'
                  f"最大金额差异 {reproduction['maximum_absolute_difference']:.12g} 元，属于浮点加总差异；不宣称文件字节全部相同。"
                  + ('首轮数据文件与源码相同，但清单分红行数写错；更正清单后重新冻结运行。首轮输出及旧清单保留于 '
                   '../continuous_2016_2025_dividend_r1_initial_metadata。' if revision else
                   '首轮完整输出保留于 ../continuous_2016_2025_first_complete。'),'']
    flow_path=out/'flow_reconstruction_audit.json'
    if flow_path.exists():
        flow=json.loads(flow_path.read_text(encoding='utf-8'))
        assert flow['status']=='passed' and flow['summary_sha256']==verification['summary_sha256']
        lines += ['从保存的订单及公司行动日志独立重建现金、应收款、已上市股数与待上市股数，'
                  '十二组每个交易日均与账本相符；108个跨年边界通过，未发现追加资金或年末账户重置。'
                  '见[逐日重建核验](flow_reconstruction_audit.json)及[跨年边界明细](year_boundary_audit.csv)。'
                  '实际样本的年末待结算权益为零，所以权益跨年结算行为的证据来自专门测试，不能把它说成已在实际年末事件中发生。','']
    for s in summary['experiment_statuses']:
        if s['status']!='completed':
            lines.append(f"- {s['strategy']}：{s.get('error','未完成')}。原始错误见该实验的 failure.txt。")
    if verification['status']=='passed':
        lines+=['12 组均完成。逐日净值、非负现金和股数、因子输入时间、注册调仓日期、费用账单、月收益复合均已核验。','']
    lines+=['## 连续年度收益','',
            '下表每年起点为同一账户的上年末净值，不是独立年度重置资金。全部实验明细见 continuous_annual_returns.csv。','',
            '| 年份 | 周频组合 | 双周加缓冲 | 双周 30bp |','|---|---:|---:|---:|']
    annual=pd.read_csv(out/'continuous_annual_returns.csv')
    pivot=annual.pivot(index='year',columns='strategy',values='return_value') if not annual.empty else pd.DataFrame()
    for year,row in pivot.iterrows():
        cells=[f"{row[label]:.2%}" if label in row and pd.notna(row[label]) else '—'
               for label in ['combined','combined_biweekly','combined_biweekly_slip30']]
        lines.append(f"| {year} | {' | '.join(cells)} |")
    lines+=['','## 净值轨迹','']
    if observed:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans']
        fig,ax=plt.subplots(figsize=(11,5))
        shown={'combined':'周频组合','combined_biweekly':'双周加缓冲','combined_biweekly_slip30':'双周 30bp'}
        for label,title in shown.items():
            if label in observed:
                nav=pd.read_csv(out/label/'nav.csv',parse_dates=['date']).set_index('date')
                nav=nav.loc[nav.index>=pd.Timestamp('2015-12-31')]
                ax.plot(nav.index,nav.equity/1000000,label=title)
        benchmark=pd.read_csv(ROOT/'data'/name/'benchmark.csv',parse_dates=['trade_date'])
        benchmark=benchmark.sort_values('trade_date').set_index('trade_date')
        end=pd.Timestamp(summary['until'] or '20251231')
        benchmark=benchmark.loc[(benchmark.index>=pd.Timestamp('2015-12-31'))&(benchmark.index<=end)]
        if not benchmark.empty:
            ax.plot(benchmark.index,benchmark.close/benchmark.close.iloc[0],label='沪深300价格指数',color='grey',alpha=.7)
        ax.set_ylabel('起始净值 = 1');ax.grid(alpha=.2);ax.legend();fig.tight_layout()
        fig.savefig(out/'continuous_nav.png',dpi=160);plt.close(fig)
        lines+=['![连续净值](continuous_nav.png)','']
    lines+=['## 证据边界','',
            f"未解释复权观测 {summary['unexplained_adjustments']} 条，隔离股票日 {summary['quarantined_factor_rows']}；"
            f"涨跌停字段缺口 {summary['missing_price_limit_rows']} 条。未知变化影响持仓时仍会中止。",'',
            '发生在股票首次可观察报价之前的事件单独保留在 unowned_prequote_actions.csv；初始全现金账户无法持有该时点权益。'
            '这不代表这些原始事件条款已经被修复或全部获得公告证明。','',
            '小窗口首轮数值守卫中止原因尚未闭合，旧冻结和失败记录保留；后续运行仍使用严格数值守卫和坏行归档，不能把未复现等同原因已修复。','',
            '历史 ST 完整性、行业当时可得版本、日线成交近似、固定红利税、配股扣款时点、退市零回收仍是证据或研究情景限制。'
            '期末应收及待上市权益保留，不假定2026年结算或成交。完成账务核验不等于满足实盘条件。','']
    if not small and not revision and (ROOT/'output/continuous_event_audit_20261005/events.csv').exists():
        events=pd.read_csv(ROOT/'output/continuous_event_audit_20261005/events.csv')
        assert len(events)==summary['unexplained_adjustments']
        assert events.held_experiments.eq(0).all()
        lines += ['十三项观测前一个账户交易日，各组均未持有相关股或待上市股份；隔离仍可能影响后续选股。'
                  '已定位001323.SZ于2025-06-09的分红输入缺口：发行人公告确认每股含税现金1元，原始表缺少该日期。'
                  '本轮保存公告证据，未修改冻结数据或结果。见[剩余事件核对](../continuous_event_audit_20261005/report.md)。','']
    if revision:
        lines+=['本版本只补充001323.SZ于2025-06-09每股含税现金1元的公告分红；其它原始表及固定参数不变。'
                '除息参考价扣减0.9833939元与实际现金权益1元不同，账本交易前使用已观察的开盘价，未扩展参考估值模型。'
                '旧冻结数据、源码和结果保留。原始接口仍缺该分红，公告更正只限此事件，不能推广为数据接口已补齐。'
                '见[新旧版本影响比较](revision_comparison.md)。','']
    (out/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Continuous report saved:',out/'report.md')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--small',action='store_true')
    p.add_argument('--revision',action='store_true')
    args=p.parse_args()
    main(args.small,args.revision)
