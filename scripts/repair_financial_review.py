"""Offline revision of slice statistics and cached version-query coverage.

No network, trading or frozen-output writes. Slice-only, never history approval.
"""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_off_checklist_key as verifier

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/financial_review_repair_20261011_r1'
OLD = ROOT / 'output/off_checklist_revision_worklist_20261010/verification_round'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_slice_observations(frame):
    """Each stock-date has one most recent disclosed period within this slice.

    Different periods are *not* independent stocks. No complete-history claim.
    """
    frame = frame.copy()
    keys = ['ts_code', 'trade_date', 'end_date', 'ann_date']
    for col in keys[1:]:
        frame[col] = frame[col].astype(str).str.replace('-', '', regex=False)
        if not frame[col].str.fullmatch(r'\d{8}').all():
            raise ValueError('invalid date: ' + col)
    if (frame.trade_date <= frame.ann_date).any():
        raise ValueError('undisclosed slice row')
    conflict = frame.groupby(keys).consumption_value.nunique(dropna=False)
    if (conflict > 1).any():
        raise ValueError('conflicting value for same disclosure')
    return (frame.sort_values(keys).drop_duplicates(['ts_code', 'trade_date'], keep='last')
            .sort_values(['trade_date', 'ts_code']).reset_index(drop=True))


def cached_query(record, responses):
    """Read caches only; missing/invalid/truncated data cannot become clear."""
    items, pages, expected = [], 0, None
    for page in range(1, 6):
        path = responses / f"{record['ts_code']}_{record['ann_date']}_post_{page}.json"
        failure = None
        if not path.exists():
            failure = 'missing_cached_page'
        else:
            try:
                obj = json.loads(path.read_text(encoding='utf-8'))
                failure = verifier.validate_post_response(obj)
            except (ValueError, UnicodeError):
                failure = 'invalid_cached_json'
        if failure:
            return dict(items=items, complete=False, failure=failure, pages=pages, total=expected)
        if expected is not None and obj['totalAnnouncement'] != expected:
            return dict(items=items, complete=False, failure='total_changed_during_pagination',
                        pages=pages, total=expected)
        expected = obj['totalAnnouncement']
        pages += 1
        items.extend(obj['announcements'] or [])
        if not obj['hasMore']:
            complete = len(items) == expected
            return dict(items=items, complete=complete,
                        failure=None if complete else 'total_count_mismatch', pages=pages, total=expected)
    return dict(items=items, complete=False, failure='pagination_limit_reached', pages=pages, total=expected)


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    frozen_paths = [ROOT / 'output/profit_dedt_slice_alignment_20261010/merged_panel.csv',
                    ROOT / 'output/profit_dedt_slice_ic_20261010/report.md',
                    ROOT / 'output/profit_dedt_slice_ic_20261010/per_section_ic.csv',
                    OLD / 'adjudication_progress.csv'] + list((OLD / 'results').glob('*.json'))
    before = {str(p.relative_to(ROOT)): sha(p) for p in frozen_paths}
    original = pd.read_csv(frozen_paths[0], dtype={'trade_date': str, 'end_date': str, 'ann_date': str})
    unique = latest_slice_observations(original)
    assert not unique.duplicated(['ts_code', 'trade_date']).any()
    unique.to_csv(OUT / 'unique_stock_date_slice.csv', index=False)
    panel = pd.read_csv(ROOT / 'output/open_source_ml_risk_2018_2020_r1/common_samples.csv',
                        dtype={'trade_date': str}, low_memory=False)
    panel['trade_date'] = panel.trade_date.str.replace('-', '', regex=False)
    labels = panel[['ts_code', 'trade_date', 'label', 'label_valid']]
    if labels.duplicated(['ts_code', 'trade_date']).any():
        raise ValueError('duplicate label stock-date')
    joined = unique.merge(labels, on=['ts_code', 'trade_date'], how='left', validate='one_to_one')
    valid = joined[joined.label_valid.astype(str).eq('True')].dropna(subset=['label', 'consumption_value'])
    per_section = []
    for day, part in valid.groupby('trade_date'):
        if len(part) >= 3 and part.consumption_value.nunique() > 1 and part.label.nunique() > 1:
            per_section.append(dict(trade_date=day, n_stocks=len(part),
                                    ic=float(spearmanr(part.consumption_value, part.label).statistic)))
    ic = pd.DataFrame(per_section)
    ic.to_csv(OUT / 'per_section_ic.csv', index=False)
    rows, remaining = [], []
    for p in sorted((OLD / 'results').glob('*.json')):
        rec = json.loads(p.read_text(encoding='utf-8'))
        query = cached_query(rec, OLD / 'responses')
        vc = verifier.assess_version_query(query)
        result = dict(ts_code=rec['ts_code'], end_date=rec['end_date'], ann_date=rec['ann_date'],
                      old_status=rec.get('final_status'), text_verdict=rec.get('verdict'), **vc,
                      usable_in_verified_history=False)
        rows.append(result)
        if rec.get('final_status') != 'verified_flag0_clear':
            remaining.append(dict(**result, documents=rec.get('documents'),
                                  flag0_hits=rec.get('flag0_hits'),
                                  decision='unresolved_requires_field_period_unit_and_version_review'))
    assert len(rows) == 166 and len(remaining) == 23
    (OUT / 'version_cache_review.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'remaining_23_review.json').write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding='utf-8')
    counts = dict(Counter(r['status'] for r in rows))
    after = {str(p.relative_to(ROOT)): sha(p) for p in frozen_paths}
    assert before == after
    result = dict(original_rows=len(original), unique_stock_dates=len(unique),
                  removed_duplicate_rows=len(original) - len(unique),
                  ic_sections=len(ic), revised_mean_ic=float(ic.ic.mean()),
                  revised_median_ic=float(ic.ic.median()), version_cache_status_counts=counts,
                  remaining_23_unresolved=len(remaining), frozen_files_checked=len(before),
                  frozen_unchanged=before == after, usable_in_verified_history=False,
                  limitations=['32-key selected slice, not complete latest financial history',
                               '60-day present index is not a complete version chain',
                               'no OCR/manual adjudication claimed',
                               'no size/industry neutralization or profitability claim'])
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'input_sha256.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    report = f'''# 财务核验修复报告（2026-10-11）

旧2,410行切片有230行重复股票/日期。修订选择已披露切片中最新报告期、再最新公告，剩2,180个唯一股票/日期。标签一对一匹配并验证无同日或未来公告。

修订截面IC：{len(ic)}个截面，均值{result['revised_mean_ic']:.6f}，中位{result['revised_median_ic']:.6f}。旧均值0.0864属于重复股票口径，不作为新结论。修订仍只是被选择的32键局部切片：没有完整后续报告覆盖，不能当作完整时点财务面板，也不能证明收益。旧利润值的长期延续不代表已验证持续有效。

166键缓存重审：{json.dumps(counts, ensure_ascii=False)}。查询错误、缺页、数量不一致、上限截断全部视为未完成；更正说明不再被标题排除。即使60日索引未发现更正，完整历史版本链依然未核验。

剩余23键已逐键汇集原命中上下文与新版更正清单，见remaining_23_review.json。仍需核定报告期/字段/单位/原版与更正版数值；本轮未伪造人工裁定或OCR完成。原143键亦不升级为历史可用。时点批准仍为0。

旧{len(before)}个输入/输出文件核验前后SHA256一致。本轮没有训练、回测、调参或券商接入。
'''
    (OUT / 'report.md').write_text(report, encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
