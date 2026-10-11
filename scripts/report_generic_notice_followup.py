"""Record scoped manual notice review; never approve historical consumption."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import fitz

import announcement_financial_audit as audit
from collect_generic_notice_followup import OUT, PREVIOUS, ROOT

REVIEWS = {
    '1202100766': ([1, 3, 6, 7, 8, 9, 17, 18, 20],
        'multiple_disclosure_fields_changed_target_profit_not_revised_in_identified_update',
        '2015年报更正13项：累计募资使用30,789.50→43,975.08万元、担保总余额4,500→2,000万元、薪酬7,317→8,750万元、在建工程明细和预算补充、短借质押→抵押、政府补助分类说明、可随时支付银行存款78,525,562.79→70,146,312.79元及日后事项等；不可归为纯文字更正。已读更正版年度扣非仍−126,112,165.09元。风险/现金/资产类字段需逐版本处理。'),
    '1209721345': ([1, 2, 3, 4, 5, 6],
        'segment_reallocation_totals_unchanged_explicit_no_financial_results_effect',
        '2020分产品收入与成本在通信设备和系统集成业务间重分配；两类收入、成本合计分别未变。公告明确不影响2020财务状况及经营业绩，已读更新年报扣非仍−196,380,050.17元。分产品毛利率、收入增长等因子不能使用旧值或提前使用修订值。'),
    '1207944775': ([1, 2],
        'liquidity_ratios_revised_other_annual_contents_unchanged',
        '2019流动比率2.01%→193.29%、速动比率0.90%→65.28%，2018比较值及若干同比比例亦更正；公告称年报其他内容不变，更新年报扣非35,396,243.53元。流动性因子必须保留2020-06-20修订生效边界。'),
    '1209791514': ([1, 2, 3, 4, 5, 6, 7],
        'transaction_valuation_opinion_revision_not_annual_profit_restatement',
        '修正重大资产出售评估独立性、方法、定价及独董意见文件；属于交易评估意见上传错误更正，没有列示2020年度利润表重述。不能据此断言交易风险或未来利润不受影响。'),
    '1209938544': ([1, 12, 16, 50, 51, 99, 139],
        'transaction_adviser_later_rounded_financial_summary_only',
        '160页重大资产出售财顾修订稿涉及康爱多股权出售；p50–51为上市公司历史合并财务摘要，2020/2019扣非−3,228.47/3,539.62万元，与已核年报金额按万元两位小数一致。这是后续摘要佐证，不是精确金额或首次公开证据。未完成财顾原稿160页逐项对比，不认证全部修订无影响；交易事项与备考数据不得替代此前实际年报。'),
    '1207657942': ([1, 2, 3, 4],
        'compensation_and_voting_disclosure_revision_other_contents_unchanged',
        '2019高管薪酬合计955.61→837.96万元，并更正会议投票时间、部分人员资料和关联方取酬信息；公告明确其他年报内容不变，已读更新年报扣非369,705,753.25元。薪酬披露变化不自动等同合并账务重记。'),
}


def source_path(document):
    return (ROOT if document['status'] == 'existing_pdf_cache' else OUT) / document['file']


def page_evidence(path, number, prefix, rotate=False):
    with fitz.open(path) as pdf:
        page = pdf[number - 1]
        image = OUT / 'page_review' / f'{prefix}_{number}.png'
        page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4).prerotate(90 if rotate else 0)).save(image)
        return dict(pdf=str(path.relative_to(ROOT)), sha256=audit.sha(path), pdf_page=number,
            text=page.get_text(), rendered_page=str(image.relative_to(ROOT)))


def image_content_hash(path, number):
    with fitz.open(path) as pdf:
        return [hashlib.sha256(fitz.Pixmap(pdf, im[0]).samples).hexdigest()
            for im in pdf[number - 1].get_images()]


def main():
    (OUT / 'page_review').mkdir(exist_ok=True)
    preserved = json.loads((OUT / 'previous_sha256.json').read_text(encoding='utf-8'))
    assert all(audit.sha(ROOT / p) == h for p, h in preserved.items())
    collection = json.loads((OUT / 'collection_progress.json').read_text(encoding='utf-8'))
    assert collection['finished'] and len(collection['records']) == 7
    records = {Path(r['notice']['url']).stem: r for r in collection['records']}
    annuals = json.loads((ROOT / 'output/financial_review_repair_20261011_r1/corrected_report_field_review.json').read_text(encoding='utf-8'))['target_year_field_reviews']
    rows = []
    for identifier, (pages, status, conclusion) in REVIEWS.items():
        rec = records[identifier]
        path = source_path(rec['document'])
        assert audit.sha(path) == rec['document']['sha256']
        supporting = [r for r in annuals if (r['ts_code'], r['end_date']) == (rec['ts_code'], rec['end_date'])]
        for source in supporting:
            assert audit.sha(ROOT / source['path']) == source['pdf_sha256']
            with fitz.open(ROOT / source['path']) as pdf:
                text = pdf[source['pdf_page'] - 1].get_text().replace(',', '').replace(' ', '').replace('\n', '')
                assert source['observed_value_cny'] in text
        rows.append(dict(**rec, status=status, conclusion=conclusion,
            evidence=[page_evidence(path, p, identifier) for p in pages],
            supporting_updated_annual_field=supporting,
            scope='identified notice and cited pages only',
            full_version_chain_verified=False))
    # Arithmetic compares only the two explicitly revised product segments.
    segment = dict(revenue_before=['721957428.89', '1133121824.26'],
        revenue_after=['829674264.48', '1025404988.67'],
        cost_before=['684725754.08', '913797924.61'],
        cost_after=['690433155.48', '908090523.21'])
    for field in ['revenue', 'cost']:
        assert sum(map(Decimal, segment[field + '_before'])) == sum(map(Decimal, segment[field + '_after']))
    audit.write_json(OUT / 'segment_arithmetic.json', dict(**segment, selected_totals_equal=True,
        all_financial_fields_equal=False))
    adviser = source_path(records['1209938544']['document'])
    with fitz.open(adviser) as pdf:
        text = pdf[50].get_text().replace(',', '').replace(' ', '')
        for value in ['-3228.47', '3539.62']:
            assert value in text
    assert (Decimal('-32284723.16') / 10000).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) == Decimal('-3228.47')
    assert (Decimal('35396243.53') / 10000).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) == Decimal('3539.62')
    original = source_path(records['1207646993']['document'])
    revision_metadata = json.loads((PREVIOUS / '600343.SH_generic_notice.json').read_text(encoding='utf-8'))
    revised = PREVIOUS / revision_metadata['document']['file']
    assert audit.sha(revised) == revision_metadata['document']['sha256']
    identical_images = []
    for number in [3, 4, *range(7, 15)]:
        old_hash = image_content_hash(original, number)
        new_hash = image_content_hash(revised, number)
        assert old_hash == new_hash and len(old_hash) == 1
        identical_images.append(dict(pdf_page=number, embedded_image_sha256=old_hash[0]))
    fund_comparison = dict(ts_code='600343.SH', end_date='20191231',
        original_index_day='20200428', revision_index_day='20200507',
        original=records['1207646993']['document'], revised=revision_metadata['document'],
        evidence_original=[page_evidence(original, p, '1207646993', p in [5, 6]) for p in [3, 4, 5, 6]],
        evidence_revised=[page_evidence(revised, p, '1207708429', True) for p in [5, 6]],
        identical_embedded_images=identical_images,
        manually_checked_table_totals_wan=['84041.10', '625150.77', '634949.54', '74242.32'],
        selected_totals_equal=True, all_fields_equal=False,
        identified_change=dict(counterparty='西安航天科技工业有限公司', amount_wan='4468.89',
            account='其他非流动资产', before_reason='购入固定资产', after_reason='购入无形资产',
            before_nature='非经营性往来', after_nature='经营性往来'),
        conclusion='正文p3–4和资质附件p7–14内嵌扫描像素一致；p5–6为不同扫描。人工配对确认汇总四金额一致，但4,468.89万元购置款的用途和往来性质发生变化，不能认定所有字段不变。未列示新年度利润表；风险分类修订仅从2020-05-07索引公开后可知，不能倒填。',
        full_version_chain_verified=False, usable_in_verified_history=False)
    audit.write_json(OUT / 'notice_adjudications.json', rows)
    audit.write_json(OUT / 'related_funds_pair_review.json', fund_comparison)
    old_audit = json.loads((ROOT / 'output/financial_review_repair_20261011_r1/input_sha256.json').read_text(encoding='utf-8'))
    assert all(audit.sha(ROOT / p) == h for p, h in old_audit.items())
    frozen = audit.verify_old()
    assert all(audit.sha(ROOT / p) == h for p, h in preserved.items())
    audit.write_json(OUT / 'verification.json', dict(notices_reviewed=6, keys_reviewed=5,
        original_related_funds_pair_review_completed=True, collection_successful=7,
        pending_items_from_previous_round_closed_in_identified_document_scope=True,
        complete_version_chain_approvals=0, usable_in_verified_history=False,
        previous_round_files_preserved=len(preserved), old_audit_files_preserved=len(old_audit),
        old_experiments_preserved=frozen, new_backtests=0, new_models=0,
        limitations=['no certification of first disclosure or full revision-chain coverage',
            'adviser original report not compared across all 160 pages',
            'manual scan comparison certifies listed observations, not machine-extracted every cell']))
    lines = ['# 通用更正公告补核（2026-10-11）', '',
        '前轮5键6份公告已形成范围内判读，航天动力原版配对亦完成。原版这次下载成功，前轮两次超时及部分文件均保留；本轮7份采集全部成功。没有批准历史数据消费。', '',
        '| 股票 / 期末 | 公告范围内结论 |', '|---|---|']
    for row in rows:
        lines.append(f"| {row['ts_code']} / {row['end_date']} | {row['conclusion']} |")
    lines += ['', '## 航天动力关联资金分类变化', '', fund_comparison['conclusion'], '',
        '表中金额单位为万元。4,468.89万元是关联购置款，不是新确认的亏损；不能把风险类别变化直接换算成利润改变量，也不能用汇总金额相等宣布风险信息不变。视觉页、源文件哈希和具体前后值见related_funds_pair_review.json。', '',
        '## 启用边界与下一步', '',
        '当前已解决的是已识别公告的字段影响。60日当前索引不能证明首次披露和全部后续修订；财顾原稿160页逐项差异未认证。所有usable_in_verified_history继续False，批准数0，未训练、回测、调参或接入券商。', '',
        '下一步建立首次公开版本、下一交易日可用、修订后生效和覆盖不足排除的可验证规则，再重建因子面板；资产/现金/流动性/风险字段要独立核验，不能沿用扣非利润的结论。旧170审计产物、960实验文件及前轮全部文件指纹一致。']
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(dict(reviewed_notices=6, paired_original_completed=True,
        historical_approvals=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
