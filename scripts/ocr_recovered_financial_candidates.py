"""Bounded page-location evidence, never an automatic financial adjudication."""
from collections import Counter
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import time

import fitz
import numpy as np
import announcement_financial_audit as audit
import recover_large_publication_pdfs as recovery

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / 'output/publication_pdf_recovery_20261011_r3'
OUT = ROOT / 'output/publication_scan_evidence_20261011_r1'
MAX_PAGES = 12
ZOOM = 2.5
MAX_STORAGE = 2*1024**3
LABEL = re.compile('非经常|归属.*净利润|合并利润表|金额单位|单位[：:]')
CREDENTIAL = re.compile('身份证号码|身份证号|CERTIFIED|执业证书|营业执照|证券.*许可证|年度检验登记', re.I)
FINANCIAL = re.compile('财务报表附注|合并利润表|合并资产负债表|非经常性损益|净利润|主要会计数据')
NUM = re.compile(r'-?\d[\d,.]*')


def grouped_rows(boxes):
    rows = []
    for box, text, score in sorted(boxes, key=lambda b: sum(p[1] for p in b[0])/len(b[0])):
        center = sum(p[1] for p in box)/len(box)
        height = max(p[1] for p in box)-min(p[1] for p in box)
        if rows and abs(center-rows[-1]['center_y']) <= max(10, height*.45):
            row = rows[-1]
        else:
            row = dict(center_y=center, cells=[])
            rows.append(row)
        row['cells'].append(dict(box=box, text=text, confidence=score))
    for row in rows:
        row['cells'].sort(key=lambda c: min(p[0] for p in c['box']))
        row['text'] = ' | '.join(c['text'] for c in row['cells'])
    return rows


def credential_only(text):
    return bool(CREDENTIAL.search(text) and not FINANCIAL.search(text))


def toc_end(rows, page_count):
    for row in rows:
        if '附注' not in row['text']:
            continue
        match = re.search(r'(?<!\d)(\d{1,3})\s*[-—－~～]\s*(\d{1,3})(?!\d)', row['text'])
        if match and 1 <= int(match[1]) <= int(match[2]) <= page_count:
            return int(match[2])
    return None


def select_extra_pages(rows, page_count, native_hits=()):
    """One-based candidates: printed page offsets are uncertain and preserved."""
    end = toc_end(rows, page_count)
    tail = list(range(end-2, end+3)) if end else list(range(page_count-9, page_count-4))
    profit = []
    for row in rows:
        if '合并利润表' in row['text']:
            for cell in row['cells']:
                if re.fullmatch(r'\d{1,3}', cell['text'].strip()):
                    printed = int(cell['text'])
                    if 1 <= printed <= page_count:
                        profit = list(range(printed, printed+3))
                        break
    if not profit:
        profit = [8, 9, 10, 11]
    ordered = list(dict.fromkeys(tail + profit + list(native_hits)))
    return [p for p in ordered if 1 <= p <= page_count and p not in (1, 2)][:MAX_PAGES-2]


def candidate_context(rows):
    page_text = '\n'.join(r['text'] for r in rows)
    ratio = bool(re.search('每股收益|净资产收益率', page_text))
    found = []
    for row in rows:
        text = row['text']
        if not LABEL.search(text) and not ('非经常' in page_text and re.search('合计|所得税|少数股东', text)):
            continue
        role = 'financial_label_context_unverified'
        if '扣除非经常' in text or '扣除非经常损益' in text:
            role = 'dedt_label_in_ratio_context' if ratio else 'dedt_label_amount_not_selected'
        elif '归属' in text and '净利润' in text:
            role = 'parent_net_profit_not_dedt'
        found.append(dict(text=text, cells=row['cells'], role=role,
            numeric_tokens=NUM.findall(text), selected_financial_value=None,
            financial_field_verified=False, usable_in_verified_history=False))
    return found


def evidence_record(item, **details):
    """Keep input access state separate from this OCR pass's state."""
    record = {**item, 'source_access_status': item['status'], **details}
    record.update(selected_financial_value=None, verified_publication_day=None,
        financial_field_verified=False, usable_in_verified_history=False)
    return record


def engine():
    import rapidocr_onnxruntime.utils as utils
    from rapidocr_onnxruntime import RapidOCR
    original_options = utils.SessionOptions
    def options():
        value = original_options()
        value.intra_op_num_threads=2
        value.inter_op_num_threads=1
        return value
    utils.SessionOptions = options
    return RapidOCR()


def read_page(ocr, pdf, item, number):
    stem = f"{item['ts_code']}_{item['target_review_period']}_{item['announcement_id']}_p{number}"
    path = OUT / 'pages' / f'{stem}.json'
    if path.exists():
        result = recovery.read(path)
        assert result['pdf_sha256'] == item['pdf_sha256'] and result['page'] == number
        if result.get('image'):
            assert audit.sha(OUT / result['image']) == result['image_sha256']
        return result
    if shutil.disk_usage(OUT).free < 6*1024**3:
        raise RuntimeError('OCR free-space floor reached')
    if sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file()) >= MAX_STORAGE:
        raise RuntimeError('OCR storage budget reached')
    started = time.monotonic()
    page = pdf[number-1]
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
    array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    boxes, elapsed = ocr(array)
    rows = grouped_rows(boxes or [])
    text = '\n'.join(r['text'] for r in rows)
    record = dict(pdf=item['pdf'], pdf_sha256=item['pdf_sha256'], page=number,
        at=audit.now(), render_zoom=ZOOM, seconds=time.monotonic()-started,
        selected_financial_value=None, financial_field_verified=False, usable_in_verified_history=False)
    if credential_only(text):
        record.update(status='nonfinancial_credentials_excluded', rows=[], candidates=[])
    else:
        image = OUT / 'images' / f'{stem}.png'
        pix.save(image)
        record.update(status='ocr_page_evidence_only', rows=rows, candidates=candidate_context(rows),
            image=str(image.relative_to(OUT)), image_sha256=audit.sha(image),
            recognized_box_count=len(boxes or []), has_eps_or_roe_context=bool(re.search('每股收益|净资产收益率', text)))
    audit.write_json(path, record)
    return record


