"""Seal the actual r6 terminal state; a preparation stop is never a return result."""
from pathlib import Path
import json

import pandas as pd
import run_alphaforge_r6 as run


def terminal(out):
    audit = run.load(out/'preparation_audit.json')
    assert audit['independent_reconstruction_passed']
    assert audit['market_inventory_complete'] is False and audit['live_enablement'] is False
    if not audit['conditional_account_attempt_allowed']:
        assert audit['status']=='risk_input_gate_failed'
        assert not any((out/n).exists() for n in ('experiment_protocol.json','status.json','summary.json','verification.json','partial_verification.json'))
        assert not any((out/f'{p}_{b}bp').exists() for p,b in run.ORDER)
        return dict(kind='risk_input_gate_failed',accounts_started=0,completed_accounts=0,
                    performance_assessable=False,research_gates=None)
    statuses = run.load(out/'status.json')
    assert [(s['path'],s['slippage_bps']) for s in statuses]==run.ORDER
    full = all(s['status']=='completed' for s in statuses)
    verification = run.load(out/('verification.json' if full else 'partial_verification.json'))
    assert verification['full_six_account_verification_passed'] == full
    if full:
        assert verification['year_boundaries']==12 and len(verification['accounts'])==6
    else:
        failures=[i for i,s in enumerate(statuses) if s['status']!='completed']
        assert failures and statuses[failures[0]]['status']=='failed'
        assert all(s['status']=='not_started' for s in statuses[failures[0]+1:])
    return dict(kind='completed_research_passed' if full and verification['research_gates_passed'] else
                     'completed_research_failed' if full else 'account_stopped',
                accounts_started=sum(s['status']!='not_started' for s in statuses),
                completed_accounts=sum(s['status']=='completed' for s in statuses),
                performance_assessable=full,research_gates=verification['gates'])


