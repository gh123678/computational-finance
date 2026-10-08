"""Excess-return review of frozen accounts (read-only).

Reads frozen nav.csv files from two completed experiments and the registered
benchmark series, computes yearly and cumulative excess returns, tracking
error and information ratio. Does not modify any frozen output; writes only
to output/excess_return_review_20261008/.
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'output' / 'excess_return_review_20261008'
BENCH_PATH = ROOT / 'data' / 'continuous_2016_2025_dividend_r1' / 'benchmark.csv'

ML_DIR = ROOT / 'output' / 'open_source_ml_risk_2018_2020_r1'
ML_PATHS = [
    'three_weekly_0bp', 'three_weekly_10bp', 'three_weekly_30bp',
    'three_retention_0bp', 'three_retention_10bp', 'three_retention_30bp',
    'ml_retention_0bp', 'ml_retention_10bp', 'ml_retention_30bp',
    'ml_risk_0bp', 'ml_risk_10bp', 'ml_risk_30bp',
]
ML_LABELS = {
    'three_weekly': '三因子周频', 'three_retention': '三因子保留',
    'ml_retention': 'ML保留', 'ml_risk': 'ML风险预算',
}
TEN_DIR = ROOT / 'output' / 'continuous_2016_2025_dividend_r1'
TEN_PATHS = [
    'combined_zero_cost', 'combined', 'combined_slip30',
    'combined_biweekly_zero_cost', 'combined_biweekly', 'combined_biweekly_slip30',
    'combined_rank_buffer40',
]
TEN_LABELS = {
    'combined_zero_cost': '周频零成本', 'combined': '周频10bp', 'combined_slip30': '周频30bp',
    'combined_biweekly_zero_cost': '双周零成本', 'combined_biweekly': '双周10bp',
    'combined_biweekly_slip30': '双周30bp', 'combined_rank_buffer40': '缓冲40',
}
TRADING_DAYS = 252


def load_benchmark():
    bench = pd.read_csv(BENCH_PATH, dtype={'trade_date': str})
    bench = bench.sort_values('trade_date').reset_index(drop=True)
    bench['ret'] = bench['close'].pct_change()
    return bench[['trade_date', 'close', 'ret']]


UNIVERSE_DAILY = ROOT / 'data' / 'continuous_2016_2025_dividend_r1' / 'daily.csv'


def load_universe_benchmark():
    """Equal-weight mean of daily pct_chg over all main-board rows.

    Approximation: suspended stocks are absent (survivor-of-the-day bias),
    raw price returns miss dividends. Diagnostic only, not a tradable index.
    """
    daily = pd.read_csv(UNIVERSE_DAILY, usecols=['trade_date', 'pct_chg'],
                        dtype={'trade_date': str})
    bench = daily.groupby('trade_date')['pct_chg'].mean().reset_index()
    bench = bench.sort_values('trade_date').reset_index(drop=True)
    bench['ret'] = bench['pct_chg'] / 100.0
    bench['close'] = (1.0 + bench['ret'].fillna(0.0)).cumprod()
    return bench[['trade_date', 'close', 'ret']]


def load_nav(path):
    nav = pd.read_csv(path, dtype={'date': str})
    nav = nav.sort_values('date').reset_index(drop=True)
    nav['date'] = nav['date'].str.replace('-', '', regex=False)
    nav['ret'] = nav['equity'].pct_change()
    return nav[['date', 'equity', 'ret']]


def max_drawdown(equity):
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def analyse(nav, bench, start, end):
    merged = nav.merge(bench, left_on='date', right_on='trade_date', how='inner')
    anchor = merged[merged['date'] < start]
    if anchor.empty:
        raise ValueError(f'no anchor before {start}')
    anchor = anchor.iloc[-1]
    merged = merged[(merged['date'] >= start) & (merged['date'] <= end)].copy()
    if merged.empty:
        raise ValueError(f'empty window {start}..{end}')
    merged['excess'] = merged['ret_x'] - merged['ret_y']
    # Rebase at the last session before the window so the first window day's
    # move is counted, matching the project convention of prior year-end equity.
    anchor_equity = float(anchor['equity'])
    anchor_close = float(anchor['close'])
    merged['strat_index'] = merged['equity'] / anchor_equity
    merged['bench_index'] = merged['close'] / anchor_close
    merged['excess_index'] = merged['strat_index'] / merged['bench_index']

    merged['year'] = merged['date'].str[:4]
    yearly = []
    prev_s = prev_b = 1.0
    for year, g in merged.groupby('year'):
        end_s = float(g['strat_index'].iloc[-1])
        end_b = float(g['bench_index'].iloc[-1])
        s = end_s / prev_s - 1
        b = end_b / prev_b - 1
        prev_s, prev_b = end_s, end_b
        yearly.append(dict(year=year, strategy_return=s, benchmark_return=b,
                           excess_return=(1 + s) / (1 + b) - 1))
    ex = merged['excess'].dropna()
    n = len(ex)
    ann_excess = float(ex.mean() * TRADING_DAYS)
    te = float(ex.std(ddof=1) * np.sqrt(TRADING_DAYS)) if n > 1 else float('nan')
    ir = ann_excess / te if te and te > 0 else float('nan')
    summary = dict(
        sessions=int(len(merged)),
        strategy_cumulative=float(merged['strat_index'].iloc[-1] - 1),
        benchmark_cumulative=float(merged['bench_index'].iloc[-1] - 1),
        excess_cumulative=float(merged['excess_index'].iloc[-1] - 1),
        annualized_excess=ann_excess,
        tracking_error=te,
        information_ratio=ir,
        strategy_max_drawdown=max_drawdown(merged['strat_index']),
        benchmark_max_drawdown=max_drawdown(merged['bench_index']),
    )
    return merged, yearly, summary


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    benchmarks = {
        'csi300_price': load_benchmark(),
        'mainboard_equal_weight': load_universe_benchmark(),
    }
    bench_ranges = {k: (v['trade_date'].iloc[0], v['trade_date'].iloc[-1])
                    for k, v in benchmarks.items()}

    all_summary, all_yearly = [], []
    curves = {}

    jobs = []
    for name in ML_PATHS:
        nav = load_nav(ML_DIR / name / 'nav.csv')
        label = ML_LABELS[name.rsplit('_', 1)[0]] + '_' + name.rsplit('_', 1)[1]
        jobs.append(('ml_2018_2020', name, label, nav, '20171229', '20201231',
                     name.endswith(('0bp', '10bp'))))
    for name in TEN_PATHS:
        nav = load_nav(TEN_DIR / name / 'nav.csv')
        jobs.append(('continuous_2016_2025_r1', name, TEN_LABELS[name], nav,
                     '20160101', '20251231',
                     name in ('combined_zero_cost', 'combined',
                              'combined_biweekly', 'combined_rank_buffer40')))

    for bench_name, bench in benchmarks.items():
        for experiment, name, label, nav, start, end, in_chart in jobs:
            merged, yearly, summary = analyse(nav, bench, start, end)
            summary.update(experiment=experiment, path=name, label=label,
                           benchmark=bench_name)
            for row in yearly:
                row.update(experiment=experiment, path=name, label=label,
                           benchmark=bench_name)
            all_summary.append(summary)
            all_yearly.extend(yearly)
            if in_chart:
                key = ('ML实验·' if experiment == 'ml_2018_2020' else '十年·') + label
                curves.setdefault(key, {})[bench_name] = merged[['date', 'excess_index']]

    pd.DataFrame(all_summary).to_csv(OUT / 'excess_summary.csv', index=False)
    pd.DataFrame(all_yearly).to_csv(OUT / 'yearly_excess.csv', index=False)

    fig, axes = plt.subplots(2, 1, figsize=(11, 9), sharex=False)
    palette = plt.cm.tab20(np.linspace(0, 1, 20))
    for ax, bench_name, title in zip(
            axes, ['csi300_price', 'mainboard_equal_weight'],
            ['相对沪深300价格指数', '相对主板等权基准（停牌日缺失、未含分红，仅诊断）']):
        for i, (label, pair) in enumerate(curves.items()):
            curve = pair[bench_name]
            ax.plot(pd.to_datetime(curve['date']), curve['excess_index'],
                    label=label, linewidth=1.1, color=palette[i % 20])
        ax.axhline(1.0, color='grey', linewidth=0.8, linestyle='--')
        ax.set_title('冻结账户累计超额净值：' + title)
        ax.set_ylabel('策略净值 / 基准净值（起点=1）')
        ax.legend(fontsize=8, ncol=2)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / 'cumulative_excess.png', dpi=130)

    meta = dict(benchmarks={
                    'csi300_price': '000300.SH 价格指数（未含分红、不可直接投资）',
                    'mainboard_equal_weight': '主板全部日线 pct_chg 当日等权平均；停牌股票当日缺席，'
                                              '未含分红，仅作诊断基准，不可直接投资'},
                benchmark_ranges=bench_ranges,
                note='只读复核；未修改任何冻结输出。等权基准与策略股票池过滤规则（上市时长、'
                     '风险警示等）不完全一致，超额收益含残余构成差异。')
    (OUT / 'review_meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    summary_df = pd.DataFrame(all_summary)
    cols = ['label', 'benchmark', 'strategy_cumulative', 'benchmark_cumulative',
            'excess_cumulative', 'annualized_excess', 'tracking_error',
            'information_ratio', 'strategy_max_drawdown']
    for experiment in ('ml_2018_2020', 'continuous_2016_2025_r1'):
        print('==', experiment)
        print(summary_df[summary_df.experiment == experiment][cols].to_string(index=False))
        print()
    print('benchmark ranges:', bench_ranges)


if __name__ == '__main__':
    main()
