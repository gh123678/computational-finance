"""Exclusive final r4 report and preservation seal. Never starts research."""
from pathlib import Path
import json
import shutil
import pandas as pd

import run_alphaforge_r4 as run


def main():
    out=run.OUT
    with run.exclusive_stage(out,'report'):
        if (out/'output_sha256.json').exists():raise RuntimeError('Existing final seal')
        doc=run.ROOT/'docs/2026-10-19-alphaforge-r4-results.md'
        if doc.exists() or (out/'report.md').exists():raise RuntimeError('Existing final document; never overwrite')
        protocol=run.read_json(out/'frozen_protocol.json');run.verify_inputs(protocol)
        run.verify_stage('preparation_sha256.json');run.verify_stage('accounts_sha256.json')
        preserved=run.preservation()
        statuses=run.read_json(out/'status.json')
        audit_path=out/'verification.json'
        if not audit_path.exists():audit_path=out/'partial_verification.json'
        audit=run.read_json(audit_path)
        assert audit['accounts_manifest_sha256']==run.sha(out/'accounts_sha256.json')
        assert audit['status_sha256']==run.sha(out/'status.json')
        assert audit['summary_sha256']==run.sha(out/'summary.json')
        assert audit['accounts_started']==sum(s['status']!='not_started' for s in statuses)
        assert audit['completed_accounts_verified']==sum(s['status']=='completed' for s in statuses)
        complete=audit['full_six_account_verification_passed']
        lines=['# AlphaForge r4：实际账户范围固定实验结果','',
            '按客户端北京时间2026-10-19记录运行与结果。主人2026-10-18明确“批准”后实施；原r4提案中的待批准字样为保留的历史快照。','',
            '## 终态','',
            f'- 已启动{audit["accounts_started"]}账户，完整完成{audit["completed_accounts_verified"]}/6；独立核对跨年{audit["year_boundaries"]}/12。',
            '- 全市场库存仍为未通过：2806只×790日，原16441条失败完整保留。条件性账户准入不等于数据认证。',
            '- 273794形成键、154期、两条路径目标和R_week诊断逐字引用r3；无重训、重算因子、换股或调参。','',
            '|账户|终态|已完成日|失败|','|---|---|---:|---|']
        for s in statuses:
            lines.append(f'|{s["strategy"]}|{s["status"]}|{s.get("completed_sessions",0)}|{s.get("reason",s.get("error",""))}|')
        lines+=['','## 独立核验与证据','',
            f'核验凭证：`{audit_path.name}`。其status={audit["status"]}。部分证据通过不表示完整六账户通过。',
            '来源映射：`evidence_mapping.json`、`event_mapping_validation.json`。原r3全量库存与失败在`reused_r3`；每个已尝试账户留计划目标、逐日守卫、义务、账本、订单、持仓及失败现场。',
            '源码快照在`source_before`；输入、阶段及最终哈希分别为`frozen_protocol.json`、`preparation_sha256.json`、`accounts_sha256.json`与`output_sha256.json`。',
            f'保护清单成员总计{sum(x["count"] for x in preserved)}（原1924+r3 105+补证493），本轮末尾逐文件重验。','',
            '## 与r3的边界比较','',
            'r3全市场任何失败即不开户，结果0账户。r4获明确批准后保留这些失败，现金零股份起步，仅对真实敞口、活动义务与拟成交做硬门；价格缓存不为未持有股票虚构资产。卖出后的现金应收保留，尚未执行股份权利仍需价格。跨缺价普通分派只准已核三项，未知项仍停。',
            '600480仅补配股日期身份，无认购条款注入；9股状态按公开时点推进，不用后来恢复回填。所有源金额、理论陈旧估值与观测参考分别记录，不认证交易所精确参考价或托管到账。','',
            '## 绩效与启用限制','']
        if complete:
            summary=run.read_json(out/'summary.json')
            lines+=['|账户|净收益|最大回撤|费用/元|滑点成本/元|累计换手|',
                    '|---|---:|---:|---:|---:|---:|']
            for item in summary['experiments']:
                orders=pd.read_csv(out/item['strategy']/'orders.csv')
                nav=pd.read_csv(out/item['strategy']/'nav.csv')
                lines.append(f'|{item["strategy"]}|{item["total_return"]:.4%}|{item["max_drawdown"]:.4%}|{orders.fee.sum():.2f}|{orders.slippage_cost.sum():.2f}|{nav.turnover.sum():.4f}|')
            lines+=['','年度收益见`annual_returns.csv`；逐日实际净值、持仓和费用分别保留在各账户目录。','']
            lines.append('六账户完整后评估冻结关卡：'+json.dumps(audit['gates'],ensure_ascii=False)+'。')
        else:
            lines.append('首次失败按冻结规则终止整组；剩余账户未启动。完整净收益/成本比较、回撤/年收益与六项研究关卡未评估；已完成部分净值不能当作三年绩效。冻结IC是参考诊断，不能当作现金账户收益。')
        ic=pd.read_csv(out/'reused_r3/factor_ic_summary.csv')
        selected=ic.loc[ic.factor.eq('case_signal') & ic.period.astype(str).eq('all')]
        if len(selected)==1:
            lines+=['',f'引用冻结R_week主信号平均RankIC={selected.rank_ic_mean.iloc[0]:.12f}，有效{int(selected.rank_ic_n.iloc[0])}期；分层与年度诊断保留在reused_r3/factor_groups.csv和factor_ic_summary.csv，未重新挑选。']
        lines+=['','实盘保持`blocked_by_unverified_data_and_forward_validation`，未连接券商。全市场历史身份、经济条款及独立前向验证仍未完成；本轮是条件性回顾单案例，不是可启用策略。','']
        report='\n'.join(lines)
        with (out/'report.md').open('x',encoding='utf-8') as stream:stream.write(report)
        with doc.open('x',encoding='utf-8') as stream:stream.write(report)
        logs=out/'logs';logs.mkdir()
        for source in run.RUNTIME_LOGS.glob('*.log'):
            if source.name!='report.log':shutil.copy2(source,logs/source.name)
        run.persist(out/'final_preservation_check.json',dict(status='passed',manifests=preserved),exclusive=True)
        run.persist(out/'output_sha256.json',{p.relative_to(out).as_posix():run.sha(p) for p in out.rglob('*')
            if p.is_file() and p.name!='runner.lock'},exclusive=True)
        print('r4 report',str(doc),'final manifest',run.sha(out/'output_sha256.json'),flush=True)


if __name__=='__main__':main()
