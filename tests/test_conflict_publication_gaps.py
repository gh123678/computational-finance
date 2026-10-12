import pandas as pd
from profile_conflict_publication_gaps import earlier_signals


def test_iso_signal_dates_and_compact_pdf_dates_preserve_same_day_boundary():
    signals=pd.DataFrame({'trade_date':['2016-03-25','2016-03-31','2016-04-01']})
    assert earlier_signals(signals,'20160331').trade_date.tolist()==['2016-03-25']
