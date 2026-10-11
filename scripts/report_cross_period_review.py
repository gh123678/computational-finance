"""Seven manually reviewed cross-period cases, scoped to identified notices.

No full-history approval, model run, or frozen-data write. Preserve evidence.
"""
import hashlib
import json
from pathlib import Path

import fitz

import announcement_financial_audit as audit
import repair_financial_review as repair
import verify_off_checklist_key as verifier

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/cross_period_review_20261011_r1'
PREVIOUS = ROOT / 'output/financial_review_repair_20261011_r1'
CORRECTIONS = PREVIOUS / 'corrections'
OLD = ROOT / 'output/off_checklist_revision_worklist_20261010/verification_round'

CASES = [
    ('000851.SZ', '20181231', '1206072236', 7, '8904228.51',
     '新金融工具准则资产列报重分类；说明明确不追溯以前年度、不影响年初利润。该次更正未改变2018年度扣非利润。',
     'financial_classification_no_prior_profit_restatement', '000851.SZ_notice.json', [1, 4]),
    ('002360.SZ', '20171231', '1204575799', 6, '91759184.11',
     '2016年报更正供应商/客户名单金额及资金占用披露；未列示2017年度利润调整。2017年原年报字段匹配flag0。本结论只排除该已识别更正对目标利润的直接改写。',
     'other_year_disclosure_correction_no_target_profit_change_identified', '002360.SZ_20171231_1204625589.json', [1, 2, 3]),
    ('002462.SZ', '20181231', '1205855924', 6, '323695828.92',
     '2019Q1更正新增新金融工具执行说明，将787,608.80元由可供出售金融资产列为其他权益工具投资，年初总资产/负债/权益列示不变；未列示2018年度利润重述。说明会更新属于会议信息。',
     'financial_classification_no_target_profit_change_identified', '002462.SZ_20181231_1206086106.json', [1, 3, 5]),
    ('002781.SZ', '20151231', '1202244029', 7, '129046456.37',
     '2016Q1补披露关联人资金占用329.02万元，并称其他内容不变。代缴发生2016年，未列示2015年度利润重述；风险事实不能在2016-06-01公开日前反向填入2015年策略。',
     'related_party_disclosure_no_target_profit_change_identified', '002781.SZ_20151231_1202348043.json', [1, 3]),
    ('002822.SZ', '20171231', '1204628617', 7, '159769782.44',
     '2018Q1把普通股股东总数600,000,000更正为51,086，并称其他内容不变；不是2017年度扣非利润更正。',
     'shareholder_count_only_no_profit_revision', '002822.SZ_20171231_1204823703.json', [1]),
    ('600594.SH', '20181231', '1206162615', 6, '-772885149.67',
     '2019Q1原/修订版主要财务表中营业收入、归母利润、扣非利润及上年度末资产/权益均相同。修订改变2019年资产负债及新准则执行说明，未识别目标2018年度扣非利润改写；不能把利润未变扩展为资产负债类因子未变。',
     'paired_quarter_profit_unchanged_balance_sheet_changed', '600594.SH_20181231_1206254202.json', [3, 25]),
    ('603559.SH', '20201231', '1209819909', 6, '-7089886.79',
     '差错更正影响2020年二、三季度利润7,010,018.31元，但公告明确不影响2020年度报告及其他年度报告。年度字段匹配flag0；季度更正值只从2021-05-07公开后可用，不能反填2020季度信号。',
     'quarterly_profit_restatement_annual_report_explicitly_unaffected', '603559.SH_notice.json', [-2, -1]),
]

GENERIC_CASES = [
    ('000851.SZ', [2, 3, 4, 5, 6, 7, 8],
     'supplementary_disclosures_no_target_profit_revision_identified',
     '补充减值计提过程、担保明细及无反担保风险；原披露3,455.25万元减值与新增34,552,476.41元明细对应，未列示合并年度扣非利润重述。新增风险信息须保留2018-03-31索引公开日。', False),
    ('002097.SZ', [1, 3, 6, 7, 9],
     'governance_guarantee_product_scope_no_target_profit_revision_identified',
     '更正议案、投票时间、审批程序，并扩充融资担保业务、调整理财产品范围；110亿元担保上限不变，未列示2020年度扣非利润重述。不能将治理与风险范围改变视为完全无影响。', False),
    ('600343.SH', [3, 4, 5, 6],
     'scanned_related_funds_revision_comparison_pending',
     '修订版是非经营性资金占用及关联资金往来专项说明，不是新审计利润表。正文/扫描汇总表尚需原版配对才能核定改动；不能仅凭标准无保留审计意见排除风险或利润影响。', True),
    ('600804.SH', [2, 3, 4],
     'audit_emphasis_supplement_profit_effect_statement_unchanged',
     '原版p3与修订p2的强调事项及无财务状况/经营成果影响表述一致。修订新增重要性水平2,750万元、上期非标意见在本期的情况及使用限制（原扫描p4止于第四节），仍列示预付款退回与整改未达预期。新增说明只从2021-05-20索引公开后使用，不据此批准其他风险字段。', False),
]


