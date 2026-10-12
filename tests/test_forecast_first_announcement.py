import numpy as np
from audit_forecast_first_announcement import content_identity, exposure_dates


def test_prior_day_never_makes_current_revision_eligible_on_its_release_day():
    days=np.array(['2020-01-02','2020-01-03','2020-01-10','2020-01-17'],dtype='datetime64[ns]')
    result=exposure_dates(days,np.datetime64('2020-01-02'),np.datetime64('2020-01-10'))
    assert result.astype('datetime64[D]').astype(str).tolist()==['2020-01-03','2020-01-10']


def test_numeric_serialization_does_not_hide_changed_forecast_text_or_profit():
    row={'type':'预减','net_profit_min':'100.0','summary':'initial','change_reason':'reason'}
    assert content_identity(row)==content_identity(dict(row,net_profit_min='100'))
    assert content_identity(row)!=content_identity(dict(row,summary='revised'))
    assert content_identity(row)!=content_identity(dict(row,net_profit_min='101'))
