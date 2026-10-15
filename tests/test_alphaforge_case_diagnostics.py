import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from alphaforge_case_diagnostics import diagnostics, summarize_ic, render_figures


def inputs(n=20):
    factor = np.arange(n, dtype=float)
    samples = pd.DataFrame(dict(trade_date=pd.Timestamp('2018-01-05'),
                                ts_code=[f'C{i:02}' for i in range(n)],
                                case_factor=factor, case_signal=-factor,
                                three_score=(factor+1)/n, D_label=factor**3,
                                D_valid=True, D_end=pd.Timestamp('2018-01-15')))
    schedule = pd.DataFrame(dict(signal_date=[pd.Timestamp('2018-01-05')],
                                 execution_date=[pd.Timestamp('2018-01-08')]))
    return samples, schedule


def test_missing_future_labels_never_change_formation_groups():
    samples, schedule = inputs()
    _, complete = diagnostics(samples, schedule)
    samples.loc[[0, 1, 2, 3, 19], ['D_label']] = np.nan
    samples.loc[[4, 5], 'D_valid'] = False
    ic, missing = diagnostics(samples, schedule)
    pd.testing.assert_series_equal(complete.n_formed, missing.n_formed)
    original = missing.loc[missing.factor.eq('case_factor')].set_index('group')
    assert original.n_formed.tolist() == [4, 4, 4, 4, 4]
    assert original.n.tolist() == [0, 2, 4, 4, 3]
    assert np.isnan(original.loc[1, 'mean_forward_return'])
    assert original.loc[2, 'mean_forward_return'] == pytest.approx((6**3+7**3)/2)
    row = ic.loc[ic.factor.eq('case_factor')].iloc[0]
    assert row.n_formed == 20 and row.n == row.n_valid == 13
    assert row.coverage == row.label_coverage == pytest.approx(.65)


def test_pearson_is_linear_correlation_and_spearman_is_rank_correlation():
    samples, schedule = inputs()
    ic, _ = diagnostics(samples, schedule)
    row = ic.loc[ic.factor.eq('case_factor')].iloc[0]
    assert row.rank_ic == pytest.approx(1)
    assert .85 < row.ic < .95
    assert row.ic != pytest.approx(row.rank_ic)


def test_negative_signal_has_opposite_ic_without_changing_missing_statistics():
    samples, schedule = inputs()
    ic, groups = diagnostics(samples, schedule)
    indexed = ic.set_index('factor')
    assert indexed.loc['case_signal', 'ic'] == pytest.approx(-indexed.loc['case_factor', 'ic'])
    assert indexed.loc['case_signal', 'rank_ic'] == pytest.approx(-indexed.loc['case_factor', 'rank_ic'])
    g = groups.pivot(index='group', columns='factor', values='mean_forward_return')
    assert g.case_factor.tolist() == pytest.approx(g.case_signal.tolist()[::-1])
    samples.loc[:, 'D_valid'] = False
    ic, _ = diagnostics(samples, schedule)
    assert ic[['ic', 'rank_ic']].isna().all().all()


@pytest.mark.parametrize('constant', ['factor', 'label'])
def test_constant_cross_sections_are_undefined_and_groups_are_not_fabricated(constant):
    samples, schedule = inputs()
    if constant == 'factor':
        samples['case_factor'] = 0.
        samples['case_signal'] = -0.
        samples['three_score'] = .5
    else:
        samples['D_label'] = .03
    ic, groups = diagnostics(samples, schedule)
    assert ic[['ic', 'rank_ic']].isna().all().all()
    if constant == 'factor':
        assert groups.loc[groups.group.eq(3), 'n_formed'].eq(20).all()
        assert groups.loc[groups.group.ne(3), 'n_formed'].eq(0).all()


def test_ten_valid_labels_required_and_saved_false_flags_are_false():
    samples, schedule = inputs()
    samples['D_valid'] = ['true']*9 + ['false']*11
    ic, _ = diagnostics(samples, schedule)
    assert ic.n.eq(9).all()
    assert ic[['ic', 'rank_ic']].isna().all().all()
    samples.loc[9, 'D_valid'] = 'true'
    ic, _ = diagnostics(samples, schedule)
    assert ic.n.eq(10).all() and ic.ic.notna().all()


def test_nonfinite_factors_and_labels_excluded_without_label_based_formation():
    samples, schedule = inputs()
    samples.loc[0, ['case_factor', 'case_signal']] = [np.inf, -np.inf]
    samples.loc[1, 'D_label'] = np.inf
    ic, groups = diagnostics(samples, schedule)
    indexed = ic.set_index('factor')
    assert indexed.loc['case_factor', 'n_formed'] == 19
    assert indexed.loc['case_factor', 'n'] == 18
    assert indexed.loc['three_score', 'n_formed'] == 20
    assert indexed.loc['three_score', 'n'] == 19
    assert groups.loc[groups.factor.eq('case_factor'), 'n_formed'].sum() == 19


