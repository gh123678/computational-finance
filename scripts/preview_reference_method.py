"""Read-only feasibility inventory, not an approved pool, label or account run."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
R2 = ROOT / 'output/alphaforge_case_2018_2020_r2'
DATA = ROOT / 'data/continuous_2016_2025_dividend_r1'
OUT = Path('D:/QuantResearchEvidence/alphaforge_000998_revision_decision_20261016_r1/reference_preview_attempt2')
FIELDS = ['open', 'high', 'low', 'close', 'pre_close', 'vol', 'amount']


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    inputs = [Path(__file__), R2/'common_samples.csv', R2/'schedule.csv',
              R2/'events.csv', DATA/'daily.csv', DATA/'calendar.csv']
    before = {str(p): sha(p) for p in inputs}
    (OUT/'input_sha256.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    protocol = dict(scope='read_only_reference_connection_feasibility_not_experiment',
        base='frozen r2 keys and industry only; indirect legacy adjustment-factor selection remains',
        prohibited_reads=['factor scores', 'labels', 'NAV', 'orders', 'holdings'],
        windows='21 OHLCV/amount observations and 20 INTERNAL pre_close bridges; first pre_close unused',
        comparison='exact Decimal original CSV prices; no tolerance or rounding',
        events='cached timing_verified and known_date <= formation; not historical-vintage certification',
        observed_reference_change='pre_close != previous calendar-session close',
        known_match='previous calendar session < event date <= current session and known day <= formation; terms NOT certified',
        inventory_scope='all visible close/pre_close bridges in the scanned warmup-to-last-formation calendar, not only formation windows',
        output='descriptive counts; not new eligibility, adjustment correction, guard release or approval',
        computes_returns_or_labels=False, creates_targets_or_accounts=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    base = pd.read_csv(R2/'common_samples.csv', usecols=['trade_date', 'ts_code', 'industry'], dtype=str)
    schedule = pd.read_csv(R2/'schedule.csv', dtype=str)
    assert len(schedule) == 154 and not base.duplicated(['trade_date', 'ts_code']).any()
    cal = pd.read_csv(DATA/'calendar.csv', dtype=str)
    calendar = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.eq('1'), 'cal_date']))
    start = pd.Timestamp(schedule.signal_date.min()) - pd.Timedelta(days=70)
    end = pd.Timestamp(schedule.signal_date.max())
    calendar = calendar[(calendar >= start) & (calendar <= end)].sort_values()
    assert not calendar.has_duplicates
    codes = set(base.ts_code)
    pieces = []
    for chunk in pd.read_csv(DATA/'daily.csv', dtype=str, keep_default_na=False,
                             usecols=['ts_code', 'trade_date', *FIELDS], chunksize=200000):
        selected = chunk.loc[chunk.ts_code.isin(codes) &
            chunk.trade_date.between(calendar.min().strftime('%Y%m%d'), calendar.max().strftime('%Y%m%d'))]
        if len(selected): pieces.append(selected)
    raw = pd.concat(pieces, ignore_index=True)
    raw['trade_date'] = pd.to_datetime(raw.trade_date)
    assert not raw.duplicated(['ts_code', 'trade_date']).any()
    events = pd.read_csv(R2/'events.csv', dtype=str, keep_default_na=False)
    assert set(events.timing_verified) <= {'True', 'False'}
    known = {}
    for row in events.loc[events.timing_verified.eq('True')].itertuples(index=False):
        ex, publication = pd.Timestamp(row.event_date), pd.Timestamp(row.known_date)
        assert not pd.isna(ex) and not pd.isna(publication) and publication <= ex
        j = calendar.searchsorted(ex)
        if 0 < j < len(calendar) and calendar[j-1] < ex <= calendar[j]:
            key = (row.code, calendar[j])
            known[key] = min(known.get(key, publication), publication)
    positions = {d: i for i, d in enumerate(calendar)}
    dates_by_code = {c: list(pd.to_datetime(g.trade_date)) for c, g in base.groupby('ts_code')}
    records, bridges = [], []
    for code, group in raw.groupby('ts_code', sort=True):
        g = group.set_index('trade_date').reindex(calendar)
        values = g[FIELDS].apply(pd.to_numeric, errors='coerce').to_numpy(float)
        quote_columns = [i for i, f in enumerate(FIELDS) if f != 'pre_close']
        quote_values = values[:, quote_columns]
        valid = np.isfinite(quote_values).all(axis=1) & (quote_values > 0).all(axis=1)
        reference_valid = np.isfinite(values[:, 4]) & (values[:, 4] > 0)
        close_valid = np.isfinite(values[:, 3]) & (values[:, 3] > 0)
        present = calendar.isin(group.trade_date)
        changed = np.zeros(len(calendar), dtype=bool)
        for j in range(1, len(calendar)):
            if close_valid[j-1] and reference_valid[j]:
                changed[j] = Decimal(g.close.iloc[j-1]) != Decimal(g.pre_close.iloc[j])
                if changed[j]:
                    k = known.get((code, calendar[j]))
                    bridges.append(dict(ts_code=code, prior_date=str(calendar[j-1].date()),
                        date=str(calendar[j].date()), prior_close=g.close.iloc[j-1],
                        pre_close=g.pre_close.iloc[j], known_date='' if k is None else str(k.date()),
                        cached_event_known_by_event=k is not None,
                        economic_terms_verified_by_this_audit=False))
        for d in dates_by_code[code]:
            p = positions[d]; a = p - 20
            window_valid = a >= 0 and bool(valid[a:p+1].all()) and bool(reference_valid[a+1:p+1].all())
            internal = list(np.flatnonzero(changed[a+1:p+1]) + a+1) if a >= 0 else []
            unmatched = [j for j in internal if known.get((code, calendar[j]), pd.Timestamp.max) > d]
            status = 'connected_with_cached_events' if internal else 'continuous_reference'
            if not window_valid: status = 'missing_or_invalid_21_quote_window'
            elif unmatched: status = 'unexplained_reference_change'
            records.append(dict(trade_date=str(d.date()), ts_code=code,
                observed_quote_count=int(present[max(0,a):p+1].sum()),
                valid_quote_count=int(valid[max(0,a):p+1].sum()), internal_reference_changes=len(internal),
                unmatched_internal_changes=len(unmatched),
                reference_connection_available=window_valid and not unmatched,
                status=status))
    result = pd.DataFrame(records).sort_values(['trade_date', 'ts_code'])
    assert len(result) == len(base)
    result.to_csv(OUT/'connection_rows.csv', index=False)
    pd.DataFrame(bridges).to_csv(OUT/'observed_reference_changes.csv', index=False)
    counts = result.groupby('trade_date').agg(base_keys=('ts_code', 'size'),
        connected=('reference_connection_available', 'sum')).reset_index()
    assert len(counts) == 154
    counts.to_csv(OUT/'weekly_counts.csv', index=False)
    after = {str(p): sha(p) for p in inputs}
    assert before == after, 'Input mutation'
    summary = dict(created=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        status='diagnostic_completed_no_research_rule_approved', base_keys=len(base),
        assets=len(codes), periods=len(counts), raw_rows=len(raw),
        connection_available=int(result.reference_connection_available.sum()),
        minimum_connected=int(counts.connected.min()), minimum_base=int(counts.base_keys.min()),
        reasons=result.status.value_counts().to_dict(), observed_reference_changes=len(bridges),
        cached_event_matches=sum(b['cached_event_known_by_event'] for b in bridges),
        original_inputs_unchanged=True, economic_action_terms_certified=False,
        daily_reference_historical_vintage_certified=False,
        no_signal_label_selection_or_account_calculated=True)
    (OUT/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    manifest = {str(p.relative_to(OUT)): sha(p) for p in OUT.rglob('*') if p.is_file()}
    (OUT/'output_sha256.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
