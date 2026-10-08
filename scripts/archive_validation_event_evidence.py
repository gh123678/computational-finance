"""Archive identified primary PDFs; extraction is evidence, not an event approval."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import requests
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    '002142_20211202': 'https://static.cninfo.com.cn/finalpage/2021-12-02/1211763892.PDF',
    '000970_20220224': 'https://static.cninfo.com.cn/finalpage/2022-02-24/1212443412.PDF',
    '000049_20231208': 'https://static.cninfo.com.cn/finalpage/2023-12-08/1218545401.PDF',
    '601377_20220825': 'https://static.cninfo.com.cn/finalpage/2022-08-25/1214390207.PDF',
    '002948_20220113': 'https://www.qdccb.com/images/ag_gsgg/2022/01/26/44A37D760B7C3D35965A654E4B2EADC7.pdf',
    '601916_20230627': 'https://www.czbank.com/cn/investor/announcements_3867/202306/P020230626637994950210.pdf',
    '600030_20220127': 'https://www.citics.com/newsite/tzzgx/ggyth/gg/aggg/202201/P020220328648174712581.pdf',
    '601015_20210713_listing': 'https://static.cninfo.com.cn/finalpage/2021-07-13/1210467348.PDF',
    '600081_20230819_listing': 'https://static.cninfo.com.cn/finalpage/2023-08-19/1217575253.PDF',
    '601016_20221128_bond_adjustment': 'https://static.cninfo.com.cn/finalpage/2022-11-28/1215213852.PDF',
    '600888_20210813_funding': 'https://static.cninfo.com.cn/finalpage/2021-08-13/1210734759.PDF',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--remaining', action='store_true')
    args = parser.parse_args()
    folder = ROOT / 'data/evidence/validation_events_20261004'
    folder.mkdir(parents=True, exist_ok=True)
    sources = SOURCES
    if args.remaining:
        queries = json.loads((folder / 'remaining_queries.json').read_text(encoding='utf-8'))
        sources = {f"{q['code']}_{q['date'].replace('-', '')}_result": q['source'] for q in queries}
    def archive(item):
        name, url = item
        path = folder / (name + '.pdf')
        result = dict(name=name, source=url, local_path=str(path.relative_to(ROOT)))
        try:
            if not path.exists():
                response = requests.get(url, timeout=25)
                response.raise_for_status()
                if not response.content.startswith(b'%PDF'):
                    raise ValueError('Response is not PDF')
                path.write_bytes(response.content)
            reader = PdfReader(path)
            text = '\n'.join(f'--- Page {i+1} ---\n{page.extract_text()}' for i, page in enumerate(reader.pages))
            path.with_suffix('.txt').write_text(text, encoding='utf-8')
            result.update(status='archived', sha256=hashlib.sha256(path.read_bytes()).hexdigest(), pages=len(reader.pages))
        except Exception as error:
            result.update(status='failed', reason=str(error))
        print(name, result['status'], flush=True)
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(archive, sources.items()))
    manifest_name = 'manifest_remaining.json' if args.remaining else 'manifest.json'
    (folder / manifest_name).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
