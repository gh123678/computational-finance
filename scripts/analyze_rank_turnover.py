"""Diagnose frozen factor ranks and targets; never simulate or change rules."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.factors import FACTORS, rank_scores, select_targets, select_buffered_targets
from quant_research.universe import historical_universe

SOURCE = ROOT / 'output/continuous_2016_2025_dividend_r1'
OUT = ROOT / 'output/continuous_rank_turnover_20261006'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    OUT.mkdir(exist_ok=True)
    verification = json.loads((SOURCE / 'verification.json').read_text())
    assert verification['status'] == 'passed'
    assert verification['summary_sha256'] == sha(SOURCE / 'summary.json')
    frozen = json.loads((SOURCE / 'frozen_protocol.json').read_text())
    for name, expected in frozen['source_sha256'].items():
        assert sha(ROOT / 'quant_research' / name) == expected, name
    provenance = {}
    paths = [SOURCE / 'factors.csv', SOURCE / 'summary.json', SOURCE / 'verification.json',
             SOURCE / 'frozen_protocol.json', ROOT / 'scripts/analyze_rank_turnover.py']
    for name, expected in frozen['metadata_sha256'].items():
        path = ROOT / 'data/audit' / name
        assert sha(path) == expected
        paths.append(path)
    calendar_path = ROOT / 'data/continuous_2016_2025_dividend_r1/calendar.csv'
    paths.append(calendar_path)
    cal = pd.read_csv(calendar_path, dtype={'cal_date': str})
    full_calendar = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1), 'cal_date'])).sort_values()
    labels = ['combined', 'momentum20', 'reversal5', 'lowvol20',
              'combined_rank_buffer40', 'combined_biweekly']
    targets = {}
    for label in labels:
        path = SOURCE / label / 'historical_targets.csv'
        paths.append(path)
        targets[label] = pd.read_csv(path, parse_dates=['signal_date', 'execution_date'])
    dates = sorted(targets['combined'].signal_date.unique())
    needed = set(pd.Timestamp(d) for d in dates)
    endpoints = {}
    for d in dates:
        d = pd.Timestamp(d)
        pos = full_calendar.get_loc(d)
        for horizon in (5, 20):
            if pos + horizon < len(full_calendar):
                endpoint = full_calendar[pos + horizon]
                endpoints[d, horizon] = endpoint
                needed.add(endpoint)
    print('Reading frozen signal and forward endpoint factors', flush=True)
    pieces = []
    for chunk in pd.read_csv(SOURCE / 'factors.csv', chunksize=150000, parse_dates=['trade_date']):
        pieces.append(chunk.loc[chunk.trade_date.isin(needed)])
    factors = pd.concat(pieces, ignore_index=True)
    assert not factors.duplicated(['trade_date', 'ts_code']).any()
    groups = {pd.Timestamp(d): g for d, g in factors.groupby('trade_date')}
    lookup = factors.set_index(['trade_date', 'ts_code'])
    metadata = pd.read_csv(ROOT / 'data/audit/universe.csv', dtype=str)
    names = pd.read_csv(ROOT / 'data/audit/name_history.csv', dtype=str)
    sectors = pd.read_csv(ROOT / 'data/audit/industry_history.csv', dtype=str)
    ranks, snapshots = {}, {}
    for d in dates:
        d = pd.Timestamp(d)
        available = historical_universe(d, metadata, names, sectors, full_calendar)
        frame = groups[d].dropna(subset=FACTORS)
        frame = frame.loc[frame.adv20_cny.ge(20000000)].merge(
            available[['ts_code', 'industry']], on='ts_code', validate='one_to_one')
        snapshots[d] = frame
        ranked = frame.set_index('ts_code')[FACTORS].rank(pct=True, method='average')
        ranked['score'] = ranked.mean(axis=1)
        ranks[d] = ranked
    print('Reconstructing all six saved target sequences', flush=True)
    replay_count = 0
    for label in labels:
        previous = set()
        columns = [label] if label in FACTORS else FACTORS
        for d, saved in targets[label].groupby('signal_date', sort=True):
            score = rank_scores(snapshots[d], columns=columns)
            buffered = label in ('combined_rank_buffer40', 'combined_biweekly')
            rebuilt = (select_buffered_targets(score, previous, exit_rank=40)
                       if buffered else select_targets(score))
            left = rebuilt.sort_values('ts_code').reset_index(drop=True)
            right = saved.sort_values('ts_code').reset_index(drop=True)
            assert left.ts_code.tolist() == right.ts_code.tolist(), (label, d)
            assert np.allclose(left.score, right.score, rtol=0, atol=1e-12), (label, d)
            assert np.allclose(left.target_weight, right.target_weight, rtol=0, atol=1e-12)
            previous = set(left.ts_code)
            replay_count += 1
    transitions, exits, forwards, retained = [], [], [], []
    for label in labels:
        prior_codes = None
        prior_date = None
        for d, target in targets[label].groupby('signal_date', sort=True):
            codes = set(target.ts_code)
            if prior_codes is None:
                prior_codes, prior_date = codes, d
                continue
            before, after = ranks[prior_date], ranks[d]
            common = before.index.intersection(after.index)
            gone, entered, kept = prior_codes - codes, codes - prior_codes, prior_codes & codes
            retained.append(dict(strategy=label,signal_date=d,previous_size=len(prior_codes),
                                 exits=len(gone),entries=len(entered),retention=len(kept)/len(prior_codes),
                                 exits_ineligible=len(gone-set(after.index))))
            for factor in FACTORS:
                delta = after.loc[common, factor] - before.loc[common, factor]
                previous_common = sorted(prior_codes & set(common))
                transitions.append(dict(strategy=label,signal_date=d,factor=factor,common_count=len(common),
                    rank_correlation=before.loc[common,factor].corr(after.loc[common,factor]),
                    mean_abs_rank_change=float(delta.abs().mean()),
                    previous_target_mean_rank_change=float(delta.reindex(previous_common).mean())))
            for code in sorted(gone):
                record = dict(strategy=label,signal_date=d,ts_code=code,
                              current_eligible=code in after.index)
                if code in after.index and code in before.index:
                    delta = after.loc[code,FACTORS]-before.loc[code,FACTORS]
                    record.update({f'{f}_rank_change': float(delta[f]) for f in FACTORS})
                    record['combined_score_change'] = float(delta.mean())
                    negative = (-delta).clip(lower=0)
                    record['largest_negative_component'] = (negative.idxmax() if negative.max()>0 else 'none')
                    # Ties are explicitly retained rather than attributed to first column.
                    if negative.max()>0 and np.isclose(negative,negative.max(),rtol=0,atol=1e-12).sum()>1:
                        record['largest_negative_component'] = 'tie'
                exits.append(record)
            for role, assets in [('exit', gone), ('entry', entered), ('retained', kept)]:
                for code in sorted(assets):
                    for horizon in (5,20):
                        endpoint = endpoints.get((d,horizon))
                        value = np.nan
                        if endpoint is not None and (endpoint,code) in lookup.index:
                            row = lookup.loc[(endpoint,code)]
                            value = -row.reversal5 if horizon==5 else row.momentum20
                        forwards.append(dict(strategy=label,signal_date=d,ts_code=code,role=role,
                                             horizon=horizon,endpoint=endpoint,forward_return=value))
            prior_codes, prior_date = codes, d
    transition = pd.DataFrame(transitions)
    exit_frame = pd.DataFrame(exits)
    forward = pd.DataFrame(forwards)
    retention = pd.DataFrame(retained)
    transition.to_csv(OUT/'rank_transitions.csv',index=False)
    exit_frame.to_csv(OUT/'exit_rank_components.csv',index=False)
    forward.to_csv(OUT/'forward_observations.csv',index=False)
    retention.to_csv(OUT/'target_transitions.csv',index=False)
    stats = transition.groupby(['strategy','factor']).agg(
        mean_rank_correlation=('rank_correlation','mean'),
        mean_abs_rank_change=('mean_abs_rank_change','mean'),
        previous_target_mean_rank_change=('previous_target_mean_rank_change','mean')).reset_index()
    stats.to_csv(OUT/'rank_summary.csv',index=False)
    fstats = forward.groupby(['strategy','horizon','role']).agg(
        total=('ts_code','size'),valid=('forward_return','count'),mean_return=('forward_return','mean')).reset_index()
    fstats['coverage'] = fstats.valid/fstats.total
    fstats.to_csv(OUT/'forward_summary.csv',index=False)
    # Paired date averages prevent unequal entry/exit sample sizes from dominating.
    means = forward.groupby(['strategy','signal_date','horizon','role']).forward_return.mean().unstack('role')
    paired = means.dropna(subset=['entry','exit']).copy()
    paired['entry_minus_exit'] = paired.entry-paired.exit
    paired.to_csv(OUT/'paired_forward_returns.csv')
    yearly = transition.assign(year=transition.signal_date.dt.year).groupby(
        ['strategy','year','factor']).agg(mean_rank_correlation=('rank_correlation','mean'),
        mean_abs_rank_change=('mean_abs_rank_change','mean')).reset_index()
    yearly.to_csv(OUT/'annual_rank_summary.csv',index=False)
    forward_yearly = paired.reset_index().assign(year=lambda f: f.signal_date.dt.year).groupby(
        ['strategy','year','horizon']).agg(mean_entry_minus_exit=('entry_minus_exit','mean'),
        paired_dates=('entry_minus_exit','size')).reset_index()
    forward_yearly.to_csv(OUT/'annual_paired_forward_returns.csv',index=False)
    for path in paths:
        provenance[str(path.relative_to(ROOT))] = sha(path)
    (OUT/'input_sha256.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    check = dict(status='passed',target_sequences=6,reconstructed_cross_sections=replay_count,
                 source_summary_sha256=verification['summary_sha256'],
                 checks=['冻结核心与元数据指纹一致','六组每个形成日目标代码完全一致，得分和权重误差小于1e-12',
                         '形成日仅采用当时股票池与过去因子；未来收益只用于事后诊断'],
                 scope='目标与排名分析，不运行账户或修改规则')
    (OUT/'verification.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf-8')
    combined_exits = exit_frame.loc[exit_frame.strategy.eq('combined') & exit_frame.current_eligible]
    reversal_share = combined_exits.largest_negative_component.eq('reversal5').mean()
    weekly = stats.loc[stats.strategy.eq('combined')].set_index('factor')
    yearly_reversal = yearly.loc[yearly.strategy.eq('combined') & yearly.factor.eq('reversal5')]
    lines = ['# 因子排名变化与换股来源诊断','',
             '沿用分红修订r1冻结结果，重建六组所有目标组合并逐日核对。没有新增策略、参数搜索或账户回测。','',
             '## 主要发现','',
             f'短期反转是本次观察中最不稳定的排名分量：周际平均排名相关为{weekly.loc["reversal5","mean_rank_correlation"]:.4f}，'
             f'动量为{weekly.loc["momentum20","mean_rank_correlation"]:.3f}，低波动为{weekly.loc["lowvol20","mean_rank_correlation"]:.3f}。'
             f'前后都合格的{len(combined_exits)}条周频换出记录中，{reversal_share:.2%}的最大负向排名变化来自反转。','',
             f'这一周际不稳定性跨年份存在：十年逐年平均反转排名相关范围为'
             f'{yearly_reversal.mean_rank_correlation.min():.3f}至{yearly_reversal.mean_rank_correlation.max():.3f}。'
             '上期目标股票的反转排名在下一次重排时经常下降，但不能直接推出删除该因子会改善收益。'
             '5日反转的相邻周窗口通常很少重叠，20日动量及低波动的窗口重叠较多，排名持久性差异部分来自定义。'
             '目标股票本身也是按高分选出，因此后续排名回落还包含选择后的均值回归。','',
             '换入股票的未来平均收益优势很小，双周5日配对差甚至为负。该结果尚未证明频繁换股有足够的净收益补偿；'
             '需要将它与此前成本诊断一起用于后续规则设计，而不是把收盘标签与交易成本直接相减。','',
             '## 排名稳定性','',
             '百分位排名越接近1越优；相关系数是各调仓间共同合格股票的百分位排名相关，再按日期平均。变化幅度按百分位计算。','',
             '| 调仓方案 | 因子 | 平均排名相关 | 全池平均绝对变化 | 上期目标平均变化 |',
             '|---|---|---:|---:|---:|']
    for label in ['combined','combined_biweekly']:
        for row in stats.loc[stats.strategy.eq(label)].itertuples():
            lines.append(f'| {label} | {row.factor} | {row.mean_rank_correlation:.3f} | {row.mean_abs_rank_change:.3f} | {row.previous_target_mean_rank_change:.3f} |')
    lines += ['','## 换出股票的排名变化','',
              '| 方案 | 平均目标保留率 | 换出数 | 当期不再合格 | 最大负向排名分量分布 |',
              '|---|---:|---:|---:|---|']
    for label in ['combined','combined_rank_buffer40','combined_biweekly']:
        subset = exit_frame.loc[exit_frame.strategy.eq(label)]
        counts = subset.largest_negative_component.value_counts()
        description = '；'.join(f'{key}: {value}' for key,value in counts.items())
        r = retention.loc[retention.strategy.eq(label)]
        lines.append(f'| {label} | {r.retention.mean():.2%} | {len(subset)} | {int((~subset.current_eligible).sum())} | {description} |')
    lines += ['','最大负向分量指该股票三项百分位排名变化中降幅最大的一项，仅统计前后都合格的股票。'
              '综合得分变化精确等于三项变化的均值；该拆分描述得分移动，不能解释行业约束、其他股票竞争或证明移除某因子后的因果效果。'
              '不再合格可能涉及流动性、缺失因子、股票池或隔离，本轮未进一步区分这些原因。','',
              '## 换出与换入后的收益','',
              '| 方案 | 后续交易日 | 换出均值及覆盖率 | 换入均值及覆盖率 | 配对日期换入减换出 | 配对日期数 |',
              '|---|---:|---:|---:|---:|---:|']
    for label in ['combined','combined_biweekly']:
        for horizon in (5,20):
            rows = fstats.loc[fstats.strategy.eq(label)&fstats.horizon.eq(horizon)].set_index('role')
            part = paired.xs((label,horizon),level=('strategy','horizon'))
            lines.append(f'| {label} | {horizon} | {rows.loc["exit","mean_return"]:.2%} / {rows.loc["exit","coverage"]:.1%} | '
                         f'{rows.loc["entry","mean_return"]:.2%} / {rows.loc["entry","coverage"]:.1%} | {part.entry_minus_exit.mean():.2%} | {len(part)} |')
    lines += ['','## 各年换入减换出（配对日期均值）','',
              '| 年份 | 周频5日 | 周频20日 | 双周5日 | 双周20日 |',
              '|---|---:|---:|---:|---:|']
    for year in sorted(forward_yearly.year.unique()):
        values=[]
        for label,horizon in [('combined',5),('combined',20),('combined_biweekly',5),('combined_biweekly',20)]:
            row=forward_yearly.loc[forward_yearly.strategy.eq(label)&forward_yearly.year.eq(year)&forward_yearly.horizon.eq(horizon)]
            values.append(f'{row.iloc[0].mean_entry_minus_exit:.2%}' if len(row) else '缺失')
        lines.append(f'| {year} | '+' | '.join(values)+' |')
    lines += ['','未来收益从形成日收盘到第5/20个交易日收盘，使用冻结复权因子对应的连续有效价格窗口；'
              '5日收益由终点reversal5取负，20日收益由终点momentum20取得。缺行情、隔离与窗口结束未满期的记录保留为空并报告覆盖率。'
              '这不是次日开盘可执行收益，也未扣费或模拟分红税；复权价处理与现金股数账本并不等价。缺失可能非随机。','',
              '换出与换入总体均值按股票记录平均，配对列先按同一形成日分别等权平均再求差，最后对有双方有效观测的日期平均。'
              '5/20日标签互有重叠，未给出独立样本显著性或据此挑选参数。','',
              '## 核验与限制','',
              f'六组共{replay_count}个形成日目标代码、权重和得分重建一致。输入指纹、逐日排名、换出分量、未来标签和覆盖率另存。'
              '2016—2025均已使用，本诊断不构成新封存检验；历史ST/行业版本、未闭合复权事件等限制继续存在。','']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(stats.loc[stats.strategy.isin(['combined','combined_biweekly'])].to_string(index=False),flush=True)
    print(check,flush=True)


if __name__ == '__main__':
    main()