def summarize(records, total, finished=False):
    result = dict(at=audit.now(), pid=os.getpid(), state='completed' if finished else 'running',
        total_documents=total, processed_documents=len(records),
        status_counts=dict(Counter(r['status'] for r in records)),
        recognized_pages=sum(len(r.get('pages', [])) for r in records),
        candidate_rows=sum(r.get('candidate_rows', 0) for r in records),
        financial_field_adjudications=0, historical_approvals=0,
        new_features=0, new_models=0, new_backtests=0)
    audit.write_json(OUT / 'status.json', result)
    return result


def main():
    for name in ['pages', 'images', 'results', 'source_snapshot']:
        (OUT / name).mkdir(parents=True, exist_ok=True)
    items = recovery.read(PREVIOUS / 'document_access_coverage.json')
    assert len(items) == 63
    manifest = OUT / 'input_sha256.json'
    if not manifest.exists():
        inputs = recovery.read(PREVIOUS / 'input_sha256.json')
        inputs.update({str(p.relative_to(ROOT)): audit.sha(p) for p in PREVIOUS.rglob('*') if p.is_file()})
        audit.write_json(manifest, inputs)
    inputs = recovery.read(manifest)
    recovery.verify(inputs)
    for item in items:
        assert audit.sha(ROOT / item['pdf']) == item['pdf_sha256']
    import rapidocr_onnxruntime as rapid
    package = Path(rapid.__file__).parent
    models = [package/'config.yaml', package/'utils.py', package/'rapid_ocr_api.py', *sorted((package/'models').glob('*.onnx'))]
    protocol = dict(queue_sha256=audit.sha(PREVIOUS / 'document_access_coverage.json'),
        source_sha256=audit.sha(Path(__file__)), max_pages_per_document=MAX_PAGES, render_zoom=ZOOM,
        engine_sha256={str(p.relative_to(ROOT)):audit.sha(p) for p in models},
        package_versions={name:importlib.metadata.version(name) for name in ['rapidocr-onnxruntime','onnxruntime','PyMuPDF']},
        cpu_threads=2, cpu_inter_threads=1, max_storage_bytes=MAX_STORAGE,
        resolved_output_directory=str(OUT.resolve()), historical_approvals=0)
    saved = OUT / 'protocol.json'
    if saved.exists():
        assert recovery.read(saved) == protocol, 'Frozen OCR protocol changed'
    else:
        audit.write_json(saved, protocol)
        shutil.copy2(__file__, OUT / 'source_snapshot' / Path(__file__).name)
    lock = OUT / 'ocr.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode());os.close(fd)
    records=[]
    try:
        ocr = engine()
        for item in items:
            stem = f"{item['ts_code']}_{item['target_review_period']}_{item['announcement_id']}"
            target = OUT / 'results' / f'{stem}.json'
            if target.exists():
                record = recovery.read(target)
            else:
                try:
                    with fitz.open(ROOT / item['pdf']) as pdf:
                        front = [read_page(ocr, pdf, item, n) for n in range(1, min(2, len(pdf))+1)]
                        rows = [r for p in front for r in p['rows']]
                        native_hits = [i+1 for i in range(len(pdf)) if re.search('扣除非经常|非经常性损益',pdf[i].get_text())]
                        extra = select_extra_pages(rows, len(pdf), native_hits)
                        pages = front + [read_page(ocr,pdf,item,n) for n in extra]
                        assert len(pages) <= MAX_PAGES
                        record=evidence_record(item, status='bounded_ocr_pass_only',
                            pages=[dict(page=p['page'], status=p['status'],
                                page_record=f"pages/{stem}_p{p['page']}.json") for p in pages],
                            candidate_rows=sum(len(p['candidates']) for p in pages),
                            unprocessed_pages=len(pdf)-len(pages),
                            selected_financial_value=None, verified_publication_day=None,
                            historical_release_status='unverified')
                except Exception as exc:
                    record=evidence_record(item, status='document_ocr_failed', error_type=type(exc).__name__, error=str(exc),
                        selected_financial_value=None, verified_publication_day=None)
                audit.write_json(target, record)
            records.append(record)
            summarize(records,len(items))
            print(stem,record['status'],len(record.get('pages',[])),record.get('candidate_rows',0),flush=True)
        recovery.verify(inputs)
        assert all(audit.sha(ROOT/p)==h for p,h in protocol['engine_sha256'].items())
        assert audit.sha(Path(__file__)) == protocol['source_sha256']
        audit.write_json(OUT/'verification.json',dict(frozen_input_files_checked=len(inputs),
            preserved_experiment_files=audit.verify_old(), financial_field_adjudications=0,
            historical_approvals=0, source_unchanged=True, engine_unchanged=True))
        print(json.dumps(summarize(records,len(items),finished=True),ensure_ascii=False),flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
