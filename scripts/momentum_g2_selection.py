"""The approved single momentum rule and one fixed, no-score control.

This module consumes an already admitted, shared formation pool. It neither
loads market data nor changes eligibility or targets after account fills.
"""
import hashlib
import re

import numpy as np
import pandas as pd

from retention_selector import select_retention

CONTROL_PREFIX = 'CF2026_G2_MOM_CONTROL_V1|'
PATHS = ('momentum', 'control')
TARGET_COLUMNS = ['signal_date', 'execution_date', 'ts_code', 'industry',
                  'target_weight', 'formation_close', 'adv20_cny']


def control_key(code):
    if not isinstance(code, str) or re.fullmatch(r'(?:60\d{4}\.SH|00\d{4}\.SZ)', code) is None:
        raise ValueError('Canonical main-board ts_code required')
    return hashlib.sha256((CONTROL_PREFIX + code).encode('utf-8')).hexdigest()


def select_control(pool, previous_codes=()):
    required = {'trade_date', 'ts_code', 'industry'}
    if not required.issubset(pool) or pool.ts_code.duplicated().any() or pool.trade_date.nunique() > 1:
        raise ValueError('One unique formation cross-section required')
    if pool.industry.isna().any() or pool.industry.astype(str).str.strip().eq('').any():
        raise ValueError('Control cannot impute missing industry')
    frame = pool.copy()
    frame['control_key'] = frame.ts_code.map(control_key)
    frame = frame.sort_values(['control_key', 'ts_code'])
    rows = frame.set_index('ts_code', drop=False).to_dict('index')
    previous = set(previous_codes)
    chosen, events, counts = [], [], {}

    def admit(code):
        sector = rows[code]['industry']
        if len(chosen) >= 20 or counts.get(sector, 0) >= 5:
            return False
        chosen.append(code)
        counts[sector] = counts.get(sector, 0) + 1
        return True

    for code in sorted(previous - set(rows)):
        events.append(dict(kind='forced_exit', code=code, other_code='', reason='ineligible'))
    for code in frame.loc[frame.ts_code.isin(previous), 'ts_code']:
        if not admit(code):
            events.append(dict(kind='forced_exit', code=code, other_code='', reason='industry_cap'))
    for code in frame.ts_code:
        if code not in chosen and admit(code):
            events.append(dict(kind='initial_entry' if not previous else 'vacancy_fill',
                               code=code, other_code='', reason='fixed_hash_fill'))
    selected = pd.DataFrame([rows[c] for c in chosen], columns=frame.columns)
    selected['target_weight'] = .049
    return selected, pd.DataFrame(events, columns=['kind', 'code', 'other_code', 'reason'])


def build_targets(feature_rows, schedule):
    required = {'trade_date', 'ts_code', 'industry', 'momentum', 'formation_close', 'adv20_cny'}
    if not required.issubset(feature_rows):
        raise ValueError('Admitted formation inputs missing')
    if feature_rows.duplicated(['trade_date', 'ts_code']).any():
        raise ValueError('Duplicate admitted formation key')
    if not {'signal_date', 'execution_date'}.issubset(schedule) or schedule.signal_date.duplicated().any():
        raise ValueError('Unique weekly schedule required')
    numeric = feature_rows[['momentum', 'formation_close', 'adv20_cny']].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (numeric[:, 1] <= 0).any() or (numeric[:, 2] < 20_000_000).any():
        raise ValueError('Invalid admitted numerical input')
    if (schedule.signal_date >= schedule.execution_date).any():
        raise ValueError('Formation must precede execution')
    groups = {pd.Timestamp(d): g.copy() for d, g in feature_rows.groupby('trade_date')}
    memory = {p: set() for p in PATHS}
    targets, logs, scores = {p: [] for p in PATHS}, [], []
    for row in schedule.itertuples(index=False):
        date, execution = pd.Timestamp(row.signal_date), pd.Timestamp(row.execution_date)
        pool = groups.get(date)
        if pool is None or len(pool) < 200:
            raise ValueError('Shared formation pool below fixed 200-code gate: ' + str(date.date()))
        main = pool.copy()
        main['score'] = main.momentum.rank(method='average', pct=True)
        scores.append(main.copy())
        selected_main, main_events = select_retention(main, memory['momentum'])
        # The control never receives momentum or score values.
        control_input = pool.drop(columns=['momentum', 'score'], errors='ignore')
        selected_control, control_events = select_control(control_input, memory['control'])
        for path, selected, events in [('momentum', selected_main, main_events),
                                        ('control', selected_control, control_events)]:
            memory[path] = set(selected.ts_code)
            selected = selected.copy()
            selected['signal_date'], selected['execution_date'] = date, execution
            extras = [c for c in ('score', 'control_key') if c in selected]
            targets[path].append(selected[TARGET_COLUMNS + extras])
            for event in events.to_dict('records'):
                logs.append(dict(path=path, signal_date=date, execution_date=execution, **event))
    return {'targets': {p: pd.concat(v, ignore_index=True) if v else pd.DataFrame(columns=TARGET_COLUMNS)
                        for p, v in targets.items()},
            'selection_events': pd.DataFrame(logs),
            'ranked_features': pd.concat(scores, ignore_index=True) if scores else pd.DataFrame()}
