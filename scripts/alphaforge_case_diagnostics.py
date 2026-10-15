"""Formation-date diagnostics and plots for the approved AlphaForge case study.

``D_label`` is next-open to following-open stock return minus the benchmark
return.  Its group means and IC sums are diagnostics, never account NAV.
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd


FACTORS = ('case_factor', 'case_signal', 'three_score')
IC_COLUMNS = ['signal_date', 'execution_date', 'year', 'factor', 'n_formed',
              'n', 'n_valid', 'label_coverage', 'coverage', 'ic', 'rank_ic']
GROUP_COLUMNS = ['signal_date', 'execution_date', 'year', 'factor', 'group',
                 'n_formed', 'n', 'n_valid', 'coverage', 'mean_forward_return']


def _valid_flags(series):
    """Parse saved Boolean labels without treating the string 'False' as true."""
    values = series.astype('string').str.lower()
    accepted = values.isin(['true', 'false', '1', '0']) | values.isna()
    if not accepted.all():
        raise ValueError('Unrecognized D_valid flag')
    return values.isin(['true', '1']).fillna(False).to_numpy(dtype=bool)


def diagnostics(samples, schedule):
    """Return weekly IC and fixed-five-group diagnostics for 2018--2020.

    Buckets are ``ceil(average_tie_percentile_rank * 5)`` on finite formation
    values.  Missing future labels cannot alter bucket membership.  At least
    ten valid labels and two nonconstant vectors are required for IC; group
    means need at least two valid labels.  Missing statistics remain NaN.
    """
    required = {'trade_date', 'ts_code', 'D_label', 'D_valid', *FACTORS}
    if not required.issubset(samples.columns):
        raise ValueError('Missing diagnostic sample fields: ' + ', '.join(sorted(required - set(samples.columns))))
    if not {'signal_date', 'execution_date'}.issubset(schedule.columns):
        raise ValueError('Schedule requires signal_date and execution_date')
    frame = samples.copy()
    frame['trade_date'] = pd.to_datetime(frame.trade_date)
    if frame.duplicated(['trade_date', 'ts_code']).any():
        raise ValueError('Duplicate diagnostic asset/date')
    for column in [*FACTORS, 'D_label']:
        frame[column] = pd.to_numeric(frame[column], errors='raise').replace([np.inf, -np.inf], np.nan)
    finite_original = frame.case_factor.notna()
    finite_signal = frame.case_signal.notna()
    if not finite_original.equals(finite_signal) or not np.array_equal(
            frame.loc[finite_original, 'case_signal'].to_numpy(),
            -frame.loc[finite_original, 'case_factor'].to_numpy()):
        raise ValueError('case_signal must be the negative of case_factor with identical missingness')
    frame['_label_valid'] = _valid_flags(frame.D_valid) & frame.D_label.notna().to_numpy()
    evaluated = schedule.copy()
    evaluated['signal_date'] = pd.to_datetime(evaluated.signal_date)
    evaluated['execution_date'] = pd.to_datetime(evaluated.execution_date)
    evaluated = evaluated.loc[evaluated.execution_date.between('2018-01-01', '2020-12-31')]
    if evaluated.signal_date.duplicated().any() or evaluated.execution_date.duplicated().any():
        raise ValueError('Duplicate evaluation schedule date')
    if evaluated[['signal_date', 'execution_date']].isna().any().any() or not (
            evaluated.signal_date < evaluated.execution_date).all():
        raise ValueError('Signals must precede execution')
    by_date = {date: group for date, group in frame.groupby('trade_date')}
    ic_rows, group_rows = [], []
    for row in evaluated.sort_values('execution_date').itertuples(index=False):
        cross_section = by_date.get(row.signal_date, frame.iloc[:0])
        for factor in FACTORS:
            formed = cross_section.loc[cross_section[factor].notna()].copy()
            formed['_group'] = np.ceil(formed[factor].rank(method='average', pct=True) * 5).clip(1, 5)
            valid = formed.loc[formed._label_valid]
            sufficient = len(valid) >= 10 and valid[factor].nunique() > 1 and valid.D_label.nunique() > 1
            ic = valid[factor].corr(valid.D_label) if sufficient else np.nan
            rank_ic = valid[factor].rank(method='average').corr(valid.D_label.rank(method='average')) if sufficient else np.nan
            metadata = dict(signal_date=row.signal_date, execution_date=row.execution_date,
                            year=row.execution_date.year, factor=factor)
            coverage = len(valid) / len(formed) if len(formed) else np.nan
            ic_rows.append(dict(metadata, n_formed=len(formed), n=len(valid), n_valid=len(valid),
                                label_coverage=coverage, coverage=coverage, ic=ic, rank_ic=rank_ic))
            for bucket in range(1, 6):
                members = formed.loc[formed._group.eq(bucket)]
                observed = members.loc[members._label_valid]
                group_rows.append(dict(metadata, group=bucket, n_formed=len(members), n=len(observed),
                                       n_valid=len(observed), coverage=len(observed)/len(members) if len(members) else np.nan,
                                       mean_forward_return=float(observed.D_label.mean()) if len(observed) >= 2 else np.nan))
    return pd.DataFrame(ic_rows, columns=IC_COLUMNS), pd.DataFrame(group_rows, columns=GROUP_COLUMNS)


def summarize_ic(ic):
    """All-period and execution-year IC means/IR; ddof=1, not annualized.

    An exactly constant or single-observation IC series has undefined IR.
    """
    rows = []
    for factor in FACTORS:
        selected = ic.loc[ic.factor.eq(factor)]
        periods = [('all', selected)] + [(str(int(year)), group) for year, group in selected.groupby('year')]
        for period, group in periods:
            result = dict(factor=factor, period=period, formed_periods=len(group), annualized=False, std_ddof=1)
            for statistic in ('ic', 'rank_ic'):
                values = pd.to_numeric(group[statistic], errors='coerce').replace([np.inf, -np.inf], np.nan).dropna()
                mean = float(values.mean()) if len(values) else np.nan
                std = float(values.std(ddof=1)) if len(values) >= 2 else np.nan
                ir = mean/std if len(values) >= 2 and values.nunique() > 1 and std > 0 else np.nan
                result.update({statistic+'_n': len(values), statistic+'_mean': mean,
                               statistic+'_std': std, statistic+'_ir': ir})
            rows.append(result)
    return pd.DataFrame(rows)


def render_figures(out):
    """Read saved diagnostics and real account ledgers; return relative PNG paths.

    Required: factor_ic.csv, factor_groups.csv, common_samples.csv, summary.json
    and each completed experiment's <strategy>/nav.csv.  feature_coverage.csv is
    optional.  Plotting never synthesizes a NAV by compounding forward labels.
    """
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt, font_manager, dates as mdates
    from matplotlib.ticker import PercentFormatter

    root = Path(out)
    ic = pd.read_csv(root/'factor_ic.csv', parse_dates=['signal_date', 'execution_date'])
    groups = pd.read_csv(root/'factor_groups.csv', parse_dates=['signal_date', 'execution_date'])
    samples = pd.read_csv(root/'common_samples.csv', usecols=['trade_date', *FACTORS], parse_dates=['trade_date'])
    summary = json.loads((root/'summary.json').read_text(encoding='utf-8'))
    destination = root/'figures'
    destination.mkdir(exist_ok=True)
    available = {font.name for font in font_manager.fontManager.ttflist}
    font = next((name for name in ('Microsoft YaHei', 'SimHei', 'SimSun', 'Noto Sans CJK SC', 'Arial Unicode MS') if name in available), 'DejaVu Sans')
    paths = []

    def save(figure, filename):
        for axis in figure.axes:
            if isinstance(axis.xaxis.get_major_locator(), mdates.DateLocator):
                locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
                axis.xaxis.set_major_locator(locator)
                axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        figure.tight_layout(rect=(0, .025, 1, .955))
        figure.savefig(destination/filename, dpi=160, facecolor='white')
        plt.close(figure)
        paths.append('figures/' + filename)

    names = {'case_factor': '原公式 f', 'case_signal': '预先固定方向 −f', 'three_score': '同池旧三因子'}
    with plt.rc_context({'font.family': 'sans-serif', 'font.sans-serif': [font], 'axes.unicode_minus': False}):
        figure, axes = plt.subplots(3, 2, figsize=(15, 11), squeeze=False)
        for index, factor in enumerate(FACTORS):
            subset = ic.loc[ic.factor.eq(factor)].sort_values('execution_date')
            for statistic, label in [('ic', 'IC'), ('rank_ic', 'RankIC')]:
                axes[index, 0].plot(subset.execution_date, subset[statistic], label=label, linewidth=1)
                axes[index, 1].plot(subset.execution_date, subset[statistic].cumsum(), label=label + ' 逐期和', linewidth=1)
            for axis in axes[index]:
                axis.axhline(0, color='grey', linewidth=.6)
                axis.legend(fontsize=8)
                axis.grid(alpha=.2)
            axes[index, 0].set_title(names[factor] + '：逐期相关系数')
            axes[index, 1].set_title(names[factor] + '：累计相关系数（非净值）')
        figure.suptitle('每周形成截面 IC / RankIC；至少10个有效标签，非常量才计算')
        save(figure, 'factor_ic.png')

        figure, axes = plt.subplots(3, 2, figsize=(15, 11), squeeze=False)
        finite_means = groups.mean_forward_return.dropna().to_numpy()
        color_limit = max(float(np.max(np.abs(finite_means))) if len(finite_means) else 0, .001)
        for index, factor in enumerate(FACTORS):
            subset = groups.loc[groups.factor.eq(factor)]
            mean = subset.groupby('group').mean_forward_return.mean().reindex(range(1, 6))
            axes[index, 0].plot(mean.index, mean.values, marker='o')
            axes[index, 0].set_xticks(range(1, 6))
            axes[index, 0].set_xlabel('形成日因子值由低到高的固定五组')
            axes[index, 0].yaxis.set_major_formatter(PercentFormatter(1))
            axes[index, 0].axhline(0, color='grey', linewidth=.6)
            axes[index, 0].set_title(names[factor] + '：各期组内均值的等权均值')
            heat = subset.pivot_table(index='year', columns='group', values='mean_forward_return', aggfunc='mean').reindex(index=[2018, 2019, 2020], columns=range(1, 6))
            image = axes[index, 1].imshow(np.ma.masked_invalid(heat.to_numpy()), cmap='RdBu_r', aspect='auto', vmin=-color_limit, vmax=color_limit)
            axes[index, 1].set_xticks(range(5), labels=range(1, 6))
            axes[index, 1].set_yticks(range(3), labels=[2018, 2019, 2020])
            axes[index, 1].set_title(names[factor] + '：按执行年分层')
            for y, values in enumerate(heat.to_numpy()):
                for x, value in enumerate(values):
                    axes[index, 1].text(x, y, f'{value:.2%}' if np.isfinite(value) else '缺失', ha='center', va='center', fontsize=8)
            figure.colorbar(image, ax=axes[index, 1], format=PercentFormatter(1), fraction=.03)
        figure.suptitle('组内未来周收益减基准：诊断性超额收益，不含成本，不是账户收益')
        figure.text(.02, .008, '先用形成日信息固定组别，再连接标签；每组至少2个有效标签。未构造多空账户或复利标签。', fontsize=9)
        save(figure, 'factor_groups.png')

        figure, axes = plt.subplots(2, 2, figsize=(15, 10))
        for factor in FACTORS:
            subset = ic.loc[ic.factor.eq(factor)].sort_values('execution_date')
            axes[0, 0].plot(subset.execution_date, subset.n_formed, label=names[factor])
            axes[0, 1].plot(subset.execution_date, subset.label_coverage, label=names[factor])
            values = samples[factor].replace([np.inf, -np.inf], np.nan).dropna()
            if len(values):
                axes[1, 0].hist(values, bins=50, density=True, histtype='step', label=names[factor])
        axes[0, 0].set_title('形成截面：有限因子值股票数')
        axes[0, 1].set_title('形成截面有效未来标签覆盖率')
        axes[0, 1].set_ylim(0, 1.02)
        axes[0, 1].yaxis.set_major_formatter(PercentFormatter(1))
        axes[1, 0].set_title('全部形成期因子值分布（数值口径不同，非可比尺度）')
        coverage_path = root/'feature_coverage.csv'
        if coverage_path.exists():
            coverage = pd.read_csv(coverage_path)
            if 'reason' in coverage:
                counts = coverage.reason.fillna('缺失原因').value_counts().head(8)
                axes[1, 1].barh(counts.index.astype(str), counts.values)
                axes[1, 1].set_title('逐股逐期因子覆盖记录：原因计数')
            else:
                axes[1, 1].text(.1, .5, '覆盖文件未提供 reason 字段', transform=axes[1, 1].transAxes)
        else:
            axes[1, 1].text(.1, .5, '没有额外覆盖原因文件；上图仅为共同池覆盖', transform=axes[1, 1].transAxes)
        for axis in [axes[0, 0], axes[0, 1], axes[1, 0]]:
            axis.legend(fontsize=8)
            axis.grid(alpha=.2)
        figure.suptitle('因子形成与标签覆盖；缺标签未改变形成分组')
        save(figure, 'factor_coverage.png')

        figure, axes = plt.subplots(2, 2, figsize=(16, 11))
        experiments = summary.get('experiments', [])
        labels, fees, slippages, returns = [], [], [], []
        for experiment in experiments:
            strategy = experiment['strategy']
            path = experiment.get('path', '')
            name = '旧三因子' if 'three' in path else ('案例 −f' if 'alphaforge' in path or 'case' in path else strategy)
            bps = experiment.get('config', {}).get('slippage_bps')
            label = f'{name} {bps}bp' if name != strategy and bps is not None else name
            nav_path = root/strategy/'nav.csv'
            if not nav_path.exists():
                raise ValueError('Missing actual account NAV: ' + strategy)
            nav = pd.read_csv(nav_path, parse_dates=['date']).sort_values('date')
            if nav.empty or not np.isfinite(nav.equity).all() or nav.equity.iloc[0] <= 0:
                raise ValueError('Invalid actual account NAV: ' + strategy)
            axes[0, 0].plot(nav.date, nav.equity/nav.equity.iloc[0], label=label, linewidth=1)
            axes[0, 1].plot(nav.date, nav.equity/nav.equity.cummax()-1, label=label, linewidth=1)
            labels.append(label)
            fees.append(experiment.get('total_fees', np.nan))
            slippages.append(experiment.get('total_slippage', np.nan))
            returns.append(experiment.get('total_return', np.nan))
        axes[0, 0].set_title('真实账户净值：首日权益归一为1')
        axes[0, 1].set_title('真实账户历史最大权益至当日的回撤')
        axes[0, 1].yaxis.set_major_formatter(PercentFormatter(1))
        for axis in axes[0]:
            axis.legend(fontsize=7)
            axis.grid(alpha=.2)
        positions = np.arange(len(labels))
        axes[1, 0].bar(positions, fees, label='账本费用')
        axes[1, 0].bar(positions, slippages, bottom=fees, label='滑点成本')
        axes[1, 0].set_title('实际账户成本归因（人民币元）')
        axes[1, 0].legend(fontsize=8)
        axes[1, 1].bar(positions, returns)
        axes[1, 1].set_title('实际账户全期累计收益')
        axes[1, 1].yaxis.set_major_formatter(PercentFormatter(1))
        axes[1, 1].axhline(0, color='grey', linewidth=.6)
        for axis in axes[1]:
            axis.set_xticks(positions, labels=labels, rotation=30, ha='right', fontsize=7)
        figure.suptitle(f'{len(experiments)}个固定真实账户：净值、回撤、成本与收益（非标签复利）')
        save(figure, 'account_performance.png')
    return paths
