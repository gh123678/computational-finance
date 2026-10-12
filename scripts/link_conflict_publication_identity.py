"""Bind fixed conflict PDF observations to cached official index identities only."""
from pathlib import Path
from collections import defaultdict, Counter
import json
import re
import pandas as pd
import announcement_financial_audit as audit
from audit_publication_time import calendar_map, next_session, current_index_items
from collect_issuer_listing_evidence import local_day

ROOT=Path(__file__).resolve().parents[1]
CONTENT=ROOT/'output/unanchored_conflict_pages_20261012_r1'
OUT=ROOT/'output/conflict_publication_identity_20261012_r1'


def announcement_id(pdf):
    match=re.search(r'_(\d{10})\.pdf$',pdf or '',re.IGNORECASE)
    return match.group(1) if match else None


def main():
    if OUT.exists():raise RuntimeError('Snapshot exists; do not overwrite')
    OUT.mkdir()
    inputs={};read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    for name,h in read(CONTENT/'artifact_sha256.json').items():assert audit.sha(CONTENT/name)==h,name
    files=[CONTENT/'claims_after_followup.json',CONTENT/'conflict_key_content_scope.csv',
        ROOT/'data/continuous_2016_2025_dividend_r1/calendar.csv',Path(__file__)]
    for p in files:inputs[str(p.relative_to(ROOT))]=audit.sha(p)
    calendar=calendar_map(pd.read_csv(files[2],dtype={'cal_date':str}))
    keys=pd.read_csv(files[1],dtype=str,keep_default_na=False)
    needed={tuple(k) for k in keys[['ts_code','ann_date','end_date']].itertuples(index=False,name=None)}
    assert len(needed)==61
    claims=[r for r in read(files[0]) if (r['ts_code'],r['key_ann_date'],r['end_date']) in needed and r['pdf_sha256']]
    identifiers={(r['ts_code'][:6],announcement_id(r['pdf'])) for r in claims}
    index=defaultdict(list);skipped=Counter();failures=[]
    # All existing response caches in these two collection scopes; no network calls.
    bases=[ROOT/'output/announcement_financial_audit_20261007',ROOT/'output/off_checklist_revision_worklist_20261010/verification_round']
    for base in bases:
        for p in sorted(base.rglob('responses/*.json')):
            try:
                raw=read(p)
                if not isinstance(raw,dict) or not isinstance(raw.get('announcements'),list):
                    skipped['not_announcement_list']+=1;continue
                items=current_index_items(raw)
            except (ValueError,UnicodeError) as exc:
                failures.append(dict(path=str(p.relative_to(ROOT)),error=type(exc).__name__));continue
            relevant=[]
            for item in items:
                identifier=str(item.get('announcementId') or Path(item.get('adjunctUrl','')).stem)
                if (str(item.get('secCode')),identifier) not in identifiers:continue
                relevant.append((item,identifier))
            if relevant:inputs[str(p.relative_to(ROOT))]=audit.sha(p)
            for item,identifier in relevant:
                index[(str(item.get('secCode')),identifier)].append(dict(
                    announcement_id=identifier,current_index_day=local_day(item),
                    title=item.get('announcementTitle'),adjunct_url=item.get('adjunctUrl'),
                    source=str(p.relative_to(ROOT))))
    groups=defaultdict(list)
    for r in claims:groups[(r['ts_code'],r['key_ann_date'],r['end_date'],r['pdf_sha256'])].append(r)
    events=[]
    for (code,ann,period,digest),refs in sorted(groups.items()):
        for r in refs:
            assert audit.sha(ROOT/r['pdf'])==digest
            inputs[r['pdf']]=digest
        ids={announcement_id(r['pdf']) for r in refs}
        assert len(ids)==1
        identifier=ids.pop();matches=index.get((code[:6],identifier),[])
        dates={r['current_index_day'] for r in matches}
        state='matched_single_current_index_day' if len(dates)==1 else 'conflicting_current_index_days' if dates else 'no_current_index_identity_in_scanned_caches'
        day=next(iter(dates)) if len(dates)==1 else None
        candidate,status=next_session(day,calendar)
        cancelled=any('取消' in (r['title'] or '') for r in matches)
        blockers=['historical_original_release_identity_unverified','complete_historical_version_sequence_unverified']
        if day is None:blockers.append(state)
        if cancelled:blockers.append('cancellation_effective_day_unverified')
        if day and day>ann:blockers.append('current_pdf_index_later_than_vendor_key_no_backward_substitution')
        events.append(dict(ts_code=code,key_ann_date=ann,end_date=period,pdf_sha256=digest,
            source_claims=refs,announcement_id=identifier,current_index_observations=matches,
            current_index_identity_state=state,observed_current_index_day=day,candidate_available_day=candidate,
            candidate_date_status=status,current_title_cancelled=cancelled,cancellation_effective_day=None,
            blockers=blockers,selected_financial_value=None,verified_publication_day=None,usable_in_verified_history=False))
    per_key=[]
    for code,ann,period in sorted(needed):
        own=[r for r in events if (r['ts_code'],r['key_ann_date'],r['end_date'])==(code,ann,period)]
        assert own
        per_key.append(dict(ts_code=code,ann_date=ann,end_date=period,pdf_content_identities=len(own),
            identities_with_current_index_day=sum(r['observed_current_index_day'] is not None for r in own),
            later_than_vendor_key=sum(bool(r['observed_current_index_day'] and r['observed_current_index_day']>ann) for r in own),
            cancelled_current_titles=sum(r['current_title_cancelled'] for r in own),historical_approval=False))
    summary=dict(conflict_keys=61,pdf_content_identities=len(events),identity_states=dict(Counter(r['current_index_identity_state'] for r in events)),
        keys_with_no_matched_current_index_identity=sum(r['identities_with_current_index_day']==0 for r in per_key),
        later_indexed_pdf_identities=sum(r['later_than_vendor_key'] for r in per_key),
        current_cancelled_pdf_identities=sum(r['cancelled_current_titles'] for r in per_key),
        historical_approvals=0,cache_read_failures=failures,skipped_cache_types=dict(skipped),new_models=0,new_backtests=0)
    pd.DataFrame(per_key).to_csv(OUT/'key_identity_gaps.csv',index=False)
    audit.write_json(OUT/'events.json',events);audit.write_json(OUT/'summary.json',summary)
    for p,h in inputs.items():assert audit.sha(ROOT/p)==h,p
    audit.write_json(OUT/'input_sha256.json',inputs)
    audit.write_json(OUT/'verification.json',dict(inputs_unchanged=True,previous_content_snapshot_unchanged=True,
        old_experiments=audit.verify_old(),all_history_gates_closed=True))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
