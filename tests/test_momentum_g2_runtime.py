from pathlib import Path

import pytest

from momentum_g2_runtime import clean, persist, read_json, read_table, sha, source_closure


def test_scientific_outputs_are_exclusive_and_no_silent_failure_overwrite(tmp_path):
    p = tmp_path / 'state.json'
    persist(p, {'status': 'failed', 'value': float('nan')})
    first = sha(p)
    with pytest.raises(FileExistsError):
        persist(p, {'status': 'passed'})
    assert sha(p) == first
    assert read_json(p) == {'status': 'failed', 'value': None}


def test_frozen_closure_includes_reused_actual_selector_not_old_outputs():
    root = Path(__file__).resolve().parents[1]
    paths = source_closure([root / 'scripts/momentum_g2_selection.py'])
    assert root / 'scripts/retention_selector.py' in paths
    assert all(p.suffix == '.py' and 'output' not in p.parts for p in paths)


def test_price_text_survives_csv_roundtrip_and_absent_partial_is_distinct(tmp_path):
    p = tmp_path / 'bridges.csv'
    p.write_text('ts_code,theoretical_pre_close_text,previous_close_text,D\n000001.SZ,10.00,10.005,0.0\n', encoding='utf-8')
    row = read_table(p).iloc[0]
    assert row.ts_code == '000001.SZ' and row.theoretical_pre_close_text == '10.00'
    assert row.previous_close_text == '10.005' and row.D == 0.
    assert read_table(tmp_path / 'missing.csv', missing_ok=True).empty
    with pytest.raises(FileNotFoundError):
        read_table(tmp_path / 'missing.csv')


def test_evidenced_human_pause_does_not_reset_original_clock(tmp_path, monkeypatch):
    import momentum_g2_runtime as rt
    from datetime import datetime, timezone
    monkeypatch.setattr(rt, 'OUT', tmp_path)
    persist(tmp_path / 'runtime/root_clock_origin.json', dict(root_effective_origin_utc='2026-10-21T01:00:00+00:00'))
    persist(tmp_path / 'runtime/human_interruptions.json', [dict(start_utc='2026-10-21T02:00:00+00:00', end_utc='2026-10-21T04:00:00+00:00')])
    assert rt.root_active_seconds(datetime(2026, 10, 21, 5, tzinfo=timezone.utc)) == 7200


def test_nested_bridge_provenance_is_json_not_python_repr(tmp_path):
    import json
    import pandas as pd
    from momentum_g2_runtime import write_table
    p = tmp_path / 'bridges.csv'
    write_table(p, pd.DataFrame([dict(event_ids=['ordinary:000001.SZ'], source_known_dates=['2016-05-01'])]))
    row = read_table(p).iloc[0]
    assert json.loads(row.event_ids) == ['ordinary:000001.SZ']
