"""Retrieve public CNInfo metadata for a fixed, pre-existing event inventory."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    ('000065', '北方国际', '2022-04-14'),
    ('600081', '东风科技', '2023-08-10'),
    ('600459', '贵研铂业', '2022-12-22'),
    ('600888', '新疆众和', '2021-04-21'),
    ('600909', '华安证券', '2021-06-10'),
    ('600958', '东方证券', '2022-04-29'),
    ('601015', '陕西黑猫', '2021-07-08'),
    ('601016', '节能风电', '2022-11-28'),
    ('601108', '财通证券', '2022-04-12'),
    ('601236', '红塔证券', '2021-08-04'),
    ('601555', '东吴证券', '2021-12-23'),
]


def main():
    def query(item):
        code, name, date = item
        payload = dict(pageNum=1, pageSize=30, tabName='fulltext',
                       column='szse' if code.startswith('0') else 'sse',
                       searchkey=f'{name} 配股发行结果',
                       seDate=f'{date}~{date}', isHLtitle='false')
        for keyword in (f'{name} 配股发行结果', '配股发行结果'):
            payload['searchkey'] = keyword
            response = requests.post('https://www.cninfo.com.cn/new/hisAnnouncement/query',
                data=payload, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cninfo.com.cn/'}, timeout=25)
            response.raise_for_status()
            data = response.json()
            matches = [a for a in (data.get('announcements') or [])
                       if a['secCode'] == code and '配股发行结果' in a['announcementTitle']]
            if len(matches) == 1:
                break
        assert len(matches) == 1, (item, matches)
        announcement = matches[0]
        result = dict(code=code, date=date, name=name,
                      query_endpoint=response.url, query=payload, announcement=announcement,
                      source='https://static.cninfo.com.cn/' + announcement['adjunctUrl'])
        print(code, result['source'], flush=True)
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(query, QUERIES))
    out = ROOT / 'data/evidence/validation_events_20261004/remaining_queries.json'
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
