"""Pre-specified development-period comparison; no parameter optimization."""
import hashlib
import json
import argparse
from dataclasses import asdict, replace
import numpy as np
import pandas as pd
from .data import ROOT
from .factors import (FACTORS, compute_factors, rank_scores, select_targets, select_buffered_targets,
                      weekly_schedule, biweekly_schedule)
from .universe import historical_universe
from .accounting import normalize_actions
from .backtest import Config, simulate, summarize
from .datasets import DATASETS, dataset_config
from .attribution import cost_breakdown, monthly_returns
from .corporate_corrections import correct_actions, correct_adjustments, correct_limit_code_aliases
from .rights import verified_rights
from .adjustment_audit import audit_adjustments, quarantine_factors, return_consistency_check


def read_market(root, name):
    frame = pd.read_csv(root / f'{name}.csv', dtype={'ts_code': str, 'trade_date': str})
    if 'trade_date' in frame:
        frame['trade_date'] = pd.to_datetime(frame.trade_date, format='%Y%m%d')
    return frame


def diagnostics(snapshots, bars, schedule):
    rows, groups = [], []
    quotes = bars.assign(adj_open=bars.open * bars.adj_factor).set_index(['trade_date', 'ts_code']).adj_open
    executions = schedule.execution_date.tolist()
    for index, row in enumerate(schedule.itertuples(index=False)):
        if index + 1 >= len(executions) or row.signal_date not in snapshots:
            continue
        entry, exit_date = row.execution_date, executions[index+1]
        frame = snapshots[row.signal_date].copy()
        frame['forward_return'] = [quotes.get((exit_date, c), np.nan) / quotes.get((entry, c), np.nan) - 1 for c in frame.ts_code]
        frame = frame.replace([np.inf, -np.inf], np.nan)
        for factor in FACTORS:
            formed = frame.dropna(subset=[factor]).copy()
            # Group membership is fixed using formation-date information only.
            formed['bucket'] = np.ceil(formed[factor].rank(method='average', pct=True) * 5).clip(1, 5)
            valid = formed.dropna(subset=['forward_return'])
            sufficient = len(valid) >= 10 and valid[factor].nunique() > 1 and valid.forward_return.nunique() > 1
            ic = valid[factor].corr(valid.forward_return) if sufficient else np.nan
            rank_ic = valid[factor].rank(method='average').corr(valid.forward_return.rank(method='average')) if sufficient else np.nan
            rows.append(dict(signal_date=row.signal_date, entry=entry, exit=exit_date, factor=factor,
                             n=len(valid), n_formed=len(formed), label_coverage=len(valid)/len(formed) if len(formed) else np.nan,
                             ic=ic, rank_ic=rank_ic))
            for group in range(1, 6):
                original = formed.loc[formed.bucket.eq(group)]
                subset = original.dropna(subset=['forward_return'])
                groups.append(dict(signal_date=row.signal_date, factor=factor, group=group,
                                   n_formed=len(original), n=len(subset),
                                   mean_forward_return=float(subset.forward_return.mean()) if len(subset) >= 2 else np.nan))
    return pd.DataFrame(rows), pd.DataFrame(groups)


