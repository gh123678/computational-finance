import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import collect_fixed_financial_indices as indices


def setup_cache(tmp_path,monkeypatch):
    monkeypatch.setattr(indices,'OUT',tmp_path)
    monkeypatch.setattr(indices.audit,'OUT',tmp_path)
    monkeypatch.setattr(indices.time,'sleep',lambda seconds:None)
    (tmp_path/'responses').mkdir()


def test_cached_pagination_preserves_other_issuers_and_never_grants_approval(tmp_path,monkeypatch):
    setup_cache(tmp_path,monkeypatch)
    first={'hasMore':True,'announcements':[{'secCode':'601318','announcementId':'parent'}]}
    second={'hasMore':False,'announcements':[{'secCode':'000001','announcementId':'bank'}]}
    for page,payload in enumerate([first,second],1):
        (tmp_path/'responses'/f'000001.SZ_20130308_{page}.json').write_text(json.dumps(payload),encoding='utf-8')
    result=indices.collect('000001.SZ','20130308')
    assert len(result['pages'])==2
    assert result['exact_code_matches'][0]['announcementId']=='bank'
    assert result['other_code_results'][0]['announcementId']=='parent'
    assert result['usable_in_verified_history'] is False


def test_successful_empty_query_differs_from_network_failure(tmp_path,monkeypatch):
    setup_cache(tmp_path,monkeypatch)
    cache=tmp_path/'responses'/'000001.SZ_20130308_1.json'
    cache.write_text(json.dumps({'hasMore':False,'announcements':[]}),encoding='utf-8')
    assert indices.collect('000001.SZ','20130308')['status']=='successful_query_no_exact_code_match'
    monkeypatch.setattr(indices.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=28,stderr=b'connection timeout'))
    result=indices.collect('000001.SZ','20130309')
    assert result['status']=='query_failed'
    assert len(result['errors'])==2
    assert result['request']['seDate']=='2013-03-09~2013-03-09'
