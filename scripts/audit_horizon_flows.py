"""Original cash/share auditor, scoped to 18 new groups and 36 boundaries."""
import json
from run_horizon_coverage import ROOT,OUT,sha

original=ROOT/'scripts/audit_continuous_flows.py'
source=original.read_text(encoding='utf-8')
assert source.count('assert len(checks) == 12 and len(boundaries) == 108')==1
adapted=source.replace('assert len(checks) == 12 and len(boundaries) == 108','assert len(checks) == 18 and len(boundaries) == 36')
assert adapted.count("previous['date'].year >= 2016")==1
adapted=adapted.replace("previous['date'].year >= 2016","previous['date'].year >= 2018")
ns={'__file__':str(original),'__name__':'horizon_flow_audit'}
exec(compile(adapted,str(original),'exec'),ns);ns['OUT']=OUT;ns['main']()
path=OUT/'flow_reconstruction_audit.json';result=json.loads(path.read_text(encoding='utf-8'))
result.update(original_auditor_sha256=sha(original),adapter_sha256=sha(__import__('pathlib').Path(__file__)))
path.write_text(json.dumps(result,indent=2),encoding='utf-8')
