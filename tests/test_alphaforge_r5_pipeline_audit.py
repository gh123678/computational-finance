import json

import pytest

import verify_alphaforge_r5 as audit


def frozen(tmp_path,monkeypatch):
    monkeypatch.setattr(audit,'ROOT',tmp_path);monkeypatch.setattr(audit,'OUT',tmp_path)
    monkeypatch.setattr(audit,'R3',tmp_path)
    original=tmp_path/'module.py';original.write_text('original',encoding='utf-8')
    snapshot=tmp_path/'source_before';snapshot.mkdir();(snapshot/'module.py').write_bytes(original.read_bytes())
    entries=[]
    for i,count in enumerate([1924,105,493,110,646,115,78,7,14,12,35]):
        path=tmp_path/f'manifest{i}.json'
        path.write_text(json.dumps({str(k):'unused_in_shallow_check' for k in range(count)}),encoding='utf-8')
        entries.append(dict(path=str(path),sha256=audit.sha(path),count=count))
    return dict(inputs={'module.py':audit.sha(original)},external_inputs={},reused_r3={},
        original_r4_inputs={},original_r4_external_inputs={},source_snapshot_files=['module.py'],
        prior_artifact_manifests=entries)


def test_snapshot_may_not_lose_or_gain_members(tmp_path,monkeypatch):
    protocol=frozen(tmp_path,monkeypatch)
    assert audit.fingerprints(protocol)['total']==3539
    (tmp_path/'source_before/module.py').unlink()
    with pytest.raises(AssertionError,match='snapshot'):audit.fingerprints(protocol)
    (tmp_path/'source_before/module.py').write_text('original',encoding='utf-8')
    (tmp_path/'source_before/unfrozen.py').write_text('extra',encoding='utf-8')
    with pytest.raises(AssertionError,match='snapshot'):audit.fingerprints(protocol)


def test_snapshot_contents_and_original_sources_both_bound(tmp_path,monkeypatch):
    protocol=frozen(tmp_path,monkeypatch)
    (tmp_path/'source_before/module.py').write_text('tamper',encoding='utf-8')
    with pytest.raises(AssertionError):audit.fingerprints(protocol)
    (tmp_path/'source_before/module.py').write_text('original',encoding='utf-8')
    (tmp_path/'module.py').write_text('new',encoding='utf-8')
    with pytest.raises(AssertionError,match='Frozen input'):audit.fingerprints(protocol)


def test_stage_hash_detects_late_output_tamper(tmp_path,monkeypatch):
    monkeypatch.setattr(audit,'OUT',tmp_path)
    member=tmp_path/'coverage.csv';member.write_text('original',encoding='utf-8')
    (tmp_path/'preparation_sha256.json').write_text(json.dumps({'coverage.csv':audit.sha(member)}),encoding='utf-8')
    audit.stage_fingerprint('preparation_sha256.json')
    member.write_text('dropped key',encoding='utf-8')
    with pytest.raises(AssertionError,match='Stage changed'):audit.stage_fingerprint('preparation_sha256.json')


def test_final_seal_prevents_audit_and_does_not_create_lock(tmp_path,monkeypatch):
    import sys
    monkeypatch.setattr(audit,'OUT',tmp_path)
    monkeypatch.setattr(audit.run,'check_disk',lambda:None)
    monkeypatch.setattr(sys,'argv',['verify','--stage','preparation'])
    (tmp_path/'output_sha256.json').write_text('{}',encoding='utf-8')
    with pytest.raises(RuntimeError,match='sealed'):audit.main()
    assert not (tmp_path/'runner.lock').exists()
