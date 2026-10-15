"""Render the completed, independently verified single-expression study.

No market acquisition, model fitting, factor calculation or account simulation
is performed here. A failed research gate is a reportable research result.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/alphaforge_case_2018_2020_r1'
DOC = ROOT / 'docs/2026-10-15-alphaforge-case-results.md'
PRIMARY = 'case_negative_retention_common200'
CONTROL = 'three_retention_case_common200'
PATHS = (PRIMARY, CONTROL)
FACTORS = ('case_factor', 'case_signal', 'three_score')
NAMES = {'case_factor': '原公式 f', 'case_signal': '固定负方向 −f',
         'three_score': '同池旧三因子'}
GATES = {
    'net_positive_10and30': '主候选10bp和30bp三年累计净收益均大于0',
    'beats_same_pool_control': '主候选10bp累计收益严格高于同池对照10bp',
    'drawdown_at_most_25pct': '主候选10bp最大回撤不超过25%',
    'two_positive_return_years': '主候选10bp至少两年正收益',
    'rankIC_positive': '固定负方向全期平均RankIC大于0',
    'two_positive_rankIC_years': '固定负方向至少两年平均RankIC大于0',
}


def read_json(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def percent(value):
    return f'{float(value):.2%}' if pd.notna(value) and np.isfinite(float(value)) else '—'


def number(value, decimals=4):
    return f'{float(value):,.{decimals}f}' if pd.notna(value) and np.isfinite(float(value)) else '—'


def path_name(strategy):
    path, cost = strategy.rsplit('_', 1)
    if path not in PATHS or cost not in ('0bp', '10bp', '30bp'):
        raise ValueError('Unknown fixed account: ' + strategy)
    return ('主候选 −f' if path == PRIMARY else '同池旧三因子') + ' / ' + cost


def require_columns(frame, columns, name):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(name + ' missing columns: ' + ', '.join(sorted(missing)))


def main():
    # Verification is mandatory even if all account CSVs happen to exist.
    verification = read_json('verification.json')
    if verification['status'] != 'passed' or verification['engineering_verification_passed'] is not True:
        raise RuntimeError('Independent engineering verification has not passed')
    summary = read_json('summary.json')
    digest = hashlib.sha256((OUT / 'summary.json').read_bytes()).hexdigest()
    if digest != verification['summary_sha256']:
        raise RuntimeError('Account summary changed after verification')
    expected = {f'{path}_{cost}bp' for path in PATHS for cost in (0, 10, 30)}
    statuses = summary['experiment_statuses']
    experiments = summary['experiments']
    if (len(statuses) != 6 or {s['strategy'] for s in statuses} != expected or
            not all(s['status'] == 'completed' for s in statuses) or
            len(experiments) != 6 or {e['strategy'] for e in experiments} != expected):
        raise RuntimeError('Exactly six fixed completed accounts are required')
    accounts = verification['accounts']
    if len(accounts) != 6 or {a['strategy'] for a in accounts} != expected:
        raise RuntimeError('Independent verification does not cover all six accounts')
    if verification['year_boundaries'] != 12 or verification['broker_connected'] is not False:
        raise RuntimeError('Unexpected account boundary or brokerage state')
    if verification['future_label_used_for_formation'] is not False:
        raise RuntimeError('Formation used future labels')
    gates = verification['gates']
    if set(gates) != set(GATES) or not all(isinstance(v, bool) for v in gates.values()):
        raise ValueError('Expected the six predeclared Boolean research gates')
    passed = all(gates.values())
    if passed != verification['research_gates_passed']:
        raise ValueError('Research gate aggregate disagrees with individual gates')

    ic = pd.read_csv(OUT / 'factor_ic_summary.csv')
    groups = pd.read_csv(OUT / 'factor_groups.csv')
    feature = read_json('feature_summary.json')
    precision = pd.read_csv(OUT / 'float_precision_audit.csv')
    operations = pd.read_csv(OUT / 'account_operations.csv').set_index('strategy', verify_integrity=True)
    annual = pd.read_csv(OUT / 'annual_returns.csv')
    require_columns(ic, ['factor', 'period', 'ic_n', 'ic_mean', 'ic_ir',
                         'rank_ic_n', 'rank_ic_mean', 'rank_ic_ir', 'annualized', 'std_ddof'], 'IC summary')
    require_columns(groups, ['factor', 'year', 'group', 'n_formed', 'n', 'mean_forward_return'], 'Groups')
    require_columns(precision, ['absolute_difference', 'guard64', 'guard32'], 'Precision audit')
    require_columns(operations, ['formal_sessions', 'annualized_half_turnover_prior_equity',
                                'total_fees_cny', 'total_slippage_cny', 'rejected_count',
                                'average_cash_weight', 'maximum_actual_positions'], 'Operations')
    require_columns(annual, ['strategy', 'year', 'return_value'], 'Annual returns')
    if set(operations.index) != expected:
        raise ValueError('Operations must cover exactly six fixed accounts')
    if (len(annual) != 18 or annual.duplicated(['strategy', 'year']).any() or
            set(annual.strategy) != expected or
            any(set(g.year) != {2018, 2019, 2020} for _, g in annual.groupby('strategy'))):
        raise ValueError('Expected all three annual returns for each of six accounts')
    if ic.duplicated(['factor', 'period']).any():
        raise ValueError('Duplicate IC summary')
    for factor in FACTORS:
        if set(ic.loc[ic.factor.eq(factor), 'period'].astype(str)) != {'all', '2018', '2019', '2020'}:
            raise ValueError('Missing all-period or annual IC summary for ' + factor)
    if precision.empty or not np.isfinite(precision.absolute_difference).all():
        raise ValueError('Missing finite float-precision evidence')

    figures = [('factor_ic.png', '逐期与累计IC／RankIC；累计相关系数不是净值'),
               ('factor_groups.png', '固定五组的未来周度平均超额收益与年度分层'),
               ('factor_coverage.png', '形成样本、标签覆盖、因子分布与排除原因'),
               ('account_performance.png', '六个真实股份账户的净值、回撤与实际成本')]
    for filename, _ in figures:
        file = OUT / 'figures' / filename
        if not file.is_file() or not file.stat().st_size:
            raise FileNotFoundError('Required actual figure is missing: ' + str(file))

    stats = {e['strategy']: e for e in experiments}
    ordered = [f'{path}_{cost}bp' for path in PATHS for cost in (0, 10, 30)]
    primary = stats[PRIMARY + '_10bp']
    conclusion = ('工程核验通过；预登记的历史策略关卡全部通过。该结果只构成回顾性历史候选，尚不能实盘启用。'
                  if passed else
                  '工程核验通过；预登记的历史策略关卡未全部通过。本次完成单公式复现与本地适配检验，策略资格判失败，不启用实盘。')
    lines = ['# AlphaForge公开因子案例：复现与周频账户结果', '', conclusion, '',
             f"主候选10bp在{primary['start']}至{primary['end']}的三年窗口累计净收益为"
             f"**{percent(primary['total_return'])}**，年化收益{percent(primary['annualized_return'])}，"
             f"最大回撤{percent(primary['max_drawdown'])}。累计收益与年化收益是不同指标；本报告不把论文收益当成本地成绩。", '',
             f"报告生成时刻：{datetime.now().astimezone().isoformat(timespec='seconds')}。"
             '数据及实验设计固定于2026-10-15；生成报告不重新计算因子或运行账户。', '',
             '## 预登记关卡', '', '| 关卡 | 结果 |', '|---|---|']
    for key, label in GATES.items():
        lines.append(f"| {label} | {'通过' if gates[key] else '未通过'} |")
    lines += ['', '工程正确性与策略有效性分别判断。失败后不翻转方向、不扫描窗口、不提升对照为主候选，'
              '不打开2021—2025年救援；本轮没有券商连接。', '',
              '## 来源、数学定义与适配边界', '',
              '来源为[AlphaForge作者预印本v5](https://arxiv.org/abs/2406.18394v5)第6页表2第5号表达式，'
              '正式发表记录见[AAAI 2025论文页](https://ojs.aaai.org/index.php/AAAI/article/view/33365)。'
              '作者源码对照固定提交`d0cfc27df23c60f271bc885fd43027b86b787746`，本地独立实现公开数学定义，未执行整套作者框架。', '',
              '`f = S_log1p(ts_min(ts_corr(close, volume, 10), 1))`。', '',
              '令10个观测的去均值价格、成交量分别为x、y，A=Σx²、B=Σy²、N=Σxy：', '',
              '- `rho = N / (1 if A < 1e-6 or B < 1e-6 else sqrt(A*B))`。',
              '- `f = sign(rho) * log1p(abs(rho))`；长度1的滚动最小值在完整有限输入下不改变当前值。',
              '- 本轮交易信号预先固定为`−f`，再以形成日平均同分百分位作为score。', '',
              '统计的是收盘价水平与成交量水平的10日相关，既不是收益率与量增长率相关，也不能直接解释为主动资金流。'
              '负方向检验价量背离假说，是本轮独立改编；论文某一天的负组合权重不是永久交易规则。', '',
              '本地输入使用冻结且修正后的原始收盘价（元）、Tushare原始vol乘100（股）。窗口含形成日及之前9个开市日，'
              '完整10日有效且不填充缺口；任意精确的adj_factor变化使含两种因子水平的窗口失效，变化移出窗口后恢复。'
              '基础common200已要求历史资格、流动性与过去200日报价，价格、量、额及调整因子有限且为正，继承更长未知事件隔离。'
              '这是本地字段映射，不能声称与作者Qlib调整价、量缩放分支相同。', '',
              '作者完整方法还包括因子挖掘与动态组合，原市场、标签和持仓不同；本轮没有复现该整篇训练流程或原文业绩，'
              '也未运行付费模型。单案例工程复现完成不自动证明经济有效。', '',
              '## 样本、时点与数值核验', '',
              f"旧common200形成记录{feature['original_rows']:,}条；本轮同池有效记录{feature['common_rows']:,}条，"
              f"覆盖{feature['schedule_rows']:,}个周度形成期，每期最少{feature['minimum_formed']:,}只。"
              '资格与分组均在形成日确定，未来D标签缺失不剔除形成资格。', '',
              '| 形成状态 | 记录数 |', '|---|---:|']
    for reason, count in sorted(feature['reasons'].items()):
        lines.append(f'| {reason} | {count:,} |')
    guard_count = int(feature['guard_rows'])
    guard_differences = int((precision.guard64.astype(str).str.lower() != precision.guard32.astype(str).str.lower()).sum())
    lines += ['', f'小方差guard分支实际出现{guard_count:,}条有效形成记录；常量形成值0保留为并列。'
              'guard分支下rho可能超出±1，因此没有裁剪或强行约束f在±log(2)内。', '',
              f"每只股票固定选择首个有效窗口进行float64／float32对照，共{len(precision):,}个窗口；"
              f"最大因子绝对差{number(precision.absolute_difference.max(), 12)}，"
              f"平均绝对差{number(precision.absolute_difference.mean(), 12)}，guard分支差异{guard_differences:,}个。"
              '本地计算使用float64，作者数据加载使用torch.float；这不是全样本位级一致性认证。', '',
              f"独立标量重算核对{verification['feature_rows_checked']:,}条形成候选，最大因子误差"
              f"{number(verification['maximum_factor_error'], 12)}。未来信息未用于形成资格；"
              '新增单元测试另检验缺行、常量、微方差、单位、调整变化与未来扰动不改变过去。', '',
              '## IC、RankIC与标签覆盖', '',
              'D标签为下一周首日复权开盘至再下一周首日复权开盘的个股收益，减去同期基准收益；'
              '这是未扣成本的诊断性超额收益。IC为截面Pearson相关，RankIC为平均同分排名后的Spearman相关。'
              '每期不足10个有效标签或因子／标签截面常量时留空。IR=逐期均值／样本标准差（ddof=1），不年化；'
              '单观测或标准差为0时留空。下表覆盖率是该期间有效标签记录数除以形成记录数。', '',
              '| 因子 | 执行年 | 有效IC期数 | IC均值 | ICIR | RankIC均值 | RankICIR | 标签覆盖 |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    for factor in FACTORS:
        for period in ('all', '2018', '2019', '2020'):
            row = ic.loc[ic.factor.eq(factor) & ic.period.astype(str).eq(period)].iloc[0]
            subset = groups.loc[groups.factor.eq(factor)]
            if period != 'all':
                subset = subset.loc[subset.year.eq(int(period))]
            formed = int(subset.n_formed.sum())
            coverage = float(subset.n.sum()) / formed if formed else np.nan
            lines.append(f"| {NAMES[factor]} | {'全期' if period == 'all' else period} | {int(row.ic_n)} | "
                         f"{number(row.ic_mean)} | {number(row.ic_ir)} | {number(row.rank_ic_mean)} | "
                         f"{number(row.rank_ic_ir)} | {percent(coverage)} |")
    lines += ['', '## 固定五组的平均超额收益', '',
              '按照形成日因子平均同分百分位乘5后向上取整；先分组再连接标签。'
              '允许并列导致不等组或空组；每组不足2个有效标签时均值留空。'
              '下表是各期组内未来周度超额收益均值的等权平均，既不是三年累计收益，也不是可交易净值。'
              '第五组减第一组仅为分层差诊断，不代表本项目允许卖空。', '',
              '| 因子 | 组1低 | 组2 | 组3 | 组4 | 组5高 | 同期组5−组1均值 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for factor in FACTORS:
        selected = groups.loc[groups.factor.eq(factor)]
        means = selected.groupby('group').mean_forward_return.mean().reindex(range(1, 6))
        pivot = selected.pivot(index='signal_date', columns='group', values='mean_forward_return')
        spread = (pivot[5] - pivot[1]).mean()
        lines.append('| ' + NAMES[factor] + ' | ' + ' | '.join(percent(v) for v in means) + ' | ' + percent(spread) + ' |')
    lines += ['', '## 六个真实股份账户', '',
              '100万元一次投入、A股主板多头、周频；周末最后交易日形成，下一周首日开盘执行，跨年不断账。'
              '目标最多20只、单股4.9%、每行业最多5只、现金底线2%、容量0.5%；'
              '留仓替换分差严格大于0.05且每周最多5只主动替换，完整权重提交仍可能产生resize交易。'
              '保留整手、T+1、停牌、涨跌停、退市、分红配股及应收约束。拒卖可能使实际持股数超过目标上限。', '',
              '0bp沿原配置关闭交易费用及滑点；10／30bp沿原历史费用口径并加对应滑点。'
              '这不是对2026现行费率的承诺。费用和滑点已计入账户净值，表格列示用于归因，不再次扣除。'
              '年化收益按实际交易日数、每年252日换算。', '',
              '| 账户 | 三年累计净收益 | 年化净收益 | 最大回撤 | 费用（元） | 滑点（元） | 年化半换手（倍） |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for label in ordered:
        row, op = stats[label], operations.loc[label]
        lines.append(f"| {path_name(label)} | {percent(row['total_return'])} | {percent(row['annualized_return'])} | "
                     f"{percent(row['max_drawdown'])} | {number(op.total_fees_cny, 2)} | {number(op.total_slippage_cny, 2)} | "
                     f"{number(op.annualized_half_turnover_prior_equity, 2)} |")
    lines += ['', '半换手定义为Σ[(买入成交额+卖出成交额)/(2×前交易日权益)]×252/N；'
              'N包含全部正式开市日，初始建仓计入。它与引擎以当日开盘权益为分母的gross_turnover不同，不混用。', '',
              '| 账户 | 2018 | 2019 | 2020 | 拒单数 | 平均现金权重 | 实际最多持股数 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for label in ordered:
        yearly = annual.loc[annual.strategy.eq(label)].set_index('year').return_value
        op = operations.loc[label]
        lines.append(f"| {path_name(label)} | {percent(yearly.loc[2018])} | {percent(yearly.loc[2019])} | "
                     f"{percent(yearly.loc[2020])} | {int(op.rejected_count):,} | {percent(op.average_cash_weight)} | "
                     f"{int(op.maximum_actual_positions)} |")
    total_sessions = sum(a['sessions'] for a in accounts)
    maximum_cash = max(a['maximum_cash_error'] for a in accounts)
    maximum_receivable = max(a['maximum_receivable_error'] for a in accounts)
    maximum_equity = max(a['maximum_equity_error'] for a in accounts)
    lines += ['', '## 独立账务与旧证据保护', '',
              f'六个账户合计逐日重建{total_sessions:,}个账本日，包含空仓基准准备期；'
              f"正式研究各账户开市日数为{', '.join(str(int(operations.loc[s, 'formal_sessions'])) for s in ordered)}。"
              '六账户的普通股份、待到账股份逐日精确匹配；现金、应收和权益成分独立核对。'
              f'现金最大误差{number(maximum_cash, 10)}元、应收最大误差{number(maximum_receivable, 10)}元、'
              f'权益成分最大误差{number(maximum_equity, 10)}元；共核验12个2018→2019／2019→2020跨年边界。', '',
              '| 受保护旧输出 | 通过哈希核验的文件数 |', '|---|---:|']
    for name, count in sorted(verification['old_artifacts'].items()):
        lines.append(f'| {name} | {int(count):,} |')
    lines += ['', '旧数据、旧结果、源码快照及实际失败日志保留；工程修复不改策略参数。'
              '本轮已见2016—2025历史，2018—2020检验属于回顾性研究，不能恢复为未见样本外。'
              '即使历史关卡全部通过，也仍需要冻结后的独立前向模拟。未接券商，不构成实盘启用结论。', '',
              '## 实际结果图', '']
    for filename, caption in figures:
        lines += [f'![{caption}]({(OUT / "figures" / filename).as_posix()})', '', caption + '。', '']
    lines += ['## 复现入口与证据', '',
              f'- [冻结设计]({(ROOT / "docs/superpowers/specs/2026-10-15-alphaforge-case-design.md").as_posix()})',
              f'- [来源筛选与差异说明]({(ROOT / "docs/2026-10-15-paper-reproduction-selection.md").as_posix()})',
              f'- [独立核验结果]({(OUT / "verification.json").as_posix()})',
              f'- [账户摘要]({(OUT / "summary.json").as_posix()})',
              f'- [年度收益]({(OUT / "annual_returns.csv").as_posix()})',
              f'- [交易与换手]({(OUT / "account_operations.csv").as_posix()})',
              f'- [形成覆盖]({(OUT / "feature_coverage.csv").as_posix()})',
              f'- [float64／float32对照]({(OUT / "float_precision_audit.csv").as_posix()})', '',
              '执行入口为`scripts/run_alphaforge_case.py`（准备及账户）、`scripts/verify_alphaforge_case.py`（只读独立核验）'
              '和本报告生成器。已有协议拒绝覆盖研究运行；查看现有证据不需要重复启动账户。', '']
    text = '\n'.join(lines)
    (OUT / 'report.md').write_text(text, encoding='utf-8')
    DOC.write_text(text, encoding='utf-8')
    print(str(OUT / 'report.md'))
    print(str(DOC))


if __name__ == '__main__':
    main()
