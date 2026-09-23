import pandas as pd
from quant_research.adjustment_audit import audit_adjustments
from quant_research.rights import RightsIssue


def test_event_in_quote_gap_is_explained_but_unrelated_change_is_exposed():
    bars = pd.DataFrame(dict(ts_code=['A', 'A', 'B', 'B'],
                             trade_date=pd.to_datetime(['20200102','20200110','20200102','20200110']),
                             adj_factor=[1., 2., 1., 1.001]))
    rights = [RightsIssue('A', pd.Timestamp('20200103'), pd.Timestamp('20200106'), 'source')]
    result = audit_adjustments(bars, [], rights)
    assert result.ts_code.tolist() == ['B']
