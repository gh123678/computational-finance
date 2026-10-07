import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_financial_candidate_age import candidate_age


def test_future_revision_never_changes_earlier_publication_age():
    signals = pd.DataFrame({'ts_code':['A','A','A'], 'trade_date':['2020-01-20','2020-01-22','2020-02-03']})
    rows = pd.DataFrame([
        ['A','20200121','20191231','2020-01-22','a','original'],
        ['A','20200131','20191231','2020-02-03','b','revision1'],
        ['A','20200131','20191231','2020-02-03','c','revision2']], columns=[
            'ts_code','ann_date','end_date','candidate_available_date','row_sha256','content_sha256'])
    units = pd.DataFrame({'ts_code':['A'], 'status':['success_nonempty']})
    result = candidate_age(signals,rows,units).reset_index(drop=True)
    assert pd.isna(result.loc[0,'candidate_available_date'])
    assert result.loc[1,'latest_candidate_ann_age_calendar_days'] == 1
    assert result.loc[1,'candidate_batch_rows'] == 1
    assert result.loc[2,'candidate_batch_rows'] == 2
    assert result.loc[2,'candidate_batch_has_content_conflict'] == True
    assert not result.usable_in_verified_history.any()


def test_empty_query_and_unfinished_download_remain_distinct_unknowns():
    signals = pd.DataFrame({'ts_code':['A','B'], 'trade_date':['2020-01-20']*2})
    rows = pd.DataFrame(columns=['ts_code','ann_date','end_date','candidate_available_date','row_sha256','content_sha256'])
    units = pd.DataFrame({'ts_code':['A','B'], 'status':['success_empty','not_completed']})
    result = candidate_age(signals,rows,units).set_index('ts_code')
    assert result.loc['A','coverage_status'] == 'successful_empty_query'
    assert result.loc['B','coverage_status'] == 'download_not_completed'
    assert result.latest_candidate_ann_age_calendar_days.isna().all()