def metadata_pdf(filename):
    base = OUT if filename.endswith('_notice.json') else CORRECTIONS
    rec = json.loads((base / filename).read_text(encoding='utf-8'))
    doc = rec if filename.endswith('_notice.json') else rec['document']
    return ROOT / doc['file'] if doc['status'] == 'existing_pdf_cache' else base / doc['file']


def evidence_page(path, number, name):
    with fitz.open(path) as pdf:
        index = number - 1 if number > 0 else len(pdf) + number
        page = pdf[index]
        image = OUT / 'page_review' / f'{name}_{index + 1}.png'
        page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).save(image)
        return dict(path=str(path.relative_to(ROOT)), sha256=audit.sha(path), pdf_page=index + 1,
                    text=page.get_text(), rendered_page=str(image.relative_to(ROOT)))


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / 'page_review').mkdir(exist_ok=True)
    frozen = json.loads((PREVIOUS / 'input_sha256.json').read_text(encoding='utf-8'))
    assert all(audit.sha(ROOT / n) == h for n, h in frozen.items())
    rows = []
    for code, period, identifier, page, value, conclusion, status, notice, pages in CASES:
        source = json.loads((OLD / 'results' / f'{code}_{period}.json').read_text(encoding='utf-8'))
        original = next(d for d in source['documents'] if Path(d['file']).stem.endswith(identifier))
        annual_path = OLD / original['file']
        annual = evidence_page(annual_path, page, f'{code}_{period}_annual')
        assert value == source['val_flag0']
        assert value in annual['text'].replace(',', '').replace(' ', '').replace('\n', '')
        notice_path = metadata_pdf(notice)
        evidence = [evidence_page(notice_path, p, f'{code}_{period}_notice') for p in pages]
        rows.append(dict(ts_code=code, end_date=period, vendor_ann_date=source['ann_date'],
                         observed_annual_profit_dedt_cny=value, selected_flag='0',
                         annual_document_index_day=original['index_day'], annual_evidence=annual,
                         correction_evidence=evidence, conclusion=conclusion, status=status,
                         scope='identified correction documents only; no global no-revision claim',
                         full_version_chain_verified=False, usable_in_verified_history=False))
    old_quarter = json.loads((OUT / '600594.SH_original_quarter.json').read_text(encoding='utf-8'))
    original_path = OUT / old_quarter['file']
    updated_path = metadata_pdf('600594.SH_20181231_1206254202.json')
    old = evidence_page(original_path, 3, '600594_quarter_original')
    new = evidence_page(updated_path, 3, '600594_quarter_updated')
    values = ['824625331.83', '59230798.23', '58735290.73', '6475568370.27', '3503440804.42']
    for evidence in [old, new]:
        compact = evidence['text'].replace(',', '').replace(' ', '').replace('\n', '')
        assert all(value in compact for value in values)
    audit.write_json(OUT / 'paired_quarter_comparison.json', dict(
        original=old, updated=new, checked_fields=['2019Q1 revenue', '2019Q1 parent profit',
        '2019Q1 profit excluding nonrecurring', '2018 year-end assets', '2018 year-end parent equity'],
        checked_values_equal=True, all_fields_equal=False, annual_profit_restatement_approval=False))
    audit.write_json(OUT / 'seven_key_adjudications.json', rows)
    version_rows = []
    for path in sorted((OLD / 'results').glob('*.json')):
        source = json.loads(path.read_text(encoding='utf-8'))
        query = repair.cached_query(source, OLD / 'responses')
        vc = verifier.assess_version_query(query)
        version_rows.append(dict(ts_code=source['ts_code'], end_date=source['end_date'],
                                 old_status=source['final_status'], **vc,
                                 usable_in_verified_history=False))
    audit.write_json(OUT / 'generic_notice_cache_review.json', version_rows)
    generic_rows = []
    for code, pages, status, conclusion, pending in GENERIC_CASES:
        metadata = json.loads((OUT / f'{code}_generic_notice.json').read_text(encoding='utf-8'))
        document = metadata['document']
        path = OUT / document['file']
        assert audit.sha(path) == document['sha256']
        evidence = [evidence_page(path, p, f'{code}_generic') for p in pages]
        original_metadata = OUT / f'{code}_generic_original.json'
        original = json.loads(original_metadata.read_text(encoding='utf-8')) if original_metadata.exists() else None
        original_evidence = []
        if code == '600804.SH':
            original_path = OUT / original['document']['file']
            assert audit.sha(original_path) == original['document']['sha256']
            original_evidence = [evidence_page(original_path, p, '600804_generic_original') for p in [3, 4]]
        generic_rows.append(dict(ts_code=code, end_date=metadata['end_date'],
            index_day=metadata['index_day'], status=status, conclusion=conclusion,
            evidence=evidence, original_document=original, original_evidence=original_evidence,
            comparison_pending=pending,
            full_version_chain_verified=False, usable_in_verified_history=False))
    audit.write_json(OUT / 'generic_notice_adjudications.json', generic_rows)
    reviewed_generic_keys = {(r['ts_code'], r['end_date']) for r in generic_rows}
    reviewed_generic_keys |= {('000851.SZ', '20181231'), ('603559.SH', '20201231')}
    pending_generic = [dict(ts_code=r['ts_code'], end_date=r['end_date'],
        notices=r['ambiguous_corrections'], status='content_review_pending',
        usable_in_verified_history=False) for r in version_rows
        if r['ambiguous_corrections'] and (r['ts_code'], r['end_date']) not in reviewed_generic_keys]
    audit.write_json(OUT / 'remaining_generic_notice_review.json', pending_generic)
    from collections import Counter
    counts = dict(Counter(r['status'] for r in version_rows))
    old_results = audit.verify_old()
    assert all(audit.sha(ROOT / n) == h for n, h in frozen.items())
    failure_record = OUT / 'run_failures.json'
    test_record = json.loads(failure_record.read_text(encoding='utf-8'))['resolved'] if failure_record.exists() else None
    audit.write_json(OUT / 'verification.json', dict(seven_keys_reviewed=len(rows),
        unidentified_target_annual_profit_effect_in_reviewed_cases=0,
        historical_version_approvals=0, source_archive_unchanged=True,
        preserved_audit_artifacts=len(frozen), preserved_experiment_files=old_results,
        generic_notice_cache_status_counts=counts,
        generic_notices_read=len(generic_rows),
        generic_original_comparisons_pending=sum(r['comparison_pending'] for r in generic_rows),
        additional_generic_notice_keys_pending=len(pending_generic),
        additional_generic_notices_pending=sum(len(r['notices']) for r in pending_generic),
        tests=test_record, run_failures='run_failures.json',
        limitations=['only identified notices are adjudicated',
                     'first publication and complete version chains not globally certified',
                     'other financial/risk fields not enabled', 'no new model/backtest']))
    lines = ['# 七键跨期修订复核（2026-10-11）', '',
        '本轮七键已全部形成已识别公告范围内的影响结论。没有把60日索引检索升级为完整历史可用认证。', '',
        '| 股票 | 年度期末 | 已识别更正的影响 |', '|---|---|---|']
    for r in rows:
        lines.append(f"| {r['ts_code']} | {r['end_date']} | {r['conclusion']} |")
    lines += ['', '另补读高鸿通用更正、中通国脉会计差错更正及益佰原季报三份PDF，无下载失败。原文、页号、源哈希和视觉核验页见seven_key_adjudications.json。', '',
        '修复通用会计差错/补充更正标题的漏分流：不能因没有“年报/季报”字样就自动视为无关。166键既有缓存重新分类：' + json.dumps(counts, ensure_ascii=False) + '。这些是机器检索状态，不是可用批准。', '',
        '七键已识别的目标年度利润疑点已闭合，但未批准全量历史消费。季度修订、资金占用等风险事实必须保留自身公开日期，不得倒填。资产负债表或其他字段的修订不因扣非利润未变而自动清零。', '',
        '旧170个审计输入/产物、665+295个模型和账户结果保持指纹一致；没有训练、回测、调参或券商接入。下一阶段是逐版本公开日期与持续覆盖规则，当前历史批准仍0。']
    lines += ['', '## 通用公告漏分流补核', '',
              '四份修订PDF均已保存。下表明确区分当前公告判读与尚未完成的原版比较；没有将机器重新分类写回旧结果。', '',
              '| 股票 | 范围内结论及限制 |', '|---|---|']
    for r in generic_rows:
        lines.append(f"| {r['ts_code']} | {r['conclusion']} |")
    lines += ['', '项目既有 .venv_ml_risk 环境实测145项通过，6个既有警告。第一次未限定目录误收集归档/提交副本，引发31个收集错误；第二次使用系统Anaconda环境，144通过、1项因缺LightGBM失败。均为测试入口/环境问题，不改测试断言；正确环境完整日志见tests_project_runtime.log，环境失败见tests.log及run_failures.json。下载重试失败保留events.jsonl。', '',
              '鹏博士原版配对完成；航天动力原版两次55秒下载均超时，尚缺原版核对，部分下载文件与失败日志保留。', '',
              '此外，已有定期报告更正版的5键还伴随6份通用更正/财务顾问修订公告，正文影响尚待逐条核定：000595.SZ/20151231、000851.SZ/20201231、002433.SZ/20191231、002433.SZ/20201231、002462.SZ/20191231。其目标年报字段的上一轮核对不代替这些公告审查。清单见remaining_generic_notice_review.json。', '',
              '下一步补齐上述未决正文与原版比较，再制定并验证首次公开版本、修订生效日与覆盖不足的排除规则。当前局部核验仍不能直接推进实盘。']
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(dict(reviewed=len(rows), version_cache_counts=counts), ensure_ascii=False))


if __name__ == '__main__':
    main()
