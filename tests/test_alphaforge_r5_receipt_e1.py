import json
from pathlib import Path

import pytest

import report_alphaforge_r5_receipt_e1 as e1


def save(path,value):
    path.write_text(json.dumps(value),encoding='utf-8')


def fixture(tmp_path):
    reuse=['common_samples.csv','reference_labels.csv']
    snapshot='scripts/module.py'
    source=tmp_path/'source_before'/snapshot;source.parent.mkdir(parents=True);source.write_text('frozen source',encoding='utf-8')
    clone=tmp_path/'reused_r3';clone.mkdir()
    for name in reuse:(clone/name).write_text('original '+name,encoding='utf-8')
    protocol=dict(source_snapshot_files=[str(Path(snapshot))],inputs={str(Path(snapshot)):e1.run.sha(source)},
        reused_r3={name:e1.run.sha(clone/name) for name in reuse})
    for name in e1.PREPARATION_FILES:(tmp_path/name).write_text('original '+name,encoding='utf-8')
    manifest={name:e1.run.sha(tmp_path/name) for name in e1.PREPARATION_FILES}
    manifest.update({'source_before/'+snapshot:e1.run.sha(source),
        **{'reused_r3/'+name:e1.run.sha(clone/name) for name in reuse}})
    save(tmp_path/'preparation_sha256.json',manifest)
    receipt=dict(preparation_manifest_sha256=protocol['reused_r3']['reference_labels.csv'])
    save(tmp_path/'preparation_audit.json',receipt)
    accounts={name:manifest[name] for name in e1.PREPARATION_FILES}
    accounts['preparation_audit.json']=e1.run.sha(tmp_path/'preparation_audit.json')
    save(tmp_path/'accounts_sha256.json',accounts)
    return protocol,reuse


def test_shadowed_receipt_field_corrected_without_writing_original_or_rerunning(tmp_path):
    protocol,reuse=fixture(tmp_path);before=(tmp_path/'preparation_audit.json').read_bytes()
    corrected,proof=e1.reconstruct_receipt(tmp_path,protocol,reuse)
    assert corrected['preparation_manifest_sha256']==e1.run.sha(tmp_path/'preparation_sha256.json')
    assert corrected['preparation_manifest_sha256']!=json.loads(before)['preparation_manifest_sha256']
    assert (tmp_path/'preparation_audit.json').read_bytes()==before
    assert proof['member_scope_exact'] and proof['all_member_bytes_rehashed'] and proof['correction_required']
    assert not proof['accounts_rerun'] and not proof['source_or_data_edited']


@pytest.mark.parametrize('member',['source_bridge_coverage.csv','reused_r3/common_samples.csv','source_before/scripts/module.py'])
def test_every_anchor_class_rejects_changed_bytes(tmp_path,member):
    protocol,reuse=fixture(tmp_path);(tmp_path/member).write_text('changed',encoding='utf-8')
    with pytest.raises(AssertionError,match='bytes changed'):e1.reconstruct_receipt(tmp_path,protocol,reuse)


@pytest.mark.parametrize('mutation',['drop','add'])
def test_preparation_manifest_member_scope_cannot_be_narrowed_or_broadened(tmp_path,mutation):
    protocol,reuse=fixture(tmp_path);path=tmp_path/'preparation_sha256.json';manifest=json.loads(path.read_text())
    if mutation=='drop':manifest.pop('source_bridge_coverage.csv')
    else:manifest['unverified.csv']='forged'
    save(path,manifest)
    with pytest.raises(AssertionError,match='scope changed'):e1.reconstruct_receipt(tmp_path,protocol,reuse)


def test_unknown_receipt_corruption_not_repaired(tmp_path):
    protocol,reuse=fixture(tmp_path);receipt=tmp_path/'preparation_audit.json'
    save(receipt,dict(preparation_manifest_sha256='unexplained'))
    accounts=json.loads((tmp_path/'accounts_sha256.json').read_text());accounts['preparation_audit.json']=e1.run.sha(receipt)
    save(tmp_path/'accounts_sha256.json',accounts)
    with pytest.raises(AssertionError,match='Unknown receipt'):e1.reconstruct_receipt(tmp_path,protocol,reuse)


def test_correcting_original_file_in_place_is_rejected_as_cohort_change(tmp_path):
    protocol,reuse=fixture(tmp_path)
    save(tmp_path/'preparation_audit.json',dict(preparation_manifest_sha256=e1.run.sha(tmp_path/'preparation_sha256.json')))
    with pytest.raises(AssertionError,match='Original receipt changed'):e1.reconstruct_receipt(tmp_path,protocol,reuse)


def test_relabelled_unchanged_manifest_cannot_bypass_frozen_reuse_anchor(tmp_path):
    protocol,reuse=fixture(tmp_path);path=tmp_path/'preparation_sha256.json';manifest=json.loads(path.read_text())
    file=tmp_path/'reused_r3/common_samples.csv';file.write_text('changed',encoding='utf-8')
    manifest['reused_r3/common_samples.csv']=e1.run.sha(file);save(path,manifest)
    with pytest.raises(AssertionError,match='frozen r3'):e1.reconstruct_receipt(tmp_path,protocol,reuse)


def test_final_seal_rejected_without_new_sidecar_or_lock(tmp_path,monkeypatch):
    monkeypatch.setattr(e1.run,'OUT',tmp_path)
    (tmp_path/'output_sha256.json').write_text('{}',encoding='utf-8')
    with pytest.raises(RuntimeError,match='never repeat'):e1.main()
    assert sorted(p.name for p in tmp_path.iterdir())==['output_sha256.json']
