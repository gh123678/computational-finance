"""Package required deliverables, excluding private notes and runtime caches."""
from pathlib import Path
import hashlib,json,zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    excluded={'private_workflow_note.md'}
    path=ROOT.parent/'12410604_ZhangBowen_HW-02.zip'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(ROOT.rglob('*')):
            if p.is_file() and p.name not in excluded and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts and p.suffix not in ['.aux','.log','.out','.toc','.pyc']:
                z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        assert all(Path(n).name not in excluded for n in z.namelist())
        manifest=json.loads(z.read('checksums.json'))
        assert all(Path(n).name not in excluded for n in manifest)
        for name,digest in manifest.items():
            assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
        print(f'ZIP verified: {len(z.namelist())} files; {path.stat().st_size} bytes; private note excluded.')


if __name__=='__main__':main()
