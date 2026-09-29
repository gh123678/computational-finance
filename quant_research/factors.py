"""Past-only factors on an explicit exchange calendar; no silent forward fills."""
import numpy as np
import pandas as pd

FACTORS = ['momentum20', 'reversal5', 'lowvol20']


def compute_factors(bars: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    required = {'trade_date', 'ts_code', 'close', 'adj_factor', 'amount'}
    if not required.issubset(bars):
        raise ValueError(f'Missing columns: {required - set(bars)}')
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Calendar must be unique and sorted.')
    frame = bars.copy()
    frame['trade_date'] = pd.to_datetime(frame['trade_date'], format='%Y%m%d')
    if frame.duplicated(['trade_date', 'ts_code']).any():
        raise ValueError('Duplicate asset/date rows.')
    if not frame['trade_date'].isin(calendar).all():
        raise ValueError('Some rows fall outside the exchange calendar.')
    if frame['ts_code'].isna().any():
        raise ValueError('Missing asset identifier.')
    numeric = frame[['close', 'adj_factor', 'amount']].apply(pd.to_numeric, errors='raise')
    if not np.isfinite(numeric.to_numpy()).all() or (numeric[['close', 'adj_factor']] <= 0).any().any() or (numeric['amount'] < 0).any():
        raise ValueError('Invalid prices, adjustment factors or turnover.')
    frame[numeric.columns] = numeric
    parts = []
    for code, group in frame.groupby('ts_code', sort=True):
        group = group.set_index('trade_date').reindex(calendar)
        price = group['close'] * group['adj_factor']
        returns = price.pct_change(fill_method=None)
        full21 = price.rolling(21, min_periods=21).count().eq(21)
        full6 = price.rolling(6, min_periods=6).count().eq(6)
        result = pd.DataFrame(index=calendar)
        result['momentum20'] = price.div(price.shift(20)).sub(1).where(full21)
        result['reversal5'] = price.div(price.shift(5)).sub(1).mul(-1).where(full6)
        result['lowvol20'] = -returns.rolling(20, min_periods=20).std(ddof=1)
        # Tushare daily.amount is thousands of CNY; convert once at the boundary.
        result['adv20_cny'] = group['amount'].rolling(20, min_periods=20).mean() * 1000
        result['ts_code'] = code
        result.index.name = 'trade_date'
        parts.append(result.reset_index())
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=['trade_date', 'ts_code', *FACTORS, 'adv20_cny'])


def rank_scores(factors: pd.DataFrame, columns=FACTORS) -> pd.DataFrame:
    """Caller must first filter the historical investable universe."""
    if not columns or not set(columns).issubset(factors):
        raise ValueError('Provide valid factor columns.')
    frame = factors.copy()
    if frame.duplicated(['trade_date', 'ts_code']).any():
        raise ValueError('Duplicate asset/date rows.')
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=list(columns))
    ranked = frame.groupby('trade_date')[list(columns)].rank(method='average', pct=True)
    frame['score'] = ranked.mean(axis=1)
    return frame


def select_targets(scores: pd.DataFrame, count=20, cash_buffer=0.02, industry_cap=0.25) -> pd.DataFrame:
    """One date only. Missing historical industries are excluded, never imputed."""
    if not isinstance(count, int) or isinstance(count, bool) or count < 1 or not 0 <= cash_buffer < 1 or not 0 < industry_cap <= 1:
        raise ValueError('Invalid portfolio parameters.')
    required = {'trade_date', 'ts_code', 'industry', 'score'}
    if not required.issubset(scores):
        raise ValueError('Historical industry and ranked scores are required.')
    if scores['trade_date'].nunique() > 1 or scores['ts_code'].duplicated().any():
        raise ValueError('Supply one unique cross-section.')
    weight = (1 - cash_buffer) / count
    eligible = scores.replace([np.inf, -np.inf], np.nan).dropna(subset=['score', 'industry'])
    eligible = eligible.loc[eligible['industry'].astype(str).str.strip().ne('')]
    eligible = eligible.sort_values(['score', 'ts_code'], ascending=[False, True])
    selected, industry_weights = [], {}
    for row in eligible.to_dict('records'):
        exposure = industry_weights.get(row['industry'], 0.0) + weight
        if exposure > industry_cap + 1e-12:
            continue
        row['target_weight'] = weight
        selected.append(row)
        industry_weights[row['industry']] = exposure
        if len(selected) == count:
            break
    return pd.DataFrame(selected, columns=[*scores.columns, 'target_weight'])


def select_buffered_targets(scores: pd.DataFrame, previous_codes=(), count=20, exit_rank=40,
                            cash_buffer=0.02, industry_cap=0.25) -> pd.DataFrame:
    """Keep prior targets inside a fixed rank buffer, then fill by score."""
    if not isinstance(exit_rank, int) or isinstance(exit_rank, bool) or exit_rank < count:
        raise ValueError('Exit rank must be an integer no smaller than portfolio size')
    required = {'trade_date', 'ts_code', 'industry', 'score'}
    if not required.issubset(scores) or scores['trade_date'].nunique() > 1 or scores.ts_code.duplicated().any():
        raise ValueError('Supply one valid unique cross-section')
    weight = (1 - cash_buffer) / count
    eligible = scores.replace([np.inf, -np.inf], np.nan).dropna(subset=['score', 'industry']).copy()
    eligible = eligible.loc[eligible.industry.astype(str).str.strip().ne('')]
    eligible = eligible.sort_values(['score', 'ts_code'], ascending=[False, True])
    eligible['rank'] = np.arange(1, len(eligible) + 1)
    prior = set(previous_codes)
    retained = eligible.loc[eligible.ts_code.isin(prior) & eligible['rank'].le(exit_rank)]
    candidates = pd.concat([retained, eligible.loc[~eligible.ts_code.isin(retained.ts_code)]], ignore_index=True)
    selected, industry_weights = [], {}
    for row in candidates.to_dict('records'):
        exposure = industry_weights.get(row['industry'], 0.) + weight
        if exposure > industry_cap + 1e-12:
            continue
        row['target_weight'] = weight
        selected.append(row)
        industry_weights[row['industry']] = exposure
        if len(selected) == count:
            break
    return pd.DataFrame(selected, columns=[*scores.columns, 'target_weight'])


def weekly_schedule(calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Last session of each complete ISO week -> next week's first session.

    The final observed week is deliberately not assumed complete.
    """
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('Calendar must be unique and sorted.')
    iso = calendar.isocalendar()
    weeks = list(zip(iso.year, iso.week))
    pairs = [(calendar[i-1], calendar[i]) for i in range(1, len(calendar)) if weeks[i] != weeks[i-1]]
    return pd.DataFrame(pairs, columns=['signal_date', 'execution_date'])


def biweekly_schedule(calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Every second complete week retained as a rebalance week.

    2026-09-29 pre-registered with the turnover-reduction design
    (docs/superpowers/specs/2026-09-29-biweekly-design.md): keep weeks 1, 3, 5, ...
    of the weekly schedule (rows 0, 2, 4, ...); skipped weeks hold positions.
    """
    schedule = weekly_schedule(calendar)
    return schedule.iloc[::2].reset_index(drop=True)
