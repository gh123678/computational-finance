"""A recovered attachment must never turn candidate timing into approval."""
import copy
import json
from pathlib import Path

import pytest

import recover_large_publication_pdfs as recovery


@pytest.fixture
def recovery_case(tmp_path, monkeypatch):
    previous = tmp_path / 'previous'
    out = tmp_path / 'recovery'
    previous.mkdir(); out.mkdir()
    calendar = tmp_path / 'data/continuous_2016_2025_dividend_r1/calendar.csv'
    calendar.parent.mkdir(parents=True)
    calendar.write_text('cal_date,is_open\n20210507,1\n20210508,0\n20210509,0\n20210510,1\n')
    event = dict(ts_code='603559.SH', target_review_period='20201231',
        announcement_id='1209935419', observed_current_index_day='20210507',
        source_observations=[], blockers=['pdf_missing', 'historical_release_content_identity_unverified',
            'complete_version_chain_unverified'], identity_status='current_index_identity_date_matches',
        candidate_available_day=None, date_status='candidate_next_session_only',
        selected_financial_value=None, verified_publication_day=None, usable_in_verified_history=False)
    path = previous / 'events.json'
    path.write_text(json.dumps([event]))
    pdf = out / 'candidate.pdf'
    pdf.write_bytes(b'current-candidate-bytes')
    record = dict(ts_code='603559.SH', target_review_period='20201231',
        announcement_id='1209935419', current_index_day='20210507', title='更正公告',
        record_file='results/example.json', document=dict(status='downloaded_readable_candidate_only',
            file=pdf.name, sha256=recovery.audit.sha(pdf)))
    monkeypatch.setattr(recovery, 'ROOT', tmp_path)
    monkeypatch.setattr(recovery, 'PREVIOUS', previous)
    monkeypatch.setattr(recovery, 'OUT', out)
    monkeypatch.setattr(recovery.audit, 'verify_old', lambda: {'frozen': 960})
    return event, record, path, out


def test_recovery_only_removes_attachment_gap_and_preserves_original(recovery_case):
    original, record, path, out = recovery_case
    digest = recovery.audit.sha(path)
    status = recovery.summarize([record], [record], {'previous/events.json': digest}, final=True)
    supplemented = json.loads((out / 'supplemental_events.json').read_text(encoding='utf-8'))[0]
    assert status['recovered_pdf_events'] == 1
    assert status['approved_historical_events'] == 0
    assert supplemented['candidate_available_day'] == '20210510'
    assert supplemented['blockers'] == ['historical_release_content_identity_unverified',
        'complete_version_chain_unverified']
    assert supplemented['usable_in_verified_history'] is False
    assert supplemented['verified_publication_day'] is None
    assert supplemented['selected_financial_value'] is None
    assert recovery.audit.sha(path) == digest
    assert json.loads(path.read_text())[0] == original


def test_changed_recovered_bytes_rejected_before_supplemental_ledger(recovery_case):
    _, record, _, out = recovery_case
    (out / 'candidate.pdf').write_bytes(b'different-candidate-content')
    with pytest.raises(RuntimeError, match='fingerprint changed'):
        recovery.summarize([record], [record], {})
    assert not (out / 'supplemental_events.json').exists()


def test_failed_download_cannot_remove_gap_or_assign_candidate_date(recovery_case):
    _, record, _, out = recovery_case
    failed = copy.deepcopy(record)
    failed['document']['status'] = 'document_transport_failed'
    status = recovery.summarize([failed], [failed], {})
    supplemented = json.loads((out / 'supplemental_events.json').read_text(encoding='utf-8'))[0]
    assert status['recovered_pdf_events'] == 0
    assert 'pdf_missing' in supplemented['blockers']
    assert supplemented['candidate_available_day'] is None
    assert supplemented['usable_in_verified_history'] is False
