import io
import json
import pytest
from quant_research.data import TushareClient, DataError


def test_cache_excludes_credential_and_detects_corruption(tmp_path, monkeypatch):
    payload = {'code': 0, 'data': {'fields': ['code'], 'items': [['A']]}}
    monkeypatch.setattr('quant_research.data.urlopen', lambda *a, **k: io.BytesIO(json.dumps(payload).encode()))
    client = TushareClient('fake-private-token', cache=tmp_path, interval=0)
    assert client.query('fake', {})['items'] == [['A']]
    file = next(tmp_path.rglob('*.json'))
    assert 'fake-private-token' not in file.read_text()
    changed = json.loads(file.read_text())
    changed['data']['items'][0][0] = 'B'
    file.write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(DataError, match='corrupt'):
        client.query('fake', {})


def test_api_error_redacts_token(tmp_path, monkeypatch):
    payload = {'code': 1, 'msg': 'invalid fake-private-token'}
    monkeypatch.setattr('quant_research.data.urlopen', lambda *a, **k: io.BytesIO(json.dumps(payload).encode()))
    client = TushareClient('fake-private-token', cache=tmp_path, interval=0)
    with pytest.raises(DataError) as exc:
        client.query('fake', {})
    assert 'fake-private-token' not in str(exc.value)
    assert not list(tmp_path.rglob('*.json'))
