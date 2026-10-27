"""Freeze a file manifest and build the final project ZIP without local caches."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SKIP={"__pycache__",".pytest_cache",".venv","reproduced_results","demo_results","integration_review",".latex_tmp"}


def main():
    files=sorted(p for p in ROOT.rglob("*") if p.is_file() and
                 not any(part in SKIP for part in p.relative_to(ROOT).parts) and
                 p.relative_to(ROOT).as_posix() not in {"report/Project2_Report.pdf","report/Project2_Report_v2.pdf"} and
                 p.name!="FILE_MANIFEST.json" and p.suffix.lower() not in {".pyc",".pyo",".aux",".log"})
    records=[{"path":p.relative_to(ROOT).as_posix(),"bytes":p.stat().st_size,
              "sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
    manifest=ROOT/"FILE_MANIFEST.json"
    manifest.write_text(json.dumps({"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
        "hash_algorithm":"SHA-256","excluded":[*sorted(SKIP),"report/Project2_Report.pdf (v1)","report/Project2_Report_v2.pdf","*.pyc","*.pyo","*.aux","*.log","FILE_MANIFEST.json (self)"],
        "files":records},ensure_ascii=False,indent=2),encoding="utf-8")
    target=ROOT.parent/"12410604_ZhangBowen_Project2_v3.zip"
    with zipfile.ZipFile(target,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in [*files,manifest]:
            archive.write(path,(Path(ROOT.name)/path.relative_to(ROOT)).as_posix())
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(files)+1
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(digest+"  "+target.name+"\n",encoding="ascii")
    print(json.dumps({"zip":str(target),"bytes":target.stat().st_size,"files":len(files)+1,"sha256":digest},ensure_ascii=True,indent=2))


if __name__=="__main__":
    main()