def main(dataset='development_2020q4'):
    spec = dataset_config(dataset)
    root = ROOT / 'data' / dataset
    output = ROOT / 'output' / dataset
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / 'manifest.json').read_text())
    if (manifest['start'], manifest['end']) != (spec['start'], spec['end']):
        raise ValueError('Dataset dates differ from the registered experiment')
    evaluation_start = spec['evaluation_start']
    for name, checksum in manifest['files_sha256'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != checksum:
            raise ValueError(f'Data checksum mismatch: {name}')
    metadata = pd.read_csv(ROOT / 'data/audit/universe.csv', dtype=str)
    names = pd.read_csv(ROOT / 'data/audit/name_history.csv', dtype=str)
    sectors = pd.read_csv(ROOT / 'data/audit/industry_history.csv', dtype=str)
    full_cal = pd.read_csv(root / 'calendar.csv', dtype={'cal_date': str})
    full_calendar = pd.DatetimeIndex(pd.to_datetime(full_cal.loc[full_cal.is_open.eq(1), 'cal_date'], format='%Y%m%d')).sort_values()
    calendar = full_calendar[(full_calendar >= pd.Timestamp(manifest['start'])) & (full_calendar <= pd.Timestamp(manifest['end']))]
    bars = read_market(root, 'daily')
    bars = bars.loc[bars.ts_code.isin(metadata.ts_code) & bars.ts_code.str.match(r'^(60\d{4}\.SH|00\d{4}\.SZ)$')].copy()
    bars = bars.merge(read_market(root, 'adj_factor'), on=['trade_date', 'ts_code'], validate='one_to_one')
    limits, limit_corrections = correct_limit_code_aliases(read_market(root, 'stk_limit'))
    bars = bars.merge(limits, on=['trade_date', 'ts_code'], how='left', validate='one_to_one')
    if bars.adj_factor.isna().any():
        raise ValueError('Missing adjustment factors')
    limit_missing = bars[['up_limit', 'down_limit']].isna().any(axis=1)
    execution_coverage = bars.assign(missing_limit=limit_missing).groupby('trade_date').agg(
        quoted_assets=('ts_code', 'size'), missing_limit_assets=('missing_limit', 'sum'))
    execution_coverage.to_csv(output / 'execution_data_coverage.csv')
    dividends = pd.read_csv(root / 'dividend.csv', dtype=str)
    dividends, corrections = correct_actions(dividends)
    corrections = limit_corrections + corrections
    bars, adjustment_corrections = correct_adjustments(bars)
    corrections.extend(adjustment_corrections)
    (output / 'corporate_action_corrections.json').write_text(json.dumps(corrections, ensure_ascii=False, indent=2), encoding='utf-8')
    # Annual simulations start entirely in cash and can only buy quoted assets.
    # Preserve out-of-window events for review, without inventing settlements.
    quoted_codes = set(bars.ts_code)
    unquoted_actions = dividends.loc[dividends.ts_code.isin(metadata.ts_code) &
                                    ~dividends.ts_code.isin(quoted_codes)].copy()
    unquoted_actions.to_csv(output / 'unquoted_asset_actions.csv', index=False)
    actions = normalize_actions(dividends, quoted_codes)
    adjustment_issues = audit_adjustments(bars, actions, verified_rights())
    adjustment_issues.to_csv(output / 'unexplained_adjustments.csv', index=False)
    consistency_issues = return_consistency_check(bars, actions, verified_rights())
    consistency_issues.to_csv(output / 'return_consistency.csv', index=False)
    suspensions = read_market(root, 'suspend_d')
    suspension_set = set(suspensions.loc[suspensions.suspend_type.eq('S'), ['trade_date', 'ts_code']].itertuples(index=False, name=None))
    delistings = dict(zip(metadata.ts_code, pd.to_datetime(metadata.delist_date, format='%Y%m%d')))
    price_input = bars.loc[bars.vol.gt(0)].copy()
    price_input['trade_date'] = price_input.trade_date.dt.strftime('%Y%m%d')
    factors = compute_factors(price_input, calendar)
    factors, quarantined_factor_rows = quarantine_factors(factors, adjustment_issues, calendar)
    factors.to_csv(output / 'factors.csv', index=False)
    schedule = weekly_schedule(calendar)
    snapshots, coverage, industry_maps = {}, [], {}
    for date in calendar:
        stamp = date.strftime('%Y%m%d')
        industry = sectors.loc[(sectors.in_date <= stamp) & (sectors.out_date.isna() | (sectors.out_date > stamp))]
        counts = industry.groupby('ts_code').l1_code.nunique()
        industry = industry.loc[industry.ts_code.isin(counts[counts == 1].index)].drop_duplicates('ts_code')
        industry_maps[date] = dict(zip(industry.ts_code, industry.l1_code))
    for row in schedule.itertuples(index=False):
        available = historical_universe(row.signal_date, metadata, names, sectors, full_calendar)
        frame = factors.loc[factors.trade_date.eq(row.signal_date)].dropna(subset=FACTORS)
        frame = frame.loc[frame.adv20_cny >= 20_000_000].merge(available[['ts_code', 'industry']], on='ts_code', validate='one_to_one')
        snapshots[row.signal_date] = frame
        coverage.append(dict(signal_date=row.signal_date, execution_date=row.execution_date,
                             historical_eligible=len(available), factor_liquidity_eligible=len(frame)))
    populated = [row.execution_date for row in schedule.itertuples(index=False) if len(snapshots[row.signal_date]) >= 20
                 and (evaluation_start is None or row.execution_date >= pd.Timestamp(evaluation_start))]
    if not populated:
        raise ValueError('No usable complete-factor cross section')
    first_execution = min(populated)
    active_schedule = schedule.loc[schedule.execution_date >= first_execution]
    configurations = [('combined', FACTORS, 10), ('momentum20', ['momentum20'], 10),
                      ('reversal5', ['reversal5'], 10), ('lowvol20', ['lowvol20'], 10),
                      ('liquidity_control', ['adv20_cny'], 10), ('combined_slip30', FACTORS, 30),
                      ('combined_slip50', FACTORS, 50)]
    if spec['evaluation_start'] is not None:
        configurations.extend([('combined_zero_cost', FACTORS, 0),
                               ('combined_rank_buffer40', FACTORS, 10),
                               ('combined_biweekly', FACTORS, 10),
                               ('combined_biweekly_zero_cost', FACTORS, 0),
                               ('combined_biweekly_slip30', FACTORS, 30)])
    buffered_labels = {'combined_rank_buffer40', 'combined_biweekly', 'combined_biweekly_zero_cost',
                       'combined_biweekly_slip30'}
    active_biweekly = biweekly_schedule(calendar).loc[lambda s: s.execution_date >= first_execution]
    results, curves = [], {}
    for label, columns, slippage in configurations:
        exp_schedule = active_biweekly if 'biweekly' in label else active_schedule
        plans, previous_codes = [], set()
        for row in exp_schedule.itertuples(index=False):
            frame = rank_scores(snapshots[row.signal_date], columns=columns)
            target = (select_buffered_targets(frame, previous_codes, exit_rank=40)
                      if label in buffered_labels else select_targets(frame))
            target['signal_date'], target['execution_date'] = row.signal_date, row.execution_date
            plans.append(target)
            previous_codes = set(target.ts_code)
        targets = pd.concat(plans, ignore_index=True)
        config = Config(slippage_bps=slippage,
                        zero_trading_costs=label in ('combined_zero_cost', 'combined_biweekly_zero_cost'))
        run = simulate(bars, calendar, targets, actions, suspension_set, delistings, industry_maps, config,
                       rebalance_dates=exp_schedule.execution_date.tolist(), rights=verified_rights())
        folder = output / label
        folder.mkdir(exist_ok=True)
        targets.to_csv(folder / 'historical_targets.csv', index=False)
        for name, frame in run.items():
            frame.to_csv(folder / f'{name}.csv', index=False)
        summary = summarize(run['nav'], run['orders'], first_execution, evaluation_start)
        summary.update(strategy=label, config=asdict(config), corporate_events=len(run['corporate_events']))
        summary['ex_events'] = int(run['corporate_events'].event.eq('ex').sum()) if not run['corporate_events'].empty else 0
        summary['stock_settlements'] = int(run['corporate_events'].event.eq('stock_settlement').sum()) if not run['corporate_events'].empty else 0
        summary['delisting_writeoffs'] = int(run['corporate_events'].event.eq('delisting_zero_recovery').sum()) if not run['corporate_events'].empty else 0
        summary['rights_not_subscribed'] = int(run['corporate_events'].event.eq('rights_not_subscribed').sum()) if not run['corporate_events'].empty else 0
        summary['rights_subscribed'] = int(run['corporate_events'].event.eq('rights_subscribed').sum()) if not run['corporate_events'].empty else 0
        results.append(summary)
        curves[label] = run['nav'].set_index('date').equity
        evaluated = run['nav'].loc[run['nav'].date >= pd.Timestamp(summary['start'])].set_index('date').equity
        monthly_returns(evaluated).to_csv(folder / 'monthly_returns.csv')
        attribution = cost_breakdown(run['orders'])
        attribution.to_csv(folder / 'cost_attribution.csv')
        summary['cost_attribution'] = attribution.reset_index().to_dict('records')
        print(json.dumps(summary, ensure_ascii=True), flush=True)
    ic, groups = diagnostics(snapshots, bars, active_schedule)
    ic.to_csv(output / 'factor_ic.csv', index=False)
    groups.to_csv(output / 'factor_groups.csv', index=False)
    formation_long = pd.concat(snapshots.values(), ignore_index=True).melt(
        id_vars=['trade_date', 'ts_code'], value_vars=FACTORS, var_name='factor', value_name='value'
    ).rename(columns={'trade_date': 'date', 'ts_code': 'asset'})
    formation_long.to_csv(output / 'formation_factors_long.csv', index=False)
    pd.DataFrame(coverage).to_csv(output / 'coverage.csv', index=False)
    summary = dict(data_manifest=manifest, dataset=dataset, title=spec['title'], initial_capital=1_000_000, experiments=results,
                   actions_in_dataset=len(actions), corporate_action_corrections=corrections,
                   unexplained_adjustments=len(adjustment_issues),
                   quarantined_factor_rows=quarantined_factor_rows,
                   unexplained_adjustment_dates=adjustment_issues.trade_date.dt.strftime('%Y-%m-%d').value_counts().to_dict(),
                   rights_policy='No subscription: no cash or shares credited; raw-price dilution losses remain. Not a live recommendation.',
                   bars=len(bars), assets=int(bars.ts_code.nunique()),
                   missing_price_limit_rows=int(limit_missing.sum()),
                   factor_ic_observations=len(ic), first_execution=str(first_execution.date()),
                   status=('Frozen-parameter out-of-sample test on a sealed period. Parameters and corrections '
                           'were fixed before this run; still not a live recommendation.'
                           if dataset.startswith('out_of_sample')
                           else 'Development-window engineering study. No out-of-sample evidence or live recommendation.'),
                   metadata_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'data/audit').glob('*.csv')},
                   source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'quant_research').glob('*.py')})
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    render_report(output, summary, curves, read_market(root, 'benchmark'), ic, groups)


