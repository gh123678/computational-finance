"""Reconcile a registered annual run against its calendar and factor inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd


def verify(dataset):
    # This script can be invoked directly without installing the package.
    import sys
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    from quant_research.datasets import dataset_config
    from quant_research.factors import biweekly_schedule
    spec = dataset_config(dataset)
    assert spec['evaluation_start'] is not None
    root = project / 'output' / dataset
    summary = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
    cal = pd.read_csv(project / 'data' / dataset / 'calendar.csv', dtype={'cal_date': str})
    full_dates = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1), 'cal_date'])).sort_values()
    # The exchange calendar also covers history used for listing-age checks.
    # Rebalance phase must begin at the registered study's warmup start,
    # exactly as research.py does, rather than at the first historical session.
    dates = full_dates[(full_dates >= pd.Timestamp(spec['start'])) &
                       (full_dates <= pd.Timestamp(spec['end']))]
    expected = dates[(dates >= pd.Timestamp(spec['evaluation_start'])) & (dates <= pd.Timestamp(spec['end']))]
    baseline = dates[dates < expected[0]][-1]
    factors = pd.read_csv(root / 'factors.csv', parse_dates=['trade_date'])
    columns = ['momentum20', 'reversal5', 'lowvol20']
    expected_strategies = {'combined', *columns, 'liquidity_control', 'combined_slip30',
                           'combined_slip50', 'combined_zero_cost', 'combined_rank_buffer40',
                           'combined_biweekly', 'combined_biweekly_zero_cost', 'combined_biweekly_slip30'}
    assert {x['strategy'] for x in summary['experiments']} == expected_strategies
    assert len(summary['experiments']) == len(expected_strategies)
    checks = []
    for item in summary['experiments']:
        folder = root / item['strategy']
        nav = pd.read_csv(folder / 'nav.csv', parse_dates=['date'])
        orders = pd.read_csv(folder / 'orders.csv', parse_dates=['date'])
        holdings = pd.read_csv(folder / 'holdings.csv')
        monthly = pd.read_csv(folder / 'monthly_returns.csv')
        costs = pd.read_csv(folder / 'cost_attribution.csv')
        targets = pd.read_csv(folder / 'historical_targets.csv', parse_dates=['signal_date', 'execution_date'])
        if item['strategy'].startswith('combined_biweekly'):
            schedule = biweekly_schedule(dates)
            schedule = schedule.loc[schedule.execution_date >= expected[0]]
            pairs = targets[['signal_date', 'execution_date']].drop_duplicates().reset_index(drop=True)
            assert pairs.equals(schedule[['signal_date', 'execution_date']].reset_index(drop=True))
            assert orders.date.isin(schedule.execution_date).all()
        inputs = targets.merge(factors[['ts_code', 'trade_date', *columns]],
                               left_on=['ts_code', 'signal_date'], right_on=['ts_code', 'trade_date'],
                               how='left', validate='many_to_one', suffixes=('', '_source'))
        assert inputs[[c + '_source' for c in columns]].notna().all().all()
        for col in columns:
            assert np.allclose(inputs[col], inputs[col + '_source'], atol=1e-12)
        assert (targets.signal_date < targets.execution_date).all()
        error = (nav.equity - nav[['cash', 'stock_value', 'bonus_value', 'receivable']].sum(axis=1)).abs().max()
        assert error < 1e-6
        assert nav.cash.min() >= 0 and holdings.shares.min() >= 0 and holdings.pending_shares.min() >= 0
        assert orders.date.min() >= expected[0]
        evaluated = nav.loc[nav.date >= expected[0], 'date']
        assert pd.DatetimeIndex(evaluated).equals(expected)
        assert item['sessions'] == len(expected) and item['start'] == str(baseline.date())
        assert len(monthly) == len(expected.to_period('M').unique()) == 12
        assert np.isclose((1 + monthly['return']).prod() - 1, item['total_return'], atol=1e-12)
        assert np.isclose(costs.total_cost.sum(), item['total_fees'] + item['total_slippage'], atol=1e-6)
        assert np.isclose(orders.fee.sum(), item['total_fees'], atol=1e-6)
        assert np.isclose(orders.slippage_cost.sum(), item['total_slippage'], atol=1e-6)
        checks.append(dict(strategy=item['strategy'], maximum_nav_identity_error=float(error),
                           minimum_cash=float(nav.cash.min()), sessions=len(expected)))
    result = dict(status='passed', dataset=dataset, checks=checks,
                  summary_sha256=hashlib.sha256((root / 'summary.json').read_bytes()).hexdigest())
    (root / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', required=True)
    verify(parser.parse_args().dataset)
