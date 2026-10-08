"""Report all approved queue rows, including still-pending evidence access."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import announcement_financial_audit as audit
import collect_remaining_financial_evidence as collector


def main():
    out=collector.OUT
    protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    if audit.sha(collector.QUEUE)!=protocol['queue_sha256']:
        raise RuntimeError('Queue changed since access protocol was frozen')
    active,outside,groups=collector.load_queue()
    results={}
    for path in (out/'results').glob('*.json'):
        result=json.loads(path.read_text(encoding='utf-8'))
        key=(result['ts_code'],result['ann_date'])
        if key not in groups:
            raise RuntimeError('Result outside approved queue/window')
        results[key]=result
    checks={}
    with (audit.OUT/'evidence/field_checks.csv').open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):checks.setdefault(row['row_sha256'],[]).append(row)
    fields=['api','ts_code','ann_date','end_date','row_sha256','access_status',
        'candidate_documents_downloaded_for_stock_day','numeric_fields_checked',
        'numeric_fields_different','historical_version_status','usable_in_verified_history']
    with (out/'remaining_review_rows.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in active:
            result=results.get((row['ts_code'],row['ann_date']),{})
            checked=checks.get(row['row_sha256'],[])
            writer.writerow(dict(**{k:row[k] for k in fields[:5]},access_status=result.get('status','pending_access'),
                candidate_documents_downloaded_for_stock_day=sum(
                    d['status']=='downloaded_readable_candidate_only' for d in result.get('documents',[])),
                numeric_fields_checked=len(checked),numeric_fields_different=sum(Decimal(r['difference'])!=0 for r in checked),
                historical_version_status='unverified_original_release_and_version_chain',usable_in_verified_history=False))
    counts={}
    for result in results.values():counts[result['status']]=counts.get(result['status'],0)+1
    failures=[]
    events=out/'events.jsonl'
    if events.exists():
        for line in events.read_text(encoding='utf-8').splitlines():
            if line.strip():failures.append(json.loads(line))
    manifest=json.loads((audit.OUT/'evidence/manifest.json').read_text(encoding='utf-8'))
    supplement=[]
    for name in ['reader_qualitative_forecast_checks.json','sinosoft_mirror_case.json','reader_prospectus_checks.json']:
        path=audit.OUT/'evidence'/name
        if path.exists():
            obj=json.loads(path.read_text(encoding='utf-8'))
            supplement.extend(obj.get('checks',[obj]))
    if any(item['usable_in_verified_history'] for item in supplement):
        raise RuntimeError('Supplemental mirror/qualitative evidence cannot approve history')
    progress=json.loads((out/'status.json').read_text(encoding='utf-8'))
    downloaded=sum(d['status']=='downloaded_readable_candidate_only' for r in results.values() for d in r.get('documents',[]))
    lines=['# 全部剩余公告核查状态','',f'更新时间：{audit.now()}（UTC）。',
        '',f'批准窗口内{len(active)}行、{len(groups)}个股票/公告日组合；窗口外{len(outside)}行仅保留诊断，不下载原文。',
        f'当前已处理证据访问{len(results)}/{len(groups)}组，取得{downloaded}份可读取候选PDF。采集状态：{progress["state"]}。',
        '', '**候选取得不是原文数值、真实发布时刻或原版本链核验通过。**',
        '每行待办均列于remaining_evidence_r1/remaining_review_rows.csv。尚未访问的行明确标记pending_access；同一股票/日期候选数不等于对应报告期的正确报告数。',
        '', '## 访问分类','', '| 状态 | 股票/日期组合数 |','|---|---|']
    lines += [f'| {state} | {count} |' for state,count in sorted(counts.items())]
    lines += [f'| pending_access | {len(groups)-len(results)} |','', '## 已有人工检查与未解决事项','',
        f'人工数值检查{manifest["field_checks"]}项，{manifest["matched_fields"]}项一致，{manifest["mismatched_fields"]}项差异；另有1例审计签字核查。',
        f'当前官方索引日期核查{manifest["publication_index_checks"]}条；完整历史可用记录仍为{manifest["verified_original_version_rows"]}。',
        f'另有{len(supplement)}项定性文字、镜像或招股书补充核查，单独保存，未混入既有73项检查；详见reader-sinosoft-followup-20261008.md。',
        '固定样本、同日版本冲突及亏损股涉及记录均在同一批准队列内。未取到原文、查询失败、候选报告未确定与数值不一致分别记录，不能解释为“无风险”。',
        '两条API版本数值相同不能证明原版本均被保留；当前索引和下载时间不能替代历史发布快照。未知值不补填，未核验记录不进入策略。',
        '', '## 失败与可追溯性','',f'已记录{len(failures)}条失败事件（包括重试后成功的尝试）；详情见remaining_evidence_r1/events.jsonl。',
        '单组最多5页索引、4份候选PDF；单PDF20MB、总候选存储4GB、磁盘剩余6GB下限。超限是明确访问限制，不能宣称报告候选完整。',
        '当前名称替代检索不保证历史名称一致；上市前公司/挂牌代码关系未确认时不接受其他证券代码作为匹配。',
        '输入队列和采集源码已单独冻结，原年度/连续账户数据、旧结果、失败日志和人工检查快照保留。未新增策略训练、调参、回测或券商连接。',
        '', '## 文件','', '- remaining_evidence_r1/protocol.json：输入及源码哈希、范围、资源上限。',
        '- remaining_evidence_r1/results：每组结果，含请求参数、索引返回、候选来源、PDF与文本哈希。',
        '- remaining_evidence_r1/documents：候选PDF及提取文本；需要继续人工核验。',
        '- remaining_evidence_r1/remaining_review_rows.csv：全部2166行的逐项真实状态。',
        '- remaining_evidence_collection.log：采集进度日志。']
    (audit.OUT/'remaining-review-status.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    audit.write_json(out/'report_snapshot.json',dict(at=audit.now(),keys_seen=len(results),
        downloaded_documents=downloaded,events_seen=len(failures),rows=len(active),
        verified_original_version_rows=0,queue_sha256=protocol['queue_sha256'],report_source_sha256=audit.sha(__file__)))
    print(json.dumps(dict(keys=len(results),total=len(groups),documents=downloaded,events=len(failures))))


if __name__=='__main__':main()
