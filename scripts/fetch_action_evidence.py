"""Download public issuer results for the fixed 23-event review; no credentials."""
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path

import pandas as pd
from pypdf import PdfReader
import requests

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'output/development_comparison/action_evidence_20260928'


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    scope = set()
    for year in (2016, 2017, 2019):
        events = pd.read_csv(ROOT / f'output/development_comparison/before_rights_20260928/development_{year}/unexplained_adjustments.csv')
        scope.update((e.ts_code[:6], e.trade_date[:4]) for e in events.itertuples())
    announcements = []
    for page in (1, 2):
        response = requests.post('https://www.cninfo.com.cn/new/hisAnnouncement/query',
            data=dict(pageNum=page, pageSize=30, tabName='fulltext', column='szse',
                      searchkey='配股发行结果', seDate='2016-01-01~2019-12-31', isHLtitle='true'),
            headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        (DEST / f'index_{page}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        announcements.extend(a for a in payload['announcements']
                             if (a['secCode'], a['adjunctUrl'].split('/')[1][:4]) in scope
                             and 'H股' not in a['announcementTitle'])

    def download(a):
        url = 'https://static.cninfo.com.cn/' + a['adjunctUrl']
        filename = a['secCode'] + '_' + a['adjunctUrl'].split('/')[-1]
        result = dict(code=a['secCode'], title=a['announcementTitle'], url=url, filename=filename)
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            content = response.content
            if not content.startswith(b'%PDF'):
                raise ValueError('Not PDF content')
            pages = [p.extract_text() for p in PdfReader(io.BytesIO(content)).pages]
            (DEST / filename).write_bytes(content)
            (DEST / (filename + '.txt')).write_text('\n'.join(f'PAGE {n+1}\n{t}' for n,t in enumerate(pages)), encoding='utf-8')
            result.update(status='downloaded', sha256=hashlib.sha256(content).hexdigest())
            excerpts = []
            for n, page in enumerate(pages):
                lines = page.splitlines()
                for i, line in enumerate(lines):
                    if '登记日' in line or '除权基准' in line or '更正为' in line:
                        excerpts.append(f'p{n+1}: ' + ' '.join(lines[max(0,i-1):i+3]))
            result['date_excerpts'] = excerpts
        except Exception as error:
            result.update(status='failed', error=str(error))
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(download, announcements))
    (DEST / 'manifest.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in results:
        print(row['code'], row['url'], row['status'])
        for excerpt in row.get('date_excerpts', []):
            print(excerpt)


if __name__ == '__main__':
    main()
