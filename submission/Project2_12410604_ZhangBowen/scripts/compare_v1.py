"""Optional audit: compare unchanged scientific results with the preserved v1 ZIP."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",type=Path,default=ROOT.parent/"12410604_ZhangBowen_Project2.zip")
    args=parser.parse_args();archive=args.archive
    prefix=ROOT.name+"/"
    checks=[]
    with zipfile.ZipFile(archive) as z:
        previous=json.loads(z.read(prefix+"config.json"));current=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
        for key,value in previous.items():assert current[key]==value,"Scientific config changed: "+key
        checks.append({"check":"all original configuration entries unchanged","entries":len(previous)})
        source=json.loads(z.read(prefix+"data/source_manifest.json"))
        for item in source:
            assert hashlib.sha256((ROOT/"data/raw"/item["file"]).read_bytes()).hexdigest()==item["sha256"]
        checks.append({"check":"all four original raw inputs unchanged","files":len(source)})
        names=["original_account.csv","original_market_account.csv","original_monthly.csv","comparison.csv",
               "holdout_metrics.csv","sensitivities.csv"]
        names.extend(p.name for p in (ROOT/"results").glob("holdout_*bp*.csv"))
        for name in sorted(set(names)):
            old=pd.read_csv(io.BytesIO(z.read(prefix+"results/"+name)))
            new=pd.read_csv(ROOT/"results"/name)
            assert list(old.columns)==list(new.columns) and old.shape==new.shape,name+" schema"
            maximum=0.
            for col in old:
                if pd.api.types.is_numeric_dtype(old[col]):
                    np.testing.assert_allclose(old[col],new[col],atol=1e-10,rtol=1e-12,err_msg=name+"/"+col)
                    maximum=max(maximum,float(np.nanmax(abs(old[col]-new[col]))))
                else:assert old[col].equals(new[col]),name+"/"+col
            checks.append({"check":name,"rows":len(new),"maximum_absolute_numeric_difference":maximum})
    result={"status":"PASS","previous_zip":archive.name,"previous_zip_sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
        "scope":"All v1 research configuration entries and raw inputs unchanged; core and all 11 holdout accounts numerically equivalent",
        "checks":checks}
    (ROOT/"audit/v1_to_v2_comparison.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(f"PASS: {len(checks)} v1/v2 comparisons; scientific results preserved")


if __name__=="__main__":main()
