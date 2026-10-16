"""Frozen day-level event records for the retrospective AlphaForge r2 filter.

``timing_verified`` only certifies a valid cached implementation-announcement
day no later than the effective day. It does not certify an immutable original
version or the intraday time when an announcement became public. Proposal
``ann_date`` and dates embedded in a source URL are never timing substitutes.
"""
from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
import math
import re

import pandas as pd

from quant_research.corporate_corrections import correct_actions
from quant_research.rights import verified_rights


COLUMNS = ['code', 'event_date', 'known_date', 'timing_verified', 'event_id',
           'kind', 'source', 'known_date_field', 'timing_reason']
AMOUNT_FIELDS = ('cash_div', 'cash_div_tax', 'stk_div', 'stk_bo_rate', 'stk_co_rate')


def _day(value):
    if value is None or pd.isna(value):
        return pd.NaT
    if isinstance(value, (datetime, date, pd.Timestamp)):
        result = pd.Timestamp(value)
        if result.tzinfo is not None or result != result.normalize():
            return pd.NaT
        return result
    text = str(value)
    if re.fullmatch(r'\d{8}', text):
        return pd.to_datetime(text, format='%Y%m%d', errors='coerce')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return pd.to_datetime(text, format='%Y-%m-%d', errors='coerce')
    return pd.NaT


def _code(value):
    if not isinstance(value, str) or re.fullmatch(r'\d{6}\.(?:SH|SZ|BJ)', value) is None:
        raise ValueError('Invalid event security code')
    return value


def _amount(value):
    if value is None or pd.isna(value):
        return 0.
    if isinstance(value, bool):
        raise ValueError('Boolean corporate-action amount')
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError('Non-numeric corporate-action amount') from error
    if not math.isfinite(number) or number < 0:
        raise ValueError('Invalid corporate-action amount')
    return number


def build_events(dividend_frame, rights=None):
    """Return corrected implemented distributions and verified-rights risks.

    Duplicate dividend versions remain separate rows. Event IDs include a
    duplicate occurrence counter instead of selecting a last or earliest
    proposal version. ``rights=None`` uses the existing verified-rights list;
    supply an empty iterable for no rights. Existing rights objects have an
    effective date and a source, but no independently verified public day, so
    they are recorded with unknown timing and never assert past availability.
    """
    if not isinstance(dividend_frame, pd.DataFrame):
        raise TypeError('dividend_frame must be a DataFrame')
    if len(dividend_frame) and not {'ts_code', 'ex_date', 'div_proc'}.issubset(dividend_frame):
        raise ValueError('Missing dividend code, effective date or implementation state')
    frame = dividend_frame.copy(deep=True)
    if frame.empty:
        frame = pd.DataFrame(columns=['ts_code', 'ex_date', 'div_proc', 'imp_ann_date', *AMOUNT_FIELDS])
    corrected, _ = correct_actions(frame)
    rows, counts = [], defaultdict(int)

    def identifier(kind, identity):
        # Proposal-announcement dates are deliberately absent from identity.
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                            default=str).encode('utf-8')).hexdigest()
        key = (kind, digest)
        counts[key] += 1
        return f'{kind}:{digest}:{counts[key]}'

    for item in corrected.to_dict('records'):
        if item['div_proc'] != '实施':
            continue
        code, event_date = _code(item['ts_code']), _day(item['ex_date'])
        if pd.isna(event_date):
            raise ValueError('Invalid implemented-distribution effective date')
        amounts = {name: _amount(item.get(name)) for name in AMOUNT_FIELDS}
        cash = amounts['cash_div'] > 0 or amounts['cash_div_tax'] > 0
        stock = any(amounts[name] > 0 for name in ('stk_div', 'stk_bo_rate', 'stk_co_rate'))
        if not cash and not stock:
            continue
        raw_known = item.get('imp_ann_date')
        known_date = _day(raw_known)
        if raw_known is None or pd.isna(raw_known):
            timing, reason = False, 'missing_imp_ann_date'
        elif pd.isna(known_date):
            timing, reason = False, 'invalid_imp_ann_date'
        elif known_date > event_date:
            timing, reason = False, 'imp_ann_date_after_event_date'
        else:
            timing, reason = True, 'valid_cached_implementation_day_not_after_event'
        kind = 'cash_and_stock' if cash and stock else 'cash' if cash else 'stock'
        identity = dict(code=code, event_date=event_date.strftime('%Y-%m-%d'),
                        implementation_day=str(raw_known), **amounts)
        rows.append(dict(code=code, event_date=event_date, known_date=known_date,
                         timing_verified=timing, event_id=identifier('dividend', identity), kind=kind,
                         source='dividend_frame_after_existing_correct_actions',
                         known_date_field='imp_ann_date', timing_reason=reason))

    for item in verified_rights() if rights is None else rights:
        code, event_date = _code(item.code), _day(item.ex)
        record_date = _day(item.record)
        if pd.isna(event_date) or pd.isna(record_date) or record_date >= event_date:
            raise ValueError('Invalid verified-rights record/effective date')
        if not isinstance(item.source, str) or not item.source.strip():
            raise ValueError('Verified rights require an explicit source')
        identity = dict(code=code, event_date=event_date.strftime('%Y-%m-%d'),
                        record_date=record_date.strftime('%Y-%m-%d'), source=item.source)
        rows.append(dict(code=code, event_date=event_date, known_date=pd.NaT,
                         timing_verified=False, event_id=identifier('rights', identity), kind='rights',
                         source=item.source, known_date_field='none_verified',
                         timing_reason='public_announcement_day_not_verified'))
    result = pd.DataFrame(rows, columns=COLUMNS)
    for name in ('event_date', 'known_date'):
        result[name] = pd.to_datetime(result[name]).astype('datetime64[ns]')
    result['timing_verified'] = result.timing_verified.astype(bool)
    assert not result.event_id.duplicated().any()
    return result.reset_index(drop=True)
