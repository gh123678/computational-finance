import hashlib

import pandas as pd
import pytest

from momentum_g2_selection import CONTROL_PREFIX, build_targets, control_key, select_control


def pool(count=240):
    return pd.DataFrame({'trade_date': pd.Timestamp('2017-12-29'),
                         'ts_code': [f'{i:06d}.SZ' for i in range(1, count + 1)],
                         'industry': [f'I{i % 12}' for i in range(count)],
                         'momentum': [i / count for i in range(count)],
                         'formation_close': 10., 'adv20_cny': 30_000_000.})


def test_fixed_utf8_digest_and_leading_zero_identity():
    expected = hashlib.sha256(b'CF2026_G2_MOM_CONTROL_V1|000001.SZ').hexdigest()
    assert control_key('000001.SZ') == expected
    assert len(expected) == 64 and expected == expected.lower()
    for invalid in ('1.SZ', '000001.sz', '300001.SZ', '600001.SH\n'):
        with pytest.raises(ValueError):
            control_key(invalid)


def test_new_lower_key_does_not_replace_eligible_incumbents_and_ignores_scores():
    frame = pool()
    ordered = sorted(frame.ts_code, key=control_key)
    incumbents = ordered[-20:]
    first, _ = select_control(frame, incumbents)
    changed = frame.assign(momentum=lambda x: -x.momentum, score=999.)
    second, events = select_control(changed, incumbents)
    assert set(first.ts_code) == set(incumbents) == set(second.ts_code)
    assert not events.kind.eq('active_replace').any()


def test_industry_change_forces_exit_by_hash_without_renormalizing():
    frame = pool(8).assign(industry='ONE')
    selected, events = select_control(frame, frame.ts_code)
    assert selected.ts_code.tolist() == sorted(frame.ts_code, key=control_key)[:5]
    assert len(events.loc[events.reason.eq('industry_cap')]) == 3
    assert selected.target_weight.tolist() == [.049] * 5
    assert selected.target_weight.sum() == pytest.approx(.245)


def test_two_cost_independent_target_paths_and_equal_momentum_ties():
    frame = pool().assign(momentum=0.)
    dates = pd.DataFrame({'signal_date': [pd.Timestamp('2017-12-29')],
                          'execution_date': [pd.Timestamp('2018-01-02')]})
    result = build_targets(frame, dates)
    assert result['ranked_features'].score.nunique() == 1
    assert set(result['targets']) == {'momentum', 'control'}
    assert 'momentum' not in result['targets']['control']
    assert 'score' not in result['targets']['control']
    assert result['targets']['momentum'].ts_code.tolist() == sorted(frame.ts_code)[:20]
    assert all(len(t) == 20 for t in result['targets'].values())


def test_fixed_200_gate_and_duplicate_identity_not_silently_dropped():
    dates = pd.DataFrame({'signal_date': [pd.Timestamp('2017-12-29')],
                          'execution_date': [pd.Timestamp('2018-01-02')]})
    with pytest.raises(ValueError, match='200'):
        build_targets(pool(199), dates)
    duplicated = pd.concat([pool(), pool().iloc[:1]], ignore_index=True)
    with pytest.raises(ValueError, match='Duplicate'):
        build_targets(duplicated, dates)


def test_future_week_does_not_change_already_formed_targets():
    first = pool()
    second = pool().assign(trade_date=pd.Timestamp('2018-01-05'), momentum=lambda x: -x.momentum)
    dates = pd.DataFrame({'signal_date': pd.to_datetime(['2017-12-29', '2018-01-05']),
                          'execution_date': pd.to_datetime(['2018-01-02', '2018-01-08'])})
    initial = build_targets(first, dates.iloc[:1])
    longer = build_targets(pd.concat([first, second], ignore_index=True), dates)
    for path in ('momentum', 'control'):
        pd.testing.assert_frame_equal(initial['targets'][path],
            longer['targets'][path].loc[lambda x: x.signal_date.eq(pd.Timestamp('2017-12-29'))].reset_index(drop=True))
