"""Trace the existing 2019/2020 annual inputs and cached response boundaries.

Only local, frozen inputs are read. No API client, strategy or account runner
is invoked, and no source observation or eligibility rule is repaired.
"""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = Path('D:/QuantResearchEvidence/alphaforge_000998_crosscheck_20261016_r1/local_provenance')
CODE = '000998.SZ'
LO, HI = '20191101', '20200103'
BOUNDARY_DATES = {'20191230', '20191231', '20200102', '20200103'}


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def select_annual(name, api):
    pieces = []
    for chunk in pd.read_csv(ROOT / 'data' / name / (api + '.csv'),
                             dtype=str, keep_default_na=False, chunksize=150000):
        selected = chunk.loc[chunk.ts_code.eq(CODE) & chunk.trade_date.between(LO, HI)].copy()
        if len(selected):
            pieces.append(selected)
    if not pieces:
        raise RuntimeError('Missing expected annual observations: ' + name + '/' + api)
    frame = pd.concat(pieces, ignore_index=True).sort_values('trade_date').reset_index(drop=True)
    assert not frame.duplicated(['ts_code', 'trade_date']).any()
    return frame


def relevant_cache_files():
    """Inspect public request headers only; no credentials or unrelated payloads."""
    matches, scanned = [], 0
    roots = [ROOT / 'data/raw/adj_factor',
             ROOT / 'output/continuous_event_audit_20261005/fresh_factor_probe/adj_factor']
    for directory in roots:
        if not directory.exists():
            continue
        for path in sorted(directory.glob('*.json')):
            scanned += 1
            with path.open('r', encoding='utf-8') as stream:
                head = stream.read(2048)
            found = re.search(r'"params"\s*:\s*(\{[^}]*\})', head)
            if found is None:
                continue
            params = json.loads(found.group(1))
            requested_code = str(params.get('ts_code', ''))
            requested_date = str(params.get('trade_date', ''))
            if CODE in requested_code or requested_date in BOUNDARY_DATES:
                matches.append(path)
    return matches, scanned


