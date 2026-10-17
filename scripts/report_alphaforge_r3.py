"""Report the actual fixed r3 terminal stage, including honest pre-account stops."""
import json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/alphaforge_case_2018_2020_r3'
REPORT=ROOT/'docs/2026-10-17-alphaforge-r3-results.md'


def read(name, default=None):
    p=OUT/name
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def diagnostic_figures():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    folder=OUT/'figures';folder.mkdir(exist_ok=True)
    ic=pd.read_csv(OUT/'factor_ic.csv',parse_dates=['execution_date'])
    groups=pd.read_csv(OUT/'factor_groups.csv')
    names={'case_signal':'固定负方向案例','three_score':'新参考价三因子对照'}
    fig,axes=plt.subplots(1,2,figsize=(13,4.5),layout='constrained')
    for factor,label in names.items():
        frame=ic.loc[ic.factor.eq(factor)].sort_values('execution_date')
        axes[0].plot(frame.execution_date,frame.rank_ic,label=label,alpha=.7)
        axes[1].plot(frame.execution_date,frame.rank_ic.cumsum(),label=label)
    axes[0].set_title('R_week每周RankIC');axes[1].set_title('RankIC累加，仅相关系数诊断')
    for ax in axes:ax.axhline(0,color='grey',lw=.6);ax.legend();ax.grid(alpha=.2)
    fig.suptitle('参考价口径标签，不是账户收益或净值')
    fig.savefig(folder/'reference_rank_ic.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    for ax,(factor,label) in zip(axes,names.items()):
        subset=groups.loc[groups.factor.eq(factor)]
        avg=subset.groupby('group').mean_forward_return.mean().reindex([1,2,3,4,5])
        ax.bar(avg.index,avg.values*100);ax.axhline(0,color='grey',lw=.6)
        ax.set_xticks([1,2,3,4,5]);ax.set_title(label);ax.set_ylabel('组内有效周标签均值（%）')
    fig.suptitle('固定五层R_week超额均值：未扣费、非真实组合收益')
    fig.savefig(folder/'reference_groups.png',dpi=150);plt.close(fig)
    return [folder/'reference_rank_ic.png',folder/'reference_groups.png']


def main():
    if (OUT/'output_sha256.json').exists():
        raise RuntimeError('Evidence already finalized; do not overwrite report')
    stage=read('experiment_stage.json',{})
    prep=read('preparation_status.json',{})
    guard=read('guard_summary.json',{})
    statuses=read('status.json',[])
    failure=read('last_failure.json',{})
    full=read('verification.json',{})
    protocol=read('frozen_protocol.json',{})
    if not protocol or stage.get('state') not in {'blocked_guard','failed_data','failed_accounts','completed'}:
        raise RuntimeError('No reviewed terminal research stage; do not close an incomplete engineering run')
    lines=['# AlphaForge r3固定研究结果','',
        '用户于2026-10-17在具体设计和批准问题后回复“继续”，批准完整有预检硬门的条件性研究。原r1/r2及数据、源码和失败保留。','',
        '**本页仅报告实际阶段。实盘启用保持关闭，参考价收益不等于股份账户总收益。**','',
        f'- 准备状态：{prep.get("state","not_started")}。',
        f'- 守卫预检：{guard.get("passed","not_completed")}。',
        f'- 实际账户尝试：{len(statuses)}／6；完成{sum(s.get("status")=="completed" for s in statuses)}组。',
        f'- 终态：{stage.get("state","preparation_incomplete")}。','']
    if guard:
        lines+=['## 数据预检观察','',
            '预检扫描固定证券完整账户日历，按冻结上市／退市日期、逐日停牌、原价参考和已登记现金／股份行动检查；不按实际持仓筛异常，也不以孤立A变化作新经济判定。',
            '具体字段和计数以[guard_summary.json]('+str((OUT/'guard_summary.json').resolve()).replace('\\','/')+')为准：','',
            '```json',json.dumps(guard,ensure_ascii=False,indent=2),'```','']
    if not statuses:
        lines+=['六账户未启动；没有主候选实际净值、收益、费用、回撤或十二跨年完成结论。准备的参考价标签／IC即使存在，也不能冒充实际账户收益。','']
    elif statuses:
        lines+=['## 六账户真实终态','','|账户|状态|原因|','|---|---|---|']
        for row in statuses:
            error=row.get('error','').replace('|','/').replace('\n',' ')
            lines.append(f'|{row["strategy"]}|{row["status"]}|{error}|')
        lines+=['']
        summary=read('summary.json',{})
        completed=summary.get('experiments',[])
        if completed:
            lines+=['仅以下已完成账户有实际股份账本结果；成本已经在净值内。','','|账户|累计净收益|最大回撤|费用元|滑点元|','|---|---:|---:|---:|---:|']
            for row in completed:
                lines.append(f'|{row["strategy"]}|{row["total_return"]:.4%}|{row["max_drawdown"]:.4%}|{row["total_fees"]:.2f}|{row["total_slippage"]:.2f}|')
            lines+=['']
    if read('preparation_audit.json',{}).get('status')=='passed' and (OUT/'factor_ic_summary.csv').exists():
        stats=pd.read_csv(OUT/'factor_ic_summary.csv',dtype={'period':str})
        lines+=['## 参考价标签诊断','','标签为R_week，先固定形成记录和分层再连接未来数据；缺标签不影响主计划目标。','','|信号|期间|有效周数|平均IC|平均RankIC|','|---|---|---:|---:|---:|']
        for row in stats.loc[stats.factor.isin(['case_signal','three_score'])].itertuples(index=False):
            lines.append(f'|{row.factor}|{row.period}|{row.rank_ic_n}|{row.ic_mean:.6f}|{row.rank_ic_mean:.6f}|')
        lines+=['']
        for path in diagnostic_figures():
            lines+=['![R_week参考价诊断，非账户收益]('+path.resolve().as_posix()+')','']
    if failure:
        lines+=['## 真实失败','',f'失败发生于{failure.get("stage")}阶段；完整错误：[日志]('+str((OUT/failure['failure']).resolve()).replace('\\','/')+')。数据覆盖／策略关卡失败按冻结规则停止，不重跑失败研究、缩池或修改规则。','']
    if full.get('status')=='passed':
        lines+=['## 固定数值关卡','',
            '本轮数值关卡结论：'+('全部通过' if full.get('research_gates_passed') else '未全部通过')+'；数据认证与前向评价的启用门仍关闭。','',
            '|关卡|结果|','|---|---|']
        for name,value in full.get('gates',{}).items():lines.append(f'|{name}|'+('通过' if value else '失败')+'|')
        lines+=['']
    lines+=['## 核验与限制','',
        f'- 独立准备核验：{read("preparation_audit.json",{}).get("status","not_completed")}。',
        f'- 独立守卫核验：{read("guard_audit.json",{}).get("status","not_completed")}。',
        f'- 完整账户核验：{full.get("status","not_completed")}。',
        '- 固定母池间接依赖旧A资格与隔离，新R_week完整内部桥与旧D端点标签不同；同源pre_close、行动经济覆盖、历史版本和公告日内时间未全量认证。',
        '- 已登记行动及原不认购／固定红利税／陈旧估值／退市零回收均是研究场景，不是完整真实交易权利保证。',
        '- 原公式、负方向、10日、200只及成本／留仓／行业规则不调整；主计划目标须精确保持r2，独立前向评价未完成。','',
        '方案：[批准设计]('+str((ROOT/'docs/superpowers/specs/2026-10-16-alphaforge-reference-r3-design.md')).replace('\\','/')+')；批准和执行顺序：[实施记录]('+str((ROOT/'docs/superpowers/plans/2026-10-17-alphaforge-r3-implementation.md')).replace('\\','/')+')。']
    text='\n'.join(lines)+'\n'
    REPORT.write_text(text,encoding='utf-8');(OUT/'report.md').write_text(text,encoding='utf-8')
    (OUT/'closeout.json').write_text(json.dumps(dict(status=stage.get('state','preparation_incomplete'),
        accounts_started=len(statuses),accounts_completed=sum(s.get('status')=='completed' for s in statuses),
        full_verification_passed=full.get('status')=='passed',live_enablement=False,
        approved_scope_completed=True,scope='fixed experiment terminal outcome; overall usable strategy remains incomplete'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(REPORT),flush=True)


if __name__=='__main__':main()
