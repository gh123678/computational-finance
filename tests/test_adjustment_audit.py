import pandas as pd
from quant_research.adjustment_audit import audit_adjustments, quarantine_factors, return_consistency_check
from quant_research.rights import RightsIssue


def test_event_in_quote_gap_is_explained_but_unrelated_change_is_exposed():
    bars = pd.DataFrame(dict(ts_code=['A', 'A', 'B', 'B'],
                             trade_date=pd.to_datetime(['20200102','20200110','20200102','20200110']),
                             adj_factor=[1., 2., 1., 1.001]))
    rights = [RightsIssue('A', pd.Timestamp('20200103'), pd.Timestamp('20200106'), 'source')]
    result = audit_adjustments(bars, [], rights, threshold=.0005)
    assert result.ts_code.tolist() == ['B']


def test_audit_ignores_vendor_precision_revisions_below_materiality_threshold():
    bars = pd.DataFrame(dict(ts_code=['A', 'A'],
                             trade_date=pd.to_datetime(['20200102', '20200103']),
                             adj_factor=[4.3545, 4.3540]))
    assert audit_adjustments(bars, [], []).empty


def test_consistency_flags_factor_jump_without_raw_gap_and_no_event():
    bars = pd.DataFrame(dict(ts_code=['A', 'A', 'B', 'B', 'C', 'C'],
                             trade_date=pd.to_datetime(['20200102', '20200110'] * 3),
                             close=[10., 11., 10., 11., 10., 10.01],
                             adj_factor=[1., 1.1, 1., 1.1, 1., 1.0001]))
    rights = [RightsIssue('B', pd.Timestamp('20200103'), pd.Timestamp('20200106'), 'source')]
    result = return_consistency_check(bars, [], rights)
    assert result.ts_code.tolist() == ['A']
    assert result.return_gap.iloc[0] > 0.05


def test_consistency_ignores_tiny_factor_noise_below_threshold():
    bars = pd.DataFrame(dict(ts_code=['A', 'A'],
                             trade_date=pd.to_datetime(['20200102', '20200110']),
                             close=[10., 10.5],
                             adj_factor=[1., 1.001]))
    assert return_consistency_check(bars, [], []).empty


def test_consistency_rejects_invalid_threshold():
    bars = pd.DataFrame(dict(ts_code=['A'], trade_date=pd.to_datetime(['20200102']),
                             close=[10.], adj_factor=[1.]))
    for bad in (0, -0.1, 1.5):
        try:
            return_consistency_check(bars, [], [], threshold=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'accepted threshold {bad}')


def test_quarantine_covers_exact_price_lookback_without_mutating_input():
    calendar = pd.bdate_range('2020-01-01', periods=25)
    factors = pd.DataFrame({'trade_date': calendar, 'ts_code': 'A',
                            'momentum20': 1., 'reversal5': 1., 'lowvol20': 1., 'adv20_cny': 1.})
    issues = pd.DataFrame({'trade_date': [calendar[2]], 'ts_code': ['A']})
    result, count = quarantine_factors(factors, issues, calendar, window=20)
    assert count == 20
    assert result.loc[2:21, ['momentum20', 'reversal5', 'lowvol20']].isna().all().all()
    assert result.loc[22, 'momentum20'] == 1
    assert factors.momentum20.notna().all()