def main():
    if OUT.exists():
        raise RuntimeError('Existing local-provenance evidence; refuse overwrite')
    names = ('development_2019', 'development_2020')
    annual_manifests = {name: read_json(ROOT / 'data' / name / 'manifest.json') for name in names}
    continuous = read_json(ROOT / 'data/continuous_2016_2025/manifest.json')
    revision = read_json(ROOT / 'data/continuous_2016_2025_dividend_r1/manifest.json')
    inputs = [Path(__file__), ROOT / 'scripts/build_continuous_dataset.py',
              ROOT / 'quant_research/download.py', ROOT / 'quant_research/data.py',
              ROOT / 'data/continuous_2016_2025/manifest.json',
              ROOT / 'data/continuous_2016_2025/overlap_checks.json',
              ROOT / 'data/continuous_2016_2025_dividend_r1/manifest.json',
              ROOT / 'output/alphaforge_case_2018_2020_r2/failure_evidence/raw_quote_adj.csv']
    inputs += [ROOT / 'data' / name / filename for name in names
               for filename in ('manifest.json', 'daily.csv', 'adj_factor.csv')]
    caches, scanned = relevant_cache_files()
    inputs += caches
    fingerprints = {str(path): sha(path) for path in inputs}
    for name in names:
        for api in ('daily', 'adj_factor'):
            path = ROOT / 'data' / name / (api + '.csv')
            expected = annual_manifests[name]['files_sha256'][api + '.csv']
            assert fingerprints[str(path)] == expected
            relative = str(path.relative_to(ROOT))
            assert continuous['input_sha256'][relative] == expected
            assert revision['input_sha256'][relative] == expected
    annual = {(name, api): select_annual(name, api) for name in names for api in ('daily', 'adj_factor')}
    factor = annual[(names[0], 'adj_factor')].merge(annual[(names[1], 'adj_factor')],
              on=['ts_code', 'trade_date'], validate='one_to_one', suffixes=('_2019', '_2020'))
    assert set(factor.trade_date) == set(annual[(names[0], 'adj_factor')].trade_date)
    factor['ratio_2020_to_2019_exact_decimal'] = [str(Decimal(b) / Decimal(a))
              for a, b in zip(factor.adj_factor_2019, factor.adj_factor_2020)]
    factor['strings_identical'] = factor.adj_factor_2019.eq(factor.adj_factor_2020)
    daily = annual[(names[0], 'daily')].merge(annual[(names[1], 'daily')],
              on=['ts_code', 'trade_date'], validate='one_to_one', suffixes=('_2019', '_2020'))
    value_fields = [name for name in annual[(names[0], 'daily')].columns if name not in ('ts_code', 'trade_date')]
    daily_mismatches = {field: int(daily[field + '_2019'].ne(daily[field + '_2020']).sum())
                        for field in value_fields}
    daily['all_source_strings_identical'] = pd.DataFrame({field: daily[field + '_2019'].eq(daily[field + '_2020'])
                                                        for field in value_fields}).all(axis=1)
    overlap_checks = read_json(ROOT / 'data/continuous_2016_2025/overlap_checks.json')
    saved_overlap = [row for row in overlap_checks if row['left'] == names[0] and row['right'] == names[1]
                     and row['api'] in ('daily', 'adj_factor')]
    assert len(saved_overlap) == 2 and all(row['conflict'] is None for row in saved_overlap)
    boundary = annual[(names[1], 'daily')].merge(annual[(names[1], 'adj_factor')],
                 on=['ts_code', 'trade_date'], validate='one_to_one')
    boundary = boundary.loc[boundary.trade_date.isin(BOUNDARY_DATES)].copy()
    assert set(boundary.trade_date) == BOUNDARY_DATES
    derived = pd.read_csv(inputs[7], dtype=str, keep_default_na=False)
    pd.testing.assert_frame_equal(boundary.sort_values('trade_date').reset_index(drop=True)[derived.columns],
                                  derived.sort_values('trade_date').reset_index(drop=True), check_dtype=False)
    cache_records = []
    for path in caches:
        envelope = read_json(path)
        payload = envelope['data']
        checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        assert checksum == envelope['sha256']
        exact = json.loads(path.read_text(encoding='utf-8'), parse_float=Decimal)
        public = {name: envelope[name] for name in ('api_name', 'params', 'fields')}
        key = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
        assert key == path.stem
        rows = [dict(zip(payload['fields'], row)) for row in exact['data']['items']]
        selected = [row for row in rows if row['ts_code'] == CODE and LO <= row['trade_date'] <= HI]
        serializable = [{name: str(value) if isinstance(value, Decimal) else value for name, value in row.items()}
                        for row in selected]
        cache_records.append(dict(source_path=str(path), file_sha256=fingerprints[str(path)],
              public_request=public, request_key_matches_filename=True, payload_checksum_verified=True,
              payload_sha256=checksum, retrieved_at=envelope['retrieved_at'], total_rows=len(rows),
              selected_rows=serializable, representation='Exact numeric text as preserved in the serialized local cache; not an original HTTP-byte archive'))
    date_caches = [row for row in cache_records if row['public_request']['params'].get('trade_date') in BOUNDARY_DATES
                   and 'data/raw/adj_factor' in row['source_path'].replace('\\', '/')]
    assert {row['public_request']['params']['trade_date'] for row in date_caches} == BOUNDARY_DATES
    annual_lookup = boundary.set_index('trade_date').adj_factor.to_dict()
    for record in date_caches:
        assert len(record['selected_rows']) == 1
        row = record['selected_rows'][0]
        assert Decimal(str(row['adj_factor'])) == Decimal(annual_lookup[row['trade_date']])
    result = dict(recorded_at=datetime.now(timezone.utc).isoformat(), code=CODE,
        scope='Local source provenance only; no market request, simulation, correction or historical eligibility change',
        overlap=dict(start=max(annual_manifests[name]['start'] for name in names),
                     end=min(annual_manifests[name]['end'] for name in names), factor_rows=len(factor),
                     factor_string_mismatches=int((~factor.strings_identical).sum()),
                     exact_factor_ratios=sorted(set(factor.ratio_2020_to_2019_exact_decimal)),
                     ratio_is_constant=factor.ratio_2020_to_2019_exact_decimal.nunique() == 1,
                     daily_rows=len(daily), daily_field_mismatches=daily_mismatches,
                     all_daily_source_strings_identical=bool(daily.all_source_strings_identical.all()),
                     saved_marketwide_overlap_checks=saved_overlap,
                     marketwide_checks_recomputed=False),
        boundary_within_single_annual_file=dict(dataset='development_2020', rows=boundary.to_dict('records'),
             observation='The single 2020 annual source itself contains 20191231 factor 11.267 followed by 20200102 factor 10.97; this transition does not require stitching two annual files.'),
        cache_inventory=dict(public_headers_scanned=scanned, selected_cache_files=len(caches),
                             boundary_full_market_date_cache_rows_verified=len(date_caches)),
        cache_records=cache_records,
        stitching=dict(source=str(ROOT / 'scripts/build_continuous_dataset.py'),
             policy='Read annual CSV values as strings, reject inconsistent overlaps, select 2019 calendar-year rows from development_2019 and 2020 calendar-year rows from development_2020; no rescaling or rounding of factor columns.',
             boundary_selection=[dict(trade_date='20191231', source_dataset='development_2019', factor='11.267'),
                                 dict(trade_date='20200102', source_dataset='development_2020', factor='10.97')],
             original_and_dividend_revision_price_hashes_identical={api: continuous['files_sha256'][api + '.csv'] == revision['files_sha256'][api + '.csv'] for api in ('daily', 'adj_factor')},
             annual_inputs_authenticate_to_both_manifests=True,
             existing_failure_quote_extract_matches_2020_annual_source=True),
        supported=['The selected same-date annual overlap does not show a different constant factor base: all compared strings match and each exact ratio is one.',
                   'The boundary move exists within the 2020 annual source and the matching pre-existing full-market-date cached payloads. Annual-to-continuous stitching is not required to produce it.',
                   'Raw daily OHLC/pre_close strings in the compared annual overlap also match.'],
        still_unknown=['The supplier internal origin, economic cause, historical revisions and correct treatment of the factor boundary are not established by these local comparisons.',
                       'Equality on the selected overlap does not prove every provider vintage, parameterization or date range is equivalent.',
                       'A 2026 cache retrieval does not certify what was available in 2019 or 2020; equality of pre_close and prior close does not prove absence of a corporate event.'],
        future_information_policy='Later observations and apparent recoveries are diagnostic only; none are used to backfill earlier formation eligibility.',
        network_requests=0, simulations_started=0, old_sources_modified=False)
    for path, expected in fingerprints.items():
        assert sha(Path(path)) == expected, 'Consumed source changed during provenance diagnosis'
    OUT.mkdir()
    for (name, api), frame in annual.items():
        frame.to_csv(OUT / f'{name}_{api}_selected.csv', index=False)
    factor.to_csv(OUT / 'overlap_adj_factor_comparison.csv', index=False)
    daily.to_csv(OUT / 'overlap_daily_comparison.csv', index=False)
    boundary.to_csv(OUT / 'boundary_inside_development_2020.csv', index=False)
    cache_dir = OUT / 'cached_response_copies'
    cache_dir.mkdir()
    for index, path in enumerate(caches):
        destination = cache_dir / f'{index:02d}_{path.name}'
        shutil.copy2(path, destination)
        assert sha(destination) == fingerprints[str(path)]
    write_json(OUT / 'provenance.json', result)
    write_json(OUT / 'inputs_sha256.json', fingerprints)
    text = ('# 000998跨年系数断点：本地来源追溯\n\n'
            f"2019与2020年度源在{result['overlap']['start']}至{result['overlap']['end']}的000998重叠期，"
            f"复权系数核对{len(factor)}个同日观测，字符串差异{result['overlap']['factor_string_mismatches']}条，"
            f"2020源／2019源的Decimal比值集合为{result['overlap']['exact_factor_ratios']}。"
            f"日线核对{len(daily)}个同日观测，全部原字段字符串一致为{result['overlap']['all_daily_source_strings_identical']}。\n\n"
            '更直接地，development_2020单个年度文件本身已含2019-12-31系数11.267及2020-01-02系数10.97。'
            '因此不能把这次断点归因于连续构建阶段切换两个年度基准；所核对重叠期也没有显示不同的常数归一化基准。\n\n'
            '连续构建以字符串读取年度表，校验重叠一致后取各年度正式自然年记录，不对因子重新缩放或舍入。'
            '四个边界日期的旧全市场API缓存与年度源值一致，原请求参数、抓取时间、payload校验与文件哈希已留存。'
            '缓存副本是客户端序列化的响应载荷，不冒充原始HTTP字节。\n\n'
            '这不证明供应商内部算法、历史修订或经济原因。相同字段不能证明无行动，2026年的下载也不是2019/2020当时版本认证。'
            '未来恢复没有用于回填先前资格。本轮没有市场请求、账户重跑、源文件改写或规则更改。\n')
    (OUT / 'report.md').write_text(text, encoding='utf-8')
    manifest = {str(path.relative_to(OUT)): sha(path) for path in sorted(OUT.rglob('*')) if path.is_file()}
    write_json(OUT / 'output_sha256.json', manifest)
    print(json.dumps(dict(out=str(OUT), overlap=result['overlap'],
                          cache_inventory=result['cache_inventory'], inputs=len(fingerprints),
                          artifacts=len(manifest)), ensure_ascii=False))


if __name__ == '__main__':
    main()
