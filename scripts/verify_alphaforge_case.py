"""Independent formula, formation, target and real-share ledger verification.

This verifier never fits a model, runs an account or changes a frozen input.
Engineering checks and the predeclared strategy gates are separate results.
"""
from collections import defaultdict
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
import traceback

import numpy as np
import pandas as pd
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.backtest import Config, summarize
from quant_research.corporate_corrections import correct_adjustments
from quant_research.factors import FACTORS, weekly_schedule
from retention_selector import select_retention
from run_retention_development import read_subset, sha

DATA = ROOT / 'data/continuous_2016_2025_dividend_r1'
OUT = ROOT / 'output/alphaforge_case_2018_2020_r1'
OLD = ROOT / 'output/price_amount_ridge_2018_2020_r1'
PATHS = ('case_negative_retention_common200', 'three_retention_case_common200')
PRIMARY = PATHS[0]
DIAGNOSTIC_FACTORS = ('case_factor', 'case_signal', 'three_score')
PRIOR_DIRECTORIES = ('label_horizon_coverage_2018_2020_r1',
                     'open_source_ml_risk_2018_2020_r1',
                     'price_amount_ridge_2018_2020_r1')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def persist(name, value, out=OUT):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def check_fingerprints(protocol):
    for name, expected in protocol['inputs'].items():
        assert sha(ROOT / name) == expected, 'Input changed: ' + name
    for name, expected in protocol['external_inputs'].items():
        assert sha(Path(name)) == expected, 'External source changed: ' + name
    core = {p.name: sha(p) for p in (ROOT / 'quant_research').glob('*.py')}
    assert core == protocol['source_sha256'], 'Frozen account core changed'
    # All market files consumed by the frozen account adapter are checked,
    # including dividends, suspensions and limits rather than just prices.
    manifest = read_json(DATA / 'manifest.json')['files_sha256']
    assert {'daily.csv', 'adj_factor.csv', 'calendar.csv', 'benchmark.csv',
            'stk_limit.csv', 'suspend_d.csv', 'dividend.csv'}.issubset(manifest)
    for name, expected in manifest.items():
        assert sha(DATA / name) == expected, 'Market manifest mismatch: ' + name
    prior = protocol['prior_artifact_manifests']
    expected_paths = {str((ROOT / 'output' / name / 'output_sha256.json').relative_to(ROOT))
                      for name in PRIOR_DIRECTORIES}
    assert {str(Path(name)) for name in prior} == expected_paths
    counts = {}
    for name, expected in prior.items():
        path = ROOT / name
        assert sha(path) == expected, 'Prior manifest changed: ' + name
        entries = read_json(path)
        for item, digest in entries.items():
            assert sha(path.parent / item) == digest, 'Prior artifact changed: ' + item
        counts[path.parent.name] = len(entries)
    return counts


def scalar_formula(close, volume_lots):
    """Separate ten-point scalar arithmetic; no production factor import."""
    assert len(close) == len(volume_lots) == 10
    left = [float(v) for v in close]
    right = [float(v) * 100.0 for v in volume_lots]
    left_mean, right_mean = sum(left) / 10, sum(right) / 10
    x = [v - left_mean for v in left]
    y = [v - right_mean for v in right]
    nlvar = sum(v * v for v in x)
    nrvar = sum(v * v for v in y)
    guard = nlvar < 1e-6 or nrvar < 1e-6
    denominator = 1.0 if guard else math.sqrt(nlvar * nrvar)
    rho = sum(a * b for a, b in zip(x, y)) / denominator
    factor = math.copysign(math.log1p(abs(rho)), rho) if rho else 0.0
    return dict(case_factor=factor, case_signal=-factor, case_rho=rho,
                case_nlvar=nlvar, case_nrvar=nrvar, case_guard=guard)