def test_average_tie_percentiles_are_formed_before_future_label_filter():
    samples, schedule = inputs()
    samples['case_factor'] = np.repeat([0., 1., 2., 3.], 5)
    samples['case_signal'] = -samples.case_factor
    samples.loc[0, 'D_valid'] = False
    _, groups = diagnostics(samples, schedule)
    original = groups.loc[groups.factor.eq('case_factor')].set_index('group')
    # The tied percentiles are .15, .40, .65 and .90, mapping to 1, 2, 4, 5.
    assert original.n_formed.tolist() == [5, 5, 0, 5, 5]
    assert original.n.tolist() == [4, 5, 0, 5, 5]


def test_schedule_uses_execution_year_and_ignores_other_years():
    samples, _ = inputs()
    samples['trade_date'] = pd.Timestamp('2017-12-29')
    schedule = pd.DataFrame(dict(signal_date=pd.to_datetime(['2017-12-22', '2017-12-29', '2020-12-31']),
                                 execution_date=pd.to_datetime(['2017-12-25', '2018-01-02', '2021-01-04'])))
    ic, groups = diagnostics(samples, schedule)
    assert len(ic) == 3 and len(groups) == 15
    assert ic.year.eq(2018).all() and ic.n.eq(20).all()


def test_empty_scheduled_cross_section_is_reported_as_missing():
    samples, schedule = inputs()
    ic, groups = diagnostics(samples.iloc[:0], schedule)
    assert len(ic) == 3 and len(groups) == 15
    assert ic.n_formed.eq(0).all() and ic.ic.isna().all()
    assert ic.coverage.isna().all() and groups.mean_forward_return.isna().all()


@pytest.mark.parametrize('fault', ['duplicate', 'signal_direction', 'flag', 'schedule'])
def test_invalid_diagnostic_inputs_fail_explicitly(fault):
    samples, schedule = inputs()
    if fault == 'duplicate':
        samples = pd.concat([samples, samples.iloc[:1]], ignore_index=True)
    elif fault == 'signal_direction':
        samples.loc[1, 'case_signal'] = samples.loc[1, 'case_factor']
    elif fault == 'flag':
        samples['D_valid'] = 'unknown'
    else:
        schedule['execution_date'] = schedule.signal_date
    with pytest.raises(ValueError):
        diagnostics(samples, schedule)


def test_ic_summary_uses_sample_std_and_no_annualization_or_zero_imputation():
    rows = pd.DataFrame(dict(factor=['case_factor']*3, year=[2018]*3,
                             ic=[.1, .2, .3], rank_ic=[.5, .5, .5]))
    result = summarize_ic(rows).set_index(['factor', 'period'])
    row = result.loc[('case_factor', 'all')]
    assert row.ic_mean == pytest.approx(.2)
    assert row.ic_std == pytest.approx(.1)
    assert row.ic_ir == pytest.approx(2)
    assert np.isnan(row.rank_ic_ir)
    assert row.std_ddof == 1 and not row.annualized
    empty = result.loc[('case_signal', 'all')]
    assert empty.ic_n == 0 and np.isnan(empty.ic_mean) and np.isnan(empty.ic_ir)


def test_render_reads_six_saved_account_ledgers_and_diagnostic_files(tmp_path):
    import json
    from PIL import Image
    samples, schedule = inputs()
    ic, groups = diagnostics(samples, schedule)
    ic.to_csv(tmp_path/'factor_ic.csv', index=False)
    groups.to_csv(tmp_path/'factor_groups.csv', index=False)
    samples.to_csv(tmp_path/'common_samples.csv', index=False)
    pd.DataFrame({'reason': ['valid', 'valid', 'warmup_200']}).to_csv(tmp_path/'feature_coverage.csv', index=False)
    experiments = []
    for path in ['case_fixture', 'three_fixture']:
        for cost in [0, 10, 30]:
            strategy = f'{path}_{cost}bp'
            folder = tmp_path/strategy
            folder.mkdir()
            pd.DataFrame(dict(date=['2017-12-29', '2018-01-02', '2018-01-03'],
                              equity=[1_000_000, 990_000, 1_010_000])).to_csv(folder/'nav.csv', index=False)
            experiments.append(dict(strategy=strategy, path=path, config=dict(slippage_bps=cost),
                                    total_fees=cost*100, total_slippage=cost*200, total_return=.01))
    (tmp_path/'summary.json').write_text(json.dumps(dict(experiments=experiments)), encoding='utf-8')
    rendered = render_figures(tmp_path)
    assert len(rendered) == 4
    for filename in rendered:
        with Image.open(tmp_path/filename) as image:
            assert image.width >= 2000 and image.height >= 1500
    # A missing actual ledger must fail rather than plotting compounded D_label.
    (tmp_path/experiments[-1]['strategy']/'nav.csv').unlink()
    with pytest.raises(ValueError, match='Missing actual account NAV'):
        render_figures(tmp_path)
