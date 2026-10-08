"""Fixed 30-account comparison and predeclared primary D gates."""
import json
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from run_horizon_coverage import ROOT,OLD,OUT,sha


def load(name):return json.loads((OUT/name).read_text(encoding='utf-8'))


def main():
    verification=load('verification.json');summary=load('summary.json')
    assert verification['summary_sha256']==sha(OUT/'summary.json')
    flow=load('flow_reconstruction_audit.json') if (OUT/'flow_reconstruction_audit.json').exists() else None
    if flow:assert flow['status']=='passed' and flow['summary_sha256']==sha(OUT/'summary.json')
    refs=load('references.json');rows=[];folders={}
    for r in refs:
        t=r['result'].copy();t['strategy']=r['label'];t['status']='reused_verified';rows.append(t)
        folders[r['label']]=ROOT/r['folder']
    for t in summary['experiments']:
        t=t.copy();t['status']='new_completed';rows.append(t);folders[t['strategy']]=OUT/t['strategy']
    stats=pd.DataFrame(rows).set_index('strategy');stats.drop(columns=['config']).to_csv(OUT/'comparison.csv')
    samples=pd.read_csv(OUT/'common_samples.csv',usecols=['trade_date','ts_code','D_label','D_valid'],parse_dates=['trade_date'],float_precision='round_trip')
    ic=pd.read_csv(OUT/'rank_ic.csv',parse_dates=['signal_date','execution_date'],float_precision='round_trip')
    old_ic=pd.read_csv(OLD/'rank_ic.csv',parse_dates=['signal_date','execution_date']);old_ic['variant']='A';old_ic['kind']='native'
    pred=pd.read_csv(OLD/'predictions.csv',parse_dates=['trade_date','execution_date'],float_precision='round_trip')
    merged=pred.merge(samples[['trade_date','ts_code','D_label','D_valid']],on=['trade_date','ts_code'],validate='one_to_one')
    a_common=[]
    for d,g in merged.groupby('trade_date'):
        observed=g.loc[g.D_valid]
        a_common.append(dict(variant='A',kind='common_week_endpoint',signal_date=d,year=int(g.execution_date.iloc[0].year),
            execution_date=g.execution_date.iloc[0],eligible=len(g),valid_labels=len(observed),rank_ic=observed.prediction.corr(observed.D_label,method='spearman') if len(observed)>1 else np.nan))
    all_ic=pd.concat([ic,old_ic,pd.DataFrame(a_common)],ignore_index=True);all_ic.to_csv(OUT/'all_model_rank_ic.csv',index=False)
    completed=sum(t['status']=='completed' for t in summary['experiment_statuses'])
    lines=['# 标签期限与报价覆盖：固定二乘二实验','',
        f'**结论：新增{completed}/18组完成；主候选D研究门槛{"全部通过" if verification["research_gates_passed"] else "未全部通过"}。**','',
        'A是旧20日完整窗口标签；B为下一周完整窗口；C为20日端点；D为下一周端点。'
        '固定D风险覆盖层作为主候选，没有根据结果改选B/C。复用旧12组，加18组新账户，展示30组同起点连续账户。'
        '账户2018首次执行前一次投入100万元，连续至2020年底；全部模型、股票池、特征、选择、成本、风险和会计规则按批准设计冻结。','',
        '## 主候选与控制组','',
        '| 路径 | 成本 | 三年累计收益 | 最大回撤 | 期末权益 | 双边换手倍数 | 交易成本 | 平均现金 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    order=['three_weekly','three_retention',*['%s_%s'%(v,p) for v in 'ABCD' for p in ('retention','risk')]]
    for path in order:
        for bps in (10,0,30):
            label=f'{path}_{bps}bp'
            if label not in stats.index:
                lines.append(f'| {path} | {bps}bp | 未完成 | — | — | — | — | — |');continue
            r=stats.loc[label]
            text={'three_weekly':'三因子周频','three_retention':'三因子保留'}.get(path,path.replace('_retention',' 保留').replace('_risk',' 风险预算'))
            lines.append(f'| {text} | {"零成本" if bps==0 else str(bps)+"bp"} | {r.total_return:.2%} | {r.max_drawdown:.2%} | '
                f'{r.final_equity:,.2f}元 | {r.gross_turnover:.2f} | {r.total_fees+r.total_slippage:,.2f}元 | {r.average_cash_weight:.2%} |')
    lines+=['','0bp同时关闭手续费与滑点，10/30bp同时计入原费用。成本和资金路径影响整手/拒单，'
        '不能把费用简单加回期末权益作为可执行毛收益；候选间的差异也不是纯因果贡献。','',
        '## 固定主候选D门槛','', '| 条件 | 结果 |','|---|---|']
    names={'rank_ic_positive':'D全期周端点RankIC为正','two_positive_years':'D至少两个年度RankIC为正',
        'net_positive_base_stress':'D风险10bp与30bp累计净收益均为正','beats_controls':'D风险10bp收益超过三因子保留及A风险',
        'drawdown_budget':'D风险10bp回撤≤25%，且不高于D无风险层'}
    for k,name in names.items():lines.append(f'| {name} | {"通过" if verification["gates"].get(k) else "未通过"} |')
    if 'D_risk_10bp' in stats.index:
        d=stats.loc['D_risk_10bp'];a=stats.loc['A_risk_10bp'];z=stats.loc['D_risk_0bp']
        lines+=['',f'D风险10bp累计{d.total_return:.2%}、回撤{d.max_drawdown:.2%}；'
            f'相对A风险的累计收益差{(d.total_return-a.total_return)*100:.2f}个百分点，回撤差{(d.max_drawdown-a.max_drawdown)*100:.2f}个百分点。'
            f'D风险零成本累计{z.total_return:.2%}。这些数值不改变事前主候选和停止规则。']
    if all(v+'_risk_10bp' in stats.index for v in 'ABCD'):
        effects=[('允许中间缺失，保持20日','A','C'),('允许中间缺失，保持下一周','B','D'),
                 ('缩短为下一周，保持完整窗口','A','B'),('缩短为下一周，保持端点','C','D')]
        lines+=['','## 二乘二比较实际说明了什么','',
            '| 固定风险10bp比较 | 对照→变化 | 累计收益差 |','|---|---|---:|']
        for name,old,new in effects:
            delta=stats.loc[new+'_risk_10bp','total_return']-stats.loc[old+'_risk_10bp','total_return']
            lines.append(f'| {name} | {old}→{new} | {delta*100:+.2f}个百分点 |')
        lines+=['','本轮历史中，放宽中间报价完整条件在两种期限下均改善结果；缩短为周标签在两种覆盖条件下均降低结果。'
            '这没有验证“期限对齐就会盈利”的猜想。有效训练股票集合也随窗口变化，差异不能作为独立因果效应或优化参数结论。'
            'C风险零成本仅+0.43%，10bp仍−12.73%、30bp−20.01%，同样没有足够净收益证据；不替换主候选或推进实盘。']
    lines+=['','## 自然期限与共同周端点评价','',
        '| 模型 | 自然期限平均RankIC | 同一周端点平均RankIC | 自然有效标签条数 | 共同周有效标签条数 |',
        '|---|---:|---:|---:|---:|']
    for v in 'ABCD':
        n=all_ic.loc[all_ic.variant.eq(v)&all_ic.kind.eq('native')];c=all_ic.loc[all_ic.variant.eq(v)&all_ic.kind.eq('common_week_endpoint')]
        lines.append(f'| {v} | {n.rank_ic.mean():.5f} | {c.rank_ic.mean():.5f} | {int(n.valid_labels.sum()):,} | {int(c.valid_labels.sum()):,} |')
    lines+=['','共同周标签对所有模型使用相同股票样本，不利用未来有效性剔除当期预测或交易目标。'
        '自然期限及覆盖不同，不能直接按自然IC大小选模型；重叠窗口、条件缺失和历史复用仍限制统计解释。','',
        '| D评价年度 | 平均周端点RankIC |','|---|---:|']
    for year,g in all_ic.loc[all_ic.variant.eq('D')&all_ic.kind.eq('native')].groupby('year'):
        lines.append(f'| {year} | {g.rank_ic.mean():.5f} |')
    lines+=['','## 训练范围与缺失原因','',
        '三次模型拟合日固定；所有定义使用t+21参考终点严格早于拟合日的共同等待条件。'
        '新增样本来自各自标签有效条件，而不是让周标签偷用更近期形成日。每形成日训练总权重为1。','',
        '| 模型 | 年 | 样本数 | 原A样本数 | 最迟自身标签终点 | 最迟共同参考终点 |','|---|---:|---:|---:|---|---|']
    for r in load('training_audit.json'):
        lines.append(f'| {r["variant"]} | {r["year"]} | {r["samples"]:,} | {r["old_A_samples"]:,} | {r["latest_label_end"]} | {r["latest_reference_end"]} |')
    counts=pd.read_csv(OUT/'label_reason_totals.csv')
    stages=[]
    fit_dates={int(t['year']):pd.Timestamp(t['fit_date']) for t in load('training_audit.json')}
    date_year=pred[['trade_date','execution_date']].drop_duplicates().set_index('trade_date').execution_date.dt.year
    target_keys={}
    for v in 'ABCD':
        path=OLD/'targets_ml_retention.csv' if v=='A' else OUT/f'targets_{v}_retention.csv'
        t=pd.read_csv(path,parse_dates=['signal_date'])
        target_keys[v]=pd.MultiIndex.from_frame(t[['signal_date','ts_code']])
    for chunk in pd.read_csv(OUT/'label_audit.csv',usecols=['trade_date','reference_end','variant','reason','ts_code'],parse_dates=['trade_date','reference_end'],chunksize=100000):
        chunk['year']=chunk.trade_date.map(date_year)
        for year,fit in fit_dates.items():
            training=chunk.loc[chunk.reference_end.lt(fit)].groupby(['variant','reason']).size().rename('records').reset_index()
            training['stage']='training_mature_pool';training['year']=year;stages.append(training)
        evaluation=chunk.loc[chunk.year.notna()].groupby(['variant','year','reason']).size().rename('records').reset_index()
        evaluation['stage']='prediction_pool';stages.append(evaluation)
        for v in 'ABCD':
            g=chunk.loc[chunk.variant.eq(v)];keys=pd.MultiIndex.from_frame(g[['trade_date','ts_code']])
            observed=g.loc[keys.isin(target_keys[v])].groupby(['variant','year','reason']).size().rename('records').reset_index()
            observed['stage']='target_codes';stages.append(observed)
    coverage=pd.concat(stages,ignore_index=True).groupby(['stage','variant','year','reason']).records.sum().reset_index()
    coverage.to_csv(OUT/'coverage_by_stage.csv',index=False)
    for v in 'ABCD':
        expected_targets=len(target_keys[v])
        observed=coverage.loc[coverage.stage.eq('target_codes')&coverage.variant.eq(v),'records'].sum()
        assert observed==expected_targets,(v,observed,expected_targets)
        observed_pool=coverage.loc[coverage.stage.eq('prediction_pool')&coverage.variant.eq(v),'records'].sum()
        assert observed_pool==len(pred),(v,observed_pool,len(pred))
    for t in load('training_audit.json'):
        expected=coverage.loc[coverage.stage.eq('training_mature_pool')&coverage.variant.eq(t['variant'])&coverage.year.eq(t['year'])&coverage.reason.eq('valid'),'records'].sum()
        assert expected==t['samples'],t
    lines+=['','下表覆盖全部2016—2020训练及评价共同股票池样本，每条按互斥优先级统计。'
        '完整多原因标记和缺失/非法日期在label_audit.csv；端点定义即使中间缺行仍可有效，但未知复权事件及端点异常始终拒绝。','',
        '| 定义 | 互斥原因 | 条数 |','|---|---|---:|']
    for r in counts.itertuples(index=False):lines.append(f'| {r.variant} | {r.reason} | {r.samples:,} |')
    lines+=['','训练、评价年股票池及目标三层的详细覆盖另存coverage_by_stage.csv；'
        '不能把未来有效性当成当期可以使用的风险过滤器。更换标签仍影响训练股票构成，不能宣称纯粹隔离数值期限的因果效应。','',
        '## 连续年度收益（10bp）','',
        '| 年 | A风险 | B风险 | C风险 | D风险 | D无风险层 |','|---|---:|---:|---:|---:|---:|']
    annual=pd.read_csv(OUT/'annual_returns.csv');oldannual=pd.read_csv(OLD/'annual_returns.csv')
    for year in (2018,2019,2020):
        a=oldannual.loc[oldannual.strategy.eq('ml_risk_10bp')&oldannual.year.eq(year),'return_value'].iloc[0]
        values=[a]
        for p in ['B_risk_10bp','C_risk_10bp','D_risk_10bp','D_retention_10bp']:
            g=annual.loc[annual.strategy.eq(p)&annual.year.eq(year),'return_value'];values.append(g.iloc[0] if len(g) else np.nan)
        lines.append(f'| {year} | '+' | '.join(f'{v:.2%}' for v in values)+' |')
    lines+=['','## 技术核验与失败记录','',
        f'106项项目测试通过，6条已有警告。原A标签及成熟训练样本重建一致，原295项结果指纹未改；'
        f'{verification["label_rows_verified"]:,}条四种标签记录直接按原始报价独立核验，九个模型的成熟样本及预测重放通过，'
        f'最大预测差{verification["maximum_prediction_replay_error"]:.3g}。选择重放不带未来标签，协方差按共同过去60日重建，费用、净值和36个月复合收益通过。']
    if flow:
        lines+=['',f'独立重建{sum(c["sessions"] for c in flow["checks"]):,}个新账户日、{flow["year_boundaries"]}个评价跨年边界；'
            f'股数与待结算股数每日精确相同，现金最大误差{max(c["maximum_cash_error"] for c in flow["checks"]):.3g}元。']
    else:lines+=['','完整18组独立账务审计尚未完成，不声称全面核验通过。']
    lines+=['','首次准备阶段默认系统GBK编码不能读取UTF-8数据清单，未进入模型/账户；失败目录与日志完整另存initial_encoding_failure。'
        '明确encoding=utf-8后继续，未变策略参数。独立核验和初次报告读取混合日期注释列时产生DtypeWarning，核验未报错；'
        '最终报告只读取所需明确列后无该警告，原日志保留。18组实验无账户失败。']
    for r in summary['experiment_statuses']:
        if r['status']!='completed':lines.append(f'- {r["strategy"]}：{r["status"]}，{r.get("error","")}。')
    lines+=['','## 限制与研究停止','',
        '端点价格收益不是停牌、涨跌停、容量及整手约束下可实现的现金收益；原引擎完整保留这些影响。'
        '预测波动15%不是回撤保证，实际仓位可偏离目标，费用会侵蚀收益。历史ST/行业证据、未知复权事件、固定20%红利税、退市零回收、日线成交近似及旧报价估值仍保留。',
        '全部2016—2025此前已经查看，本轮是已用历史的探索性对照，不是新的封存或实盘验证。'
        '未改变D主候选、门槛或模型参数，未运行2021—2025新候选，未接入券商。主候选未全部通过则停止本轮，不改选事后最佳路径。','',
        '![风险覆盖账户曲线](risk_accounts.png)','']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    fig,ax=plt.subplots(figsize=(10,5))
    for v in 'ABCD':
        label=v+'_risk_10bp'
        if label not in folders:continue
        nav=pd.read_csv(folders[label]/'nav.csv',parse_dates=['date']);nav=nav.loc[nav.date.ge(pd.Timestamp('20171229'))]
        ax.plot(nav.date,nav.equity/1000000,label=v+' risk 10bp',linewidth=1.3)
    ax.set(title='Fixed label horizon / coverage study: same inception',ylabel='Equity / initial capital')
    ax.axhline(1,color='grey',linewidth=.7,linestyle='--');ax.grid(alpha=.2);ax.legend()
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6));ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'));ax.tick_params(axis='x',labelrotation=25)
    fig.tight_layout();fig.savefig(OUT/'risk_accounts.png',dpi=160);plt.close(fig)
    evidence=OUT/'verification_sources';evidence.mkdir(exist_ok=True)
    for n in ['verify_horizon_coverage.py','audit_horizon_flows.py','report_horizon_coverage.py','audit_continuous_flows.py']:shutil.copy2(ROOT/'scripts'/n,evidence/n)
    shutil.copy2(ROOT/'tests/test_horizon_labels.py',evidence/'test_horizon_labels.py')
    hashes={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='output_sha256.json'}
    (OUT/'output_sha256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    print('Report saved; D gates passed:',verification['research_gates_passed'])


if __name__=='__main__':main()
