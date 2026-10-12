import hashlib
import pytest
import consolidate_financial_field_evidence as ledger


def test_pdf_identity_change_stops_claim_reuse(tmp_path,monkeypatch):
    monkeypatch.setattr(ledger,'ROOT',tmp_path)
    p=tmp_path/'original.pdf';p.write_bytes(b'original document')
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    c=ledger.claim('000001.SZ','20201231','-10.00','original.pdf',digest,7,'original','review.json')
    assert c['usable_in_verified_history'] is False and c['selected_financial_value'] is None
    p.write_bytes(b'changed document')
    with pytest.raises(ValueError,match='hash changed'):
        ledger.claim('000001.SZ','20201231','-10.00','original.pdf',digest,7,'original','review.json')


def test_later_version_value_is_separate_from_same_pdf_claim_conflict():
    def c(digest,value):return dict(pdf_sha256=digest,target_review_period='20201231',observed_review_value_cny=value)
    result=ledger.summarize_claims([c('original','10'),c('updated','12')])
    assert result['reviewed_pdf_versions']==2 and not result['intra_pdf_review_value_conflict']
    assert ledger.summarize_claims([c('original','10'),c('original','12')])['intra_pdf_review_value_conflict']
    assert result['verified_publication_day'] is None and not result['usable_in_verified_history']
