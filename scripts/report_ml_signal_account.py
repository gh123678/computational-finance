"""Report read-only diagnosis; distinguish evidence from causal hypotheses."""
import json
import shutil
from pathlib import Path

import pandas as pd

from run_retention_development import ROOT,sha
from analyze_ml_signal_account import SOURCE,OUT


def main():
    verification=json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    assert verification['status']=='passed'
    assert sha(ROOT/'scripts/analyze_ml_signal_account.py')==verification['diagnostic_source_sha256']
    annual=pd.read_csv(OUT/'annual_account_pnl.csv')
    attribution=pd.read_csv(OUT/'asset_annual_pnl.csv')
    detail=pd.read_csv(OUT/'target_horizon_labels.csv')
    horizons=pd.read_csv(OUT/'annual_horizon_means.csv')
    episodes=pd.read_csv(OUT/'holding_presence_episodes.csv')
    benchmark=pd.read_csv(OUT/'benchmark_annual.csv')
    selected=attribution.loc[attribution.strategy.eq('ml_retention_0bp')&attribution.year.eq(2020)]
    worst=selected.nsmallest(10,'net_pnl')
    labels=detail.loc[detail.path.eq('ml_retention')&detail.year.eq(2020)]
    coverage=labels.groupby('ts_code').agg(target_weeks=('ts_code','size'),
        weekly_valid=('week_raw_price_return','count'),twenty_valid=('twenty_excess_label','count'))
    worst=worst.merge(coverage,on='ts_code',validate='one_to_one')
    worst.to_csv(OUT/'ml_2020_worst_ten_with_coverage.csv',index=False)
    matched=detail.loc[detail.path.eq('ml_retention')].dropna(subset=['week_excess_price_return','twenty_excess_label'])
    pairs=[]
    for year,g in matched.groupby('year'):
        means=g.groupby('signal_date')[['week_excess_price_return','twenty_excess_label']].mean()
        pairs.append(dict(year=int(year),matched_records=len(g),matched_signals=len(means),
            mean_weekly_excess=float(means.week_excess_price_return.mean()),
            mean_twenty_excess=float(means.twenty_excess_label.mean())))
    pairs=pd.DataFrame(pairs);pairs.to_csv(OUT/'matched_horizon_comparison.csv',index=False)
    closed=episodes.loc[episodes.strategy.eq('ml_retention_0bp')&~episodes.censored]
    year_loss=float(selected.net_pnl.sum());ten_loss=float(worst.net_pnl.sum())
    before_tail=labels.loc[labels.execution_date.lt('2020-12-01')]
    assert len(worst)==10 and year_loss<0
    lines=['# 预测排序与账户亏损：冻结实验后诊断','',
        '**结论：2020年亏损集中于部分持仓，20日标签与周调仓评价存在期限差异；缺失标签也遮蔽了部分亏损记录。**','',
        '本轮只读取已冻结2018—2020十二组结果及同版行情，不新增模型或组合，不扫描参数，不接入券商。'
        '逐股净盈亏可与实际账户逐日净值变化对上，因果贡献仍未分离。','',
        '## 账户层面确认的损失','',
        '| 年份 | ML零交易成本收益 | ML风险层零成本收益 | 沪深300价格指数收益 |','|---|---:|---:|---:|']
    for year in (2018,2019,2020):
        a=annual.loc[annual.strategy.eq('ml_retention_0bp')&annual.year.eq(year)].iloc[0]
        b=annual.loc[annual.strategy.eq('ml_risk_0bp')&annual.year.eq(year)].iloc[0]
        c=benchmark.loc[benchmark.year.eq(year)].iloc[0]
        lines.append(f'| {year} | {a.return_value:.2%} | {b.return_value:.2%} | {c.price_index_return:.2%} |')
    lines+=['','指数列按相邻年末原始收盘值计算，未含分红或可投资账户的费用，不是新增指数回测。'
        '2020年指数上涨27.21%，ML零成本却亏损25.66%，该年不能仅以“大盘下跌”或“手续费太高”解释。','',
        f'ML零成本2020年净亏损{abs(year_loss):,.2f}元，亏损最大的十只股票合计{abs(ten_loss):,.2f}元，'
        f'相当于年度净亏损余额的{ten_loss/year_loss:.2%}。其它股票有盈利抵消；该比例不是独立因果贡献。'
        f'全部亏损股票合计{abs(selected.loc[selected.net_pnl.lt(0)].net_pnl.sum()):,.2f}元，'
        f'盈利股票合计{selected.loc[selected.net_pnl.gt(0)].net_pnl.sum():,.2f}元。','',
        '| 股票代码 | 2020年净盈亏 | 当年目标周数 | 有效下一周标签 | 有效20日标签 |',
        '|---|---:|---:|---:|---:|']
    for r in worst.itertuples(index=False):
        lines.append(f'| {r.ts_code} | {r.net_pnl:,.2f}元 | {r.target_weeks} | {r.weekly_valid} | {r.twenty_valid} |')
    lines+=['','净盈亏包含实际成交、待结算股份及公司行动的账务影响；用年末仍持有资产估值计算未实现盈亏，未假设全部即时平仓。'
        '不根据当前公司名称回填历史ST状态，也不把亏损股票自动列成未来可用的黑名单。','',
        '## 20日目标与下一次周调仓的差异','',
        '只比较同一形成日、同一股票且两种标签均有效的记录。下一周从本次执行日开盘到下次计划执行日开盘；'
        '20日标签沿用冻结模型定义。每个截面先等权平均，再按截面平均，不能复合为可实现组合收益。','',
        '| 年份 | 配对记录 | 下一周平均毛价格超额收益 | 20日平均毛价格超额标签 |','|---|---:|---:|---:|']
    for r in pairs.itertuples(index=False):
        lines.append(f'| {r.year} | {r.matched_records} | {r.mean_weekly_excess:.3%} | {r.mean_twenty_excess:.3%} |')
    lines+=['',f'ML零成本账户共有{len(closed)}段已结束的连续日末持仓记录，中位长度{closed.sessions.median():.0f}个交易日，'
        f'平均{closed.sessions.mean():.2f}日，{closed.sessions.lt(20).mean():.2%}短于20日。'
        '仍持有至2020年末的记录为右删失，未纳入上述长度统计；同一记录内可能加减仓，不是FIFO交易的资金加权持有期。',
        '配对结果支持检查预测期限与实际调仓的匹配，但不能据此保证改成周标签会赚钱。'
        '尚未运行期限消融实验，也未改变已确认模型。','',
        '## 缺失标签影响了哪些评价','',
        f'2020年ML目标共有{len(labels)}条，20日有效{labels.twenty_excess_label.count()}条'
        f'（{labels.twenty_excess_label.notna().mean():.2%}）；12月之前仍有'
        f'{len(before_tail)-before_tail.twenty_excess_label.count()}/{len(before_tail)}条缺失，不能全归咎年末截断。',
        f'上述十只主要亏损股票的20日有效标签仅{int(worst.twenty_valid.sum())}/{int(worst.target_weeks.sum())}条。'
        '600122.SH、002447.SZ、603555.SH在当年所选目标中没有有效20日标签，却分别产生真实账户损失。',
        '因此，报告中的有效标签均值与RankIC没有覆盖这些对应记录。未来窗口缺报价、零成交或异常隔离等会使标签缺失；'
        '该缺失条件可能与风险有关，存在条件样本偏差的警讯，但本轮未证明其造成全部训练或交易亏损。',
        '未来标签有效性是在事后判断的，不能据此在当时剔除股票。不得填零收益或利用未来停牌信息构造“改善”策略。','',
        '## 为什么正RankIC不能代替盈利','',
        'Qlib的calc_ic按日期计算预测与标签的Spearman相关；源码另设多空收益评价，指标本身没有成交会计。'
        '参见[固定提交的官方评价源码](https://github.com/microsoft/qlib/blob/be725493eb1a6bbb42bf11b37aa7669f59610ff1/qlib/contrib/eva/alpha.py)。',
        f'数学上，每个截面减去同一个指数收益不改变股票排序。本轮{verification["rank_translation_checks"]}个有效截面在标签整体平移后RankIC一致。'
        '这说明正排序相关不能判定收益绝对为正、是否跑赢指数、最上端20只是否有效，也不能补上缺失标签。','',
        '## 验证方法与失败记录','',
        '每个账户日按股票重建：当日资产价值减前日资产价值，加卖出现金、减买入现金及费用，加除息净应收、减配股认购款。'
        '待结算股份计入资产；红利到账仅将应收转现金，不重复记收益。股票盈亏之和与每日日终权益变化对账，并核对全部年度与期末。',
        f'十二组全部通过，最大逐日误差{max(c["maximum_daily_pnl_error"] for c in verification["account_checks"]):.3g}元；'
        f'原{verification["source_artifacts_unchanged"]}项冻结输出指纹在分析前后均相同，原核心与输入清单也通过核对。'
        '源码、验证、逐股年度盈亏、持仓段、逐目标两种期限标签和配对表全部保存。',
        '首次窗口分析因原始交易日历倒序导致空窗口而中止，修正排序并校验窗口首尾后通过。'
        '随后复核发现基准指数同样未排序，按iloc取到的“年末”位置不正确；无效基准表、原程序和说明完整另存benchmark_order_failure，'
        '改为排序后保存并检查实际起止日期。两项只涉及本次诊断，原模型与账户结果未改。','',
        '## 下一步的研究方向','',
        '优先研究固定“下一次周执行开盘”标签与当前20日标签的对照，同时对缺失标签原因分组，明确可观察样本的局限。'
        '另一个可选方向是只审计这些主要亏损股票在当时可知的风险状态；这需要公告日期证据，不能由今天的ST名称倒推。'
        '继续更换复杂模型暂缺依据，因为当前模型已有正排序，而期限、覆盖与实际持仓尚未闭合。',
        '建议先做期限匹配和标签覆盖的设计，维持特征、模型参数、选择、风险、成本和账户规则作为控制变量。'
        '本轮没有运行该新候选；任何下一轮收益仍属于已查看历史上的探索验证，不能称为新封存或实盘结论。','']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    for p in [ROOT/'scripts/analyze_ml_signal_account.py',Path(__file__)]:shutil.copy2(p,OUT/p.name)
    evidence=ROOT/'output/ml_signal_account_diagnosis_20261006_initial_benchmark_order_failure/qlib_alpha_pinned.py.txt'
    shutil.copy2(evidence,OUT/evidence.name)
    hashes={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='output_sha256.json'}
    (OUT/'output_sha256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    print('Read-only diagnosis report saved; no new strategy executed')


if __name__=='__main__':
    main()
