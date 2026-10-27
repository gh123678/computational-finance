"""Exclusive r5 final report: zero, partial and full cohorts stay distinct."""
import json
from pathlib import Path
import shutil

import pandas as pd

import run_alphaforge_r5 as run


def collect(out):
    out=Path(out)
    preparation=run.read_json(out/'preparation_audit.json')
    assert preparation['market_inventory_complete'] is False and preparation['live_enablement'] is False
    assert preparation['preparation_manifest_sha256']==run.sha(out/'preparation_sha256.json')
    assert preparation['source_bridge_summary_sha256']==run.sha(out/'source_bridge_summary.json')
    assert preparation['verifier_sha256']==run.sha(run.ROOT/'scripts/verify_alphaforge_r5.py')
    bridge=preparation['source_bridge_audit']
    assert bridge['independent_source_bridge_reconstruction']
    summary=run.read_json(out/'source_bridge_summary.json')
    assert summary['passed']==bridge['source_bridge_passed']
    assert summary['failure_count']==bridge['source_failure_count']
    if not preparation['conditional_account_attempt_allowed']:
        assert preparation['status']=='source_gate_failed' and bridge['source_failure_count']>0
        assert not bridge['source_bridge_passed'] and bridge['source_failures_exact'] and bridge['coverage_exact']
        assert not any((out/n).exists() for n in ('experiment_protocol.json','accounts_sha256.json',
            'status.json','verification.json','partial_verification.json','summary.json','annual_returns.csv','year_boundary_audit.csv'))
        assert not any((out/f'{path}_{bps}bp').exists() for path,bps in run.ORDER)
        statuses=[dict(strategy=f'{p}_{b}bp',path=p,slippage_bps=b,status='not_started') for p,b in run.ORDER]
        return dict(kind='source_gate_failed',preparation=preparation,audit=None,statuses=statuses,
                    accounts_started=0,completed_accounts=0,year_boundaries=0,full=False,gates=None)
    assert preparation['status']=='passed' and bridge['source_bridge_passed']
    run.verify_stage('accounts_sha256.json')
    audit_file=out/'verification.json'
    if not audit_file.exists():audit_file=out/'partial_verification.json'
    audit=run.read_json(audit_file)
    statuses=run.read_json(out/'status.json')
    assert [(s['path'],s['slippage_bps']) for s in statuses]==run.ORDER
    assert audit['accounts_manifest_sha256']==run.sha(out/'accounts_sha256.json')
    assert audit['status_sha256']==run.sha(out/'status.json')
    assert audit['summary_sha256']==run.sha(out/'summary.json')
    assert audit['live_enablement'] is False and audit['market_inventory_complete'] is False
    started=sum(s['status']!='not_started' for s in statuses)
    complete=sum(s['status']=='completed' for s in statuses)
    assert audit['accounts_started']==started and audit['completed_accounts_verified']==complete
    full=audit['full_six_account_verification_passed']
    if full:
        assert started==complete==6 and audit['year_boundaries']==12
        assert audit_file.name=='verification.json' and audit['research_gates_assessable']
        assert len(run.read_json(out/'summary.json')['experiments'])==6
        assert isinstance(audit['gates'],dict) and len(audit['gates'])==6
    else:
        assert audit_file.name=='partial_verification.json' and complete<6
        assert not audit['research_gates_assessable'] and audit['gates'] is None
        failures=[i for i,s in enumerate(statuses) if s['status'] in ('failed','engineering_failure')]
        assert len(failures)==1
        first=failures[0]
        assert all(s['status']=='completed' for s in statuses[:first])
        assert all(s['status']=='not_started' for s in statuses[first+1:])
    return dict(kind='full_cohort' if full else 'stopped_first_account_failure',preparation=preparation,
        audit=audit,audit_file=audit_file.name,statuses=statuses,accounts_started=started,
        completed_accounts=complete,year_boundaries=audit['year_boundaries'],full=full,gates=audit['gates'])


