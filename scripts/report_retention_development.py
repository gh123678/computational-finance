"""Report the fixed single-candidate experiment; never optimize its rules."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/retention_threshold_development_2016_2020_r1'
SOURCE=ROOT/'output/continuous_2016_2025_dividend_r1'


def main():
    verification=json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    flow=json.loads((OUT/'flow_reconstruction_audit.json').read_text(encoding='utf-8'))
    summary_hash=hashlib.sha256((OUT/'summary.json').read_bytes()).hexdigest()
    assert verification['status']==flow['status']=='passed'
    assert verification['summary_sha256']==flow['summary_sha256']==summary_hash
    stats=pd.read_csv(OUT/'comparison.csv').set_index('strategy')
    names={'combined':'原周频','combined_biweekly':'原双周加缓冲',
           'combined_zero_cost':'原周频零成本','combined_biweekly_zero_cost':'原双周零成本',
           'combined_retention_gap05_cap5':'新保留规则10bp',
           'combined_retention_gap05_cap5_zero_cost':'新保留规则零成本',
           'combined_retention_gap05_cap5_slip30':'新保留规则30bp'}
    base=stats.loc['combined_retention_gap05_cap5'];weekly=stats.loc['combined'];bw=stats.loc['combined_biweekly']
    reductions=1-base.gross_turnover/weekly.gross_turnover
    transitions=pd.read_csv(OUT/'target_transitions.csv')
    counts=transitions.loc[transitions.previous_count.gt(0)]
    annual=pd.read_csv(OUT/'annual_returns.csv').pivot(index='year',columns='strategy',values='return_value')
    lines=['# 持仓保留与换股门槛：固定开发期实验','',
           '**结论：机械降换手有效，事前研究门槛未全部通过。** 原规则、费用和账户核心未修改；没有运行2021—2025候选，也没有扫描参数。','',
           f'开发期2016—2020一次投入100万元，连续跨年。新规则10bp累计收益{base.total_return:.2%}，最大回撤{base.max_drawdown:.2%}，'
           f'期末{base.final_equity:,.2f}元；相比原双周净收益提高{(base.total_return-bw.total_return)*100:.2f}个百分点，但仍亏损。'
           f'累计双边换手较原周频下降{reductions:.2%}，目标股票平均保留{verification["mean_target_retention"]:.2%}。','',
           '## 同一起点的连续账户比较','',
           '| 方案 | 五年累计收益 | 最大回撤 | 累计双边换手倍数 | 交易成本 |',
           '|---|---:|---:|---:|---:|']
    for label in ['combined','combined_biweekly','combined_retention_gap05_cap5',
                  'combined_retention_gap05_cap5_zero_cost','combined_retention_gap05_cap5_slip30',
                  'combined_zero_cost','combined_biweekly_zero_cost']:
        r=stats.loc[label]
        lines.append(f'| {names[label]} | {r.total_return:.2%} | {r.max_drawdown:.2%} | {r.gross_turnover:.2f} | {r.total_fees+r.total_slippage:,.2f}元 |')
    lines += ['','成本含实际模型手续费与滑点，价格按分向不利方向取整。累计成本不能直接加回期末权益成为可执行毛收益。'
              '零成本情景使用相同目标，但资金、整手及拒单路径不同。实际行业比例可因涨跌及拒单偏离目标上限，不能把目标行业约束当成逐日持仓保证。','',
              '## 事前门槛','',
              '| 条件 | 结果 |','|---|---|']
    labels={'turnover_halved':'换手不高于原周频50%',
            'net_positive_and_beats_biweekly':'基准净收益为正且超过原双周',
            'drawdown_not_above_biweekly':'基准回撤不高于原双周',
            'slip30_net_positive':'30bp情景净收益为正'}
    for key,name in labels.items():
        lines.append(f'| {name} | {"通过" if verification["gates"][key] else "未通过"} |')
    lines += ['','门槛未修改、未豁免。技术核验通过与研究绩效通过是两个不同结论。','',
              '## 连续年度收益','',
              '| 年份 | 原周频 | 原双周 | 新规则10bp | 新规则零成本 | 新规则30bp |',
              '|---|---:|---:|---:|---:|---:|']
    order=['combined','combined_biweekly','combined_retention_gap05_cap5','combined_retention_gap05_cap5_zero_cost','combined_retention_gap05_cap5_slip30']
    for year,row in annual.iterrows():
        lines.append(f'| {year} | '+' | '.join(f'{row[label]:.2%}' for label in order)+' |')
    lines += ['','新规则2018年10bp仍亏损33.98%，零成本仍亏损28.99%。本轮只改变选择与保留规则，没有提供市场回撤控制机制。','',
              '## 选择机制实际运行','',
              f'255个形成日的旧周频目标重建一致。除首次建仓外，{len(counts)}次调仓全部主动替换5对，'
              f'共{verification["active_replacements"]}对；另有{verification["forced_exits"]}次不合格或行业约束强制退出。'
              f'包含必需补位的单周新目标最多{int(counts.changed_count.max())}只，因此5只是主动替换上限。'
              '替换上限每周都达到，说明这一候选中上限持续约束选择；没有做消融实验，不能分别量化0.05门槛与5只上限的贡献。','',
              '保持的是上期目标而非实际成交持仓。三个成本情景目标文件完全一致，实际成交与资金路径不同；股价变动引起的等权微调仍执行。','',
              f'新规则基准情景有{int(base.stale_valuation_days)}个评价日含沿用旧报价估值，实际行业权重超过目标上限的日数为'
              f'{int(base.industry_breach_days)}；平均实际持仓{base.average_positions:.2f}只。'
              '目标退出遇停牌或拒单时，实际旧持仓可能继续存在。账务重建通过不代表这些持仓能按当天价格立即卖出。','',
              '## 技术核验与失败证据','',
              '全部95项测试通过（含7项新选择规则测试）。三个情景均完成；每组1218个评价交易日，含预热1262日。'
              '逐日净值恒等式、现金非负、目标因子及行业约束、60个月复合收益、费用摘要与同一目标序列核验通过。'
              '独立重建共3786个账户日及12个跨年边界，现金最大误差小于1e-6元，股数与待结算股数每日精确一致；原核心源码指纹逐字不变。','',
              '初次完整测试中5项依赖临时目录的测试因系统默认pytest临时目录访问受限而报错，88项通过；'
              '改用独立工作区临时目录后全量通过，未改业务规则。首次Git保存因.git写权限受限失败，授权执行后设计提交成功。'
              '生成独立账务核验适配器的首个终端命令因引号转义产生语法错误，未写出程序；改用文件工具创建适配器后通过。'
              '以上日志或说明保留；三组实验本身无失败。','',
              '## 范围与后续依据','',
              '2016—2025已经全部查看，方案又由十年诊断启发，开发期实验不能重建样本外独立性。'
              '历史ST/行业版本、未闭合复权事件、日线成交近似、固定20%红利税与退市零回收等限制沿用。'
              '候选没有达到全部门槛，不进入实盘，也不运行剩余年份或临时改门槛。'
              '下一轮若另行立项，应先研究价格回撤与收益来源，明确成本和持有收益的取舍，而不把本轮参数视为最优解。','',
              '![连续账户曲线](continuous_nav.png)','']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    fig,ax=plt.subplots(figsize=(10,5))
    for label,text in [('combined','Original weekly'),('combined_biweekly','Original biweekly'),
                       ('combined_retention_gap05_cap5','Retention 10bp'),
                       ('combined_retention_gap05_cap5_zero_cost','Retention zero cost'),
                       ('combined_retention_gap05_cap5_slip30','Retention 30bp')]:
        folder=SOURCE/label if label in ('combined','combined_biweekly') else OUT/label
        nav=pd.read_csv(folder/'nav.csv',parse_dates=['date'])
        nav=nav.loc[nav.date.between(pd.Timestamp('20151231'),pd.Timestamp('20201231'))]
        ax.plot(nav.date,nav.equity/1000000,label=text,linewidth=1.3)
    ax.set(title='2016-2020 continuous account: fixed retention experiment',ylabel='Equity / initial capital')
    ax.axhline(1,color='grey',linewidth=.7,linestyle='--');ax.grid(alpha=.2)
    ax.legend(fontsize=8);fig.tight_layout();fig.savefig(OUT/'continuous_nav.png',dpi=160);plt.close(fig)
    fingerprints={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name!='output_sha256.json'}
    (OUT/'output_sha256.json').write_text(json.dumps(fingerprints,indent=2),encoding='utf-8')
    print('Report and plot saved; research gates did not all pass')


if __name__=='__main__':
    main()
