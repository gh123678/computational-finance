import json

import pandas as pd
import pytest

import run_momentum_g2 as runner


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    data, meta = tmp_path / 'data', tmp_path / 'meta'
    data.mkdir(); meta.mkdir()
    mapping = tmp_path / 'mapping.json'
    mapping.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(runner, 'DATA', data)
    monkeypatch.setattr(runner, 'META', meta)
    monkeypatch.setattr(runner, 'MAPPING', mapping)
    monkeypatch.setattr(runner, 'verified_rights', lambda: ())
    dates = ['20171229', '20180102', '20201231']
    pd.DataFrame({'exchange': 'SSE', 'cal_date': dates, 'is_open': '1'}).to_csv(data / 'calendar.csv', index=False)
    pd.DataFrame(columns=['ts_code', 'ann_date', 'imp_ann_date', 'div_proc', 'record_date', 'ex_date',
                         'pay_date', 'div_listdate', 'cash_div_tax', 'cash_div', 'stk_div',
                         'stk_bo_rate', 'stk_co_rate', 'end_date']).to_csv(data / 'dividend.csv', index=False)
    row = dict(ts_code='000001.SZ', trade_date='20171229', open='10', high='11', low='9',
               close='10.005', pre_close='10.005', vol='1000', amount='20000')
    # Future malformed numerical text must not be parsed, used or returned.
    pd.DataFrame([row, dict(row, trade_date='20210104', close='FUTURE_NOT_A_NUMBER')]).to_csv(data / 'daily.csv', index=False)
    pd.DataFrame([dict(ts_code='000001.SZ', trade_date='20171229', up_limit='11', down_limit='9')]).to_csv(data / 'stk_limit.csv', index=False)
    pd.DataFrame(columns=['ts_code', 'trade_date', 'suspend_timing', 'suspend_type']).to_csv(data / 'suspend_d.csv', index=False)
    pd.DataFrame([dict(ts_code='000001.SZ', list_date='20100101', delist_date=None)]).to_csv(meta / 'universe.csv', index=False)
    pd.DataFrame(columns=['ts_code', 'name', 'start_date', 'end_date', 'ann_date']).to_csv(meta / 'name_history.csv', index=False)
    pd.DataFrame(columns=['ts_code', 'l1_code', 'in_date', 'out_date']).to_csv(meta / 'industry_history.csv', index=False)
    return data


def test_context_preserves_lexical_prices_and_filters_future_before_numeric_conversion(local_data):
    context = runner.load_context()
    frame = context['bars']
    assert len(frame) == 1
    assert frame.iloc[0].close_text == '10.005'
    assert frame.iloc[0].pre_close_text == '10.005'
    assert frame.iloc[0].close == 10.005
    assert frame.iloc[0].up_limit == 11
    assert context['schedule'].signal_date.iloc[0] == pd.Timestamp('2017-12-29')
    assert context['schedule'].execution_date.iloc[0] == pd.Timestamp('2018-01-02')
    assert not context['schedule'].execution_date.gt(pd.Timestamp('2020-12-31')).any()


def test_duplicate_price_limits_do_not_silently_choose_a_row(local_data):
    p = local_data / 'stk_limit.csv'
    table = pd.read_csv(p, dtype=str)
    pd.concat([table, table], ignore_index=True).to_csv(p, index=False)
    with pytest.raises(ValueError, match='Duplicate price-limit'):
        runner.load_context()


def test_event_inventory_saved_as_structured_json_before_frame_handling(tmp_path, monkeypatch):
    import momentum_g2_runtime as rt
    monkeypatch.setattr(runner, 'OUT', tmp_path)
    monkeypatch.setattr(runner, 'PREP', tmp_path / 'preparation')
    monkeypatch.setattr(rt, 'OUT', tmp_path)
    value = pd.DataFrame([dict(event_id='x', sources=[dict(path='source.pdf', sha256='abc')])])
    runner._write_preparation(dict(event_inventory=value), dict(preparation_passed=False))
    read = runner._read_preparation()
    assert read['event_inventory'][0]['sources'] == [dict(path='source.pdf', sha256='abc')]
    assert not (runner.PREP / 'event_inventory.csv').exists()