def main():
    out=run.OUT
    if (out/'output_sha256.json').exists():
        raise RuntimeError('Already sealed r6; never overwrite')
    with run.r5.exclusive_stage(out,'report'):
        protocol=run.load(out/'frozen_protocol.json')
        run.verify_inputs(protocol)
        run.verify_stage('preparation_sha256.json')
        assert run.preservation()==protocol['protected_manifests']
        audit=run.load(out/'preparation_audit.json')
        assert audit['preparation_manifest_sha256']==run.sha(out/'preparation_sha256.json')
        assert audit['verifier_sha256']==run.sha(run.ROOT/'scripts/verify_alphaforge_r6.py')
        result=terminal(out)
        if result['accounts_started']:
            run.verify_stage('accounts_sha256.json')
        periods=pd.read_csv(out/'risk_periods.csv',parse_dates=['signal_date'])
        quotes=pd.read_csv(out/'quote_failures.csv',parse_dates=['signal_date','date'])
        source=pd.read_csv(out/'source_bridge_failures.csv',parse_dates=['formation_date','bridge_left','bridge_right'])
        lines=['# AlphaForge风险预算r6实际结果','',
               '客户端日期2026-10-19。用户在收到精确r6方案后回复“继续我们的任务”，本轮据此执行。原设计待审阅字样保留为历史记录。','',
               f'终态：`{result["kind"]}`。启动{result["accounts_started"]}账户，完整完成{result["completed_accounts"]}/6。实盘关闭。','',
               '## 准备与独立核验','',
               f'原273794形成键和154期、两份基础名单及换股历史逐字保留；只检查正权目标并集{audit["bridge"]["formation_keys"]}个证券/形成日键的60桥。独立重建{audit["bridge"]["formation_bridges"]}条桥，来源失败{audit["bridge"]["source_failure_count"]}条；报价字段失败{len(quotes)}条（同一缺价行可影响多个字段及多个形成窗口）。',
               f'两条路径共{len(periods)}个路径/形成期，失败{audit["risk"]["failed_path_periods"]}期；其余{audit["risk"]["covariances_reconstructed"]}期的矩阵、去均值LedoitWolf、原NAV权重与缩放由独立实现复算一致。局部通过不能为整轮签发账户许可。','',
               '收益采用后60行的close_text/pre_close_text−1，第一报价点pre_close不参与；每个来源版本以原形成日为截止。不同路径各三成本须共享同一目标。风险目标15%是预测波动预算，不保证25%实际回撤。','']
        if not result['accounts_started']:
            lines+=['## 停止与研究边界','',
                    '准备关卡失败，按批准的冻结规则以零账户结案。没有本轮净收益、最大回撤、成本效率或完整六项研究关卡结果；不能判断风险预算是否改善了原策略。未删股、补价、缩短窗口、另挑参数或打开2021—2025。',
                    '失败窗口保存原61点报价（缺失保留为空）；不为失败期拟合协方差、不用s=1回退、不生成可运行的完整目标。部分有效期的目标只作为核验材料。','',
                    '|原因|路径/形成期数|','|---|---:|']
            for reason,count in periods.loc[periods.status.eq('failed')].groupby('reason').size().items():
                lines.append(f'|{reason}|{count}|')
            lines+=['','前12条来源失败（完整数据见source_bridge_failures.csv）：','',
                    '|证券|形成日|桥前日|桥后日|原因|','|---|---|---|---|---|']
            for row in source.head(12).itertuples(index=False):
                lines.append(f'|{row.ts_code}|{row.formation_date:%Y-%m-%d}|{row.bridge_left:%Y-%m-%d}|{row.bridge_right:%Y-%m-%d}|{row.reason}|')
        elif result['performance_assessable']:
            lines+=['## 完整账户','', '|方案|净收益|最大回撤|费用/元|滑点/元|累计双边换手|','|---|---:|---:|---:|---:|---:|']
            for item in run.load(out/'summary.json')['experiments']:
                folder=out/item['strategy']
                orders=pd.read_csv(folder/'orders.csv')
                nav=pd.read_csv(folder/'nav.csv')
                lines.append(f'|{item["strategy"]}|{item["total_return"]:.4%}|{item["max_drawdown"]:.4%}|{orders.fee.sum():.2f}|{orders.slippage_cost.sum():.2f}|{nav.turnover.sum():.4f}|')
            lines+=['','六项事前关卡：'+json.dumps(result['research_gates'],ensure_ascii=False)+'。',
                    '六组账户与12跨年核验见verification.json，年度收益见annual_returns.csv。新旧12组是相关历史情景，不是12份独立验证。']
        else:
            lines+=['首个账户失败后停止整组，其余未启动。已发生前缀由partial_verification.json独立重建，不报告三年绩效或完整六账户通过。']
        lines+=['','## 原r5结果与共同限制','',
                '原r5主10bp累计收益5.36%、回撤36.33%；主30bp累计−10.83%，原策略不启用。r6准备失败不改变这些旧结论。',
                '风险输入为参考价格收益，并非红利再投资总收益、真实账户收益或供应商系数认证。旧全市场库存失败、历史公开时点和税源等限制保持。2016—2025已被查看，本轮仍为历史开发研究，独立前向和执行验收未完成。','',
                '## 保护与复现','',
                'r5的206成员和原17份清单3539成员（存在重叠）全部重哈希一致。旧清单内C盘路径未改，新协议显式绑定迁移证明与D盘实际输入。旧r1—r5、来源、核心代码、原始失败均保留。',
                'frozen_protocol.json绑定源码快照、Git提交、依赖版本及所有消费输入；preparation_audit.json是独立核验凭证。risk_keys.csv、source_bridge_coverage/trace/failures.csv、quote_failures.csv及risk_matrices保留全部覆盖与失败。output_sha256.json封存本轮所有文件。']
        run.save(out/'conclusion.json',dict(**result,live_enablement=False,market_inventory_complete=False,
                   preparation_audit_sha256=run.sha(out/'preparation_audit.json')),exclusive=True)
        with (out/'report.md').open('x',encoding='utf-8') as stream:
            stream.write('\n'.join(lines)+'\n')
        run.verify_inputs(protocol)
        run.save(out/'output_sha256.json',run.fingerprint_stage('output_sha256.json'),exclusive=True)
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
