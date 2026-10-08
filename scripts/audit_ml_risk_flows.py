"""Independent cash/share reconstruction for 12 groups and 24 study boundaries."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/open_source_ml_risk_2018_2020_r1'
original=ROOT/'scripts/audit_continuous_flows.py'
source=original.read_text(encoding='utf-8')
assert source.count('assert len(checks) == 12 and len(boundaries) == 108')==1
assert source.count("previous['date'].year >= 2016")==1
adapted=source.replace('assert len(checks) == 12 and len(boundaries) == 108',
                      'assert len(checks) == 12 and len(boundaries) == 24')
adapted=adapted.replace("previous['date'].year >= 2016","previous['date'].year >= 2018")
namespace={'__file__':str(original),'__name__':'ml_risk_flow_audit'}
exec(compile(adapted,str(original),'exec'),namespace)
namespace['OUT']=OUT
namespace['main']()
path=OUT/'flow_reconstruction_audit.json'
result=json.loads(path.read_text(encoding='utf-8'))
result['original_auditor_sha256']=hashlib.sha256(original.read_bytes()).hexdigest()
result['adapter_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
path.write_text(json.dumps(result,indent=2),encoding='utf-8')
