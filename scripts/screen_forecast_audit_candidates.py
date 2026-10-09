"""Semi-automated screening of forecast and fina_audit rows against candidate texts.

forecast: net_profit_min/max (万元 converted to CNY), p_change_min/max (%),
last_parent_net (万元). Ranges like 盈利：10万元–150万元 are current-period
forecasts; 亏损 ranges reverse sign and order; prior-year single values must
sit near 上年同期/去年同期.

fina_audit: audit_result opinion classification, audit_sign name presence,
audit_fees amounts. Opinion precedence: 无法表示 > 否定 > 保留(excluding
无保留) > 无保留 (我们认为…公允反映), with 强调事项段 marking the emphatic
variant.

Same discipline as screen_profit_dedt_candidates.py: field-level evidence
only; usable_in_verified_history is never set.
"""
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / 'output' / 'announcement_financial_audit_20261007'
OUT = AUDIT / 'auto_screen_20261009'
ROUNDS = [AUDIT / 'remaining_evidence_r1', AUDIT / 'remaining_evidence_r2_fixed_r1']

NUM = r'([\d,]+(?:\.\d+)?)'
DASH = r'\s*[_\s]*[-–—~～至]+\s*[_\s]*'
UNIT_SUFFIX = r'[_\s]*(亿元|万元|元)'
UNIT_MULT = {'元': 1.0, '万元': 1e4, '亿元': 1e8}

PROFIT_RANGE = re.compile(
    r'(盈利|亏损)[：:]?_?约?_?' + NUM + r'_?' + UNIT_SUFFIX + DASH + NUM + r'_?' + UNIT_SUFFIX)
PROFIT_SINGLE = re.compile(r'(盈利|亏损)[：:]?_?约?_?' + NUM + r'_?' + UNIT_SUFFIX)
PCHANGE_RANGE = re.compile(
    r'比上年同期(增长|下降|增加|减少|上升)?[^：:]{0,12}[：:]?\s*_?'
    + r'(-?[\d,]+(?:\.\d+)?)' + r'\s*_?\s*%?\s*'
    + DASH + r'_?(-?[\d,]+(?:\.\d+)?)_?\s*%')
PCHANGE_DIR = 1  # group index of the direction word
PCHANGE_SINGLE = re.compile(r'比上年同期[^：:]{0,12}[：:]?\s*_?(-?[\d,]+(?:\.\d+)?)_?\s*%')
PRIOR_CONTEXT = re.compile(r'上年同期|去年同期|上年同期末')
PERIOD_TEXT = re.compile(r'业绩预告期间[：:]?(\d{4})年\d{1,2}月\d{1,2}日?[–—~～至]+(\d{1,2})月(\d{1,2})日')
PERIOD_TITLE = [
    (re.compile(r'(\d{4})年年度?.*?预告'), '1231'),
    (re.compile(r'(\d{4})年第一季度.*?预告'), '0331'),
    (re.compile(r'(\d{4})年半年度.*?预告'), '0630'),
    (re.compile(r'(\d{4})年前三季度.*?预告'), '0930'),
]
AUDIT_TITLE = re.compile(r'(\d{4})年(?:年度)?审计报告')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def to_cny(value_text, unit):
    return float(value_text.replace(',', '')) * UNIT_MULT[unit]


def signed_range(kind, lo_text, hi_text, unit_lo, unit_hi):
    lo = to_cny(lo_text, unit_lo)
    hi = to_cny(hi_text, unit_hi)
    if kind == '亏损':
        return -max(lo, hi), -min(lo, hi)
    return min(lo, hi), max(lo, hi)


def forecast_period(flat, title):
    m = PERIOD_TEXT.search(flat)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}", 'text'
    for pattern, suffix in PERIOD_TITLE:
        m = pattern.search(title or '')
        if m:
            return f"{m.group(1)}{suffix}", 'title'
    return None, 'period_unidentified'


LABEL_BEFORE = re.compile(r'(净利润|每股收益|利润总额|营业收入)')

def label_is_profit(flat, start):
    """The last metric label before the match must be 净利润 (not EPS etc.)."""
    hits = list(LABEL_BEFORE.finditer(flat[max(0, start - 40):start]))
    return bool(hits) and hits[-1].group(1) == '净利润'


def is_eps(flat, match_end):
    return flat[match_end:match_end + 3].startswith('元/股')


