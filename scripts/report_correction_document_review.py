"""Archive reviewed fields and distinguish unrelated report periods.

Read-only original/corrected PDFs. No historical publication approval.
"""
import json
from pathlib import Path

import fitz

import announcement_financial_audit as audit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/financial_review_repair_20261011_r1'
# PDF page numbers are one-based. Values refer to target-year annual headline
# profit attributable to owners excluding non-recurring gains/losses, in CNY.
REVIEWED = [
    ('000595.SZ', '20151231', '1202100765', 6, '-126112165.09'),
    ('000595.SZ', '20171231', '1204948469', 6, '-39858014.53'),
    ('000851.SZ', '20151231', '1202066963', 7, '65248664.31'),
    ('000851.SZ', '20201231', '1209721344', 9, '-196380050.17'),
    ('002433.SZ', '20191231', '1207944774', 7, '35396243.53'),
    ('002433.SZ', '20201231', '1209892868', 7, '-32284723.16'),
    ('002462.SZ', '20191231', '1207657941', 6, '369705753.25'),
    ('002872.SZ', '20171231', '1205058432', 6, '222943716.06'),
    ('600084.SH', '20181231', '1206322642', 2, '-179757957.25'),
    ('600169.SH', '20191231', '1207930588', 5, '-896163058.46'),
    ('600863.SH', '20171231', '1204921943', 7, '130130518.81'),
    ('601666.SH', '20191231', '1207783141', 5, '1132715295.02'),
]


def main():
    corrections = OUT / 'corrections'
    records = json.loads((corrections / 'progress.json').read_text(encoding='utf-8'))
    assert records['access_pass_finished']
    results = []
    rendered = OUT / 'correction_table_review'
    rendered.mkdir(exist_ok=True)
    for code, period, identifier, page, value in REVIEWED:
        source = json.loads((corrections / f'{code}_{period}_{identifier}.json').read_text(encoding='utf-8'))
        doc = source['document']
        path = ROOT / doc['file'] if doc['status'] == 'existing_pdf_cache' else corrections / doc['file']
        old = json.loads((ROOT / 'output/off_checklist_revision_worklist_20261010/verification_round/results'
                          / f'{code}_{period}.json').read_text(encoding='utf-8'))
        assert value == old['val_flag0']
        with fitz.open(path) as pdf:
            target = pdf[page - 1]
            text = target.get_text()
            compact = text.replace(',', '').replace(' ', '').replace('\n', '')
            assert value in compact
            target.get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).save(rendered / f'{code}_{period}.png')
        results.append(dict(ts_code=code, end_date=period, correction_title=source['correction']['title'],
                            correction_index_day=source['correction']['day'], pdf_page=page,
                            observed_value_cny=value, matches_original_candidate_flag0=True,
                            status='target_year_field_matches_in_identified_updated_report',
                            pdf_sha256=audit.sha(path), path=str(path.relative_to(ROOT)),
                            review_method='text extraction and rendered page visual review of target-year field',
                            field='归属于上市公司股东的扣除非经常性损益的净利润（元）',
                            full_version_chain_verified=False, usable_in_verified_history=False))
    rows = json.loads((OUT / 'remaining_23_review.json').read_text(encoding='utf-8'))
    reviewed = {(r['ts_code'], r['end_date']) for r in results}
    other = []
    for r in rows:
        key = (r['ts_code'], r['end_date'])
        if not r['corrections'] or key in reviewed:
            continue
        if key == ('600169.SH', '20161231'):
            decision = 'correction_of_board_attendance_only_notice_explicitly_says_other_content_unchanged'
        else:
            decision = 'correction_title_targets_another_period_not_direct_target_annual_revision'
        other.append(dict(ts_code=key[0], end_date=key[1], corrections=r['corrections'],
                          status=decision, comparative_value_effect_unverified=True,
                          full_version_chain_verified=False, usable_in_verified_history=False))
    assert len(results) == 12 and len(other) == 8
    audit.write_json(OUT / 'corrected_report_field_review.json', dict(
        target_year_field_reviews=results, other_period_or_nonfinancial_reviews=other,
        version_history_approvals=0))
    summary = dict(corrected_report_documents=records['records'],
                   document_access_failures=sum(r['document']['status'] not in (
                       'existing_pdf_cache', 'downloaded_readable_candidate_only') for r in records['documents']),
                   initial_three_visual_cases=3, target_year_updated_values_unchanged=12,
                   board_attendance_only_notice=1, other_period_correction_keys=7,
                   complete_version_history_approvals=0)
    audit.write_json(OUT / 'correction_review_summary.json', summary)
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
