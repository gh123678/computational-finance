"""Close the fixed r2 experiment after a genuine account data guard stopped it.

Reads existing evidence only. It neither reruns an account nor grants the
successful six-account verification or unobservable primary performance.
"""
from pathlib import Path
from datetime import datetime
import json
import shutil

import pandas as pd

from run_alphaforge_r2 import OUT, ROOT, PATHS, verify_inputs, sha

DOC=ROOT/'docs/2026-10-16-alphaforge-r2-results.md'


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def pct(value):
    return f'{float(value):.2%}'


def main():
    if (OUT/'report.md').exists() or DOC.exists():
        raise RuntimeError('Existing closeout report; do not overwrite')
    assert not (OUT/'runner.lock').exists()
    protocol=read('frozen_protocol.json')
    protected=verify_inputs(protocol)
    preparation=read('preparation_audit.json')
    assert preparation['status']=='passed'
    assert sha(ROOT/'scripts/verify_alphaforge_r2.py')==preparation['verifier_sha256']
    stage=read('experiment_stage.json')
    summary=read('summary.json')
    statuses=summary['experiment_statuses']
    assert stage['state']=='failed' and len(statuses)==6
    failed=[s for s in statuses if s['status']=='failed']
    complete=[s for s in statuses if s['status']=='completed']
    assert len(failed)==len(complete)==3
    assert {s['strategy'] for s in failed}=={f'{PATHS[0]}_{c}bp' for c in (0,10,30)}
    assert {s['strategy'] for s in complete}=={f'{PATHS[1]}_{c}bp' for c in (0,10,30)}
    for item in failed:
        assert item['error']=='Unexplained corporate action for held 000998.SZ on 2020-01-02'
        assert not (OUT/item['strategy']/'nav.csv').exists()
        assert item['error'] in (OUT/item['strategy']/'failure.txt').read_text(encoding='utf-8')
    assert not (OUT/'verification.json').exists()
    partial=read('partial_account_audit.json')
    assert partial['status']=='passed' and partial['completed_accounts_verified']==3
    assert partial['failed_primary_accounts']==3 and partial['year_boundaries']==6
    assert partial['full_six_account_verification_passed'] is False
    assert partial['research_gates_assessable'] is False
    feature=read('feature_summary.json')
    ic=pd.read_csv(OUT/'factor_ic_summary.csv',dtype={'period':str})
    signal=ic.loc[ic.factor.eq('case_signal')]
    overall=signal.loc[signal.period.eq('all')].iloc[0]
    years=signal.loc[signal.period.ne('all')]
    assert set(years.period)=={'2018','2019','2020'}
    evidence=OUT/'failure_evidence'
    assert evidence.is_dir() and any(evidence.iterdir())
    figure_names=[('factor_ic.png','IC与RankIC；累计相关系数不是净值'),
        ('factor_groups.png','固定五组的未扣费未来超额收益'),
        ('factor_coverage.png','形成与标签覆盖、排除原因'),
        ('control_accounts_only.png','仅三个已完成对照账户；主候选没有净值')]
    for name,_ in figure_names:
        assert (OUT/'figures'/name).is_file()
    lines=['# AlphaForge r2：准备通过，主账户被数据守卫中止','',
        '**本轮按停止规则结案。三个主候选账户均失败，尚无完整主候选净值或收益结论，策略不能启用。**',
        'r2解除了r1的形成池覆盖阻断，但未解除原有持仓账务守卫。工程准备正确、局部账本正确与完整策略通过是不同结论。','',
        f'生成时间：{datetime.now().astimezone().isoformat(timespec="seconds")}。用户“继续”确认r2后实施；原r1及旧结果保留。','',
        '## 完成情况','',
        '- 127项相关测试通过（77项r2新增、50项原案例回归）；两条既有pandas FutureWarning及pytest配置弃用提示保留。',
        f"- 全154期准备：{feature['original_rows']:,}条候选，{feature['common_rows']:,}条有效，每期最少{feature['minimum_formed']:,}只，固定200只门槛未降低。",
        f"- 独立重算全部资格、{preparation['feature_rows_checked']:,}条有效公式及{preparation['reference_transition_rows_checked']:,}条内部转换；最大因子误差{preparation['maximum_factor_error']:.3e}。",
        '- 六个固定账户均已尝试：三个主候选失败，三个同池旧三因子对照完成；未重跑失败主账户。',
        '- 对三个已完成对照独立重建账务及六个跨年边界通过；完整六账户与十二跨年核验没有完成，不写成功verification.json。','',
        '## 为什么本次仍不能运行到底','',
        '三个主候选的相同错误是：`Unexplained corporate action for held 000998.SZ on 2020-01-02`。',
        '原始复权系数在2019-12-31至2020-01-02由11.267降至10.97，变化约−2.6360%，超过原账务守卫0.5%的阈值，已有行动登记未解释该区间。',
        '该守卫在当日开盘交易与公司行动处理之前检查非零持股，所以目标层的新过滤无法在未知事件发生前消除已有持仓风险。形成后的隔离也不能回到过去改变买入。',
        '原价参考连续或缓存没有匹配行动，都不足以证明供应商错误或不存在真实行动。本轮没有认证这个断点，也没有删除该日、事后拉黑整只股票、提高阈值或绕过守卫。',
        '模拟器在抛错前仅保有内存账本，失败路径没有保存中断前NAV或持股数。错误可证明触发时持股非零，但不能据此补造股数、半程收益或完整账户业绩。','',
        '| 路径 | 0bp | 10bp | 30bp |','|---|---|---|---|',
        '| 主候选 −f | 同一数据守卫失败 | 同一数据守卫失败 | 同一数据守卫失败 |',
        '| 同池三因子对照 | 完成且局部核验 | 完成且局部核验 | 完成且局部核验 |','',
        '## 公式、股票池与历史边界','',
        '来源为AlphaForge作者预印本v5第6页表2第5号表达式，作者源码固定提交`d0cfc27df23c60f271bc885fd43027b86b787746`。本轮仅复现公开单公式并作本地适配，不复现完整挖掘框架或论文业绩。',
        '公开表达式为`f = S_log1p(ts_min(ts_corr(close, volume, 10), 1))`，长度1的最小值不改变当前有限值。`f = sign(rho) × log1p(abs(rho))`，rho为10个原始收盘价与成交股数的相关算子；任一去均值平方和严格小于1e−6时分母改1，不裁剪rho。价格单位元、原vol乘100转成股；信号预先固定为−f，使用平均同分百分位。',
        '窗口包含形成日共10个开市日、内部9次转换。原CSV close/pre_close用Decimal精确比较，参考缺失或变化、已在截止前公开并生效的登记行动排除；孤立系数变化只作标记。原common200较长未知行动隔离保留。',
        f"r1有效269,138条；共同有效{feature['r1_intersection_rows']:,}条的原公式值完全不变。新增4,721条，原有效转无效65条（59条已知行动、6条原价参考变化）。四个原失败日r2实际覆盖1,353／1,250／1,211／1,178。",
        '原核心仍含000998的2018-08-23／24／27三个报价日正系数替换10.8142→11.1070，原CSV未修改。该既有替换保持有限正值，不改变r2原价公式或资格；不构成对2020年新断点的解释。',
        '事件清单10,148行：10,097条实施分红采用imp_ann_date，51条配股无独立认证公开日，仅记风险；51条未命中本轮10日形成窗口。日级字段不认证日内公开时间或不可修订历史版本。',
        f"本地float64与作者torch.float精度不同。每只股票预先取首个有效窗口共{feature['precision_windows']:,}个，float64／float32最大因子差{feature['maximum_float_precision_difference']:.3e}；这不是原Qlib数据或全部结果位级一致性认证。有效形成中epsilon分支实际0条，常量／微方差边界由单元测试覆盖。",
        '2016—2025历史此前已查看，2018—2020仅是回顾性开发；本轮不恢复独立样本外身份。财务历史身份仍未批准，不消费财务预测因子；公司行动字段确实用于过滤及账务。','',
        '## IC、RankIC与分层诊断','',
        'D标签是下一周开盘至再下一周开盘的个股复权收益减同期基准收益，未扣交易费。先按形成信息确定资格／五组，再连接标签；最后一期标签未成熟，154期中153期可计算相关。',
        'IC为Pearson、RankIC为平均同分排名相关，ICIR／RankICIR以样本标准差ddof=1计算，不年化；累计相关系数不是账户净值。','',
        '| 固定负信号期间 | IC均值 | ICIR | RankIC均值 | RankICIR | 有效期数 |',
        '|---|---:|---:|---:|---:|---:|']
    for period in ('all','2018','2019','2020'):
        row=signal.loc[signal.period.eq(period)].iloc[0]
        lines.append(f'| {"全期" if period=="all" else period} | {row.ic_mean:.6f} | {row.ic_ir:.4f} | {row.rank_ic_mean:.6f} | {row.rank_ic_ir:.4f} | {int(row.rank_ic_n)} |')
    lines+=['','负号信号全期和三个年度平均RankIC为正，符合两项IC诊断条件；四项主账户收益／对照／回撤／年度收益关卡缺少完整主账本，无法评估。策略不获通过，不能用IC或对照收益代替缺失关卡。','',
        '## 已完成对照账户（不晋升为主候选）','',
        '100万元、周频、跨年连续股份账户，20只目标、单股4.9%、行业上限、留仓gap及五只主动换股规则均保持。0bp关闭费用／滑点，10／30bp沿原历史费率加对应滑点，不称2026现行费率。',
        '以下仅为三个对照实际净值结果；累计收益与年化不同，净值已扣费用，不再次扣成本。','',
        '| 对照成本 | 三年累计净收益 | 年化净收益 | 最大回撤 | 费用元 | 滑点元 |',
        '|---|---:|---:|---:|---:|---:|']
    stats={e['strategy']:e for e in summary['experiments']}
    for cost in (0,10,30):
        row=stats[f'{PATHS[1]}_{cost}bp']
        lines.append(f"| {cost}bp | {pct(row['total_return'])} | {pct(row['annualized_return'])} | {pct(row['max_drawdown'])} | {row['total_fees']:,.2f} | {row['total_slippage']:,.2f} |")
    lines+=['','真实换手、逐年收益、拒单及重建误差见局部审计文件。原ST／行业覆盖、日线成交近似、红利税、退市零回收与停牌旧估值限制继续保留。','',
        '## 失败证据、执行中断与下一步','',
        '准备核验于13:11完成；后续编排因AI服务使用额度中断，未启动账户。16:56恢复后检查无同类研究进程，再单次启动账户；这段等待是服务中断，不是数据核验失败。',
        '冻结前修复了原CSV缺失词法保留问题；一个新增测试入口最初缺scripts导入路径，修复后127项通过。正式准备一次完成；正式账户一次尝试后按真实失败停止。',
        '下一步先交叉核对000998在2020-01-02的供应商原缓存、原价连续性与公司公告，区分数据修订和真实行动。任何涉及冻结行情映射、未知行动政策或原账务守卫的改动，都应另立可审阅修订，不能在本r2中默默放行。',
        f"旧四套共{sum(protected.values()):,}项产物指纹再次通过，原r1、旧行情及失败日志不改。该固定实验结束后关闭本轮自动跟进；整体策略目标尚未达成，未连接券商。",'']
    for filename,caption in figure_names:
        lines += [f'![{caption}]({(OUT/"figures"/filename).resolve().as_posix()})','',caption+'。','']
    lines+=['## 核查入口','']
    entries=[('准备独立审计',OUT/'preparation_audit.json'),('局部账户审计',OUT/'partial_account_audit.json'),
        ('逐年覆盖',OUT/'coverage_by_year.csv'),('资格差异',OUT/'r1_pool_comparison.csv'),
        ('六组终态',OUT/'status.json'),('主账户失败证据',evidence),
        ('原始逐转换记录',OUT/'reference_transitions.csv'),('分层记录',OUT/'factor_groups.csv'),
        ('局部年度收益',OUT/'partial_annual_returns.csv'),('局部真实交易与换手',OUT/'partial_account_operations.csv'),
        ('批准和实施记录',ROOT/'docs/superpowers/plans/2026-10-16-alphaforge-r2-implementation.md')]
    for label,path in entries:
        assert path.exists(),str(path)
        lines.append(f'- [{label}]({path.resolve().as_posix()})')
    text='\n'.join(lines)+'\n'
    (OUT/'report.md').write_text(text,encoding='utf-8');DOC.write_text(text,encoding='utf-8')
    result=dict(state='closed_data_guard_failure',completed_accounts=3,failed_primary_accounts=3,
        preparation_passed=True,partial_completed_account_audit_passed=True,full_six_account_audit_passed=False,
        research_qualified=False,complete_primary_returns_available=False,research_gates_fully_assessable=False,
        mean_rankIC=float(overall.rank_ic_mean),positive_rankIC_years=int(years.rank_ic_mean.gt(0).sum()),
        prior_artifacts_verified=protected,broker_connected=False,report=str(DOC),
        inputs_sha256={name:sha(OUT/name) for name in ['preparation_audit.json','partial_account_audit.json',
            'feature_summary.json','factor_ic_summary.csv','summary.json','status.json']},
        report_source_sha256=sha(Path(__file__)))
    (OUT/'closeout.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(DOC)


if __name__=='__main__':main()
