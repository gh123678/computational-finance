import json
from pathlib import Path
import numpy as np
import pandas as pd

root = Path('output/development_2020')
summary = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
assert len(summary['experiments']) == 8
checks = []
for item in summary['experiments']:
    folder = root / item['strategy']
    nav = pd.read_csv(folder / 'nav.csv', parse_dates=['date'])
    orders = pd.read_csv(folder / 'orders.csv', parse_dates=['date'])
    holdings = pd.read_csv(folder / 'holdings.csv')
    monthly = pd.read_csv(folder / 'monthly_returns.csv')
    costs = pd.read_csv(folder / 'cost_attribution.csv')
    error = (nav.equity - nav[['cash', 'stock_value', 'bonus_value', 'receivable']].sum(axis=1)).abs().max()
    assert error < 1e-6
    assert nav.cash.min() >= 0 and holdings.shares.min() >= 0 and holdings.pending_shares.min() >= 0
    assert orders.date.min() >= pd.Timestamp('2020-01-01')
    assert item['sessions'] == 243 and item['start'] == '2019-12-31'
    assert len(monthly) == 12
    assert np.isclose((1 + monthly['return']).prod() - 1, item['total_return'], atol=1e-12)
    assert np.isclose(costs.total_cost.sum(), item['total_fees'] + item['total_slippage'], atol=1e-6)
    assert np.isclose(orders.fee.sum(), item['total_fees'], atol=1e-6)
    assert np.isclose(orders.slippage_cost.sum(), item['total_slippage'], atol=1e-6)
    checks.append(dict(strategy=item['strategy'], maximum_nav_identity_error=float(error),
                       minimum_cash=float(nav.cash.min()), months=len(monthly),
                       first_order=str(orders.date.min().date()),
                       rejected_reasons=orders.loc[orders.status.eq('rejected'), 'reason'].value_counts().to_dict()))
result = dict(status='passed', checks=checks)
(root / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
