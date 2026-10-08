import importlib.util
from pathlib import Path
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('retention_selector',Path(__file__).resolve().parents[1]/'scripts/retention_selector.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
select=module.select_retention


def frame(scores,industries=None):
    return pd.DataFrame(dict(ts_code=[f'{i:06}' for i in range(len(scores))],score=scores,
        industry=industries or [f's{i//5}' for i in range(len(scores))],trade_date=pd.Timestamp('20200103')))


def test_exact_gap_and_larger_gap():
    data=frame([.5]*20+[.55], [f's{i//5}' for i in range(20)]+['extra'])
    prior=data.ts_code.iloc[:20]
    selected,events=select(data,prior)
    assert set(selected.ts_code)==set(prior)
    data.loc[20,'score']=.550001
    selected,events=select(data,prior)
    assert len(events.loc[events.kind.eq('active_replace')])==1
    assert '000020' in set(selected.ts_code)


def test_cap_and_determinism():
    data=frame([.1]*20+[.9]*20)
    prior=data.ts_code.iloc[:20]
    a,events=select(data,prior)
    b,_=select(data.sample(frac=1,random_state=42),prior)
    assert a.ts_code.tolist()==b.ts_code.tolist()
    assert len(events.loc[events.kind.eq('active_replace')])==5
    assert len(set(a.ts_code)-set(prior))==5


def test_mandatory_exits_and_industry_limit():
    data=frame([.5]*40)
    prior=set(data.ts_code.iloc[:20])
    data=data.loc[~data.ts_code.isin(sorted(prior)[:8])]
    selected,events=select(data,prior)
    assert len(events.loc[events.kind.eq('forced_exit')])==8
    assert len(selected)==20
    assert len(set(selected.ts_code)-prior)==8
    assert selected.groupby('industry').target_weight.sum().max()<=.25


def test_industry_change_and_unfilled_cash():
    data=frame([.5]*20,['one']*20)
    selected,events=select(data,data.ts_code)
    assert len(selected)==5
    assert len(events.loc[events.reason.eq('industry_cap')])==15
    assert selected.target_weight.sum()==pytest.approx(.245)


def test_empty_pool_and_forbidden_parameters():
    data=frame([.1]).iloc[:0]
    selected,events=select(data,['missing'])
    assert selected.empty and len(events)==1
    with pytest.raises(ValueError):
        select(data,gap=.1)


def test_replacement_uses_lowest_feasible_industry_member():
    data=frame([.1]*5+[.5]*5+[.7]*5+[.8]*5+[.9],
               ['b']*5+['a']*5+['c']*5+['d']*5+['a'])
    selected,events=select(data,data.ts_code.iloc[:20])
    active=events.loc[events.kind.eq('active_replace')]
    assert active.code.tolist()==['000005']
    assert set(data.ts_code.iloc[:5]).issubset(set(selected.ts_code))
    assert selected.groupby('industry').size().max()==5


def test_forced_exits_can_exceed_cap_together_with_active_replacements():
    data=frame([.1]*20+[.9]*20)
    previous=set(data.ts_code.iloc[:20])
    data=data.loc[~data.ts_code.isin(sorted(previous)[:8])]
    selected,events=select(data,previous)
    assert len(events.loc[events.kind.eq('forced_exit')])==8
    assert len(events.loc[events.kind.eq('active_replace')])==5
    assert len(set(selected.ts_code)-previous)==13
