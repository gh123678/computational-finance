"""Validate every recorded file against the frozen submission manifest."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


if __name__=="__main__":
    data=json.loads((ROOT/"FILE_MANIFEST.json").read_text(encoding="utf-8"))
    for record in data["files"]:
        path=(ROOT/record["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError("Unsafe manifest path")
        if path.stat().st_size!=record["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest()!=record["sha256"]:
            raise ValueError("Submission file differs: "+record["path"])
    print(f"PASS: {len(data['files'])} submission files match their SHA256 manifest")
