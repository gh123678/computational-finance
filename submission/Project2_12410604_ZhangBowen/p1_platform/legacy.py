"""Exact P1 function bodies; only imports and dataset registry are local glue."""
import numpy as np
import pandas as pd
DATASETS = {}


def read_market(root, name):
    frame = pd.read_csv(root / f'{name}.csv', dtype={'ts_code': str, 'trade_date': str})
    if 'trade_date' in frame:
        frame['trade_date'] = pd.to_datetime(frame.trade_date, format='%Y%m%d')
    return frame


def dataset_config(name):
    if name not in DATASETS:
        raise ValueError('Unregistered dataset; sealed test periods cannot be requested')
    return DATASETS[name].copy()


def summarize(nav, orders, first_execution, evaluation_start=None):
    start = nav.index[nav.date.ge(pd.Timestamp(evaluation_start))][0] if evaluation_start else nav.index[nav.date.eq(first_execution)][0]
    if start == 0:
        raise ValueError('Need a pre-execution NAV observation')
    frame = nav.iloc[start-1:].copy()
    equity = frame.equity
    returns = equity.pct_change().dropna()
    drawdown = 1 - equity / equity.cummax()
    trades = orders.loc[orders.shares.gt(0)] if not orders.empty else orders
    result = dict(total_return=float(equity.iloc[-1] / equity.iloc[0] - 1), max_drawdown=float(drawdown.max()),
                sessions=len(returns), start=frame.date.iloc[0].strftime('%Y-%m-%d'), end=frame.date.iloc[-1].strftime('%Y-%m-%d'),
                final_equity=float(equity.iloc[-1]), total_fees=float(frame.fees.sum()),
                total_slippage=float(frame.slippage_cost.sum()), gross_turnover=float(frame.turnover.sum()),
                filled_orders=len(trades), rejected_orders=int(orders.status.eq('rejected').sum()) if not orders.empty else 0,
                industry_breach_days=int(frame.industry_target_breached.sum()),
                stale_valuation_days=int(frame.stale_value.gt(0).sum()),
                average_cash_weight=float((frame.cash / frame.equity).iloc[1:].mean()),
                average_positions=float(frame.position_count.iloc[1:].mean()))
    if len(returns) >= 126:
        volatility = float(returns.std(ddof=1) * np.sqrt(252))
        result.update(annualized_return=float((equity.iloc[-1] / equity.iloc[0]) ** (252 / len(returns)) - 1),
                      annualized_volatility=volatility,
                      sharpe_rf0=float(returns.mean() * 252 / volatility) if volatility > 0 else None)
    else:
        result['annualized_metrics_withheld'] = 'Short engineering window; no annualized performance claim.'
    return result
