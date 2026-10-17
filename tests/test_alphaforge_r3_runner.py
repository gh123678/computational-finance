"""Stage and provenance boundaries; no production research is started."""
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_alphaforge_r3 as runner
import report_alphaforge_r3 as report


def test_existing_preparation_cannot_be_restarted(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'OUT',tmp_path)
    (tmp_path/'frozen_protocol.json').write_text('{}')
    monkeypatch.setattr(runner,'verify_prior',lambda:pytest.fail('must reject before scanning inputs'))
    with pytest.raises(RuntimeError,match='Existing r3 preparation'):
        runner.freeze()


def test_stage_checksum_rejects_modified_preparation(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'OUT',tmp_path)
    (tmp_path/'raw.csv').write_text('original')
    digest=runner.sha(tmp_path/'raw.csv')
    (tmp_path/'preparation_sha256.json').write_text(json.dumps({'raw.csv':digest}))
    (tmp_path/'raw.csv').write_text('changed')
    with pytest.raises(RuntimeError,match='Stage artifact changed'):
        runner.verify_artifacts('preparation_sha256.json')


def test_original_account_calendar_and_week_endpoints():
    full,calendar,simulation,schedule=runner.calendars()
    assert simulation[0]==pd.Timestamp('20171009')
    assert full[full<simulation[0]][-1]==pd.Timestamp('20170929')
    assert calendar[0]==pd.Timestamp('20151102') and calendar[-1]==pd.Timestamp('20201231')
    assert len(schedule)==154
    assert schedule.loc[0,'execution_date']==pd.Timestamp('20180102')
    assert schedule.loc[0,'next_execution']==pd.Timestamp('20180108')
    assert schedule.iloc[-1].next_execution>calendar[-1]


def test_report_refuses_incomplete_engineering_stage(tmp_path,monkeypatch):
    monkeypatch.setattr(report,'OUT',tmp_path)
    monkeypatch.setattr(report,'REPORT',tmp_path/'workspace-report.md')
    (tmp_path/'frozen_protocol.json').write_text('{}')
    with pytest.raises(RuntimeError,match='No reviewed terminal'):
        report.main()
    assert not (tmp_path/'closeout.json').exists()


def test_failed_guard_report_cannot_invent_accounts_or_nav(tmp_path,monkeypatch):
    monkeypatch.setattr(report,'OUT',tmp_path)
    monkeypatch.setattr(report,'REPORT',tmp_path/'workspace-report.md')
    for file,data in [('frozen_protocol.json',{'approved':True}),
        ('experiment_stage.json',{'state':'blocked_guard'}),
        ('preparation_status.json',{'state':'completed'}),
        ('guard_summary.json',{'passed':False,'failure_count':1})]:
        (tmp_path/file).write_text(json.dumps(data))
    report.main()
    result=json.loads((tmp_path/'closeout.json').read_text(encoding='utf-8'))
    assert result['accounts_started']==0 and not result['live_enablement']
    assert not result['full_verification_passed']
    text=(tmp_path/'report.md').read_text(encoding='utf-8')
    assert '六账户未启动' in text and 'not_completed' in text
