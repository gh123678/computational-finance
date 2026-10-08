"""Check archived primary evidence and preserve the original audit locations."""
import hashlib
import json
from pathlib import Path

from quant_research.rights import verified_rights

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / 'data/evidence/validation_events_20261004'
    evidence = []
    for name in ('manifest.json', 'manifest_remaining.json'):
        evidence += json.loads((folder / name).read_text(encoding='utf-8'))
    by_source = {item['source']: item for item in evidence}
    issues = [i for i in verified_rights() if i.source in by_source]
    assert len(issues) == 18
    for issue in issues:
        item = by_source[issue.source]
        path = ROOT / item['local_path']
        assert item['status'] == 'archived'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
        text = ''.join(path.with_suffix('.txt').read_text(encoding='utf-8').split())
        for date in (issue.record, issue.ex):
            assert f'{date.year}年{date.month}月{date.day}日' in text
        assert '发行成功' in text and '除权' in text
        assert issue.price is None and issue.ratio is None and issue.list_date is None
    out = ROOT / 'output/validation_event_audit_20261004'
    original = json.loads((out / 'input_sha256.json').read_text(encoding='utf-8'))
    snapshot = json.loads((ROOT / 'output/validation_run_20261004_r2/annual_snapshot/manifest.json').read_text(encoding='utf-8'))
    locations = {}
    for name, digest in original.items():
        path = snapshot[name]['snapshot'] if name in snapshot else name
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, name
        locations[name] = dict(preserved_path=path, sha256=digest)
    (out / 'preserved_input_locations.json').write_text(json.dumps(locations, indent=2), encoding='utf-8')
    print('18 primary evidence records and all original audit inputs verified.')


if __name__ == '__main__':
    main()