def render(out,result,preserved):
    bridge=result['preparation']['source_bridge_audit']
    lines=['# AlphaForge r5：来源映射修订固定实验结果','',
        '客户端北京时间2026-10-19。用户在完整r5方案交付后回复“=继续”，本轮按该批准实施；原提案的待批准文字保留为历史证据。','',
        '## 结论','',f'终态：`{result["kind"]}`。已启动{result["accounts_started"]}账户，完整完成{result["completed_accounts"]}/6，独立核验跨年{result["year_boundaries"]}/12。',
        '实盘不启用。全市场2806只×790日的原16441条失败保持，局部补证不等于整个市场已认证；本轮也不是严格未见样本外或独立前向验证。','',
        '|账户|终态|已完成日|停止原因|','|---|---|---:|---|']
    for s in result['statuses']:
        reason=str(s.get('reason',s.get('error',''))).replace('|','/').replace('\n',' ')
        lines.append(f'|{s["strategy"]}|{s["status"]}|{s.get("completed_sessions",0)}|{reason}|')
    lines+=['','## 固定样本与来源关卡','',
        '逐字复用r3的273794形成键、154期、2806证券、两条路径目标及原因子/标签/IC/分层数值。未改变参数、股票、年份、方向、200门槛或成本；未重算或重选样本。',
        f'独立重建形成内部桥{bridge["formation_bridges"]}条、标签内部桥{bridge["label_bridges"]}条，覆盖键{bridge["coverage_keys"]}；确认新增来源失败{bridge["source_failure_count"]}条。原无效标签{bridge["original_invalid_label_keys"]}键保持，仅作诊断。',
        '形成按信号日收盘截止（日期包含当天），标签按每桥后端日截止；账户盘前来源要求早于当天。日期级索引不冒称历史分钟级或盘前认证。',
        '明细为`source_bridge_coverage.csv`、`source_bridge_failures.csv`、`source_bridge_trace.csv`；`preparation_audit.json`由独立实现重建覆盖、失败、来源版本、时点与报价，不调用新模拟器或新事件选择函数。','']
    if result['kind']=='source_gate_failed':
        failure=pd.read_csv(out/'source_bridge_failures.csv',dtype=str)
        lines+=['原键经来源修订后失效，按冻结停止规则以0账户结案。全部键和失败保留；未创建账户实验协议，未用删除样本、未来公告或重训来恢复资格。','',
            '|类型|证券|形成日|桥前日|桥后日|原因|','|---|---|---|---|---|---|']
        for row in failure.head(12).to_dict('records'):
            lines.append('|'+ '|'.join(str(row[k]) for k in ('kind','ts_code','formation_date','bridge_left','bridge_right','reason'))+'|')
        lines+=['','上表只展示前12条；完整失败及当时有效来源见明细文件。没有实际账户净值、成本后收益、最大回撤或完整六账户研究关卡结果。']
    elif result['full']:
        lines+=['','## 实际账户与冻结研究关卡','',
            '|账户|净收益|最大回撤|费用/元|滑点成本/元|累计换手|','|---|---:|---:|---:|---:|---:|']
        for item in run.read_json(out/'summary.json')['experiments']:
            orders=pd.read_csv(out/item['strategy']/'orders.csv')
            nav=pd.read_csv(out/item['strategy']/'nav.csv')
            lines.append(f'|{item["strategy"]}|{item["total_return"]:.4%}|{item["max_drawdown"]:.4%}|{orders.fee.sum():.2f}|{orders.slippage_cost.sum():.2f}|{nav.turnover.sum():.4f}|')
        lines+=['','六项冻结研究关卡：'+json.dumps(result['gates'],ensure_ascii=False)+'。',
            '年度收益见`annual_returns.csv`，12跨年重建见`year_boundary_audit.csv`。逐日现金、股份、未上市、应收、费用、拒单与估值核验见`verification.json`及各账户原记录。']
    else:
        lines+=['','首次账户失败后整组停止，其余未启动。独立核验只证明已经发生的账户前缀和相同停止；不构成完整六账户通过。完整收益、成本对比、回撤、年收益与六项研究关卡未评估，部分净值不得当作三年策略绩效。',
            f'独立账务证据：`{result["audit_file"]}`；每个已尝试账户保留失败当日、订单、账本、持仓、义务及守卫日志。']
    lines+=['','## 本轮映射与边界','',
        '普通跨缺价来源由原3项增至精确23键（20项纯现金）。7项转增税源未知及002470时点冲突仍按旧实际跨缺价/矛盾边界停止，不加入普通允许范围。000426实际现金0.019902，员工获授股份不归普通账户；理论7.190098与观测7.19不混同为舍入认证。',
        '600781保留取消公开前的研究情景登记，取消公开后撤销未执行权益，不造现金、待收或普通除息估值；601258重整股份不给普通持有人，实际股份、未上市、活动义务或拟成交触及特殊行动阶段即停，不因有报价放行。',
        '000977个人额度0.12与市场参考0.1177945分开；价格12.92、原日期不变。上市公告公开前待上市日期未知，随后更新。600999原7.46/0.3及日期不变，发行、实际结果及上市三份官方来源独立绑定；7月20日实际成功的日期级公告不能证明当天开盘前已知。',
        '认购仍为原已批准的条件研究情景：依据先前发行额度、除权日扣现金、现金不足整单不认购、上市日锁/T+1；不冒称重现实际历史缴款或当日盘前已知成功。floor是研究近似，真实托管尾数排序和实际到账未认证。其它原无条款配股不因新来源而自动认购。','',
        '## 诊断、保全与后续限制','',
        '冻结IC及分层原值保存在`reused_r3/factor_ic.csv`、`factor_ic_summary.csv`和`factor_groups.csv`。它们是历史参考诊断；来源关卡失败时不能将原诊断升级为本版有效证据，也不能替代实际现金账户收益。',
        f'源码、输入、来源及各阶段指纹保留在`source_before`、`frozen_protocol.json`及阶段清单。旧保护清单成员合计{sum(x["count"] for x in preserved)}项（重叠按各清单计数，不冒称独立文件数），结尾逐文件重验。最终清单`output_sha256.json`一次封存；原r1—r4、行情、源码及失败不覆盖。',
        '实盘保持`blocked_by_unverified_data_and_forward_validation`，未接券商。数据来源和历史可得性、个人实配与税务、完整经济条款及独立前向验证仍有限制；本次固定案例结束不表示整个策略目标完成。','']
    return '\n'.join(lines)


