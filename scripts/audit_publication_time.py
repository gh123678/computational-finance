"""Offline candidate publication ledger; no historical-use approval or features."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
import re
from pathlib import Path

import pandas as pd

import announcement_financial_audit as audit
from collect_issuer_listing_evidence import local_day

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'output/off_checklist_revision_worklist_20261010/verification_round'
REPAIR = ROOT / 'output/financial_review_repair_20261011_r1'
CROSS = ROOT / 'output/cross_period_review_20261011_r1'
FOLLOW = ROOT / 'output/generic_notice_followup_20261011_r1'
OUT = ROOT / 'output/publication_time_audit_20261011_r1'


def date_value(value):
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError('invalid date')
    return datetime.strptime(value, '%Y%m%d').date()


def calendar_map(frame):
    """Validate every calendar day, not merely a sorted list of open sessions."""
    days = {}
    for row in frame.to_dict('records'):
        day = date_value(str(row['cal_date']))
        if str(row['is_open']) not in ('0', '1'):
            raise ValueError('invalid open flag')
        opened = int(row['is_open'])
        if day in days and days[day] != opened:
            raise ValueError('conflicting calendar day')
        days[day] = opened
    if not days:
        raise ValueError('empty calendar')
    if len(days) != (max(days) - min(days)).days + 1:
        raise ValueError('calendar gap')
    return days


def next_session(day, calendar):
    try:
        current = date_value(day)
    except ValueError:
        return None, 'invalid_publication_day'
    if current not in calendar:
        return None, 'publication_day_outside_calendar'
    while True:
        current += timedelta(days=1)
        if current not in calendar:
            return None, 'next_session_not_covered'
        if calendar[current]:
            return current.strftime('%Y%m%d'), 'candidate_next_session_only'


def visible_candidate_events(events, asof):
    """Diagnostic exposure only; preserve multiple versions, never pick a value."""
    date_value(asof)
    return [e for e in events if e['candidate_available_day'] is not None
        and e['candidate_available_day'] <= asof]


def current_index_items(response):
    if not isinstance(response, dict) or not isinstance(response.get('announcements'), list):
        raise ValueError('not an announcement list response')
    if not all(isinstance(item, dict) for item in response['announcements']):
        raise ValueError('invalid announcement item')
    return response['announcements']


def read_record(path, inputs):
    inputs[str(path.relative_to(ROOT))] = audit.sha(path)
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    OUT.mkdir(exist_ok=True)
    inputs = {}
    calendar_file = ROOT / 'data/continuous_2016_2025_dividend_r1/calendar.csv'
    inputs[str(calendar_file.relative_to(ROOT))] = audit.sha(calendar_file)
    calendar = calendar_map(pd.read_csv(calendar_file, dtype={'cal_date': str}))
    observations = []
    cases = {}

    def add(code, period, day, title, document, base, source, scope):
        file = document.get('file')
        path = (ROOT if document.get('status') == 'existing_pdf_cache' else base) / file if file else None
        identifier = Path(file).stem.rsplit('_', 1)[-1] if file else None
        digest = audit.sha(path) if path and path.is_file() else None
        if document.get('sha256') and digest and document['sha256'] != digest:
            raise ValueError('PDF hash changed: ' + str(path))
        if path and digest:
            inputs[str(path.relative_to(ROOT))] = digest
        observations.append(dict(ts_code=code, target_review_period=period,
            announcement_id=identifier, reported_index_day=day, title=title,
            pdf=str(path.relative_to(ROOT)) if path else None, pdf_sha256=digest,
            source_metadata=str(source.relative_to(ROOT)),
            collection_status=document.get('status'), scope=scope))

    for path in sorted((OLD / 'results').glob('*.json')):
        rec = read_record(path, inputs)
        cases[(rec['ts_code'], rec['end_date'])] = rec
        for doc in rec['documents']:
            add(rec['ts_code'], rec['end_date'], doc.get('index_day'), doc['title'],
                doc, OLD, path, 'original_candidate_not_field_or_timing_approval')
    for path in sorted((REPAIR / 'corrections').glob('*_12*.json')):
        rec = read_record(path, inputs)
        n = rec['correction']
        add(rec['ts_code'], rec['end_date'], n['day'], n['title'], rec['document'],
            REPAIR / 'corrections', path, 'correction_may_concern_another_period_or_field')
    for path in sorted(FOLLOW.glob('*_12*.json')):
        rec = read_record(path, inputs)
        n = rec['notice']
        add(rec['ts_code'], rec['end_date'], n['day'], n['title'], rec['document'],
            FOLLOW, path, 'notice_content_adjudicated_separately')
    for code in ['000851.SZ', '002097.SZ', '600343.SH', '600804.SH']:
        path = CROSS / f'{code}_generic_notice.json'
        rec = read_record(path, inputs)
        add(code, rec['end_date'], rec['index_day'], rec['document']['title'],
            rec['document'], CROSS, path, 'notice_content_adjudicated_separately')
    for code, period, day, filename in [
        ('000851.SZ', '20181231', '20190507', '000851.SZ_notice.json'),
        ('603559.SH', '20201231', '20210507', '603559.SH_notice.json'),
        ('600594.SH', '20181231', '20190430', '600594.SH_original_quarter.json')]:
        path = CROSS / filename
        doc = read_record(path, inputs)
        add(code, period, day, doc['title'], doc, CROSS, path, 'related_period_notice_not_target_period_assignment')
    # Current official index identity is separate from historical publication proof.
    index = defaultdict(list)
    cache_failures = []
    dirs = [OLD / 'responses', ROOT / 'output/announcement_financial_audit_20261007/issuer_listing_evidence_20261009/responses']
    for base in dirs:
        for path in sorted(base.glob('*.json')):
            # orgId/topSearch caches are not announcement-list endpoints.
            if not re.search(r'_(issuer|post)_\d+\.json$', path.name):
                continue
            try:
                rec = read_record(path, inputs)
                items = current_index_items(rec)
            except (ValueError, UnicodeError) as exc:
                cache_failures.append(dict(path=str(path.relative_to(ROOT)), error=type(exc).__name__))
                continue
            for item in items:
                identifier = str(item.get('announcementId') or Path(item.get('adjunctUrl', '')).stem)
                index[(str(item.get('secCode')), identifier)].append(dict(
                    current_index_day=local_day(item), source=str(path.relative_to(ROOT)),
                    adjunct_url=item.get('adjunctUrl'), title=item.get('announcementTitle')))
    groups = defaultdict(list)
    for observation in observations:
        groups[(observation['ts_code'], observation['target_review_period'], observation['announcement_id'])].append(observation)
    events = []
    for (code, period, identifier), refs in sorted(groups.items()):
        days = {r['reported_index_day'] for r in refs}
        digests = {r['pdf_sha256'] for r in refs if r['pdf_sha256']}
        matches = index[(code[:6], identifier)]
        indexed_days = {r['current_index_day'] for r in matches}
        blockers = ['historical_release_content_identity_unverified', 'complete_version_chain_unverified']
        if len(days) != 1 or len(digests) > 1:
            state, day = 'candidate_metadata_or_content_conflict', None
            blockers.append(state)
        else:
            day = next(iter(days))
            state = ('current_index_identity_date_matches' if matches and indexed_days == {day}
                else 'current_index_date_conflict' if matches else 'current_index_identity_not_matched')
            if state != 'current_index_identity_date_matches':
                blockers.append(state)
        available, time_state = next_session(day, calendar)
        if not digests:
            blockers.append('pdf_missing')
            available = None
        if state != 'current_index_identity_date_matches':
            available = None
        if time_state != 'candidate_next_session_only':
            blockers.append(time_state)
        cancelled = any('取消' in r['title'] for r in refs)
        if cancelled:
            blockers.append('cancellation_effective_day_unverified')
        vendor_day = cases[(code, period)]['ann_date']
        events.append(dict(ts_code=code, target_review_period=period, announcement_id=identifier,
            vendor_ann_date=vendor_day, observed_current_index_day=day,
            candidate_available_day=available, date_status=time_state, identity_status=state,
            vendor_day_differs_from_document_day=vendor_day != day,
            current_title_cancelled=cancelled, cancellation_effective_day=None,
            source_observations=refs, current_index_evidence=matches, blockers=blockers,
            selected_financial_value=None, verified_publication_day=None,
            usable_in_verified_history=False))
    summaries = []
    for key, rec in sorted(cases.items()):
        own = [e for e in events if (e['ts_code'], e['target_review_period']) == key]
        summaries.append(dict(ts_code=key[0], target_review_period=key[1],
            vendor_ann_date=rec['ann_date'], event_count=len(own),
            matched_current_index_events=sum(e['identity_status'] == 'current_index_identity_date_matches' for e in own),
            candidate_days=sorted({e['candidate_available_day'] for e in own if e['candidate_available_day']}),
            historical_release_status='unverified', complete_version_chain_status='unverified',
            usable_in_verified_history=False))
    # Real revision boundaries exercise the same function as synthetic tests.
    checks = []
    for code, identifier in [('600343.SH', '1207708429'), ('000851.SZ', '1209721345'), ('603559.SH', '1209935419')]:
        event = next(e for e in events if e['ts_code'] == code and e['announcement_id'] == identifier)
        assert event['candidate_available_day'] > event['observed_current_index_day']
        assert event not in visible_candidate_events([event], event['observed_current_index_day'])
        assert event in visible_candidate_events([event], event['candidate_available_day'])
        checks.append(dict(ts_code=code, announcement_id=identifier,
            publication_candidate=event['observed_current_index_day'],
            candidate_available_day=event['candidate_available_day'], same_day_excluded=True,
            historical_approval=False))
    frozen = audit.verify_old()
    old_manifest = read_record(REPAIR / 'input_sha256.json', inputs)
    assert all(audit.sha(ROOT / p) == h for p, h in old_manifest.items())
    for base in [CROSS, FOLLOW]:
        for path in base.rglob('*'):
            if path.is_file():
                inputs[str(path.relative_to(ROOT))] = audit.sha(path)
    assert all(audit.sha(ROOT / p) == h for p, h in inputs.items())
    audit.write_json(OUT / 'events.json', events)
    audit.write_json(OUT / 'per_key_timing_gaps.json', summaries)
    audit.write_json(OUT / 'real_revision_boundary_checks.json', checks)
    missing = [dict(ts_code=e['ts_code'], target_review_period=e['target_review_period'],
        announcement_id=e['announcement_id'], current_index_day=e['observed_current_index_day'],
        title=e['source_observations'][0]['title'],
        indexed_urls=sorted({r['adjunct_url'] for r in e['current_index_evidence'] if r['adjunct_url']}),
        old_collection_statuses=sorted({r['collection_status'] for r in e['source_observations']}),
        source_metadata=sorted({r['source_metadata'] for r in e['source_observations']}),
        usable_in_verified_history=False) for e in events if 'pdf_missing' in e['blockers']]
    audit.write_json(OUT / 'missing_pdf_queue.json', missing)
    audit.write_json(OUT / 'input_sha256.json', inputs)
    result = dict(keys=len(cases), source_observations=len(observations), document_events=len(events),
        calendar_start=min(calendar).strftime('%Y%m%d'), calendar_end=max(calendar).strftime('%Y%m%d'),
        identity_status_counts=dict(Counter(e['identity_status'] for e in events)),
        candidate_next_session_events=sum(e['candidate_available_day'] is not None for e in events),
        document_day_differs_from_vendor_events=sum(e['vendor_day_differs_from_document_day'] for e in events),
        cancelled_title_events=sum(e['current_title_cancelled'] for e in events),
        missing_pdf_events=sum('pdf_missing' in e['blockers'] for e in events),
        keys_with_missing_pdf_events=len({(e['ts_code'], e['target_review_period'])
            for e in events if 'pdf_missing' in e['blockers']}),
        keys_without_any_candidate_date=sum(not r['candidate_days'] for r in summaries),
        missing_pdf_collection_status_counts=dict(Counter(r['collection_status']
            for e in events if 'pdf_missing' in e['blockers'] for r in e['source_observations'])),
        current_cache_read_failures=cache_failures, approved_historical_events=0,
        old_audit_artifacts_preserved=len(old_manifest), preserved_experiment_files=frozen,
        inputs_checked=len(inputs), new_features=0, new_models=0, new_backtests=0)
    audit.write_json(OUT / 'verification.json', result)
    text = f'''# 公开时点候选账本（2026-10-11）

审计{len(cases)}键、{len(observations)}条源引用，去重为{len(events)}个逐文档事件；只读现有PDF、官方列表缓存及完整日历。当前索引身份/日期匹配不代表已证实历史首次公开和内容身份。完整历史批准仍0，所有事件均未选择财务值、verified_publication_day为空。

当前索引身份核对：{json.dumps(result['identity_status_counts'], ensure_ascii=False)}。{result['candidate_next_session_events']}个事件得到候选首交易日；{result['document_day_differs_from_vendor_events']}个事件的自身索引日与数据商ann_date不同（含已知更正和关联其他报告期，不等于同数量错误）；{result['cancelled_title_events']}个事件当前标题含取消，历史取消生效日未知。

候选PDF仍缺{result['missing_pdf_events']}个事件，涉及{result['keys_with_missing_pdf_events']}键；旧采集状态分布{json.dumps(result['missing_pdf_collection_status_counts'], ensure_ascii=False)}。这些事件虽能配对当前索引，仍没有可读原文，候选可用日为空。逐键处理完成不等于所有候选附件下载成功；替代年报证据不补足这些文件。

真实更正边界：
'''
    for check in checks:
        text += f"\n- {check['ts_code']} {check['announcement_id']}：当前索引{check['publication_candidate']} → 候选首交易日{check['candidate_available_day']}，公告当天不可见。"
    text += '\n\n每键缺口见per_key_timing_gaps.json；逐文档源引用、PDF哈希、索引缓存和阻断原因见events.json；旧下载失败63文档的官方链接与元数据列于missing_pdf_queue.json。同一目标核验期可能关联其他期的更正，账本不把它当成该年度字段的新版本。标题已取消不倒推取消日期；同日多版保留全部，不自动挑选。\n\n只有候选日期排序获得验证：不能证明原版最早公开，也不能证明60日后没有更正。后续报告覆盖未核验前，不能把旧利润无限延续。下一步针对历史身份与公开证据缺口补证，再讨论字段可用批准及面板。旧170审计产物与960实验文件指纹一致；没有特征消费、训练或回测。\n'
    (OUT / 'report.md').write_text(text, encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
