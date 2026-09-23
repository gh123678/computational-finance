"""Read-only Tushare access with private credentials and auditable caching."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]


class DataError(RuntimeError):
    pass


def load_token() -> str:
    token = os.environ.get('TUSHARE_TOKEN', '').strip()
    if token:
        return token
    secret = ROOT / '.secrets' / 'tushare.dpapi'
    if os.name != 'nt' or not secret.is_file():
        raise DataError('Set TUSHARE_TOKEN locally; do not put it in source code.')
    script = (
        "$ErrorActionPreference='Stop'; "
        "$s=(Get-Content -Raw -LiteralPath '.secrets/tushare.dpapi').Trim() | ConvertTo-SecureString; "
        "[System.Net.NetworkCredential]::new('', $s).Password"
    )
    result = subprocess.run(
        [shutil.which('pwsh.exe') or 'powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode or not result.stdout.strip():
        raise DataError('Cannot decrypt local credential under this Windows user/profile.')
    return result.stdout.strip()


class TushareClient:
    """HTTPS only; errors never include request bodies or credentials."""

    def __init__(self, token: str, cache: Path | None = None, interval: float = 1.3):
        if not token or interval < 0:
            raise ValueError('A token and nonnegative interval are required.')
        self._token = token
        self.cache = cache or ROOT / 'data' / 'raw'
        self.interval = interval
        self._last_request = 0.0

    def query(self, api: str, params: dict, fields: str = '', *, refresh=False) -> dict:
        public = {'api_name': api, 'params': params, 'fields': fields}
        key = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
        target = self.cache / api / f'{key}.json'
        if target.exists() and not refresh:
            saved = json.loads(target.read_text(encoding='utf-8'))
            payload = saved['data']
            checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            if checksum != saved['sha256']:
                raise DataError(f'{api}: corrupt cache checksum')
            return payload
        body = json.dumps(dict(public, token=self._token)).encode()
        for attempt in range(3):
            time.sleep(max(0, self.interval - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            try:
                request = Request('https://api.tushare.pro', data=body,
                                  headers={'Content-Type': 'application/json'}, method='POST')
                with urlopen(request, timeout=20) as response:
                    result = json.load(response)
                break
            except (URLError, TimeoutError, OSError, ValueError):
                if attempt == 2:
                    raise DataError(f'{api}: network/TLS/response failure after 3 attempts') from None
                time.sleep(2 ** attempt)
        if not isinstance(result, dict):
            raise DataError(f'{api}: invalid response envelope')
        if result.get('code') != 0:
            message = str(result.get('msg', 'unknown API error')).replace(self._token, '[REDACTED]')
            raise DataError(f'{api}: code={result.get("code")}; {message}')
        payload = result.get('data')
        if not isinstance(payload, dict) or not isinstance(payload.get('fields'), list) or not isinstance(payload.get('items'), list):
            raise DataError(f'{api}: invalid response schema')
        if any(len(row) != len(payload['fields']) for row in payload['items']):
            raise DataError(f'{api}: inconsistent row lengths')
        saved = dict(public, retrieved_at=datetime.now(timezone.utc).isoformat(), data=payload,
                     sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
        temporary.replace(target)
        return payload

    def paged(self, api: str, params: dict, fields='', page_size=1000, max_pages=100):
        """Use only for interfaces supporting limit/offset; reject ignored pagination."""
        if not isinstance(page_size, int) or page_size <= 0 or not isinstance(max_pages, int) or max_pages <= 0:
            raise ValueError('Pagination bounds must be positive integers.')
        rows, schema, signatures = [], None, set()
        for page in range(max_pages):
            result = self.query(api, dict(params, limit=page_size, offset=page * page_size), fields)
            if schema is not None and schema != result['fields']:
                raise DataError(f'{api}: schema changed between pages')
            schema = result['fields']
            items = result['items']
            if len(items) > page_size:
                raise DataError(f'{api}: server ignored requested page size')
            if not items:
                return {'fields': schema, 'items': rows}
            signature = hashlib.sha256(json.dumps(items).encode()).hexdigest()
            if signature in signatures:
                raise DataError(f'{api}: repeated page; pagination may be unsupported')
            signatures.add(signature)
            rows.extend(items)
            if len(items) < page_size:
                return {'fields': schema, 'items': rows}
        raise DataError(f'{api}: pagination bound reached; refusing truncated data')