def verify_formation(common, base, calendar, bars):
    """Derive the entire eligible intersection before looking at any label."""
    key = ['trade_date', 'ts_code']
    assert not common.duplicated(key).any() and not base.duplicated(key).any()
    expected_keys = []
    maximum_error = 0.0
    checked = guarded = 0
    saved = common.set_index(key)
    grouped_base = {c: g for c, g in base.groupby('ts_code')}
    assert set(grouped_base).issubset(set(bars.ts_code))
    for code, quotes in bars.groupby('ts_code', sort=True):
        if code not in grouped_base:
            continue
        assert not quotes.trade_date.duplicated().any()
        q = quotes.set_index('trade_date').reindex(calendar)
        values = q[['close', 'vol', 'adj_factor']].to_numpy(dtype=float)
        for day in grouped_base[code].trade_date:
            pos = calendar.get_loc(day)
            if pos < 9:
                continue
            window = values[pos - 9:pos + 1]
            eligible = (np.isfinite(window).all() and (window > 0).all()
                        and (window[:, 2] == window[0, 2]).all())
            if not eligible:
                continue
            result = scalar_formula(window[:, 0], window[:, 1])
            if not all(math.isfinite(result[k]) for k in result if k != 'case_guard'):
                continue
            row_key = (day, code)
            expected_keys.append(row_key)
            assert row_key in saved.index, 'Eligible formation omitted: ' + str(row_key)
            row = saved.loc[row_key]
            assert bool(row.case_guard) == result['case_guard']
            for name in ('case_factor', 'case_signal', 'case_rho'):
                error = abs(float(row[name]) - result[name])
                maximum_error = max(maximum_error, error)
                assert math.isclose(float(row[name]), result[name], rel_tol=0, abs_tol=1e-10), (row_key, name)
            for name in ('case_nlvar', 'case_nrvar'):
                assert math.isclose(float(row[name]), result[name], rel_tol=2e-12, abs_tol=1e-10), (row_key, name)
            if 'volume_scale' in common:
                assert row.volume_scale == 100
            if 'case_valid' in common:
                assert bool(row.case_valid)
            checked += 1
            guarded += int(result['case_guard'])
    assert set(saved.index) == set(expected_keys), 'Formation pool differs from past-only intersection'
    original = base.set_index(key)
    for name in ('industry', 'D_label', 'D_valid', 'D_end', 'reference_end', *FACTORS):
        pd.testing.assert_series_equal(saved[name], original.loc[saved.index, name], check_names=False)
    sizes = common.groupby('trade_date').size()
    assert len(sizes) and sizes.ge(200).all(), 'Fewer than 200 eligible assets on a formation date'
    return dict(feature_rows_checked=checked, maximum_factor_error=maximum_error,
                source_epsilon_guard_rows=guarded, smallest_cross_section=int(sizes.min()),
                future_label_used_for_formation=False)


