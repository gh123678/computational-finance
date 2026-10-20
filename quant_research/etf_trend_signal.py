"""Fixed single-ETF monthly total-return trend, independent of account cash."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import numpy as np


def prepare_signals(bars: list[dict], actions: list[dict],
                    evaluation_start: str = '20180101',
                    evaluation_end: str = '20251231') -> dict:
    """Input must be the admitted complete exchange-session calendar, sorted.

    The supplied last month must be complete. No forward fill, factor adjustment,
    monthly reopening trade, or account dividend reinvestment is performed here.
    """
    dates = [b['trade_date'] for b in bars]
    if not dates or dates != sorted(set(dates)):
        raise ValueError('A nonempty unique ascending complete calendar is required')
    cash = {}
    for a in actions:
        ex = a['ex_date']
        if a['ann_date'] > ex:
            raise ValueError('Dividend was not announced by its ex date')
        if ex in cash:
            raise ValueError('Duplicate economic event must be resolved before signals')
        amount = Decimal(a['cash_per_share'])
        if not amount.is_finite() or amount <= 0 or ex not in dates:
            raise ValueError('Invalid cash event')
        cash[ex] = np.float64(str(amount))
    daily, month_last = [], {}
    k = np.float64(1)
    previous = None
    for b in bars:
        date = b['trade_date']
        close = np.float64(b['close'])
        dividend = cash.get(date, np.float64(0))
        if not np.isfinite(close) or close <= 0:
            raise ValueError('Invalid raw close')
        if previous is not None:
            k = np.float64(k * np.float64(np.float64(close + dividend) / previous))
        elif dividend:
            raise ValueError('Cannot apply a first-point cash distribution without prior close')
        if not np.isfinite(k) or k <= 0:
            raise ValueError('Nonfinite total-return index')
        daily.append({'date': date, 'k': float(k), 'dividend_per_share': float(dividend)})
        month_last[date[:6]] = len(daily)-1
        previous = close
    monthly, schedule, month_values = [], {}, []
    state = 0
    for month, i in month_last.items():
        # Complete coverage is admitted externally; no resampling invents a month.
        row = daily[i]
        month_values.append(np.float64(row['k']))
        average = None
        if len(month_values) >= 10:
            total = np.float64(0)
            for point in month_values[-10:]:
                total = np.float64(total + point)
            average = np.float64(total / np.float64(10))
            if not np.isfinite(average):
                raise ValueError('Nonfinite monthly mean')
            if np.float64(row['k']) > average:
                state = 1
            elif np.float64(row['k']) < average:
                state = 0
        execution = dates[i+1] if i+1 < len(dates) else ''
        monthly.append({'date': row['date'], 'k': row['k'],
                        'sma10': float(average) if average is not None else None,
                        'state': state, 'execution_date': execution})
        if average is not None and execution and evaluation_start <= execution <= evaluation_end:
            schedule[execution] = state
    return {'daily': daily, 'monthly': monthly, 'schedule': schedule}


def performance(nav: list[dict], orders: list[dict]) -> dict:
    """All returns use actual continuous-account equity, including a baseline."""
    values = np.array([float(r['equity']) for r in nav], dtype=np.float64)
    if len(values) < 3 or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Invalid account NAV series')
    returns = values[1:] / values[:-1] - 1
    total = values[-1]/values[0]-1
    std = np.std(returns, ddof=1)
    sharpe = float(np.mean(returns)/std*np.sqrt(252)) if np.isfinite(std) and std > 0 else None
    peaks = np.maximum.accumulate(values)
    annual = {}
    grouped = defaultdict(list)
    for i, row in enumerate(nav[1:], 1):
        grouped[row['date'][:4]].append(i)
    for year, indices in sorted(grouped.items()):
        annual[year] = float(values[indices[-1]]/values[indices[0]-1]-1)
    actual = [r for r in orders if int(r['filled']) > 0]
    equities = values[1:]
    exposure = np.array([float(r['market_value']) for r in nav[1:]])/equities
    traded = float(sum((Decimal(r['notional']) for r in actual), Decimal(0)))
    annual_turnover = float(sum((float(r['buy_notional'])+float(r['sell_notional']))/v
                                for r,v in zip(nav[1:], equities))*252/len(returns))
    return {'total_return': float(total),
            'annualized_return_252': float((values[-1]/values[0])**(252/len(returns))-1),
            'max_drawdown': float(np.max(1-values/peaks)),
            'sharpe_rf0_ddof1_252': sharpe, 'annual_returns': annual,
            'positive_years': sum(v > 0 for v in annual.values()),
            'evaluation_days': len(returns), 'final_equity_cny': nav[-1]['equity'],
            'mean_close_market_exposure': float(np.mean(exposure)),
            'max_close_market_exposure': float(np.max(exposure)),
            'invested_close_days': sum(int(r['shares']) > 0 for r in nav[1:]),
            'commission_cny': str(sum((Decimal(r['fee']) for r in orders), Decimal(0))),
            'slippage_cny': str(sum((Decimal(r['slippage']) for r in orders), Decimal(0))),
            'trade_notional_cny': traded,
            'annualized_buy_plus_sell_turnover': annual_turnover,
            'filled_attempts': len(actual), 'order_attempts': len(orders),
            'rejected_attempts': sum(r['status']=='rejected' for r in orders),
            'partial_attempts': sum(r['status']=='partial' for r in orders),
            'rejection_reasons': dict(Counter(r['reason'] for r in orders if r['status']=='rejected'))}