def render_report(output, summary, curves, benchmark, ic, groups):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'DejaVu Sans']
    labels = {'combined': '三因子等权', 'momentum20': '20 日动量', 'reversal5': '5 日反转',
              'lowvol20': '20 日低波动', 'liquidity_control': '高流动性对照',
              'combined_slip30': '三因子/30bp 滑点', 'combined_slip50': '三因子/50bp 滑点',
              'combined_zero_cost': '三因子/零交易成本诊断',
              'combined_rank_buffer40': '三因子/排名缓冲 40',
              'combined_biweekly': '三因子/双周调仓+缓冲 40',
              'combined_biweekly_zero_cost': '三因子/双周零成本诊断',
              'combined_biweekly_slip30': '三因子/双周/30bp 滑点'}
    start = pd.Timestamp(summary['experiments'][0]['start'])
    fig, ax = plt.subplots(figsize=(11, 5.8))
    for label, curve in curves.items():
        if 'slip' in label or 'zero_cost' in label:
            continue
        curve = curve.loc[start:]
        ax.plot(curve.index, (curve / curve.iloc[0] - 1) * 100, label=labels[label], linewidth=1.8)
    reference = benchmark.set_index('trade_date').close.sort_index().loc[start:]
    ax.plot(reference.index, (reference / reference.iloc[0] - 1) * 100, label='沪深 300 价格指数（未扣交易成本）', color='black', linestyle='--')
    ax.axhline(0, color='gray', linewidth=.6)
    ax.set(title=summary['title'] + '：扣费净值比较', ylabel='累计收益（%）')
    ax.legend(fontsize=9, loc='best')
    ax.grid(alpha=.2)
    fig.autofmt_xdate()
    fig.text(.08, .015, '仅用于工程与开发期诊断；不是样本外证据。含固定红利税情景，不代表真实账户税后收益。', fontsize=9)
    fig.tight_layout(rect=(0, .04, 1, 1))
    fig.savefig(output / 'equity_comparison.png', dpi=160)
    plt.close(fig)
    lines = ['# 周频多因子开发期研究结果', '',
             '**这是开发期研究，不是实盘推荐，也不是样本外收益证据。**', '',
             f"{summary['title']}，共 {summary['assets']} 只历史主板 A 股、{summary['bars']} 条日线（含预热）。",
             f"预热后首次调仓为 {summary['first_execution']}，实际评价 {summary['experiments'][0]['sessions']} 个交易日。初始资金 100 万元。", '',
             '| 策略 | 区间收益 | 最大回撤 | 显式费用（元） | 滑点损耗（元） | 成交/拒单 |',
             '|---|---:|---:|---:|---:|---:|']
    for item in summary['experiments']:
        lines.append(f"| {labels[item['strategy']]} | {item['total_return']:.2%} | {item['max_drawdown']:.2%} | {item['total_fees']:,.2f} | {item['total_slippage']:,.2f} | {item['filled_orders']}/{item['rejected_orders']} |")
    combined = next(item for item in summary['experiments'] if item['strategy'] == 'combined')
    zero = next((item for item in summary['experiments'] if item['strategy'] == 'combined_zero_cost'), None)
    if zero:
        lines += ['', f"零交易成本诊断中，三因子组合收益为 {zero['total_return']:.2%}；常规成本下为 {combined['total_return']:.2%}，相差 {(zero['total_return']-combined['total_return'])*100:.2f} 个百分点。零成本不代表实盘收益，固定红利税与拒单规则仍保留；该差额也包含资金规模、整数股及后续成交路径变化，不能等同于简单加回手续费。", '']
    buffered = next((item for item in summary['experiments'] if item['strategy'] == 'combined_rank_buffer40'), None)
    if buffered:
        regular_cost = combined['total_fees'] + combined['total_slippage']
        buffered_cost = buffered['total_fees'] + buffered['total_slippage']
        lines += ['', f"排名缓冲候选收益为 {buffered['total_return']:.2%}、最大回撤 {buffered['max_drawdown']:.2%}，成交 {buffered['filled_orders']} 笔，累计换手指标 {buffered['gross_turnover']:.2f}；原组合分别为 {combined['total_return']:.2%}、{combined['max_drawdown']:.2%}、{combined['filled_orders']} 笔和 {combined['gross_turnover']:.2f}。费用及滑点从 {regular_cost:,.2f} 元降至 {buffered_cost:,.2f} 元。该候选按事前登记的退出排名 40 运行，没有扫描阈值。", '']
    lines += ['', f"同期沪深 300 **价格指数**变动为 {reference.iloc[-1] / reference.iloc[0] - 1:.2%}，不含股息再投资和交易成本，与股票组合口径不同。", '',
              '![开发期净值比较](equity_comparison.png)', '', '## 如何解读', '',
              '策略均采用同一历史状态、上市年龄与流动性过滤，20 只等权目标、每周调仓、2% 现金缓冲及 25% 行业目标上限。高流动性对照按此前 20 日成交额排序，同样选 20 只、使用相同成交和成本规则。', '',
              '滑点分别按单边 10/30/50 基点建模，并按分价位向不利方向取整。显式费用包含佣金、印花税与过户费；滑点已经反映在成交价和净值中，不能再次从收益扣除。未假定期末全部清仓。', '',
              '分价位向不利方向取整使低价股票的实际滑点可能明显高于名义基点。单股目标金额不足购买一手时保留现金，因此实际持股可能少于 20 只，对照组也遵循该规则。', '',
              '2016—2020 年开发期情景为佣金万三、每笔最低 5 元，卖出印花税千一、双边过户费十万分之二。佣金是研究假设，未取得用户交割单。现金红利和送股应税面值按固定 20% 税率预留，面值按每股 1 元情景；资本公积转增不计该项税。该简化未实现逐笔持有期差别税率及真实追缴时间。', '',
              '登记日记录权利；除权日确认应收现金和未上市红股；派息/上市日期到达后才转成现金/可卖股数。停牌估值沿用前值并在公司行动时调整参考价；退市按股票价值零回收情景处理。未解释的复权变化若影响持仓，会终止回测。', '',
              '配股自 2026-09-29 起按条款登记区分：经公告取证的配股价、实际配售比例与获配上市日登记后，除权日按获配股数扣认购款（获配 = 登记日持股 × 实际比例向下取整），获配股份计入待上市股份、上市日转为持仓，记 rights_subscribed；现金不足或无条款的已核验事件维持“不认购”情景，记 rights_not_subscribed。仅对已有一手来源核验的事件开放识别，其他未知变化仍会中止回测。', '',
              '因子 IC 与分组收益采用下周首日复权开盘至再下一周首日复权开盘，属于未扣费诊断标签，不等同于可成交收益。缺少退出价格的样本不补零，见 n 列。', '',
              '## 因子诊断', '', '| 因子 | 周期数 | 平均 IC | 平均 Rank IC |', '|---|---:|---:|---:|']
    for factor, frame in ic.groupby('factor'):
        lines.append(f"| {labels[factor]} | {len(frame)} | {frame.ic.mean():.4f} | {frame.rank_ic.mean():.4f} |")
    lines += ['', '## 三因子组合的成本来源', '', '| 交易类型 | 成交笔数 | 成交额（元） | 费用及滑点（元） | 成本占比 |', '|---|---:|---:|---:|---:|']
    roles = {'entry': '新建仓位（含首次建仓）', 'exit': '退出未入选股票', 'resize': '原持仓数量调整'}
    for item in combined['cost_attribution']:
        lines.append(f"| {roles[item['role']]} | {item['orders']} | {item['notional']:,.2f} | {item['total_cost']:,.2f} | {item['cost_share']:.2%} |")
    lines += ['', '## 月度收益', '', '| 月份 | 三因子 | 动量 | 反转 | 低波动 | 流动性对照 |', '|---|---:|---:|---:|---:|---:|']
    monthly = pd.concat({name: monthly_returns(curves[name].loc[start:]) for name in
                         ['combined', 'momentum20', 'reversal5', 'lowvol20', 'liquidity_control']}, axis=1)
    for period, values in monthly.iterrows():
        lines.append('| ' + str(period) + ' | ' + ' | '.join(f'{v:.2%}' for v in values) + ' |')
    monthly.to_csv(output / 'monthly_comparison.csv')
    if 'annualized_return' in combined:
        lines += ['', '## 年化描述指标', '', '| 策略 | 年化收益 | 年化波动 | Sharpe（无风险率情景为 0） |', '|---|---:|---:|---:|']
        for item in summary['experiments']:
            sharpe = f"{item['sharpe_rf0']:.3f}" if item['sharpe_rf0'] is not None else '未定义'
            lines.append(f"| {labels[item['strategy']]} | {item['annualized_return']:.2%} | {item['annualized_volatility']:.2%} | {sharpe} |")
        lines += ['', '年化按 252 个交易日、样本日收益标准差计算。这些是一段开发期内的描述统计，不表示未来预期收益。']
    lines += ['', '## 执行与数据异常记录', '', '| 策略 | 实际行业超目标天数 | 沿用旧价估值天数 | 公司行动日志条数 |', '|---|---:|---:|---:|']
    for item in summary['experiments']:
        lines.append(f"| {labels[item['strategy']]} | {item['industry_breach_days']} | {item['stale_valuation_days']} | {item['corporate_events']} |")
    lines += ['', '公司行动日志条数包含确认和到账记录，不等于分红次数。各策略实际除权事件、红股到账和退市情景触发数见 summary.json；不同策略可能持有同一只股票，不应将这些次数当作独立样本。',
              '缺失日线的非成交估值沿用旧价；该估值不保证能兑现，尤其应关注低波动组合的旧价估值天数。行业超限来自实际持仓，不能用目标权重合规掩盖。']
    if summary['corporate_action_corrections']:
        lines += ['', '本次读取层更正如下；原始文件保留，详情见 corporate_action_corrections.json。', '']
        for correction in summary['corporate_action_corrections']:
            lines.append(f"- {correction['ts_code']}：{correction['action']}。{correction['reason']} 来源：{correction['source']}")
    lines += ['', '## 限制和下一步', '',
              f"- 历史主板行情中有 {summary['missing_price_limit_rows']} 个股票日缺少涨跌停字段，见 execution_data_coverage.csv；成交引擎拒绝缺少该字段的订单。",
              f"- 全股票池发现 {summary['unexplained_adjustments']} 条尚未由已核验事件登记解释的复权因子变化（见 unexplained_adjustments.csv），对应 {summary['quarantined_factor_rows']} 个股票日被隔离出价格因子截面。隔离覆盖异常日起 20 个交易日；原始行情未修改。若未知变化影响持仓账本，程序仍会中止。",
              '- 股票曾用名表按已公告 ST/PT 区间作为排除清单使用；它不是完整的逐日名称主表。2000 积分账户无法调用 3000 积分的逐日 ST 名单，风险警示事件完整性仍需外部复核。行业区间可能有历史修订，未验证当时发布版本。',
              '- 日线不能还原开盘排队、盘中停牌和手动成交；采用保守拒单及事前成交额容量近似。',
              '- 行业约束施加于目标，价格漂移或拒单后可能超限；每日实际最大行业权重及未知行业权重单独记录。',
              '- 本轮不评选最终因子，不按结果改方向。先扩展开发与验证时期，再冻结设计并打开 2024—2025 封存测试期。',
              '- 没有生成当前买入名单，没有连接券商。', '',
              '## 复现', '', f"`python -m quant_research.download --dataset {summary['dataset']}` 后运行 `python -m quant_research.research --dataset {summary['dataset']}`。数据文件和代码 SHA-256、参数见 summary.json；逐日净值、订单、持仓及公司行动日志在各策略目录。", '',
              '## 规则来源', '',
              '- [Tushare 分红送股字段](https://tushare.pro/document/2?doc_id=103)',
              '- [税务机关：2023 年印花税减半公告](https://shanxi.chinatax.gov.cn/web/detail/sx-11400-545-1780448)',
              '- [证监会：股息红利差别税率说明](https://www.csrc.gov.cn/shenzhen/c105614/c2939669/content.shtml)', '']
    lines.insert(-1, '- [券商发布的中国结算过户费调整通知](https://www.xcsc.com/main/a/20220429/1022871784.shtml)')
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', choices=DATASETS, default='development_2020q4')
    main(parser.parse_args().dataset)
