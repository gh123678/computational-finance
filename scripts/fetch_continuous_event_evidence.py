"""Archive public issuer documents and query public announcement metadata."""
import hashlib
import argparse
import io
import json
from pathlib import Path

import requests
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/continuous_event_audit_20261005/evidence'


def main(additional=False):
    OUT.mkdir(parents=True, exist_ok=True)
    sources = {
        '002713_20251224': 'https://static.cninfo.com.cn/finalpage/2025-12-24/1224894734.PDF',
        '002742_20251227': 'https://static.cninfo.com.cn/finalpage/2025-12-27/1224900858.PDF',
        '600375_20241220': 'https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2024-12-20/600375_20241220_NA50.pdf',
    }
    if additional:
        sources = {
            '001323_20250603': 'https://static.cninfo.com.cn/finalpage/2025-06-03/1223733350.PDF',
            '002742_20251205': 'https://static.cninfo.com.cn/finalpage/2025-12-05/1224850420.PDF',
        }
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cninfo.com.cn/'})
    results = []
    try:
        if additional:
            raise StopIteration
        response = session.post('https://www.cninfo.com.cn/new/hisAnnouncement/query',
                                data={'pageNum': 1, 'pageSize': 30, 'tabName': 'fulltext',
                                      'column': 'szse', 'searchkey': '慕思 权益分派',
                                      'seDate': '2025-05-20~2025-06-09', 'isHLtitle': 'false'}, timeout=25)
        response.raise_for_status()
        metadata = response.json()
        (OUT / '001323_query.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        for item in metadata.get('announcements') or []:
            if item.get('secCode') == '001323':
                sources[f"001323_{item['announcementId']}"] = 'https://static.cninfo.com.cn/' + item['adjunctUrl']
                print(item['announcementTitle'], item['adjunctUrl'])
    except StopIteration:
        pass
    except (requests.RequestException, ValueError) as error:
        results.append({'query': '001323', 'status': 'failed', 'error': str(error)})
    for name, url in sources.items():
        try:
            response = session.get(url, timeout=25)
            response.raise_for_status()
            content = response.content
            assert content.startswith(b'%PDF'), 'response is not a PDF'
            text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(content)).pages)
            (OUT / f'{name}.pdf').write_bytes(content)
            (OUT / f'{name}.txt').write_text(text, encoding='utf-8')
            results.append({'name': name, 'url': url, 'status': 'archived', 'sha256': hashlib.sha256(content).hexdigest()})
            print(name, 'archived', len(content))
        except (requests.RequestException, ValueError, AssertionError) as error:
            results.append({'name': name, 'url': url, 'status': 'failed', 'error': str(error)})
    name = 'additional_manifest.json' if additional else 'manifest.json'
    (OUT / name).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--additional', action='store_true')
    main(parser.parse_args().additional)