def main():
    out=run.OUT;doc=run.ROOT/'docs/2026-10-19-alphaforge-r5-results.md'
    if (out/'output_sha256.json').exists():raise RuntimeError('Existing final seal; never overwrite')
    if doc.exists() or (out/'report.md').exists():raise RuntimeError('Existing final report; never overwrite')
    run.check_disk()
    with run.exclusive_stage(out,'report'):
        protocol=run.read_json(out/'frozen_protocol.json');run.verify_inputs(protocol)
        run.verify_stage('preparation_sha256.json')
        result=collect(out);preserved=run.preservation()
        report=render(out,result,preserved)
        with (out/'report.md').open('x',encoding='utf-8') as stream:stream.write(report)
        with doc.open('x',encoding='utf-8') as stream:stream.write(report)
        run.persist(out/'final_experiment_status.json',result['statuses'],exclusive=True)
        run.persist(out/'final_outcome.json',dict(kind=result['kind'],accounts_started=result['accounts_started'],
            completed_accounts=result['completed_accounts'],year_boundaries=result['year_boundaries'],
            research_gates_assessable=result['full'],gates=result['gates'],
            market_inventory_complete=False,live_enablement=False),exclusive=True)
        logs=out/'logs';logs.mkdir()
        for source in run.RUNTIME_LOGS.glob('*.log'):
            if source.name!='report.log':shutil.copy2(source,logs/source.name)
        run.persist(out/'final_preservation_check.json',dict(status='passed',manifests=preserved),exclusive=True)
        run.persist(out/'output_sha256.json',{p.relative_to(out).as_posix():run.sha(p) for p in out.rglob('*')
            if p.is_file() and p.name!='runner.lock'},exclusive=True)
        print('r5 report',str(doc),'final manifest',run.sha(out/'output_sha256.json'),flush=True)


if __name__=='__main__':main()