def screen_forecast(flat, api_row):
    """Return list of field-check dicts for one candidate document."""
    checks = []
    # Current-period profit: first label-clean range; scrambled table headers can
    # place 上年同期 near the label, so ranges are not excluded by prior-context.
    lo = hi = None
    for m in PROFIT_RANGE.finditer(flat):
        if is_eps(flat, m.end()) or not label_is_profit(flat, m.start()):
            continue
        lo, hi = signed_range(m.group(1), m.group(2), m.group(4), m.group(3), m.group(5))
        break
    if lo is None:
        for m in PROFIT_SINGLE.finditer(flat):
            before = flat[max(0, m.start() - 60):m.start()]
            if (PRIOR_CONTEXT.search(before) or is_eps(flat, m.end())
                    or not label_is_profit(flat, m.start())):
                continue
            v = to_cny(m.group(2), m.group(3))
            lo = hi = (-v if m.group(1) == '亏损' else v)
            break
    for field, api_col in (('net_profit_min', 'net_profit_min_cny'),
                           ('net_profit_max', 'net_profit_max_cny')):
        api_val = api_row.get(api_col)
        api_val = float(api_val) if api_val == api_val and api_val is not None else None
        found = lo if field == 'net_profit_min' else hi
        if found is None:
            status = 'not_found_in_candidate_text'
        elif api_val is None:
            status = 'api_value_missing'
        elif abs(found - api_val) <= 5000.0:
            status = 'value_matches_dated_original'
        else:
            status = 'value_differs_from_dated_original'
        checks.append(dict(field=field, unit='CNY', api_value=api_val,
                           original_value=found, status=status))
    # Percentage change range.
    p_lo = p_hi = None
    m = PCHANGE_RANGE.search(flat)
    if m:
        direction = m.group(1)
        p_lo = float(m.group(2).replace(',', ''))
        p_hi = float(m.group(3).replace(',', ''))
        if direction in ('下降', '减少') and p_lo > 0 and p_hi > 0:
            p_lo, p_hi = -max(p_lo, p_hi), -min(p_lo, p_hi)
        else:
            p_lo, p_hi = min(p_lo, p_hi), max(p_lo, p_hi)
    else:
        m = PCHANGE_SINGLE.search(flat)
        if m:
            p_lo = p_hi = float(m.group(1).replace(',', ''))
            head = flat[m.start():m.start() + 20]
            if ('下降' in head or '减少' in head) and '增长' not in head and p_lo > 0:
                p_lo = p_hi = -p_lo
    for field, api_col in (('p_change_min', 'p_change_min'), ('p_change_max', 'p_change_max')):
        api_val = api_row.get(api_col)
        api_val = float(api_val) if api_val == api_val and api_val is not None else None
        found = p_lo if field == 'p_change_min' else p_hi
        if found is None:
            status = 'not_found_in_candidate_text'
        elif api_val is None:
            status = 'api_value_missing'
        elif abs(found - api_val) < 0.005:
            status = 'value_matches_dated_original'
        else:
            status = 'value_differs_from_dated_original'
        checks.append(dict(field=field, unit='%', api_value=api_val,
                           original_value=found, status=status))
    # Prior-year net profit (last_parent_net).
    api_val = api_row.get('last_parent_net_cny')
    api_val = float(api_val) if api_val == api_val and api_val is not None else None
    found = None
    range_spans = [m.span() for m in PROFIT_RANGE.finditer(flat)]
    for m in PROFIT_SINGLE.finditer(flat):
        if any(a <= m.start() < b for a, b in range_spans):
            continue  # part of a current-period range, not a prior-year value
        before = flat[max(0, m.start() - 60):m.start()]
        if (PRIOR_CONTEXT.search(before) and not is_eps(flat, m.end())
                and label_is_profit(flat, m.start())):
            v = to_cny(m.group(2), m.group(3))
            found = -v if m.group(1) == '亏损' else v
            break
    if found is None:
        m2 = re.search(r'去年同期净利润' + NUM + r'(元|万元|亿元)', flat)
        if m2:
            found = to_cny(m2.group(1), m2.group(2))
    cur_min = api_row.get('net_profit_min_cny')
    cur_max = api_row.get('net_profit_max_cny')
    cur_vals = [float(v) for v in (cur_min, cur_max)
                if v == v and v is not None]
    if found is not None and any(abs(found - v) <= 5000.0 for v in cur_vals):
        # Scrambled header put 上年同期 near the current-period figure.
        status = 'prior_year_column_ambiguous_excluded'
    elif found is None:
        status = 'not_found_in_candidate_text'
    elif api_val is None:
        status = 'api_value_missing'
    elif abs(found - api_val) <= 5000.0:
        status = 'value_matches_dated_original'
    else:
        status = 'value_differs_from_dated_original'
    checks.append(dict(field='last_parent_net', unit='CNY', api_value=api_val,
                       original_value=found, status=status))
    return checks


