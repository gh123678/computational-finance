"""Export this homework's visible dialogue/tool records, never private reasoning."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def export(sessions,thread):
    records=[]
    redactions=[]
    for path in sessions.glob('*.jsonl'):
        with path.open(encoding='utf8') as h:
            first=json.loads(h.readline()).get('payload',{})
        identity=first.get('id',first.get('session_id'))
        source=first.get('source',{})
        child=source.get('subagent',{}).get('thread_spawn',{}) if isinstance(source,dict) else {}
        if identity!=thread and child.get('parent_thread_id')!=thread: continue
        kept=[]
        for line in path.read_text(encoding='utf8').splitlines():
            try: row=json.loads(line)
            except json.JSONDecodeError: continue # a still-being-written final line is not a record
            if row.get('type')!='response_item': continue
            p=row.get('payload',{})
            kind=p.get('type')
            if kind=='message':
                if p.get('role') not in ('user','assistant') or p.get('channel')=='analysis' or p.get('phase')=='analysis': continue
                allowed=['type','role','content','phase']
            elif kind in ('function_call','function_call_output','custom_tool_call','custom_tool_call_output'):
                allowed=['type','name','namespace','arguments','input','output','call_id','content']
            else: continue
            record={k:p[k] for k in allowed if k in p}
            if 'output' in record and any(token in str(record['output']) for token in ('base_instructions','creator_account_id','creator_user_id')):
                record['output']='[Redacted diagnostic output: account/session metadata and internal configuration; no substantive I1/I2 model response was removed.]'
                redactions.append(dict(session=identity,timestamp=row.get('timestamp'),reason='Diagnostic account/session metadata'))
            kept.append({'timestamp':row.get('timestamp'),'record':record})
        name=(child.get('agent_path','root').split('/')[-1] or 'root') if identity!=thread else 'root'
        target=ROOT/'ai_logs'/f'visible_{name}.jsonl'
        target.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in kept),encoding='utf8')
        records.append(dict(name=name,thread_id=identity,records=len(kept),last_record_utc=kept[-1]['timestamp'] if kept else None,
                            output=target.name))
    index=dict(exported_at_utc=datetime.now(timezone.utc).isoformat(),
        scope='Visible user/assistant messages and actual tool calls/results; no private reasoning or system/developer/account metadata.',
        limitations='Snapshot ends at each last_record_utc. Export/file-handoff operations after cutoff are not asserted to be inside the snapshot.',redactions=redactions,sessions=records)
    (ROOT/'ai_logs/visible_export_index.json').write_text(json.dumps(index,indent=2),encoding='utf8')
    print(json.dumps(index,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--sessions',type=Path,required=True);p.add_argument('--thread',required=True)
    a=p.parse_args();export(a.sessions,a.thread)
