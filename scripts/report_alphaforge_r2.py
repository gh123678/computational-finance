"""Report only completed, independently verified AlphaForge r2 results.

No acquisition, factor calculation, account simulation or strategy selection
occurs here. Optional figures use already saved diagnostics and account NAV.
The default report is separate from every frozen r1 artifact.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/alphaforge_case_2018_2020_r2'
R1 = ROOT / 'output/alphaforge_case_2018_2020_r1'
DOC = ROOT / 'docs/2026-10-16-alphaforge-r2-results.md'
PRIMARY = 'case_negative_retention_common200'
CONTROL = 'three_retention_case_common200'
PATHS = (PRIMARY, CONTROL)
FACTORS = ('case_factor', 'case_signal', 'three_score')
FACTOR_NAMES = {'case_factor': '原公式 f', 'case_signal': '固定负方向 −f', 'three_score': '同池旧三因子'}
GATES = {
    'net_positive_10and30': '主10bp与30bp累计净收益均严格大于0',
    'beats_same_pool_control': '主10bp累计净收益严格超过同池对照10bp',
    'drawdown_at_most_25pct': '主10bp最大回撤不超过25%',
    'two_positive_return_years': '主10bp至少两年净收益严格为正',
    'rankIC_positive': '固定负信号全期平均RankIC严格为正',
    'two_positive_rankIC_years': '固定负信号至少两年平均RankIC严格为正',
}
FIGURES = [('factor_ic.png', '逐期及累计IC／RankIC，累计相关系数不是净值'),
           ('factor_groups.png', '固定五组的未扣费未来周度超额收益'),
           ('factor_coverage.png', '形成样本、标签覆盖、因子分布及排除原因'),
           ('account_performance.png', '六个真实股份账户净值、回撤与实际成本')]


def load(out, name):
    return json.loads((out / name).read_text(encoding='utf-8'))


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def percent(value):
    return f'{float(value):.2%}' if pd.notna(value) and np.isfinite(float(value)) else '—'


def number(value, decimals=4):
    return f'{float(value):,.{decimals}f}' if pd.notna(value) and np.isfinite(float(value)) else '—'


def boolean(value):
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if str(value).lower() not in ('true', 'false', '1', '0'):
        raise ValueError('Missing or invalid saved Boolean')
    return str(value).lower() in ('true', '1')


def columns(frame, required, name):
    missing = set(required) - set(frame)
    if missing:
        raise ValueError(name + ' missing columns: ' + ', '.join(sorted(missing)))


def account_name(strategy):
    path, cost = strategy.rsplit('_', 1)
    if path not in PATHS or cost not in ('0bp', '10bp', '30bp'):
        raise ValueError('Unexpected fixed account: ' + strategy)
    return ('主候选 −f' if path == PRIMARY else '同池三因子') + ' / ' + cost


def cell(value):
    return str(value).replace('|', '&#124;').replace('\n', ' ')


def main(out=OUT, render_figures=False):
    out = Path(out)
    resolved, original = out.resolve(), R1.resolve()
    if resolved == original or original in resolved.parents:
        raise ValueError('The report must not write into the frozen r1 directory')
    verification = load(out, 'verification.json')
    if (verification['status'] != 'passed' or verification['engineering_verification_passed'] is not True
            or verification['engineering_preparation_verified'] is not True):
        raise RuntimeError('Independent r2 preparation and account engineering checks must pass first')
    if (verification['broker_connected'] is not False or verification['r1_modified'] is not False
            or verification['future_label_used_for_formation'] is not False
            or verification['unknown_event_timing_does_not_change_eligibility'] is not True
            or verification['adjustment_factor_change_alone_does_not_exclude'] is not True):
        raise RuntimeError('Unexpected r2 scope or time-policy state')
    if verification['formation_dates'] != 154 or verification['year_boundaries'] != 12:
        raise ValueError('Expected exactly 154 formation dates and 12 account year boundaries')
    summary = load(out, 'summary.json')
    if sha(out / 'summary.json') != verification['summary_sha256']:
        raise RuntimeError('Summary changed after independent verification')
    expected = {f'{path}_{cost}bp' for path in PATHS for cost in (0, 10, 30)}
    statuses, experiments = summary['experiment_statuses'], summary['experiments']
    if (len(statuses) != 6 or {s['strategy'] for s in statuses} != expected or
            not all(s['status'] == 'completed' for s in statuses) or len(experiments) != 6 or
            {s['strategy'] for s in experiments} != expected):
        raise RuntimeError('Exactly six fixed completed accounts are required')
    if len(verification['accounts']) != 6 or {a['strategy'] for a in verification['accounts']} != expected:
        raise ValueError('Independent audit must cover all six accounts')
    gates = verification['gates']
    if set(gates) != set(GATES) or any(not isinstance(value, bool) for value in gates.values()):
        raise ValueError('Expected the unchanged six Boolean research gates')
    passed = all(gates.values())
    if passed != verification['research_gates_passed']:
        raise ValueError('Research gate aggregate disagrees with individual gates')

    feature = load(out, 'feature_summary.json')
    event_mapping = load(out, 'event_mapping_summary.json')
    event_audit = verification['event_timing']
    pool = verification['pool_comparison']
    if feature['schedule_rows'] != 154 or feature['minimum_formed'] < 200:
        raise RuntimeError('Full coverage gate was not completed')
    if event_audit['original_version_identity_certified'] or event_audit['intraday_publication_time_certified']:
        raise ValueError('This study cannot certify original versions or intraday announcement times')
    ic = pd.read_csv(out / 'factor_ic_summary.csv', dtype={'period': str})
    groups = pd.read_csv(out / 'factor_groups.csv')
    operations = pd.read_csv(out / 'account_operations.csv').set_index('strategy', verify_integrity=True)
    annual = pd.read_csv(out / 'annual_returns.csv')
    precision = pd.read_csv(out / 'float_precision_audit.csv')
    coverage = pd.read_csv(out / 'feature_coverage.csv', usecols=['trade_date', 'event_timing_unverified_count'],
                           parse_dates=['trade_date'])
    events = pd.read_csv(out / 'events.csv', usecols=['code', 'event_date', 'known_date', 'timing_verified', 'kind', 'timing_reason'],
                         parse_dates=['event_date', 'known_date'])
    columns(ic, ['factor', 'period', 'ic_n', 'ic_mean', 'ic_ir', 'rank_ic_mean', 'rank_ic_ir', 'annualized', 'std_ddof'], 'IC summary')
    columns(groups, ['signal_date', 'factor', 'year', 'group', 'n_formed', 'n', 'mean_forward_return'], 'Groups')
    columns(operations, ['formal_sessions', 'annualized_half_turnover_prior_equity', 'total_fees_cny',
                         'total_slippage_cny', 'rejected_count', 'rejected_reasons_json', 'average_cash_weight',
                         'maximum_actual_positions'], 'Operations')
    columns(annual, ['strategy', 'year', 'return_value'], 'Annual returns')
    columns(precision, ['absolute_difference', 'guard64', 'guard32'], 'Float precision')
    if set(operations.index) != expected or len(annual) != 18 or annual.duplicated(['strategy', 'year']).any():
        raise ValueError('Missing or duplicate account operations or yearly results')
    if set(annual.strategy) != expected or any(set(frame.year) != {2018, 2019, 2020} for _, frame in annual.groupby('strategy')):
        raise ValueError('Each fixed account needs 2018, 2019 and 2020 results')
    if ic.duplicated(['factor', 'period']).any():
        raise ValueError('Duplicate IC summary')
    for factor in FACTORS:
        if set(ic.loc[ic.factor.eq(factor), 'period']) != {'all', '2018', '2019', '2020'}:
            raise ValueError('Missing all-period/yearly diagnostics: ' + factor)
    if not ic.annualized.map(boolean).eq(False).all() or not ic.std_ddof.eq(1).all():
        raise ValueError('IR must use nonannualized sample standard deviation')
    if precision.empty or not np.isfinite(precision.absolute_difference).all():
        raise ValueError('Missing finite precision evidence')
    verified_flags = events.timing_verified.map(boolean)
    if len(events) != event_audit['event_rows'] or int(verified_flags.sum()) != event_audit['timing_verified_rows']:
        raise ValueError('Event count disagrees with independent audit')
    if event_mapping['rows'] != len(events):
        raise ValueError('Event mapping count disagrees with event ledger')
    if render_figures:
        from alphaforge_case_diagnostics import render_figures as render_saved_figures
        render_saved_figures(out)
    for filename, _ in FIGURES:
        path = out / 'figures' / filename
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError('Actual saved-result figure is required: ' + str(path))

    stats = {item['strategy']: item for item in experiments}
    ordered = [f'{path}_{cost}bp' for path in PATHS for cost in (0, 10, 30)]
    primary = stats[PRIMARY + '_10bp']
    conclusion = ('工程核验通过；六项预登记历史策略关卡全部通过。该结果仍只是回顾性历史候选，尚不能启用实盘。'
                  if passed else '工程核验通过；预登记历史策略关卡未全部通过，策略资格判失败，不启用实盘。')
    lines = ['# AlphaForge r2：单公式复现与周频适配结果', '', conclusion, '',
             f"主候选10bp累计净收益**{percent(primary['total_return'])}**，年化净收益{percent(primary['annualized_return'])}，"
             f"最大回撤{percent(primary['max_drawdown'])}；评价结束于{primary['end']}。累计和年化收益分别列示。", '',
             '本轮保留2018—2020、154期、同池两路径及0／10／30bp六账户，仅修订形成窗口的原价参考／行动隔离政策。'
             'r1因覆盖失败而停止，没有r1 IC或六账户业绩；下文只比较形成资格与共同有效公式，不虚构新旧收益比较。', '',
             '报告生成：' + datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds') + '。报告只读取已完成真实结果。', '',
             '## 预登记关卡', '', '| 关卡 | 结论 |', '|---|---|']
    for name, description in GATES.items():
        lines.append(f"| {description} | {'通过' if gates[name] else '未通过'} |")
    lines += ['', '工程通过与策略资格分开。失败不翻号、不扫描窗口、不提升对照为主候选、不打开2021—2025年救援；未连接券商。', '',
              '## 公开公式与本轮改编', '',
              '数学对象是[AlphaForge作者预印本v5](https://arxiv.org/abs/2406.18394v5)第6页表2第5号式，'
              '会议来源见[AAAI 2025](https://ojs.aaai.org/index.php/AAAI/article/view/33365)。'
              '固定作者提交为`d0cfc27df23c60f271bc885fd43027b86b787746`，本地按公开数学式独立实现。', '',
              '`f = S_log1p(ts_min(ts_corr(close, volume, 10), 1))`。10点价与量去均值后，A=Σx²、B=Σy²、N=Σxy；'
              '`rho=N/(1 if A<1e-6 or B<1e-6 else sqrt(A*B))`，`f=sign(rho)*log1p(abs(rho))`。'
              '长度1的滚动最小值不改变完整有限输入；不裁剪rho。固定交易假说为`−f`，再按形成日平均同分百分位选股。', '',
              '输入是原始收盘价水平（元）和原始vol×100（股），非收益率与量增长率相关，也不能直接识别主动资金流。'
              '原epsilon严格分支、float64、负号、留仓、对照和账务规则均未改。'
              '这不等于作者完整的因子挖掘、动态组合、CSI300／500与20日VWAP评价复现；没有整框架训练、自动挖掘或付费模型调用。', '',
              '## r2形成政策及事件时点边界', '',
              '每个窗口含形成日及之前9个开市日，共10点，只检查内部9次相邻转换。原common200历史资格、流动性、200日完整报价'
              '和既有未知行动隔离继续保留；不填充缺口，不把窗口首日之前的转换扩展为第11点。', '',
              '1. 前一交易日close或当日pre_close缺失、非有限或非正，记unknown_reference并排除。',
              '2. 从冻结原CSV文本以Decimal数值精确比较两者；不同记raw_reference_change并排除，不加舍入或比例容差。',
              '3. 内部生效的已登记行动只有在日级时间字段有效、known_date和event_date均不晚于形成日时才参与排除。'
              '实施分红／送转known_date只用imp_ann_date，不用提案ann_date；缺失、非法或晚于ex_date者timing_verified=False。',
              '4. 未认证行动时间仅记event_timing_unverified风险，不据它改变过去资格或排序；已有配股来源URL不能单独认证公开日，'
              '本轮没有从URL猜发布日期。参考价条件仍独立执行。',
              '5. 单独的adj_factor变化、但未观察到以上断点时保留原价量并作isolated_factor_change_no_observed_reference_break标记。'
              '它不认证“舍入”“无行动”或供应商系数错误。', '',
              'timing_verified仅表示缓存实施公告日合法且不晚于生效日，不等于已核对不可修订的原始公告版本；'
              '日内发布时间和历史版本身份均未认证。重复行动版本保留；已有有来源的correct_actions另存纠正清单，未按最新提案择优。', '',
              f"冻结事件{event_audit['event_rows']:,}条，其中日级时间字段有效{event_audit['timing_verified_rows']:,}条、"
              f"时间未认证{event_audit['timing_unverified_rows']:,}条；现金／送转记录{event_audit['dividend_rows']:,}条、"
              f"配股风险记录{event_audit['rights_rows']:,}条。", '',
              '| 未认证时间原因 | 事件记录数 |', '|---|---:|']
    unknown = events.loc[~verified_flags]
    for reason, count in unknown.timing_reason.value_counts().items():
        lines.append(f'| {cell(reason)} | {int(count):,} |')
    if unknown.empty:
        lines.append('| 本轮事件表无此记录 | 0 |')
    affected = coverage.loc[coverage.event_timing_unverified_count.gt(0)]
    affected_range = ('无形成记录命中' if affected.empty else
                      affected.trade_date.min().strftime('%Y-%m-%d') + '至' + affected.trade_date.max().strftime('%Y-%m-%d'))
    unknown_range = ('无未认证事件' if unknown.empty else
                     unknown.event_date.min().strftime('%Y-%m-%d') + '至' + unknown.event_date.max().strftime('%Y-%m-%d'))
    lines += ['', f'未认证事件生效日范围：{unknown_range}；命中形成记录{len(affected):,}条，形成日期范围：{affected_range}。'
              '这些计数是覆盖风险，不把无缓存匹配或未知时点等同没有行动。', '',
              '## 覆盖、r1交集与独立数学核验', '',
              f"原common200候选{feature['original_rows']:,}条；r2有效{feature['common_rows']:,}条，"
              f"154期最小形成池{feature['minimum_formed']:,}只，200只门槛保持。"
              f"独立重放{verification['reference_transition_rows_checked']:,}条内部转换。", '',
              '| 状态 | 记录数 |', '|---|---:|']
    for reason, count in sorted(feature['reasons'].items()):
        lines.append(f'| {cell(reason)} | {int(count):,} |')
    lines += ['', f"r1有效{pool['old_valid']:,}条，r2有效{pool['new_valid']:,}条，共同有效{pool['common_valid']:,}条；"
              f"新增有效{pool['newly_valid']:,}条、变为无效{pool['no_longer_valid']:,}条。共同有效原公式逐值一致；"
              '池变化会改变百分位、留仓和账户路径，不能归因为公式改进。', '',
              f"独立核验全部{verification['original_formation_rows']:,}条资格及{verification['feature_rows_checked']:,}条有效公式；"
              f"因子最大绝对差{number(verification['maximum_factor_error'], 12)}。"
              f"孤立系数变化仍有效的形成记录{feature['isolated_factor_change_rows']:,}条；"
              f"epsilon分支实际命中{feature['guard_rows']:,}条。资格不使用未来标签。", '',
              f"每只股票首个有效窗口的float64／float32对照共{len(precision):,}个，最大因子绝对差"
              f"{number(precision.absolute_difference.max(), 12)}，guard分支差异"
              f"{int((precision.guard64.map(boolean) != precision.guard32.map(boolean)).sum()):,}个。"
              '这是固定数值诊断，不是作者数据与全部结果的位级复制认证。', '',
              '## IC／RankIC及固定五组', '',
              'D标签是下一周开盘至再下一周开盘的个股复权收益减同期基准收益；这是未扣费用的诊断性超额。'
              'IC为Pearson相关，RankIC为平均同分排名后的Spearman相关；每期至少10个有效标签且两向量非常量。'
              'IR=逐期均值／样本标准差（ddof=1），不年化；缺失、常量或单期情形留空。', '',
              '| 因子 | 执行年 | 有效IC期数 | IC均值 | ICIR | RankIC均值 | RankICIR | 标签覆盖 |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    for factor in FACTORS:
        for period in ('all', '2018', '2019', '2020'):
            row = ic.loc[ic.factor.eq(factor) & ic.period.eq(period)].iloc[0]
            subset = groups.loc[groups.factor.eq(factor)]
            if period != 'all':
                subset = subset.loc[subset.year.eq(int(period))]
            label_coverage = subset.n.sum() / subset.n_formed.sum() if subset.n_formed.sum() else np.nan
            lines.append(f"| {FACTOR_NAMES[factor]} | {'全期' if period == 'all' else period} | {int(row.ic_n)} | "
                         f"{number(row.ic_mean)} | {number(row.ic_ir)} | {number(row.rank_ic_mean)} | "
                         f"{number(row.rank_ic_ir)} | {percent(label_coverage)} |")
    lines += ['', '分组先按形成日平均同分百分位固定，再连接未来标签；并列可导致组别不等或空组，每组至少2个有效标签。'
              '以下是各期组内超额收益均值的等权平均，不是三年累计或可交易净值。5−1仅作诊断，不假设可卖空。', '',
              '| 因子 | 组1低 | 组2 | 组3 | 组4 | 组5高 | 同期5−1均值 |', '|---|---:|---:|---:|---:|---:|---:|']
    for factor in FACTORS:
        selected = groups.loc[groups.factor.eq(factor)]
        means = selected.groupby('group').mean_forward_return.mean().reindex(range(1, 6))
        pivot = selected.pivot(index='signal_date', columns='group', values='mean_forward_return')
        spread = (pivot[5] - pivot[1]).mean()
        lines.append('| ' + FACTOR_NAMES[factor] + ' | ' + ' | '.join(percent(v) for v in means) + ' | ' + percent(spread) + ' |')
    lines += ['', '## 六个真实股份账户', '',
              '100万元一次投入，A股主板多头、周频、跨年不断账；20只目标、单股4.9%、每行业最多5只、现金底线2%、容量0.5%。'
              '保留gap严格大于0.05与每周最多5只主动替换；完整权重仍可能产生resize交易，不能先验称低换手。'
              '原整手、T+1、停牌／涨跌停、现金、退市、分红／配股及应收账务保持，拒卖可能使实际持股超过20只。', '',
              '0bp关闭交易费和滑点；10／30bp使用原历史费用口径与相应滑点，不称2026现行费率。'
              '净值已经计入费用及滑点，列示成本不再重复扣除。年化按实际开市日及252日／年计算。', '',
              '| 账户 | 累计净收益 | 年化净收益 | 最大回撤 | 费用元 | 滑点元 | 年化半换手倍 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for label in ordered:
        row, op = stats[label], operations.loc[label]
        lines.append(f"| {account_name(label)} | {percent(row['total_return'])} | {percent(row['annualized_return'])} | "
                     f"{percent(row['max_drawdown'])} | {number(op.total_fees_cny, 2)} | {number(op.total_slippage_cny, 2)} | "
                     f"{number(op.annualized_half_turnover_prior_equity, 2)} |")
    lines += ['', '半换手=Σ[(实际买入成交额+卖出成交额)/(2×前交易日权益)]×252/N；'
              'N含全部正式开市日，计入初始建仓。它与引擎基于当日开盘权益的gross_turnover不同。', '',
              '| 账户 | 2018 | 2019 | 2020 | 拒单数 | 平均现金 | 实际最多持股数 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for label in ordered:
        years = annual.loc[annual.strategy.eq(label)].set_index('year').return_value
        op = operations.loc[label]
        lines.append(f"| {account_name(label)} | {percent(years.loc[2018])} | {percent(years.loc[2019])} | "
                     f"{percent(years.loc[2020])} | {int(op.rejected_count):,} | {percent(op.average_cash_weight)} | "
                     f"{int(op.maximum_actual_positions)} |")
    lines += ['', '主候选10bp拒单原因：', '', '| 原因 | 次数 |', '|---|---:|']
    rejected = json.loads(operations.loc[PRIMARY + '_10bp', 'rejected_reasons_json'])
    for reason, count in sorted(rejected.items()):
        lines.append(f'| {cell(reason)} | {int(count):,} |')
    if not rejected:
        lines.append('| 无拒单 | 0 |')
    checks = verification['accounts']
    lines += ['', '## 独立账务、保护证据与限制', '',
              f"六账户共独立重建{sum(item['sessions'] for item in checks):,}个账本日（含空仓准备），"
              '普通股、待上市股逐日精确一致，现金／应收／权益成分均通过，12个跨年边界连续。'
              f"现金最大误差{number(max(item['maximum_cash_error'] for item in checks), 10)}元，"
              f"应收最大误差{number(max(item['maximum_receivable_error'] for item in checks), 10)}元，"
              f"权益成分最大误差{number(max(item['maximum_equity_error'] for item in checks), 10)}元。", '',
              '| 受保护旧输出 | 文件数 |', '|---|---:|']
    for name, count in sorted(verification['old_artifacts'].items()):
        lines.append(f'| {cell(name)} | {int(count):,} |')
    lines += ['', 'r1准备失败及其63项证据、旧实验和原始数据保留。已查看2016—2025历史，'
              '本轮2018—2020属于回顾性开发，不能恢复为独立样本外。事件字段来自后来取得的缓存，日级known_date不能认证当时版本。'
              '历史ST／行业证据、固定红利税、退市零回收、日线成交近似和停牌旧估值等原限制继续保留。'
              '即使本轮历史关卡全部通过，仍需冻结后的独立前向模拟；本报告不构成实盘启用。', '',
              '## 真实结果图', '']
    for filename, caption in FIGURES:
        lines += [f'![{caption}]({(out / "figures" / filename).resolve().as_posix()})', '', caption + '。', '']
    lines += ['## 复核入口', '']
    for label, path in [
            ('r2冻结设计', ROOT / 'docs/superpowers/specs/2026-10-16-alphaforge-event-filter-r2-design.md'),
            ('r2实施与批准记录', ROOT / 'docs/superpowers/plans/2026-10-16-alphaforge-r2-implementation.md'),
            ('最终独立核验', out / 'verification.json'), ('独立准备核验', out / 'preparation_audit.json'),
            ('逐事件时点', out / 'events.csv'), ('原始行动版本', out / 'raw_event_versions.csv'),
            ('已有行动纠正证据', out / 'event_corrections.json'), ('逐转换参考价证据', out / 'reference_transitions.csv'),
            ('r1与r2资格比较', out / 'r1_pool_comparison.csv'), ('账户摘要', out / 'summary.json'),
            ('年度收益', out / 'annual_returns.csv'), ('实际交易与成本', out / 'account_operations.csv')]:
        lines.append(f'- [{label}]({path.resolve().as_posix()})')
    lines += ['', '运行入口为run_alphaforge_r2.py、verify_alphaforge_r2.py和本报告生成器；'
              '已冻结运行不应重复启动。仅查看本报告无需重新下载或重算账户。', '']
    text = '\n'.join(lines)
    (out / 'report.md').write_text(text, encoding='utf-8')
    DOC.write_text(text, encoding='utf-8')
    inputs = {name: sha(out / name) for name in ['verification.json', 'summary.json', 'feature_summary.json',
              'event_mapping_summary.json', 'factor_ic_summary.csv', 'factor_groups.csv', 'account_operations.csv',
              'annual_returns.csv', 'events.csv', 'feature_coverage.csv', 'float_precision_audit.csv']}
    inputs['source_script_sha256'] = sha(Path(__file__))
    (out / 'report_inputs_sha256.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(out / 'report.md'))
    print(str(DOC))
    return dict(report=str(DOC), research_gates_passed=passed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--render-figures', action='store_true', help='Plot saved diagnostics/NAV after engineering verification')
    arguments = parser.parse_args()
    main(arguments.out, render_figures=arguments.render_figures)
