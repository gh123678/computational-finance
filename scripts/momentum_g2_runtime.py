"""Bounded file/lock primitives for the one approved momentum experiment."""
from contextlib import contextmanager
from datetime import datetime, timezone
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import shutil

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = Path('D:/QuantResearchEvidence/medium_term_momentum_2018_2020_g2_r1')
SPEC = ROOT / 'docs/superpowers/specs/2026-10-21-medium-term-momentum-g2-design.md'
SPEC_SHA = 'd037aa81b44dc9c56dfb3acc9c715f41883ef09659165d42776da02dbe2ae5c9'
PLAN = ROOT / 'docs/superpowers/plans/2026-10-21-momentum-g2-implementation.md'
DATA = ROOT / 'data/continuous_2016_2025_dividend_r1'
META = ROOT / 'data/audit'
MAPPING = ROOT / 'output/alphaforge_case_2018_2020_r5/evidence_mapping.json'
START, END, BASELINE = '20151101', '20201231', '2017-12-29'


def utcnow():
    return datetime.now(timezone.utc)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is pd.NA or value is pd.NaT:
        return None
    if hasattr(value, 'item'):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def persist(path, value, *, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w' if replace else 'x', encoding='utf-8') as stream:
        json.dump(clean(value), stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        stream.write('\n')


def status(stage, state, **kwargs):
    row = dict(observed_utc=utcnow().isoformat(), pid=os.getpid(), stage=stage, status=state, **kwargs)
    with (OUT / 'runtime/history.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(clean(row), ensure_ascii=False, default=str, allow_nan=False) + '\n')
    persist(OUT / 'runtime/latest.json', row, replace=True)
    print(json.dumps(clean(row), ensure_ascii=True, default=str), flush=True)


@contextmanager
def exclusive(stage):
    lock = OUT / 'runtime/runner.lock'
    persist(lock, dict(pid=os.getpid(), stage=stage, started_utc=utcnow().isoformat()))
    try:
        yield
    finally:
        if lock.exists() and read_json(lock).get('pid') == os.getpid():
            lock.unlink()


def check_disk():
    if shutil.disk_usage(OUT).free < 6 * 1024 ** 3:
        raise RuntimeError('6GiB disk floor')


def check_g2_budget():
    elapsed = root_active_seconds()
    cap = read_json(OUT / 'authorization_and_budget.json')['G2_caps_seconds']['root']
    if elapsed > cap:
        raise RuntimeError('Root G2 task wall budget exceeded; no reset')
    return elapsed


def root_active_seconds(at=None):
    """Original wall origin minus evidenced human interruption, never a reset."""
    at = at or utcnow()
    origin = datetime.fromisoformat(read_json(OUT / 'runtime/root_clock_origin.json')['root_effective_origin_utc'])
    previous, excluded = origin, 0.
    path = OUT / 'runtime/human_interruptions.json'
    for row in read_json(path) if path.exists() else []:
        start, end = (datetime.fromisoformat(row[k]) for k in ('start_utc', 'end_utc'))
        if start < previous or end < start or end > at:
            raise RuntimeError('Invalid/overlapping human interruption evidence')
        excluded += (end - start).total_seconds()
        previous = end
    return (at - origin).total_seconds() - excluded


def check_g3_budget():
    phase = read_json(OUT / 'runtime/G3_phase_start.json')
    elapsed = (utcnow() - datetime.fromisoformat(phase['started_utc'])).total_seconds()
    if elapsed > phase['cap_seconds']:
        raise RuntimeError('G3 fixed cohort/audit/report budget exceeded')
    check_disk()
    return elapsed


def source_closure(seeds):
    """Fingerprint the local imported Python closure, not old output corpora."""
    pending, seen = [Path(p).resolve() for p in seeds], set()
    while pending:
        path = pending.pop()
        if path in seen or not path.is_file() or not path.is_relative_to(ROOT):
            continue
        seen.add(path)
        for parent in path.parents:
            if parent == ROOT:
                break
            init = parent / '__init__.py'
            if init.is_file():
                pending.append(init)
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            candidates = []
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
                if node.level:
                    parent = path.parent
                    for _ in range(node.level - 1):
                        parent = parent.parent
                    candidates.extend(parent / (n.replace('.', '/') + '.py') for n in names)
                    names = []
            else:
                continue
            for name in names:
                candidates.extend([ROOT / (name.replace('.', '/') + '.py'),
                                   ROOT / 'scripts' / (name.replace('.', '/') + '.py')])
            pending.extend(p.resolve() for p in candidates if p.is_file())
    return sorted(seen)


def verify_frozen(*, full_inputs=True):
    protocol = read_json(OUT / 'frozen_protocol.json')
    if protocol['approved_spec_sha256'] != SPEC_SHA or sha(SPEC) != SPEC_SHA:
        raise RuntimeError('Approved scientific design changed')
    for path, expected in protocol['sources'].items():
        if sha(path) != expected:
            raise RuntimeError('Frozen source changed: ' + path)
    for path, info in protocol['inputs'].items():
        p = Path(path)
        stat = p.stat()
        if stat.st_size != info['bytes'] or stat.st_mtime_ns != info['mtime_ns']:
            raise RuntimeError('Frozen input size/time changed: ' + path)
        if full_inputs and sha(p) != info['sha256']:
            raise RuntimeError('Frozen input content changed: ' + path)
    check_disk()
    return protocol


def write_table(path, frame):
    path = Path(path)
    if path.exists():
        raise RuntimeError('No output overwrite: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    serial = frame.copy()
    for column in serial.select_dtypes(include='object'):
        serial[column] = serial[column].map(lambda value: json.dumps(clean(value), ensure_ascii=False, default=str)
            if isinstance(value, (list, tuple, dict)) else value)
    serial.to_csv(path, index=False, date_format='%Y-%m-%d')


def read_table(path, *, missing_ok=False):
    if missing_ok and not Path(path).exists():
        return pd.DataFrame()
    try:
        columns = pd.read_csv(path, nrows=0).columns
        types = {c: str for c in columns if c in ('ts_code', 'code') or c.endswith('_text')}
        return pd.read_csv(path, float_precision='round_trip', dtype=types)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def make_manifest(directory, filename):
    directory, filename = Path(directory), Path(filename)
    members = {p.relative_to(OUT).as_posix(): sha(p) for p in sorted(directory.rglob('*'))
               if p.is_file() and p.resolve() != filename.resolve()}
    persist(filename, members)
    return members


def verify_manifest(path):
    entries = read_json(path)
    for name, expected in entries.items():
        p = (OUT / name).resolve()
        if not p.is_relative_to(OUT.resolve()) or sha(p) != expected:
            raise RuntimeError('Stage output changed: ' + name)
    return entries
