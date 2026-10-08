"""Reuse the unchanged independent ledger auditor for 3 groups/4 boundaries."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/retention_threshold_development_2016_2020_r1'
original=ROOT/'scripts/audit_continuous_flows.py'
source=original.read_text(encoding='utf-8')
assert source.count('assert len(checks) == 12 and len(boundaries) == 108')==1
# Only expected study sizes change; all independent cash/share reconstruction
# logic remains identical to the auditor used for the frozen twelve groups.
adapted=source.replace('assert len(checks) == 12 and len(boundaries) == 108',
                       'assert len(checks) == 3 and len(boundaries) == 12')
namespace={'__file__':str(original),'__name__':'retention_flow_audit'}
exec(compile(adapted,str(original),'exec'),namespace)
namespace['OUT']=OUT
namespace['main']()
path=OUT/'flow_reconstruction_audit.json'
result=json.loads(path.read_text(encoding='utf-8'))
result['original_auditor_sha256']=hashlib.sha256(original.read_bytes()).hexdigest()
result['adapter_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
path.write_text(json.dumps(result,indent=2),encoding='utf-8')