def _correlation(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    x, y = x - x.mean(), y - y.mean()
    denominator = float(np.sqrt(np.dot(x, x) * np.dot(y, y)))
    return float(np.dot(x, y) / denominator) if denominator else np.nan


def independent_diagnostics(common, schedule):
    """Ranks are fixed across the formed pool before missing labels are removed."""
    ics, groups = [], []
    frames = {d: g for d, g in common.groupby('trade_date')}
    for day in schedule.itertuples(index=False):
        frame = frames[day.signal_date]
        label = frame.D_label.to_numpy(dtype=float)
        valid_label = frame.D_valid.to_numpy(dtype=bool) & np.isfinite(label)
        for factor in DIAGNOSTIC_FACTORS:
            x = frame[factor].to_numpy(dtype=float)
            formed = np.isfinite(x)
            x, y, valid = x[formed], label[formed], valid_label[formed]
            n_formed, n = len(x), int(valid.sum())
            sufficient = n >= 10 and np.unique(x[valid]).size > 1 and np.unique(y[valid]).size > 1
            ic = _correlation(x[valid], y[valid]) if sufficient else np.nan
            rank_ic = _correlation(rankdata(x[valid], method='average'),
                                   rankdata(y[valid], method='average')) if sufficient else np.nan
            ics.append(dict(signal_date=day.signal_date, factor=factor, n_formed=n_formed,
                            n=n, ic=ic, rank_ic=rank_ic))
            bucket = np.minimum(5, np.maximum(1, np.ceil(rankdata(x, method='average') / n_formed * 5)))
            for number in range(1, 6):
                membership = bucket == number
                selected = membership & valid
                count = int(selected.sum())
                groups.append(dict(signal_date=day.signal_date, factor=factor, group=number,
                                   n_formed=int(membership.sum()), n=count,
                                   mean_forward_return=float(np.mean(y[selected])) if count >= 2 else np.nan))
    return pd.DataFrame(ics), pd.DataFrame(groups)


def verify_diagnostics(common, schedule, out=OUT):
    expected_ic, expected_groups = independent_diagnostics(common, schedule)
    for name, expected, key, numeric in (
            ('factor_ic.csv', expected_ic, ['signal_date', 'factor'], ['n_formed', 'n', 'ic', 'rank_ic']),
            ('factor_groups.csv', expected_groups, ['signal_date', 'factor', 'group'],
             ['n_formed', 'n', 'mean_forward_return'])):
        observed = pd.read_csv(out / name, parse_dates=['signal_date'], float_precision='round_trip')
        assert not observed.duplicated(key).any()
        left, right = observed.set_index(key).sort_index(), expected.set_index(key).sort_index()
        assert left.index.equals(right.index), name + ' diagnostic keys differ'
        np.testing.assert_allclose(left[numeric], right[numeric], rtol=0, atol=1e-12, equal_nan=True)
        if 'label_coverage' in observed:
            np.testing.assert_allclose(observed.label_coverage, observed.n / observed.n_formed,
                                       rtol=0, atol=1e-12, equal_nan=True)
    return expected_ic


def strategy_gates(stats, annual, ic, schedule):
    """Evaluate the sole predeclared primary without promoting a control."""
    primary = stats.loc[PRIMARY + '_10bp']
    selected = ic.loc[ic.factor.eq('case_signal')].copy()
    selected = selected.drop(columns=['year', 'execution_date'], errors='ignore').merge(
        schedule, on='signal_date', validate='one_to_one')
    selected['year'] = selected.execution_date.dt.year
    mean_ic = float(selected.rank_ic.mean())
    yearly_ic = selected.groupby('year').rank_ic.mean()
    returns = annual.loc[annual.strategy.eq(PRIMARY + '_10bp')]
    assert set(returns.year) == {2018, 2019, 2020} and len(returns) == 3
    gates = dict(net_positive_10and30=bool(primary.total_return > 0 and stats.loc[PRIMARY + '_30bp', 'total_return'] > 0),
                 beats_same_pool_control=bool(primary.total_return > stats.loc[PATHS[1] + '_10bp', 'total_return']),
                 drawdown_at_most_25pct=bool(primary.max_drawdown <= .25),
                 two_positive_return_years=bool(returns.return_value.gt(0).sum() >= 2),
                 rankIC_positive=bool(mean_ic > 0),
                 two_positive_rankIC_years=bool(yearly_ic.gt(0).sum() >= 2))
    return gates, mean_ic, yearly_ic


def verify_targets(common, schedule, out=OUT):
    targets = {p: pd.read_csv(out / f'targets_{p}.csv',
                             parse_dates=['trade_date', 'signal_date', 'execution_date'],
                             float_precision='round_trip') for p in PATHS}
    previous = {p: set() for p in PATHS}
    for row in schedule.itertuples(index=False):
        frame = common.loc[common.trade_date.eq(row.signal_date)]
        old_score = np.mean(np.column_stack([rankdata(frame[f], method='average') / len(frame)
                                            for f in FACTORS]), axis=1)
        np.testing.assert_allclose(frame.three_score, old_score, rtol=0, atol=1e-12)
        values = {PRIMARY: rankdata(frame.case_signal, method='average') / len(frame),
                  PATHS[1]: old_score}
        for path in PATHS:
            score = frame[['trade_date', 'ts_code', 'industry']].copy()
            score['score'] = values[path]
            selected, _ = select_retention(score, previous[path])
            previous[path] = set(selected.ts_code)
            saved = targets[path].loc[targets[path].signal_date.eq(row.signal_date)].sort_values('ts_code')
            selected = selected.sort_values('ts_code')
            assert list(saved.ts_code) == list(selected.ts_code), (path, row.signal_date)
            assert saved.execution_date.eq(row.execution_date).all()
            np.testing.assert_allclose(saved.target_weight, selected.target_weight, rtol=0, atol=1e-12)
            np.testing.assert_allclose(saved.score, selected.score, rtol=0, atol=1e-12)
    for path, target in targets.items():
        assert not target.duplicated(['execution_date', 'ts_code']).any()
        pairs = target[['signal_date', 'execution_date']].drop_duplicates().reset_index(drop=True)
        assert pairs.equals(schedule[['signal_date', 'execution_date']].reset_index(drop=True))
    return targets


def reconstruct_account(nav, orders, events, holdings, initial_cash=1_000_000., boundary_start_year=2018):
    """Rebuild cash, ordinary shares, pending shares and receivables from logs."""
    assert not nav.date.duplicated().any() and nav.date.is_monotonic_increasing
    assert not holdings.duplicated(['date', 'ts_code']).any()
    assert orders.date.isin(nav.date).all() and events.date.isin(nav.date).all()
    assert holdings.date.isin(nav.date).all()
    assert orders.shares.ge(0).all() and orders.shares.eq(orders.shares.astype(int)).all()
    rejected = orders.loc[orders.status.eq('rejected')]
    assert rejected[['shares', 'fee', 'slippage_cost']].eq(0).all().all()
    allowed = {'ex', 'cash_settlement', 'stock_settlement', 'rights_subscribed',
               'rights_not_subscribed', 'delisting_zero_recovery'}
    assert set(events.event).issubset(allowed)
    cash, receivable = initial_cash, 0.
    shares, pending = defaultdict(int), defaultdict(int)
    event_days = {d: g.to_dict('records') for d, g in events.groupby('date')}
    trade_days = {d: g.to_dict('records') for d, g in orders.groupby('date')}
    holding_days = {d: g for d, g in holdings.groupby('date')}
    maximum_cash = maximum_receivable = maximum_equity = 0.
    previous, boundaries = None, []
    def number(row, name):
        value = row.get(name, 0)
        return 0. if pd.isna(value) else float(value)
    for day in nav.to_dict('records'):
        date = day['date']
        for event in event_days.get(date, []):
            code, kind = event['code'], event['event']
            if kind == 'ex':
                receivable += number(event, 'gross_cash') - number(event, 'assumed_tax')
                pending[code] += int(number(event, 'bonus_shares'))
            elif kind == 'cash_settlement':
                amount = number(event, 'cash'); cash += amount; receivable -= amount
            elif kind == 'stock_settlement':
                amount = int(number(event, 'shares')); shares[code] += amount; pending[code] -= amount
            elif kind == 'rights_subscribed':
                cash -= number(event, 'cost'); pending[code] += int(number(event, 'allotted_shares'))
            elif kind == 'delisting_zero_recovery':
                assert shares[code] + pending[code] == int(number(event, 'shares'))
                shares[code] = pending[code] = 0
        for trade in trade_days.get(date, []):
            quantity = int(trade['shares'])
            assert trade['side'] in ('buy', 'sell')
            sign = 1 if trade['side'] == 'buy' else -1
            shares[trade['ts_code']] += sign * quantity
            cash -= sign * quantity * trade['price'] + trade['fee'] if quantity else trade['fee']
            if 'cash_after' in trade:
                assert abs(cash - trade['cash_after']) < 1e-6, ('order cash', date)
            if 'notional' in trade:
                notional = quantity * trade['price'] if quantity else 0.
                assert abs(notional - trade['notional']) < 1e-6
            if quantity and 'raw_open' in trade:
                slip = quantity * (trade['price'] - trade['raw_open']) * sign
                assert abs(slip - trade['slippage_cost']) < 1e-6
        cash_error, receivable_error = abs(cash - day['cash']), abs(receivable - day['receivable'])
        equity_error = abs(day['equity'] - sum(day[k] for k in ('cash', 'stock_value', 'bonus_value', 'receivable')))
        assert cash_error < 1e-6 and receivable_error < 1e-6 and equity_error < 1e-6, date
        assert cash >= -1e-7 and all(n >= 0 for n in shares.values()) and all(n >= 0 for n in pending.values())
        expected = {c: (shares[c], pending[c]) for c in set(shares) | set(pending) if shares[c] or pending[c]}
        observed = holding_days.get(date)
        actual = {} if observed is None else {r.ts_code: (int(r.shares), int(r.pending_shares))
                                               for r in observed.itertuples(index=False)}
        assert expected == actual, ('shares', date)
        if observed is not None and 'mark' in observed:
            stock = float((observed.shares * observed.mark).sum())
            bonus = float((observed.pending_shares * observed.mark).sum())
            assert abs(stock - day['stock_value']) < 1e-6 and abs(bonus - day['bonus_value']) < 1e-6
        elif observed is None:
            assert day['stock_value'] == 0 and day['bonus_value'] == 0
        daily_trades = trade_days.get(date, [])
        if 'fees' in day:
            assert abs(sum(r['fee'] for r in daily_trades) - day['fees']) < 1e-6
        if 'slippage_cost' in day:
            assert abs(sum(r['slippage_cost'] for r in daily_trades) - day['slippage_cost']) < 1e-6
        if previous is not None and previous['date'].year != date.year and previous['date'].year >= boundary_start_year:
            boundaries.append(dict(prior_date=previous['date'], next_date=date,
                                   prior_cash=previous['cash'], next_cash=day['cash'],
                                   prior_equity=previous['equity'], next_equity=day['equity'],
                                   prior_receivable=previous['receivable'],
                                   prior_bonus_value=previous['bonus_value'], cash_reconstruction_error=cash_error,
                                   share_reconstruction_exact=True))
        maximum_cash = max(maximum_cash, cash_error)
        maximum_receivable = max(maximum_receivable, receivable_error)
        maximum_equity = max(maximum_equity, equity_error)
        previous = day
    notional = float(sum(r.shares * r.price for r in orders.loc[orders.shares.gt(0)].itertuples(index=False)))
    return dict(sessions=len(nav), maximum_cash_error=maximum_cash,
                maximum_receivable_error=maximum_receivable, maximum_equity_error=maximum_equity,
                shares_and_pending_exact_every_session=True, gross_traded_notional_cny=notional), boundaries


def summarize_operations(nav, orders):
    """Actual traded notional, using prior close equity for an explicit metric.

    Annualized half-turnover = sum((buys+sells)/(2*previous equity))*252/N.
    N counts all formal exchange sessions, including days with no orders, and
    the initial purchase is included. This differs from the engine's gross
    turnover using same-day opening equity and is labelled separately.
    """
    equity = nav.set_index('date').equity
    previous_equity = equity.shift(1)
    formal = pd.DatetimeIndex(nav.loc[nav.date >= '2018-01-01', 'date'])
    assert len(formal) and previous_equity.reindex(formal).notna().all()
    assert previous_equity.reindex(formal).gt(0).all()
    actual = orders.loc[orders.date.isin(formal) & orders.shares.gt(0)].copy()
    actual['traded_notional'] = actual.shares * actual.price
    amount = actual.groupby('date').traded_notional.sum().reindex(formal, fill_value=0.)
    turnover = amount / (2 * previous_equity.reindex(formal))
    rejected = orders.loc[orders.date.isin(formal) & orders.status.eq('rejected')]
    daily = nav.loc[nav.date.isin(formal)]
    return dict(formal_sessions=len(formal), filled_buy_notional_cny=float(actual.loc[actual.side.eq('buy'), 'traded_notional'].sum()),
                filled_sell_notional_cny=float(actual.loc[actual.side.eq('sell'), 'traded_notional'].sum()),
                half_turnover_prior_equity_total=float(turnover.sum()),
                annualized_half_turnover_prior_equity=float(turnover.sum() * 252 / len(formal)),
                initial_execution_notional_cny=float(amount.loc[actual.date.min()]) if len(actual) else 0.,
                subsequent_execution_notional_cny=float(amount.sum() - (amount.loc[actual.date.min()] if len(actual) else 0.)),
                total_fees_cny=float(daily.fees.sum()), total_slippage_cny=float(daily.slippage_cost.sum()),
                rejected_count=len(rejected), rejected_reasons_json=json.dumps(rejected.reason.fillna('unspecified').value_counts().to_dict(), sort_keys=True),
                average_cash_weight=float((daily.cash / daily.equity).mean()),
                maximum_actual_positions=int(daily.position_count.max()))


def main(out=OUT):
    out = Path(out)
    assert read_json(out / 'experiment_stage.json')['state'] == 'completed'
    if (out / 'verification.json').exists():
        raise RuntimeError('Existing verification; inspect rather than overwrite')
    protocol = read_json(out / 'frozen_protocol.json')
    old_counts = check_fingerprints(protocol)
    assert read_json(out / 'preparation_status.json')['state'] == 'completed'
    for name, expected in read_json(out / 'preparation_sha256.json').items():
        assert sha(out / name) == expected, 'Prepared artifact changed: ' + name
    experiment = read_json(out / 'experiment_protocol.json')
    assert sha(ROOT / 'scripts/run_alphaforge_case.py') == experiment['runner_sha256']
    assert sha(out / 'simulation_adapter_block.py.txt') == experiment['adapter_sha256']
    summary = read_json(out / 'summary.json')
    statuses = summary['experiment_statuses']
    expected_labels = {f'{p}_{cost}bp' for p in PATHS for cost in (0, 10, 30)}
    assert len(statuses) == 6 and {s['strategy'] for s in statuses} == expected_labels
    assert all(s['status'] == 'completed' for s in statuses)
    assert {item['strategy'] for item in summary['experiments']} == expected_labels
    assert len(summary['experiments']) == 6
    cal = pd.read_csv(DATA / 'calendar.csv', dtype={'cal_date': str})
    full = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq(1), 'cal_date'])).sort_values()
    calendar = full[(full >= '2015-11-01') & (full <= '2020-12-31')]
    schedule = weekly_schedule(full[full >= '2015-11-01'])
    schedule = schedule.loc[schedule.execution_date.between('2018-01-01', '2020-12-31')].reset_index(drop=True)
    base = pd.read_csv(OLD / 'common_samples.csv', parse_dates=['trade_date', 'D_end', 'reference_end'],
                       float_precision='round_trip')
    base = base.loc[base.trade_date.isin(schedule.signal_date)].copy()
    common = pd.read_csv(out / 'common_samples.csv', parse_dates=['trade_date', 'D_end', 'reference_end'],
                         float_precision='round_trip')
    assert set(common.trade_date) == set(schedule.signal_date)
    codes = set(base.ts_code)
    bars = read_subset('daily', codes).merge(read_subset('adj_factor', codes),
                                           on=['trade_date', 'ts_code'], validate='one_to_one')
    bars, _ = correct_adjustments(bars)
    print('Independent ten-point scalar verification', len(base), flush=True)
    formation = verify_formation(common, base, calendar, bars)
    del bars, base
    ic = verify_diagnostics(common, schedule, out)
    verify_targets(common, schedule, out)
    checks, annual, boundaries, operations = [], [], [], []
    expected_calendar = calendar[calendar >= '2017-10-01']
    for item in summary['experiments']:
        folder = out / item['strategy']
        assert sha(folder / 'historical_targets.csv') == sha(out / f'targets_{item["path"]}.csv')
        config = item['config']
        cost = int(item['strategy'].rsplit('_', 1)[1][:-2])
        assert config == asdict(Config(slippage_bps=cost, zero_trading_costs=cost == 0))
        nav = pd.read_csv(folder / 'nav.csv', parse_dates=['date'], float_precision='round_trip')
        orders = pd.read_csv(folder / 'orders.csv', parse_dates=['date'], float_precision='round_trip')
        events = pd.read_csv(folder / 'corporate_events.csv', parse_dates=['date'], float_precision='round_trip')
        holdings = pd.read_csv(folder / 'holdings.csv', parse_dates=['date'], float_precision='round_trip')
        assert pd.DatetimeIndex(nav.date).equals(expected_calendar)
        assert nav.loc[nav.date.eq(pd.Timestamp('2017-12-29')), 'equity'].iloc[0] == 1_000_000
        assert orders.date.isin(schedule.execution_date).all()
        if cost == 0:
            assert orders[['fee', 'slippage_cost']].eq(0).all().all()
        record, edges = reconstruct_account(nav, orders, events, holdings)
        assert len(edges) == 2
        checks.append(dict(strategy=item['strategy'], **record))
        operations.append(dict(strategy=item['strategy'], **summarize_operations(nav, orders)))
        boundaries.extend(dict(strategy=item['strategy'], **edge) for edge in edges)
        calculated = summarize(nav, orders, schedule.execution_date.iloc[0], pd.Timestamp('2018-01-01'))
        for name, value in calculated.items():
            if isinstance(value, (float, int)):
                assert np.isclose(value, item[name], rtol=0, atol=1e-6), (item['strategy'], name)
        assert abs(float(orders.fee.sum()) - item['total_fees']) < 1e-6
        assert abs(float(orders.slippage_cost.sum()) - item['total_slippage']) < 1e-6
        previous_equity = 1_000_000.
        for year, group in nav.loc[nav.date >= '2018-01-01'].groupby(nav.date.dt.year):
            ending = float(group.equity.iloc[-1])
            annual.append(dict(strategy=item['strategy'], year=int(year), start_equity=previous_equity,
                               end_equity=ending, return_value=ending / previous_equity - 1))
            previous_equity = ending
    assert len(checks) == 6 and len(boundaries) == 12
    annual = pd.DataFrame(annual)
    stats = pd.DataFrame(summary['experiments']).set_index('strategy')
    primary = stats.loc[PRIMARY + '_10bp']
    gates, mean_ic, yearly_ic = strategy_gates(stats, annual, ic, schedule)
    # Check the protected evidence again after all account reads.
    assert check_fingerprints(protocol) == old_counts
    annual.to_csv(out / 'annual_returns.csv', index=False)
    pd.DataFrame(operations).to_csv(out / 'account_operations.csv', index=False)
    stats.reset_index().drop(columns=['config']).to_csv(out / 'comparison.csv', index=False)
    pd.DataFrame(boundaries).to_csv(out / 'year_boundary_audit.csv', index=False)
    persist('flow_reconstruction_audit.json', dict(status='passed', checks=checks, year_boundaries=len(boundaries)), out)
    result = dict(status='passed', engineering_verification_passed=True, **formation,
                  accounts=checks, year_boundaries=len(boundaries), old_artifacts=old_counts,
                  mean_rankIC=mean_ic, yearly_rankIC={int(k): float(v) for k, v in yearly_ic.items()},
                  gates=gates, research_gates_passed=all(gates.values()), broker_connected=False,
                  verifier_sha256=sha(Path(__file__)), summary_sha256=sha(out / 'summary.json'),
                  scope='Retrospective single-expression adaptation; opened history is not an independent holdout.')
    persist('verification.json', result, out)
    print(json.dumps(dict(engineering='passed', research_gates_passed=all(gates.values()),
                          primary_net_return=float(primary.total_return), gates=gates), ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    try:
        main()
    except Exception:
        (OUT / 'verification_failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
