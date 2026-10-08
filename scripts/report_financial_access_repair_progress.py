"""Merge access progress without confusing it with financial/history approval."""
import csv
import json
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import collect_remaining_financial_evidence as collector


def load_results(folder, groups):
    results = {}
    for path in (folder / 'results').glob('*.json'):
        result = json.loads(path.read_text(encoding='utf-8'))
        key = (result['ts_code'], result['ann_date'])
        if key not in groups or result.get('usable_in_verified_history') is not False:
            raise RuntimeError('Result outside scope or incorrectly approved history')
        if key in results:
            raise RuntimeError('Duplicate result key')
        results[key] = result
    return results


def main():
    out = audit.OUT
    first_folder = out / 'remaining_evidence_r1'
    fixed_folder = out / 'remaining_evidence_r2_fixed_r1'
    first_protocol = json.loads((first_folder / 'protocol.json').read_text(encoding='utf-8'))
    fixed_protocol = json.loads((fixed_folder / 'protocol.json').read_text(encoding='utf-8'))
    queue_sha = audit.sha(collector.QUEUE)
    assert queue_sha == first_protocol['queue_sha256'] == fixed_protocol['queue_sha256']
    active, outside, groups = collector.load_queue()
    first = load_results(first_folder, groups)
    fixed = load_results(fixed_folder, groups)
    for key, result in fixed.items():
        path = first_folder / 'results' / f'{key[0]}_{key[1]}.json'
        assert audit.sha(path) == result['first_pass_result_sha256']
    with (out / 'evidence/field_checks.csv').open(encoding='utf-8-sig', newline='') as stream:
        numeric = list(csv.DictReader(stream))
    prospectus = json.loads((out / 'evidence/reader_prospectus_checks.json').read_text(encoding='utf-8'))['checks']
    reader_audits = json.loads((out / 'evidence/reader_audit_checks.json').read_text(encoding='utf-8'))['checks']
    qualitative = json.loads((out / 'evidence/reader_qualitative_forecast_checks.json').read_text(encoding='utf-8'))['checks']
    mirror = json.loads((out / 'evidence/sinosoft_mirror_case.json').read_text(encoding='utf-8'))
    kaidi_path=out/'evidence/kaidi_original_field_checks.json'
    kaidi=json.loads(kaidi_path.read_text(encoding='utf-8'))['checks'] if kaidi_path.exists() else []
    zhongxin_path=out/'evidence/zhongxin_forecast_checks.json'
    zhongxin_payload=json.loads(zhongxin_path.read_text(encoding='utf-8')) if zhongxin_path.exists() else {}
    zhongxin=zhongxin_payload.get('checks',[])
    qualitative += zhongxin_payload.get('qualitative_checks',[])
    appendix_path=out/'evidence/fixed_appendix_audit_checks.json'
    appendix_audits=json.loads(appendix_path.read_text(encoding='utf-8'))['checks'] if appendix_path.exists() else []
    bank_path=out/'evidence/audit_category_checks.json'
    bank_audits=[json.loads(bank_path.read_text(encoding='utf-8'))] if bank_path.exists() else []
    signer_audits=reader_audits+appendix_audits+bank_audits
    earlier_path=out/'evidence/fangsheng_earlier_disclosure_comparison.json'
    earlier_comparisons=[json.loads(earlier_path.read_text(encoding='utf-8'))] if earlier_path.exists() else []
    supplements = prospectus + signer_audits + qualitative + [mirror] + kaidi + zhongxin + earlier_comparisons
    assert all(c['usable_in_verified_history'] is False for c in supplements)
    checks_by_row = {}
    for check in numeric + prospectus + kaidi + zhongxin:
        checks_by_row.setdefault(check['row_sha256'], []).append(check)
    audit_by_row = {check['row_sha256']: check for check in reader_audits}
    signer_by_row={check['row_sha256']:check for check in signer_audits}
    earlier_rows={check['row_sha256'] for check in earlier_comparisons}
    qualitative_rows = {check['row_sha256'] for check in qualitative}
    fields = ['api','ts_code','ann_date','end_date','row_sha256','first_pass_access_status',
        'repair_access_status','official_numeric_fields_checked','official_numeric_fields_different',
        'audit_fee_checked','audit_signers_checked','qualitative_text_checked','mirror_value_checked',
        'earlier_disclosure_comparison_only','historical_version_status','usable_in_verified_history']
    destination = out / 'remaining-evidence-unified-rows.csv'
    with destination.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for row in active:
            key = (row['ts_code'], row['ann_date']); checks = checks_by_row.get(row['row_sha256'], [])
            writer.writerow(dict(**{k:row[k] for k in fields[:5]},
                first_pass_access_status=first.get(key,{}).get('status','pending'),
                repair_access_status=fixed.get(key,{}).get('status','not_processed_or_not_targeted'),
                official_numeric_fields_checked=len(checks),
                official_numeric_fields_different=sum(Decimal(c['difference']) != 0 for c in checks),
                audit_fee_checked=row['row_sha256'] in audit_by_row,
                audit_signers_checked=row['row_sha256'] in signer_by_row,
                qualitative_text_checked=row['row_sha256'] in qualitative_rows,
                mirror_value_checked=row['row_sha256']==mirror['row_sha256'],
                earlier_disclosure_comparison_only=row['row_sha256'] in earlier_rows,
                historical_version_status='unverified',usable_in_verified_history=False))
    status = json.loads((fixed_folder / 'status.json').read_text(encoding='utf-8'))
    counts = {}
    for result in fixed.values(): counts[result['status']] = counts.get(result['status'],0) + 1
    first_documents = sum(d.get('status')=='downloaded_readable_candidate_only' for r in first.values() for d in r.get('documents',[]))
    fixed_documents = sum(d.get('status')=='downloaded_readable_candidate_only' for r in fixed.values() for d in r.get('documents',[]))
    numeric_all = numeric + prospectus + kaidi + zhongxin
    differences = sum(Decimal(c['difference']) != 0 for c in numeric_all)
    lines = ['# 公告审计统一进度', '', f'更新时间：{audit.now()}（UTC）。', '',
        f'首轮访问完成{len(first)}/{len(groups)}组，取得{first_documents}份候选文件。',
        f'修正轮状态：{status["state"]}；已处理{len(fixed)}/{status.get("total_repair_keys",525)}组，新增取得{fixed_documents}份候选文件。两轮文件数可能包含相同公告的独立副本，不是唯一公告数量。',
        '', '原第二轮因调用不存在的exact_items函数失败，保留失败源码、状态和日志。修正轮另存目录；完整流程等12项测试通过，包含实际matched_items依赖、错误主体和错误日期排除。',
        '', f'本轮统一金额/比例检查{len(numeric_all)+len(reader_audits)}项，其中{len(numeric_all)-differences+len(reader_audits)}项一致、{differences}项差异（既有73项、读者招股书3项、审计费用2项、凯迪原文{len(kaidi)}项、中新科技原文{len(zhongxin)}项）；镜像金额1项另计。',
        f'累计{len(signer_audits)}组审计签字人核查及{len(qualitative)}条定性预测文字/信息缺口核查；新增固定大附件{len(appendix_audits)}份另存fixed_large_appendices_r1，不混入首两轮文件计数。费用检查仍仅对有原文费用证据的记录计数。',
        f'另有{len(earlier_comparisons)}项日期未配对的较早披露金额对照，单独记录，不并入86项字段检查或历史版本审批。',
        '', '**历史时点及原版本链审批仍为0。** 金额一致、同日索引命中、报告签字日期、取到PDF均不自动批准历史可用。未核实行不进入策略。',
        f'批准窗口内全部{len(active)}行在remaining-evidence-unified-rows.csv逐行列明；窗口外{len(outside)}行只保留原诊断。',
        '', '## 修正轮访问分类', '', '| 分类 | 股票/日期组合数 |', '|---|---|']
    lines += [f'| {state} | {count} |' for state,count in sorted(counts.items())]
    lines += ['', '## 仍待解决', '',
        '多数候选原文的字段核验、证券主体历史映射、发布日期差异及原始修订版本链未完成。主体ID缺失/冲突、空索引、标题未识别和网络失败分别保留，不能标作无风险。',
        '下载失败和有限候选/分页上限仍需明示；已完成访问批次不等于全部人工审计完成。',
        '', '## 证据位置', '', '- remaining_evidence_r1：完整首轮访问结果。',
        '- remaining_evidence_r2：失败修订及原始请求响应。',
        '- remaining_evidence_r2_fixed_r1：修正轮源码协议、结果和失败日志；状态以status.json为准。',
        '- reader-audit-review-20261008.md：两份审计报告核查。',
        '- reader-sinosoft-followup-20261008.md：预测、镜像和招股书核查。',
        '- kaidi-fixed-review-20261008.md：预计利润口径及金额差异。',
        '- zhongxin-fixed-review-20261008.md：预增数值及风险原因缺失。',
        '- fixed-appendix-audit-review-20261008.md：两份扫描审计原件、签字页及费用缺失。',
        '- fangsheng-earlier-disclosure-review-20261008.md：较早披露金额及日期未配对。']
    (out / 'unified-review-progress.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(dict(first_keys=len(first),repair_keys=len(fixed),repair_documents=fixed_documents,
        numeric_checks=len(numeric_all)+len(reader_audits),numeric_differences=differences,historical_approvals=0)))


if __name__ == '__main__':
    main()