@pytest.mark.parametrize('prevalidation_failure', [False, True])
def test_fixed_cohort_calls_real_progress_and_report_preserves_empty_failure(tmp_path, monkeypatch, prevalidation_failure):
    import momentum_g2_runtime as rt
    import report_momentum_g2 as rp
    from momentum_g2_events import EventBook
    for module in (runner, rt, rp):
        monkeypatch.setattr(module, 'OUT', tmp_path)
    monkeypatch.setattr(runner, 'check_g2_budget', lambda: 1.)
    monkeypatch.setattr(runner, 'verify_frozen', lambda **kwargs: {})
    monkeypatch.setattr(rp, 'verify_frozen', lambda **kwargs: {})
    dates = pd.bdate_range('2017-11-20', '2018-01-12')
    bars = pd.DataFrame(dict(trade_date=dates, ts_code='000001.SZ', open=10., high=10., low=10.,
        close=10., pre_close=10., vol=1_000_000., amount=100_000., up_limit=11., down_limit=9.))
    schedule = pd.DataFrame(dict(signal_date=pd.to_datetime(['2017-12-29']), execution_date=pd.to_datetime(['2018-01-01'])))
    target = schedule.assign(ts_code='000001.SZ', target_weight=.049)
    universe = pd.DataFrame([dict(ts_code='000001.SZ', list_date='20100101', delist_date=None)])
    data = dict(summary=dict(preparation_passed=True, status='prepared'), event_inventory=[],
                schedule=schedule, targets_momentum=target, targets_control=target)
    monkeypatch.setattr(runner, '_read_preparation', lambda: data)
    monkeypatch.setattr(runner, 'load_context', lambda: dict(bars=bars, full_calendar=dates,
        schedule=schedule, universe=universe, suspensions=None))
    rt.persist(tmp_path / 'preparation_audit.json', dict(accounts_allowed=True))
    rt.persist(tmp_path / 'preparation_audit_manifest.json', {'preparation_audit.json': rt.sha(tmp_path / 'preparation_audit.json')})
    if prevalidation_failure:
        def invalid(*args, **kwargs):
            raise ValueError('synthetic pre-validation failure')
        monkeypatch.setattr(runner, 'simulate_account', invalid)
    runner.accounts_stage()
    states = rt.read_json(tmp_path / 'accounts_status.json')
    assert len(states) == 6
    assert states[0]['status'] == ('stopped' if prevalidation_failure else 'complete')
    assert all(s['status'] == ('not_started' if prevalidation_failure else 'complete') for s in states[1:])
    rt.verify_manifest(tmp_path / 'accounts_manifest.json')
    prep = tmp_path / 'preparation'
    prep.mkdir()
    rt.persist(prep / 'summary.json', data['summary'])
    pd.DataFrame(columns=['path', 'signal_date', 'code', 'other_code', 'kind']).to_csv(prep / 'selection_events.csv', index=False)
    rt.make_manifest(prep, tmp_path / 'preparation_manifest.json')
    metadata = tmp_path / 'meta'
    metadata.mkdir()
    pd.DataFrame([dict(ts_code='000001.SZ', in_date='20100101', out_date=None, l1_code='BANK')]).to_csv(metadata / 'industry_history.csv', index=False)
    monkeypatch.setattr(rp, 'META', metadata)
    summary = rp.report()
    assert summary['status'] == ('PARTIAL_ACCOUNT_DATA_OR_ACCOUNTING_STOP' if prevalidation_failure else 'ACCOUNT_AUDIT_NOT_PASSED')
    assert not summary['passed']
    if prevalidation_failure:
        assert summary['metrics']['momentum_0bp'] is None
    else:
        assert summary['metrics']['momentum_0bp']['first_date'] == '2017-12-29'
