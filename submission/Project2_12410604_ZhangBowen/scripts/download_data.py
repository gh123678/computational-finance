"""Optional official-source download. Offline reproduction uses bundled snapshots."""
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time
import zipfile
import io
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://mba.tuck.dartmouth.edu/pages/Faculty/ken.french/"
SOURCES = {
    "fiz_monthly.zip": BASE+"ftp_202412/F-F_Research_Data_Factors_CSV.zip",
    "fiz_daily.zip": BASE+"ftp_202412/F-F_Research_Data_Factors_daily_CSV.zip",
    "ciz_monthly.zip": BASE+"ftp/F-F_Research_Data_Factors_CSV.zip",
    "ciz_daily.zip": BASE+"ftp/F-F_Research_Data_Factors_daily_CSV.zip",
}


def fetch(item):
    name,url=item
    error=None
    for attempt in range(4):
        try:
            response=requests.get(url,timeout=(15,60))
            response.raise_for_status()
            raw=response.content
            archive=zipfile.ZipFile(io.BytesIO(raw))
            if archive.testzip() is not None:
                raise ValueError("Archive CRC mismatch")
            destination=ROOT/"data"/"raw"/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists() and destination.read_bytes()!=raw:
                raise FileExistsError("Refusing to replace a different frozen snapshot: "+name)
            destination.write_bytes(raw)
            return {"file":name,"url":url,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
                    "retrieved_at_utc":datetime.now(timezone.utc).isoformat(),
                    "content_type":response.headers.get("Content-Type"),
                    "last_modified":response.headers.get("Last-Modified")}
        except FileExistsError:
            raise
        except Exception as exc:
            error=exc
            time.sleep(attempt+1)
    raise RuntimeError(f"Download failed for {name}: {error}")


if __name__=="__main__":
    with ThreadPoolExecutor(max_workers=4) as pool:
        records=list(pool.map(fetch,SOURCES.items()))
    out=ROOT/"data"/"source_manifest.json"
    if out.exists():
        raise FileExistsError("Snapshots frozen; keep the original manifest")
    out.write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding="utf-8")
    for record in records:
        print(record["file"],record["bytes"],record["sha256"])
