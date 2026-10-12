import pandas as pd
from audit_latest_financial_report_coverage import publication_states, align_states


def test_later_old_report_does_not_shadow_new_period_and_same_day_is_not_visible():
    keys=pd.DataFrame([
        dict(ts_code='A',ann_date='20200401',end_date='20191231',nonempty_profit_rows=1),
        dict(ts_code='A',ann_date='20200420',end_date='20200331',nonempty_profit_rows=0),
        dict(ts_code='A',ann_date='20200423',end_date='20181231',nonempty_profit_rows=1),
        dict(ts_code='A',ann_date='20200428',end_date='20200331',nonempty_profit_rows=2)])
    signals=pd.DataFrame([dict(ts_code='A',trade_date=d) for d in ['2020-04-20','2020-04-24','2020-04-28','2020-04-29']])
    result=align_states(signals,publication_states(keys))
    assert result.end_date.tolist()==['20191231','20200331','20200331','20200331']
    assert result.nonempty_profit_rows.tolist()==[1,0,0,2]
    assert result.ann_date.tolist()==['20200401','20200420','20200420','20200428']
    assert not result.usable_in_verified_history.any()
    assert result.selected_financial_value.isna().all()


def test_newest_period_wins_within_batch_but_competing_versions_are_not_chosen():
    keys=pd.DataFrame([
        dict(ts_code='A',ann_date='20200420',end_date='20191231',distinct_profit_values=1),
        dict(ts_code='A',ann_date='20200420',end_date='20200331',distinct_profit_values=2)])
    result=align_states(pd.DataFrame([dict(ts_code='A',trade_date='2020-04-21')]),publication_states(keys))
    assert result.iloc[0].end_date=='20200331'
    assert result.iloc[0].distinct_profit_values==2
    assert result.selected_financial_value.isna().all()
