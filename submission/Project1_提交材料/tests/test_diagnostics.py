import numpy as np
import pandas as pd
from quant_research.research import diagnostics
from quant_research.factors import FACTORS


def example(constant=False):
    dates = pd.to_datetime(['2020-01-03', '2020-01-06', '2020-01-13'])
    assets = [f'S{i:02d}' for i in range(20)]
    snapshot = pd.DataFrame({'ts_code': assets, **{f: np.ones(20) if constant else np.arange(20) for f in FACTORS}})
    bars = pd.DataFrame([{'trade_date': d, 'ts_code': c, 'open': 10 + (i / 10 if d == dates[2] else 0), 'adj_factor': 1}
                         for d in dates[1:] for i, c in enumerate(assets)])
    schedule = pd.DataFrame({'signal_date': [dates[0], pd.Timestamp('2020-01-10')], 'execution_date': dates[1:]})
    return {dates[0]: snapshot}, bars, schedule


def test_missing_future_label_preserves_original_groups():
    snapshots, bars, schedule = example()
    bars = bars.loc[~(bars.trade_date.eq(pd.Timestamp('2020-01-13')) & bars.ts_code.eq('S00'))]
    ic, groups = diagnostics(snapshots, bars, schedule)
    first = groups.loc[groups.factor.eq(FACTORS[0])].set_index('group')
    assert first.n_formed.tolist() == [4, 4, 4, 4, 4]
    assert first.n.tolist() == [3, 4, 4, 4, 4]
    assert np.isclose(first.loc[1, 'mean_forward_return'], .02)
    assert ic.n.tolist() == [19, 19, 19]


def test_constant_factor_and_sparse_labels_are_missing_not_zero():
    snapshots, bars, schedule = example(constant=True)
    ic, groups = diagnostics(snapshots, bars, schedule)
    assert ic[['ic', 'rank_ic']].isna().all().all()
    assert groups.loc[groups.n.eq(0), 'mean_forward_return'].isna().all()
    snapshots, bars, schedule = example()
    bars = bars.loc[~bars.trade_date.eq(pd.Timestamp('2020-01-13')) | bars.ts_code.isin(['S00', 'S01'])]
    ic, groups = diagnostics(snapshots, bars, schedule)
    assert ic[['ic', 'rank_ic']].isna().all().all()
    assert groups.loc[groups.n.lt(2), 'mean_forward_return'].isna().all()
