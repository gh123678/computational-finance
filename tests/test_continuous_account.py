import pandas as pd
import pytest

from quant_research.accounting import Action
from quant_research.backtest import Config, simulate
from quant_research.factors import biweekly_schedule
from scripts.build_continuous_dataset import compare_overlap
from quant_research.continuous import relevant_actions


def test_december_entitlement_and_january_settlement_keep_one_account():
    dates = pd.bdate_range('2020-12-28', '2021-01-08')
    bars = pd.DataFrame(dict(trade_date=dates, ts_code='A', open=10., close=10.,
                             amount=10000000., vol=1000000., adj_factor=1.,
                             up_limit=20., down_limit=1.))
    ex = pd.Timestamp('2020-12-31')
    bars.loc[bars.trade_date >= ex, ['open', 'close']] = 4.5
    bars.loc[bars.trade_date >= ex, 'adj_factor'] = 10/4.5
    targets = pd.DataFrame(dict(signal_date=[dates[0]], execution_date=[dates[1]],
                                ts_code=['A'], target_weight=[.5]))
    action = Action('A', pd.Timestamp('2020-12-30'), ex,
                    pd.Timestamp('2021-01-04'), pd.Timestamp('2021-01-05'), 1., 1.)
    run = simulate(bars, dates, targets, [action],
                   config=Config(initial_cash=1000000., dividend_tax=0, zero_trading_costs=True))
    nav = run['nav'].set_index('date')
    assert nav.loc[ex, 'cash'] == 500000
    assert nav.loc[ex, 'receivable'] == 50000
    assert nav.loc[ex, 'bonus_value'] == 225000
    assert nav.loc['2021-01-04', 'cash'] == 550000
    assert nav.loc['2021-01-05', 'stock_value'] == 450000
    assert nav.equity.tolist() == pytest.approx([1000000.] * len(dates))
    held = run['holdings'].set_index('date')
    assert held.loc['2021-01-05', 'shares'] == 100000
    assert run['corporate_events'].event.eq('ex').sum() == 1


def test_biweekly_phase_is_not_reset_at_year_boundary():
    dates = pd.bdate_range('2020-11-09', '2021-02-05')
    whole = biweekly_schedule(dates)
    year_start = pd.Timestamp('2021-01-01')
    continuous = whole.loc[whole.execution_date >= year_start]
    reset = biweekly_schedule(dates[dates >= year_start])
    assert not continuous.execution_date.reset_index(drop=True).equals(reset.execution_date)
    assert continuous.execution_date.iloc[0] == pd.Timestamp('2021-01-11')
    assert reset.execution_date.iloc[0] == pd.Timestamp('2021-01-04')
    assert set(continuous.execution_date) != set(reset.execution_date)


def test_overlap_rejects_changed_quote_instead_of_choosing_one_copy():
    left = pd.DataFrame(dict(ts_code=['600000.SH'], trade_date=['20201231'], close=['10.0']))
    right = left.assign(close='10.1')
    issue = compare_overlap(left, right, 'daily')
    assert issue['left_only_rows'] == issue['right_only_rows'] == 1
    assert compare_overlap(left, left.copy(), 'daily') is None


def test_equal_overlaps_still_reject_duplicate_primary_keys():
    frame = pd.DataFrame(dict(ts_code=['600000.SH']*2, trade_date=['20201231']*2, close=['10.0']*2))
    with pytest.raises(ValueError, match='Duplicate primary keys'):
        compare_overlap(frame, frame.copy(), 'daily')


def test_prequote_event_exclusion_does_not_hide_events_after_stock_is_buyable():
    bars = pd.DataFrame(dict(ts_code=['A','A'],trade_date=pd.to_datetime(['20170524','20170525'])))
    records = pd.DataFrame(dict(ts_code=['A','A','A'],ex_date=['20160415','20170524','20170525']))
    kept, excluded = relevant_actions(records,bars)
    assert excluded.ex_date.tolist() == ['20160415']
    assert kept.ex_date.tolist() == ['20170524','20170525']


def test_simulation_market_pruning_keeps_target_history_and_execution_identical():
    dates=pd.bdate_range('2020-12-28','2021-01-08')
    a=pd.DataFrame(dict(trade_date=dates,ts_code='A',open=10.,close=10.,amount=10000000.,
                        vol=1000000.,adj_factor=1.,up_limit=20.,down_limit=1.))
    b=a.assign(ts_code='B',open=15.,close=16.)
    targets=pd.DataFrame(dict(signal_date=[dates[0]],execution_date=[dates[1]],ts_code=['A'],target_weight=[.5]))
    all_market=simulate(pd.concat([a,b],ignore_index=True),dates,targets)
    pruned=simulate(a,dates,targets)
    for table in ['nav','orders','holdings','corporate_events']:
        pd.testing.assert_frame_equal(all_market[table],pruned[table])
