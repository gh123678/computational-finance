"""Verify earlier current-cached candidates for three timing gaps; no history approval."""
from pathlib import Path
from collections import defaultdict
import json
import pandas as pd
import announcement_financial_audit as audit
from audit_publication_time import calendar_map, next_session
from collect_issuer_listing_evidence import local_day
from profile_conflict_publication_gaps import earlier_signals

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/three_original_version_followup_20261012_r1'


def main():
    if (OUT/'summary.json').exists():raise RuntimeError('Snapshot already exists')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    claims=read(OUT/'visual_adjudications.json');assert len(claims)==3
    inputs={str((OUT/'visual_adjudications.json').relative_to(ROOT)):audit.sha(OUT/'visual_adjudications.json')}
    by=defaultdict(list)
    ids={Path(r['pdf']).stem.rsplit('_',1)[-1] for r in claims}
    for base in [ROOT/'output/announcement_financial_audit_20261007',ROOT/'output/off_checklist_revision_worklist_20261010/verification_round']:
        for p in sorted(base.rglob('responses/*.json')):
            raw=read(p)
            if not isinstance(raw,dict) or not isinstance(raw.get('announcements'),list):continue
            for item in raw['announcements']:
                if str(item.get('announcementId')) not in ids:continue
                inputs[str(p.relative_to(ROOT))]=audit.sha(p)
                by[(str(item.get('secCode')),str(item['announcementId']))].append(dict(
                    day=local_day(item),title=item.get('announcementTitle'),url=item.get('adjunctUrl'),source=str(p.relative_to(ROOT))))
    calendar_file=ROOT/'data/continuous_2016_2025_dividend_r1/calendar.csv'
    signal_file=ROOT/'output/latest_financial_report_coverage_20261012_r1/signal_latest_report_evidence.csv.gz'
    for p in [calendar_file,signal_file,Path(__file__)]:inputs[str(p.relative_to(ROOT))]=audit.sha(p)
    calendar=calendar_map(pd.read_csv(calendar_file,dtype={'cal_date':str}))
    signals=pd.read_csv(signal_file,dtype=str,keep_default_na=False)
    events=[]
    for r in claims:
        assert audit.sha(ROOT/r['pdf'])==r['pdf_sha256']
        inputs[r['pdf']]=r['pdf_sha256']
        for image in r['images']:assert audit.sha(OUT/image['path'])==image['sha256']
        identifier=Path(r['pdf']).stem.rsplit('_',1)[-1]
        matches=by[(r['ts_code'][:6],identifier)]
        dates={m['day'] for m in matches};assert dates=={r['key_ann_date']},(r['ts_code'],dates)
        candidate,_=next_session(r['key_ann_date'],calendar)
        own=signals.loc[signals.ts_code.eq(r['ts_code']) & signals.ann_date.eq(r['key_ann_date']) & signals.end_date.eq(r['end_date'])]
        before=earlier_signals(own,candidate)
        events.append(dict(ts_code=r['ts_code'],key_ann_date=r['key_ann_date'],end_date=r['end_date'],
            content_observation=r,announcement_id=identifier,current_index_observations=matches,
            observed_current_index_day=r['key_ann_date'],candidate_available_day=candidate,
            linked_signals=len(own),signals_before_earlier_candidate_day=len(before),
            current_title_cancelled=any('取消' in (m['title'] or '') for m in matches),
            verified_publication_day=None,selected_financial_value=None,usable_in_verified_history=False,
            remaining_gaps=['historical_release_content_identity_unverified','complete_version_sequence_unverified','cancellation_effective_day_unverified_if_cancelled']))
    for p,h in inputs.items():assert audit.sha(ROOT/p)==h,p
    for base in ['conflict_publication_identity_20261012_r1','unanchored_conflict_pages_20261012_r1']:
        directory=ROOT/'output'/base
        for p,h in read(directory/'artifact_sha256.json').items():assert audit.sha(directory/p)==h,p
    audit.write_json(OUT/'events.json',events)
    audit.write_json(OUT/'input_sha256.json',inputs)
    summary=dict(fixed_keys=3,earlier_pdf_current_index_matches=3,
        remaining_signals_before_earlier_pdf_candidate_day=sum(r['signals_before_earlier_candidate_day'] for r in events),
        earlier_pdf_current_cancelled_titles=sum(r['current_title_cancelled'] for r in events),
        direct_printed_current_content=2,conditional_audit_composition=1,historical_approvals=0,new_backtests=0,new_models=0)
    audit.write_json(OUT/'summary.json',summary)
    audit.write_json(OUT/'verification.json',dict(inputs_unchanged=True,previous_snapshots_unchanged=True,old_experiments=audit.verify_old(),all_history_gates_closed=True))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
