import json
from pathlib import Path
import sys
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import announcement_financial_audit as audit

def test_progress_replace_retries_transient_windows_lock(tmp_path,monkeypatch):
    original=Path.replace;calls=[]
    def replace(path,target):
        calls.append(path)
        if len(calls)<3:raise PermissionError('temporary Windows reader lock')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',replace);monkeypatch.setattr(audit.time,'sleep',lambda _:None)
    target=tmp_path/'status.json';audit.write_json(target,{'state':'running'})
    assert len(calls)==3 and json.loads(target.read_text())['state']=='running'

def test_announcement_next_session_not_report_period_or_first_announcement():
    f=pd.DataFrame([dict(ts_code='X',ann_date='20200103',end_date='20191231',first_ann_date='20191001'),
                    dict(ts_code='X',ann_date='20200108',end_date='20191231',first_ann_date='20191001'),
                    dict(ts_code='X',ann_date='20210103',end_date='20201231',first_ann_date='20200103')])
    calendar=pd.DatetimeIndex(pd.to_datetime(['20200103','20200106','20200108','20200109']))
    r=audit.annotate(f,'forecast',calendar)
    assert r.candidate_available_date.tolist()==[pd.Timestamp('20200106'),pd.Timestamp('20200109'),pd.NaT]
    assert not r.usable_in_verified_history.any()

def test_forecast_units_and_invalid_dates():
    f=pd.DataFrame([dict(ann_date='20200103',end_date='20191231',net_profit_min=-45000),
                    dict(ann_date='20200103',end_date='20200331',net_profit_min=None)])
    r=audit.annotate(f,'forecast',pd.DatetimeIndex(pd.to_datetime(['20200106'])))
    assert r.net_profit_min_cny.iloc[0]==-450000000
    assert r.candidate_available_date.iloc[1]==pd.Timestamp('20200106')  # Forecasts can precede the period end.
    assert pd.isna(r.net_profit_min_cny.iloc[1])
    bad=audit.annotate(f,'fina_indicator',pd.DatetimeIndex(pd.to_datetime(['20200106'])))
    assert pd.isna(bad.candidate_available_date.iloc[1])

def test_equal_original_and_updated_values_not_content_conflict():
    f=pd.DataFrame([dict(ts_code='X',ann_date='20200103',end_date='20191231',profit_dedt=1,update_flag='0'),
                    dict(ts_code='X',ann_date='20200103',end_date='20191231',profit_dedt=1,update_flag='1')])
    r=audit.annotate(f,'fina_indicator',pd.DatetimeIndex(pd.to_datetime(['20200106'])))
    assert r.content_sha256.nunique()==1 and r.row_sha256.nunique()==2
    assert not r.usable_in_verified_history.any()

def test_full_page_splits_report_period_without_overlap(tmp_path,monkeypatch):
    monkeypatch.setattr(audit,'DATA',tmp_path);monkeypatch.setitem(audit.CAPS,'fina_indicator',2)
    calls=[]
    class Fake:
        cache=tmp_path/'raw'
        def query(self,api,params,fields):
            calls.append(params)
            rows=[['X','20200430','20191231'],['X','20200830','20200630']]
            rows=[r for r in rows if params['start_date']<=r[2]<=params['end_date']]
            data={'fields':['ts_code','ann_date','end_date'],'items':rows}
            public={'api_name':api,'params':params,'fields':fields}
            key=audit.hashlib.sha256(json.dumps(public,sort_keys=True).encode()).hexdigest()
            file=self.cache/api/(key+'.json');file.parent.mkdir(parents=True,exist_ok=True)
            file.write_text(json.dumps({'data':data}),encoding='utf-8')
            return data
    leaves=audit.partitioned_query(Fake(),'fina_indicator','X','20191231','20200630')
    assert len(leaves)==2 and len(calls)==3
    assert calls[1]['end_date']<calls[2]['start_date']

def test_single_date_cap_refuses_truncation(tmp_path,monkeypatch):
    monkeypatch.setitem(audit.CAPS,'forecast',1);monkeypatch.setattr(audit,'DATA',tmp_path)
    class Fake:
        cache=tmp_path
        def query(self,*args):return {'fields':['ts_code','ann_date','end_date'],'items':[['X','20200101','20191231']]}
    monkeypatch.setattr(audit,'sha',lambda p:'stub')
    with pytest.raises(audit.DataError,match='single date'):
        audit.partitioned_query(Fake(),'forecast','X','20200101','20200101')
