"""Supplement fixed scan evidence using conservative printed-page offsets."""
from collections import Counter
from pathlib import Path
import json
import math
import os
import re
import shutil

import fitz
import announcement_financial_audit as audit
import recover_large_publication_pdfs as recovery
import ocr_recovered_financial_candidates as scan

ROOT = scan.ROOT
OLD = ROOT / 'output/publication_scan_evidence_20261011_r1'
OUT = ROOT / 'output/publication_scan_locations_20261012_r2'
MAX_ADDITIONAL = 6


def printed_footer(record, height):
    """Accept a solitary page number or explicit Chinese page footer only."""
    candidates = []
    for row in record.get('rows', []):
        if row['center_y'] < height * .93:
            continue
        for cell in row['cells']:
            try:
                confidence = float(cell.get('confidence', 0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(confidence) or confidence < .8:
                continue
            text = cell['text'].strip()
            match = re.fullmatch(r'(\d{1,3})', text)
            if not match:
                match = re.fullmatch(r'第?\s*(\d{1,3})\s*页\s*[，,]?\s*(?:共\s*\d{1,3}\s*页)?', text)
            if match and int(match[1]) > 0:
                candidates.append(int(match[1]))
    values = set(candidates)
    return next(iter(values)) if len(values) == 1 else None


def infer_offset(records, heights):
    votes = []
    for record in records:
        if record.get('page', 0) <= 2:
            continue  # Covers/TOCs/audit preambles may use another numbering.
        printed = printed_footer(record, heights[record['page']])
        if printed is not None:
            votes.append(dict(pdf_page=record['page'], printed_page=printed,
                              offset=record['page'] - printed))
    counts = Counter(v['offset'] for v in votes)
    supported = [offset for offset, count in counts.items() if count >= 2]
    if len(supported) != 1 or any(offset != supported[0] for offset in counts):
        return dict(state='offset_unknown_or_conflicting', offset=None, votes=votes)
    return dict(state='consistent_footer_offset_candidate', offset=supported[0], votes=votes)


def printed_targets(rows, count):
    profit, end = [], None
    for row in rows:
        text = row['text']
        if '附注' in text:
            match = re.search(r'(?<!\d)(\d{1,3})\s*[-—－~～]\s*(\d{1,3})\s*页?(?!\d)', text)
            if match and 1 <= int(match[1]) <= int(match[2]) <= count:
                end = int(match[2])
        if re.search(r'合并.*利润表', text):
            for cell in row['cells']:
                match = re.fullmatch(r'\s*(\d{1,3})\s*页?\s*', cell['text'])
                if match and 1 <= int(match[1]) <= count:
                    profit.append(int(match[1]))
    return dict(profit=sorted(set(profit)), notes_end=end)


def planned_pages(targets, offset, count, existing):
    if offset is None:
        return []
    printed = [n for p in targets['profit'] for n in (p, p+1)]
    if targets['notes_end']:
        printed += [targets['notes_end']-1, targets['notes_end'], targets['notes_end']+1]
    return list(dict.fromkeys(p+offset for p in printed
        if 1 <= p+offset <= count and p+offset not in existing))[:MAX_ADDITIONAL]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ['pages', 'images', 'results', 'source_snapshot']:
        (OUT/name).mkdir(exist_ok=True)
    frozen = recovery.read(OLD/'artifact_sha256.json')
    for path, digest in frozen.items():
        assert audit.sha(OLD/path) == digest, 'Old OCR artifact changed: '+path
    recovery.verify(recovery.read(OLD/'input_sha256.json'))
    protocol = dict(source_sha256=audit.sha(Path(__file__)),
        old_manifest_sha256=audit.sha(OLD/'artifact_sha256.json'),
        max_additional_pages=MAX_ADDITIONAL, min_offset_votes=2,
        conflicting_votes_rejected=True, engine_sha256=recovery.read(OLD/'protocol.json')['engine_sha256'],
        financial_field_verified=False, historical_approvals=0)
    if (OUT/'protocol.json').exists():
        assert recovery.read(OUT/'protocol.json') == protocol
    else:
        audit.write_json(OUT/'protocol.json', protocol)
        shutil.copy2(__file__, OUT/'source_snapshot'/Path(__file__).name)
    lock = OUT/'refine.lock'
    fd=os.open(lock, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    records=[]
    scan.OUT=OUT  # New evidence only; old caches remain immutable inputs.
    try:
        engine=scan.engine()
        for source in sorted((OLD/'results').glob('*.json')):
            item=recovery.read(source);target=OUT/'results'/source.name
            if target.exists():
                result=recovery.read(target)
            else:
                try:
                    with fitz.open(ROOT/item['pdf']) as pdf:
                        cached=[recovery.read(p) for p in sorted((OLD/'pages').glob(source.stem+'_p*.json'))]
                        heights={p['page']:pdf[p['page']-1].rect.height*scan.ZOOM for p in cached}
                        offset=infer_offset(cached,heights)
                        front=[r for p in cached if p['page'] <= 2 for r in p.get('rows',[])]
                        targets=printed_targets(front,len(pdf))
                        extra=planned_pages(targets,offset['offset'],len(pdf),{p['page'] for p in cached})
                        pages=[scan.read_page(engine,pdf,item,n) for n in extra]
                        result=scan.evidence_record(item,status='supplemental_pages_only' if pages else 'no_safe_new_pages',
                            offset_evidence=offset,printed_targets=targets,extra_pages=extra,
                            extra_page_records=[str(Path('pages')/(source.stem+f"_p{p['page']}.json")) for p in pages],
                            supplemental_candidate_rows=sum(len(p['candidates']) for p in pages),
                            unresolved_reason=None if pages else 'offset_unknown_or_targets_already_covered_or_absent')
                except Exception as exc:
                    result=scan.evidence_record(item,status='supplement_failed',error_type=type(exc).__name__,error=str(exc))
                audit.write_json(target,result)
            records.append(result)
            status=dict(state='running',pid=os.getpid(),processed=len(records),total=63,
                statuses=dict(Counter(r['status'] for r in records)),
                extra_pages=sum(len(r.get('extra_pages',[])) for r in records),historical_approvals=0)
            audit.write_json(OUT/'status.json',status)
            print(source.stem,result['status'],result.get('extra_pages',[]),flush=True)
        assert len(records)==63
        for path,digest in frozen.items():assert audit.sha(OLD/path)==digest
        recovery.verify(recovery.read(OLD/'input_sha256.json'))
        assert audit.sha(Path(__file__))==protocol['source_sha256']
        assert all(audit.sha(ROOT/p)==h for p,h in protocol['engine_sha256'].items())
        audit.write_json(OUT/'verification.json',dict(old_ocr_artifacts=len(frozen),old_inputs=1502,
            old_experiments=audit.verify_old(),source_unchanged=True,engine_unchanged=True,historical_approvals=0))
        status['state']='completed';audit.write_json(OUT/'status.json',status)
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    main()
