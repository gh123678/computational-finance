"""Synthetic calendars and prices only; no historical research inputs."""
from copy import deepcopy

import pytest

from quant_research.etf_trend_signal import prepare_signals


MONTH_ENDS_2017 = [
    '20170131', '20170228', '20170331', '20170428',
    '20170531', '20170630', '20170731', '20170831',
    '20170929', '20171031', '20171130', '20171229',
]


def toy_bars(points):
    """The listed dates define the complete synthetic session calendar."""
    bars = []
    previous = None
    for date, close in points:
        price = str(close)
        bars.append({
            'ts_code': '510330.SH', 'trade_date': date,
            'open': price, 'high': price, 'low': price, 'close': price,
            'pre_close': str(previous if previous is not None else close),
            'vol': '1000', 'amount': '100000',
        })
        previous = close
    return bars


def cash_event(ann='20170125', record='20170131', ex='20170201',
               pay='20170207', cash='1'):
    return {
        'ts_code': '510330.SH', 'ann_date': ann, 'record_date': record,
        'ex_date': ex, 'pay_date': pay, 'cash_per_share': cash,
    }


def monthly_by_date(result):
    return {row['date']: row for row in result['monthly']}


def test_initial_cash_and_exact_equality_remain_cash():
    points = [(date, 100) for date in MONTH_ENDS_2017]
    points += [('20180102', 100), ('20180131', 100)]
    result = prepare_signals(toy_bars(points), [])

    assert all(row['k'] == 1.0 for row in result['daily'])
    assert all(row['sma10'] is None for row in result['monthly'][:9])
    assert result['monthly'][9]['sma10'] == 1.0
    assert all(row['state'] == 0 for row in result['monthly'])
    assert result['schedule'] == {'20180102': 0}
    assert result['monthly'][-1]['execution_date'] == ''


def test_ten_month_window_includes_current_and_drops_older_month():
    prices = [100] * 9 + [200, 50, 50]
    result = prepare_signals(toy_bars(zip(MONTH_ENDS_2017, prices)), [])
    monthly = monthly_by_date(result)

    # October's window contains nine 1s and its current 2, not ten past 1s.
    assert monthly['20171031']['sma10'] == pytest.approx(1.1)
    assert monthly['20171031']['state'] == 1
    # November drops January: eight 1s, October's 2 and November's 0.5.
    assert monthly['20171130']['sma10'] == pytest.approx(1.05)
    assert monthly['20171130']['state'] == 0
    assert monthly['20171229']['sma10'] == pytest.approx(1.0)


def test_exact_equality_preserves_an_existing_holding_state():
    dates = MONTH_ENDS_2017 + [
        '20180131', '20180228', '20180330', '20180430',
        '20180531', '20180629', '20180731',
    ]
    prices = [100] * 9 + [200] * 10
    result = prepare_signals(toy_bars(zip(dates, prices)), [])
    monthly = monthly_by_date(result)

    assert monthly['20171031']['state'] == 1
    assert monthly['20180629']['state'] == 1
    final = monthly['20180731']
    assert final['k'] == final['sma10'] == 2.0
    assert final['state'] == 1


def test_december_state_executes_on_next_session_without_same_close_trade():
    points = list(zip(MONTH_ENDS_2017, [100] * 9 + [200] * 3))
    points += [
        ('20180102', 50), ('20180131', 50),
        ('20180201', 50), ('20180228', 50),
    ]
    result = prepare_signals(toy_bars(points), [])
    monthly = monthly_by_date(result)

    assert monthly['20171229']['state'] == 1
    assert monthly['20171229']['execution_date'] == '20180102'
    assert result['schedule']['20180102'] == 1
    # The first January close is already lower; it cannot rewrite December.
    assert monthly['20180131']['state'] == 0
    assert monthly['20180131']['execution_date'] == '20180201'
    assert result['schedule']['20180201'] == 0
    assert '20171229' not in result['schedule']
    assert '20180131' not in result['schedule']
    assert monthly['20180228']['execution_date'] == ''
    assert '20180228' not in result['schedule']


def test_cash_distribution_offsets_only_the_ex_date_price_drop():
    bars = toy_bars([
        ('20170103', 100), ('20170131', 100), ('20170201', 99),
        ('20170207', 99), ('20170228', 99),
    ])
    result = prepare_signals(bars, [cash_event()])
    daily = {row['date']: row for row in result['daily']}

    assert [row['k'] for row in result['daily']] == pytest.approx([1] * 5)
    assert float(daily['20170201']['dividend_per_share']) == 1.0
    assert float(daily['20170207']['dividend_per_share']) == 0.0
    assert sum(float(row['dividend_per_share']) for row in result['daily']) == 1.0
    without_cash = prepare_signals(bars, [])
    assert without_cash['daily'][-1]['k'] == pytest.approx(0.99)


def test_future_price_and_cash_changes_do_not_rewrite_past_signals():
    points = list(zip(MONTH_ENDS_2017, [100] * 9 + [200] * 3))
    points += [
        ('20180102', 200), ('20180131', 200), ('20180201', 200),
        ('20180228', 200), ('20180301', 200), ('20180330', 200),
    ]
    original_bars = toy_bars(points)
    changed_bars = deepcopy(original_bars)
    for row in changed_bars:
        if row['trade_date'] > '20180131':
            for key in ('open', 'high', 'low', 'close'):
                row[key] = '10000'
    future = cash_event(ann='20180201', record='20180201',
                        ex='20180228', pay='20180301', cash='100')
    original = prepare_signals(original_bars, [])
    changed = prepare_signals(changed_bars, [future])

    for section in ('daily', 'monthly'):
        before = [row for row in original[section] if row['date'] <= '20180131']
        after = [row for row in changed[section] if row['date'] <= '20180131']
        assert after == before
    before_schedule = {d: s for d, s in original['schedule'].items() if d <= '20180201'}
    after_schedule = {d: s for d, s in changed['schedule'].items() if d <= '20180201'}
    assert after_schedule == before_schedule


def test_evaluation_interval_filters_scheduled_execution_dates():
    points = [(date, 100) for date in MONTH_ENDS_2017]
    points += [
        ('20180102', 100), ('20180131', 100),
        ('20180201', 100), ('20180228', 100),
    ]
    result = prepare_signals(toy_bars(points), [],
                             evaluation_start='20180201', evaluation_end='20180201')
    assert result['schedule'] == {'20180201': 0}


def test_late_announcements_and_duplicate_cash_events_are_rejected():
    bars = toy_bars([
        ('20170103', 100), ('20170131', 100),
        ('20170201', 99), ('20170228', 99),
    ])
    with pytest.raises(ValueError):
        prepare_signals(bars, [cash_event(ann='20170202')])
    with pytest.raises(ValueError):
        prepare_signals(bars, [cash_event(), cash_event()])
