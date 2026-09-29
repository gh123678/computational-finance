import json
from pathlib import Path
import pytest
from quant_research.data import TushareClient, DataError


def test_repeated_pagination_fails_closed(tmp_path, monkeypatch):
    client = TushareClient('test-only', cache=tmp_path, interval=0)
    monkeypatch.setattr(client, 'query', lambda *a, **k: {'fields': ['code'], 'items': [['A']]})
    with pytest.raises(DataError, match='repeated page'):
        client.paged('fake', {}, page_size=1)


def test_partial_final_page_preserves_data(tmp_path, monkeypatch):
    client = TushareClient('test-only', cache=tmp_path, interval=0)
    def query(api, params, fields):
        return {'fields': ['code'], 'items': [['A'], ['B']] if params['offset'] == 0 else [['C']]}
    monkeypatch.setattr(client, 'query', query)
    assert client.paged('fake', {}, page_size=2)['items'] == [['A'], ['B'], ['C']]


def test_server_ignoring_page_limit_is_rejected(tmp_path, monkeypatch):
    client = TushareClient('test-only', cache=tmp_path, interval=0)
    monkeypatch.setattr(client, 'query', lambda *a, **k: {'fields': ['code'], 'items': [['A'], ['B']]})
    with pytest.raises(DataError, match='page size'):
        client.paged('fake', {}, page_size=1)
