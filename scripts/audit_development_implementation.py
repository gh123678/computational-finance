"""Independent numeric checks of saved targets and execution costs; no optimization."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.corporate_corrections import correct_adjustments


def audit_year(year):
    source = ROOT / 'data' / f'development_{year}'
    output = ROOT / 'output' / f'development_{year}'
    summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    for filename, digest in manifest['files_sha256'].items():
        if hashlib.sha256((source / filename).read_bytes()).hexdigest() != digest:
            raise ValueError(f'{year}: changed data {filename}')
    daily = pd.read_csv(source / 'daily.csv', dtype={'trade_date': str})
    adj = pd.read_csv(source / 'adj_factor.csv', dtype={'trade_date': str})
    daily = daily.merge(adj, on=['ts_code', 'trade_date'], validate='one_to_one')
    daily['trade_date'] = pd.to_datetime(daily.trade_date, format='%Y%m%d')
    daily, _ = correct_adjustments(daily)
    cal = pd.read_csv(source / 'calendar.csv', dtype={'cal_date': str})
    calendar = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1), 'cal_date'])).sort_values()
    calendar = calendar[(calendar >= pd.Timestamp(manifest['start'])) &
                        (calendar <= pd.Timestamp(manifest['end']))]
    locations = {d: i for i, d in enumerate(calendar)}
    raw = {code: g.set_index('trade_date').reindex(calendar)
           for code, g in daily.groupby('ts_code')}
    targets = []
    costs = []
    for experiment in summary['experiments']:
        label = experiment['strategy']
        folder = output / label
        target = pd.read_csv(folder / 'historical_targets.csv', parse_dates=['signal_date', 'execution_date'])
        if not (target.signal_date < target.execution_date).all():
            raise ValueError(f'{year}/{label}: signal timing')
        targets.append(target)
        orders = pd.read_csv(folder / 'orders.csv')
        filled = orders.loc[orders.shares.gt(0)].copy()
        notionals = filled.shares * filled.price
        zero = experiment['config']['zero_trading_costs']
        expected_fee = np.zeros(len(filled)) if zero else np.round(
            np.maximum(5., notionals * .0003) + notionals * .00002 +
            np.where(filled.side.eq('sell'), notionals * .001, 0), 2)
        fee_error = float(np.max(np.abs(expected_fee - filled.fee))) if len(filled) else 0.
        expected_slip = filled.shares * (filled.price - filled.raw_open) * np.where(filled.side.eq('buy'), 1, -1)
        slip_error = float(np.max(np.abs(expected_slip - filled.slippage_cost))) if len(filled) else 0.
        if fee_error > .011 or slip_error > 1e-6 or (expected_slip < -1e-7).any():
            raise ValueError(f'{year}/{label}: fee or slippage reconciliation')
        costs.append(dict(strategy=label, filled_orders=len(filled),
                          max_fee_error=fee_error, max_slippage_error=slip_error))
    unique = pd.concat(targets).drop_duplicates(['signal_date', 'ts_code'])
    errors = dict(momentum20=0., reversal5=0., lowvol20=0., adv20_cny=0.)
    for row in unique.itertuples(index=False):
        end = locations[row.signal_date]
        window = raw[row.ts_code].iloc[end-20:end+1]
        if len(window) != 21 or window.close.isna().any() or window.vol.le(0).any():
            raise ValueError(f'{year}: incomplete selected factor window {row.ts_code}')
        prices = (window.close * window.adj_factor).to_numpy()
        expected = dict(momentum20=prices[-1]/prices[0]-1,
                        reversal5=1-prices[-1]/prices[-6],
                        lowvol20=-np.std(prices[1:]/prices[:-1]-1, ddof=1),
                        adv20_cny=float(window.amount.iloc[-20:].mean()*1000))
        for field, value in expected.items():
            error = abs(float(getattr(row, field))-value)
            errors[field] = max(errors[field], error)
            if not np.isclose(getattr(row, field), value, rtol=1e-10, atol=1e-9):
                raise ValueError(f'{year}: factor mismatch {row.ts_code} {row.signal_date} {field}')
    changed = [name for name, digest in summary['source_sha256'].items()
               if (ROOT / 'quant_research' / name).exists() and
               hashlib.sha256((ROOT / 'quant_research' / name).read_bytes()).hexdigest() != digest]
    return dict(year=year, status='passed', unique_target_windows=len(unique),
                max_factor_errors=errors, cost_checks=costs,
                changed_source_files_since_run=changed,
                unresolved_adjustments=summary['unexplained_adjustments'],
                summary_sha256=hashlib.sha256((output/'summary.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    results = []
    for year in range(2016, 2021):
        result = audit_year(year)
        results.append(result)
        print(f"{year}: {result['unique_target_windows']} windows, costs passed", flush=True)
    destination = ROOT / 'output' / 'development_comparison'
    destination.mkdir(exist_ok=True, parents=True)
    (destination/'implementation_audit.json').write_text(
        json.dumps(dict(scope='Selected targets, factor arithmetic, signal timing and costs; not a full data audit',
                        years=results), indent=2), encoding='utf-8')
