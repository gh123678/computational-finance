import pytest

import retry_publication_pdf_timeouts as retry


def test_retry_changes_time_limit_without_changing_size_or_input(monkeypatch):
    calls = []
    monkeypatch.setattr(retry, 'ORIGINAL_RUN', lambda args, timeout, context:
        calls.append((args, timeout, context)) or True)
    args = ['--max-time', '55', '--max-filesize', '134217728', 'https://static.cninfo.com.cn/example']
    before = args.copy()
    assert retry.bounded_transfer(args, 65, {'attempt_scope': 'fixed_failed_queue'})
    assert args == before
    assert calls[0][0] == ['--max-time', '180', '--max-filesize', '134217728',
        'https://static.cninfo.com.cn/example']
    assert calls[0][1] == 190
    assert calls[0][2] == {'attempt_scope': 'fixed_failed_queue'}


def test_unexpected_retry_protocol_is_rejected_before_network(monkeypatch):
    def forbidden(*args):
        raise AssertionError('network must not be invoked')
    monkeypatch.setattr(retry, 'ORIGINAL_RUN', forbidden)
    with pytest.raises(ValueError, match='Unexpected request protocol'):
        retry.bounded_transfer(['--max-time', '900'], 910, {})