def classify_opinion(flat):
    m = re.search(r'出具了?((?:带强调事项段的)?(?:标准)?无保留意见|保留意见|无法表示意见|否定意见)', flat)
    if m:
        return m.group(1).replace('带强调事项段的标准', '带强调事项段的')
    if '无法表示意见' in flat:
        return '无法表示意见'
    if '否定意见' in flat:
        return '否定意见'
    for m in re.finditer('保留意见', flat):
        if flat[max(0, m.start() - 1):m.start()] != '无':
            return '保留意见'
    if '我们认为' in flat and '公允反映' in flat:
        if '强调事项' in flat:
            return '带强调事项段的无保留意见'
        return '标准无保留意见'
    return None


def screen_audit(flat, api_row):
    checks = []
    opinion = classify_opinion(flat)
    api_opinion = api_row.get('audit_result')
    if opinion is None:
        status = 'not_found_in_candidate_text'
    elif not api_opinion or api_opinion != api_opinion:
        status = 'api_value_missing'
    elif opinion == api_opinion:
        status = 'value_matches_dated_original'
    else:
        status = 'value_differs_from_dated_original'
    checks.append(dict(field='audit_result', unit='text', api_value=api_opinion,
                       original_value=opinion, status=status))
    api_sign = api_row.get('audit_sign')
    if api_sign and api_sign == api_sign:
        names = [n.strip() for n in str(api_sign).split(',') if n.strip()]
        present = [n for n in names if n in flat]
        extracted = []
        # 扫描件无文本签名时，"注册会计师"后紧跟的是意见段套话而非姓名；
        # 用套话字表过滤，避免把"的责任""们的责任"误当提取到的签名。
        boiler_chars = set('的我们准则执行审计责任判断考虑要求遵守职业道德守则'
                           '财务报表意见工作基础发表按照中国注册会计师对错报风险'
                           '评估内部控制程序保证计划存在重大由于舞弊错误导致括'
                           '设计恰当目获取合理和与及由')
        for m in re.finditer(r'注册会计师[：:]?([一-龥]{2,4})[^一-龥]{0,4}?([一-龥]{2,4})?', flat):
            for g in m.groups():
                if g and not (set(g) & boiler_chars):
                    extracted.append(g)
        if len(present) == len(names):
            status, found = 'value_matches_dated_original', api_sign
        elif present:
            status, found = 'value_matches_needs_manual_confirm', ','.join(present)
        elif extracted:
            status, found = 'value_differs_from_dated_original', ','.join(extracted[:4])
        else:
            status, found = 'signature_not_in_text_layer', None
    else:
        status, found = 'api_value_missing', None
    checks.append(dict(field='audit_sign', unit='text', api_value=api_sign,
                       original_value=found, status=status))
    api_fee = api_row.get('audit_fees')
    api_fee = float(api_fee) if api_fee == api_fee and api_fee is not None else None
    fee = None
    m = re.search(r'(?:审计费用|审计报酬|审计费)[^，。；]{0,20}?' + NUM + UNIT_SUFFIX, flat)
    if m:
        fee = to_cny(m.group(1), m.group(2))
    if fee is None:
        status = 'not_found_in_candidate_text'
    elif api_fee is None:
        status = 'api_value_missing'
    elif abs(fee - api_fee) < 0.5:
        status = 'value_matches_dated_original'
    else:
        status = 'value_differs_from_dated_original'
    checks.append(dict(field='audit_fees', unit='CNY', api_value=api_fee,
                       original_value=fee, status=status))
    return checks


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    forecast_records = pd.read_csv(AUDIT / 'forecast_records.csv', dtype=str)
    audit_records = pd.read_csv(AUDIT / 'fina_audit_records.csv', dtype=str)
    api_rows = {'forecast': {r['row_sha256']: r for _, r in forecast_records.iterrows()},
                'fina_audit': {r['row_sha256']: r for _, r in audit_records.iterrows()}}
    queue = pd.read_csv(ROUNDS[0] / 'remaining_review_rows.csv', dtype=str)
    queued = {api: set(q['row_sha256']) for api, q in
              queue[queue.api.isin(('forecast', 'fina_audit'))].groupby('api')}

    out_rows = []
    for round_dir in ROUNDS:
        results_dir = round_dir / 'results'
        if not results_dir.is_dir():
            continue
        for result_file in sorted(results_dir.glob('*.json')):
            result = json.loads(result_file.read_text(encoding='utf-8'))
            for key in result.get('row_keys', []):
                api = key.get('api')
                if api not in queued or key['row_sha256'] not in queued[api]:
                    continue
                api_row = api_rows[api].get(key['row_sha256'])
                if api_row is None:
                    continue
                for doc in result.get('documents', []):
                    text_rel = doc.get('text_file')
                    if not text_rel:
                        continue
                    text_path = round_dir / text_rel
                    if not text_path.is_file():
                        continue
                    flat = re.sub(r'\s+', '',
                                  text_path.read_text(encoding='utf-8', errors='replace'))
                    title = doc.get('title') or ''
                    if api == 'forecast':
                        if '预告' not in title and '业绩预告' not in flat[:400]:
                            period, period_source = None, 'not_a_forecast_document'
                            out_rows.append(dict(
                                ts_code=result['ts_code'], api=api,
                                ann_date=result['ann_date'], end_date=key.get('end_date'),
                                row_sha256=key['row_sha256'], field='(document)', unit='',
                                api_value=None, original_value=None,
                                status='document_type_mismatch_excluded',
                                pdf_file=Path(doc['file']).name,
                                pdf_sha256=doc.get('sha256'),
                                text_sha256=doc.get('text_sha256'),
                                source_url=doc.get('url'), document_title=title,
                                round=round_dir.name, document_period=None,
                                period_source=period_source, version_note=None,
                                usable_in_verified_history=False))
                            continue
                        period, period_source = forecast_period(flat, title)
                        checks = screen_forecast(flat, api_row)
                    else:
                        m = AUDIT_TITLE.search(title)
                        period = f'{m.group(1)}1231' if m else None
                        period_source = 'title' if m else 'title_period_unidentified'
                        is_opinion_source = ('审计报告' in title or '专项说明' in title)
                        if not is_opinion_source:
                            out_rows.append(dict(
                                ts_code=result['ts_code'], api=api,
                                ann_date=result['ann_date'], end_date=key.get('end_date'),
                                row_sha256=key['row_sha256'], field='(document)', unit='',
                                api_value=None, original_value=None,
                                status='document_type_not_opinion_source',
                                pdf_file=Path(doc['file']).name,
                                pdf_sha256=doc.get('sha256'),
                                text_sha256=doc.get('text_sha256'),
                                source_url=doc.get('url'), document_title=title,
                                round=round_dir.name, document_period=period,
                                period_source=period_source, version_note=None,
                                usable_in_verified_history=False))
                            continue
                        checks = screen_audit(flat, api_row)
                    version_note = None
                    if '已取消' in title:
                        version_note = 'document_title_marked_cancelled'
                    elif any(k in title for k in ('更正', '修订', '更新')):
                        version_note = 'document_title_marked_revised'
                    if period and key.get('end_date') and period != key['end_date']:
                        status_override = 'document_period_mismatch_excluded'
                    else:
                        status_override = None
                    for check in checks:
                        out_rows.append(dict(
                            ts_code=result['ts_code'], api=api,
                            ann_date=result['ann_date'], end_date=key.get('end_date'),
                            row_sha256=key['row_sha256'], field=check['field'],
                            unit=check['unit'], api_value=check['api_value'],
                            original_value=check['original_value'],
                            status=status_override or check['status'],
                            pdf_file=Path(doc['file']).name,
                            pdf_sha256=doc.get('sha256'),
                            text_sha256=doc.get('text_sha256'),
                            source_url=doc.get('url'), document_title=title,
                            round=round_dir.name, document_period=period,
                            period_source=period_source, version_note=version_note,
                            usable_in_verified_history=False))

    frame = pd.DataFrame(out_rows)
    frame.to_csv(OUT / 'forecast_audit_screen.csv', index=False)
    summary = dict(
        document_field_checks=int(len(frame)),
        by_api={api: g.status.value_counts().to_dict()
                for api, g in frame.groupby('api')},
        rows_by_api={api: int(g.row_sha256.nunique())
                     for api, g in frame.groupby('api')},
    )
    (OUT / 'screen_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    protocol = dict(
        script=Path(__file__).name,
        script_sha256=sha256(Path(__file__).resolve()),
        inputs=['remaining_review_rows.csv', 'forecast_records.csv',
                'fina_audit_records.csv', 'remaining_evidence_r1',
                'remaining_evidence_r2_fixed_r1'],
        rules='forecast: 盈利/亏损 ranges are current-period; prior-year singles '
              'require 上年同期/去年同期 context; 亏损 ranges negate and swap. '
              'fina_audit: opinion precedence 无法表示>否定>保留(非无保留)>无保留; '
              'signatures by exact name presence; fees from 审计费用/报酬 amounts.',
        limitation='Scrambled PDF tables can misassign 本报告期/上年同期 columns; '
                   'all matches are field-level evidence requiring manual spot-check; '
                   'usable_in_verified_history is never set.')
    (OUT / 'protocol.json').write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
