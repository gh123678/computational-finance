"""Report fixed study results, audit evidence and unchanged research gates."""
import hashlib
import json
import shutil
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/open_source_ml_risk_2018_2020_r1'
NAMES={'three_weekly':'三因子周频','three_retention':'三因子保留',
       'ml_retention':'ML保留','ml_risk':'ML保留加风险预算'}


def read_json(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def main():
    summary=read_json('summary.json');verification=read_json('verification.json')
    digest=hashlib.sha256((OUT/'summary.json').read_bytes()).hexdigest()
    assert verification['summary_sha256']==digest
    flow_path=OUT/'flow_reconstruction_audit.json'
    flow=read_json(flow_path.name) if flow_path.exists() else None
    if flow:
        assert flow['status']=='passed' and flow['summary_sha256']==digest
    stats=pd.DataFrame(summary['experiments']).set_index('strategy')
    stats.drop(columns=['config']).to_csv(OUT/'comparison.csv')
    ic=pd.read_csv(OUT/'rank_ic.csv');risk=pd.read_csv(OUT/'risk_budget.csv')
    annual=pd.read_csv(OUT/'annual_returns.csv').pivot(index='year',columns='strategy',values='return_value')
    predictions=pd.read_csv(OUT/'predictions.csv')
    universe=predictions.loc[predictions.label_valid].groupby('trade_date').label.mean()
    diagnostics=[]
    for p in ['three_weekly','three_retention','ml_retention']:
        target=pd.read_csv(OUT/f'targets_{p}.csv')[['signal_date','ts_code']]
        labels=target.merge(predictions,left_on=['signal_date','ts_code'],
                            right_on=['trade_date','ts_code'],validate='one_to_one')
        assert len(labels)==len(target) and not labels.duplicated(['signal_date','ts_code']).any()
        for d,g in labels.groupby('signal_date'):
            observed=g.loc[g.label_valid]
            mean=observed.label.mean()
            diagnostics.append(dict(path=p,signal_date=d,targets=len(g),valid_labels=len(observed),
                                    selected_excess_label=mean,universe_excess_label=universe.get(d,float('nan')),
                                    selected_universe_gap=mean-universe.get(d,float('nan'))))
    diagnostics=pd.DataFrame(diagnostics)
    diagnostics.to_csv(OUT/'selection_label_diagnostics.csv',index=False)
    completed=sum(s['status']=='completed' for s in summary['experiment_statuses'])
    success=verification['research_gates_passed']
    lines=['# 开源启发价量模型与风险预算：固定开发期实验','',
           f'**结论：{completed}/12组完成；事前研究门槛{"全部通过" if success else "未全部通过"}。**','',
           '本轮按用户已确认设计执行。LightGBM每年扩展训练，只使用拟合日前已成熟的20日开盘超额价格标签；'
           '固定12个价量特征、固定模型参数及15%预测波动预算，未扫描参数、未改变原执行会计核心。'
           '四条路径均在2018年首次执行前一次投入100万元，连续至2020年底。','',
           '## 相同起点、相同股票池的十二组结果','',
           '| 路径 | 单边滑点 | 累计收益 | 最大回撤 | 期末权益 | 双边换手倍数 | 交易成本 | 平均现金比例 |',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for p in NAMES:
        for bps in (10,0,30):
            label=f'{p}_{bps}bp'
            if label not in stats.index:
                lines.append(f'| {NAMES[p]} | {bps}bp | 未完成 | — | — | — | — | — |');continue
            r=stats.loc[label]
            lines.append(f'| {NAMES[p]} | {"零交易成本" if bps==0 else str(bps)+"bp"} | {r.total_return:.2%} | '
                         f'{r.max_drawdown:.2%} | {r.final_equity:,.2f}元 | {r.gross_turnover:.2f} | '
                         f'{r.total_fees+r.total_slippage:,.2f}元 | {r.average_cash_weight:.2%} |')
    lines+=['','10/30bp同时计入原手续费，零成本同时关闭手续费及滑点；不同资金路径会影响整手成交及拒单。'
            '成本为实际累计手续费与滑点，不能简单加回期末权益作为可执行毛收益。'
            '全部路径要求连续61个完整报价日，股票池比旧21日报价条件更严格；不能把与旧实验的全部变化归因于模型。','',
            '## 为什么研究门槛仍未通过','',
            'ML风险预算10bp累计−19.42%，虽比ML无风险层−35.10%改善，但低于三因子保留−15.48%；'
            '30bp仍−26.54%。ML无风险层零成本仍−18.37%，风险层零成本仍−7.74%，因此不能把本轮亏损全部归咎于交易成本。'
            '风险层降低暴露与回撤，不能自动补足收益来源。','',
            '平均RankIC为正与真实账户亏损同时存在。RankIC评价数千只股票的整体排序；最终账户只持少量股票，'
            '并受保留门槛、行业、周频调仓及成交限制影响。模型目标是未来20日相对指数的毛价格收益，'
            '不等同于周频调整后的现金账户净收益。以下仅是当期目标的可观察未来标签，不是可交易组合：','',
            '| 当期目标路径 | 有效标签/目标数 | 每截面平均20日毛价格超额标签 | 相对共同池平均标签差 |',
            '|---|---:|---:|---:|']
    for p,g in diagnostics.groupby('path',sort=False):
        lines.append(f'| {NAMES[p]} | {int(g.valid_labels.sum())}/{int(g.targets.sum())} | '
                     f'{g.selected_excess_label.mean():.3%} | {g.selected_universe_gap.mean():.3%} |')
    lines+=['','标签重叠且缺失部分可能与停牌/异常有关，未补值；缺失覆盖率不同，不能据此给出因果归因或可实现盈利。'
            '当前证据表明排序指标没有转化为账户盈利；尚未通过消融验证区分市场风险、标签与持有期限差异、选择约束及成交偏差的贡献。','',
            '## 预测覆盖与时间隔离','',
            f'共{len(ic)}个预测截面，全期平均RankIC为{verification["mean_rank_ic"]:.5f}；'
            f'可观察未来标签{int(ic.valid_labels.sum()):,}/{int(ic.eligible.sum()):,}条'
            f'（{ic.valid_labels.sum()/ic.eligible.sum():.2%}）。标签缺失不取消当期预测或交易。','',
            '| 评价年 | 平均RankIC | 有效标签覆盖率 |','|---|---:|---:|']
    for year,g in ic.groupby('year'):
        lines.append(f'| {year} | {g.rank_ic.mean():.5f} | {g.valid_labels.sum()/g.eligible.sum():.2%} |')
    lines+=['','RankIC衡量未来毛价格超额排序，未含实际成交成本、红利现金、约束及拒单。'
            '20日标签重叠，未假定各周独立，也未用普通独立样本显著性检验宣称稳定盈利。'
            '尾部标签仅用至2020年底的价格；没有为本轮打开2021年标签。','',
            '| 模型年 | 拟合日 | 成熟样本数 | 最迟标签终点 |','|---|---|---:|---|']
    for r in verification['training_checks']:
        lines.append(f'| {r["year"]} | {r["fit_date"]} | {r["samples"]:,} | {r["latest_label_end"]} |')
    lines+=['','训练只使用周频形成日样本，每日总样本权重为1；每年拟合一次后冻结，未使用随机分割、早停或网格搜索。',
            '未知复权异常事件日起至后续60个交易日（共61日）隔离，窗口缺失不填补。','',
            '## 风险覆盖层及收益取舍','',
            f'风险缩放发生于{int(risk.scale.lt(1).sum())}/{len(risk)}个形成日；'
            f'平均缩放{risk.scale.mean():.4f}、最小缩放{risk.scale.min():.4f}，平均目标现金{risk.target_cash.mean():.2%}。'
            f'基础目标预测年化波动范围{risk.forecast_volatility.min():.2%}—{risk.forecast_volatility.max():.2%}。',
            'LedoitWolf使用60个共同日收益；只统一缩小同一ML目标股票权重，不加杠杆。15%是预测波动预算，不能保证实际波动或回撤。']
    if 'ml_risk_0bp' in stats.index and 'ml_retention_0bp' in stats.index:
        r=stats.loc['ml_risk_0bp'];b=stats.loc['ml_retention_0bp']
        lines+=['',f'零成本下风险层相对ML保留的累计收益差为{(r.total_return-b.total_return)*100:.2f}个百分点，'
                f'最大回撤差为{(r.max_drawdown-b.max_drawdown)*100:.2f}个百分点。'
                '这是整个风险缩放和成交路径的比较，不是对现金机会成本的单独因果估计。现金收益沿用原引擎假设。']
    lines+=['','## 事前固定研究门槛','', '| 条件 | 结果 |','|---|---|']
    labels={'rank_ic_positive':'全期平均RankIC为正',
            'positive_ic_at_least_two_years':'至少两个年度平均RankIC为正',
            'base_and_stress_net_positive':'风险路径10bp与30bp累计净收益均为正',
            'beats_three_retention':'风险路径10bp收益超过同起点三因子保留',
            'drawdown_budget':'风险路径10bp回撤不超过25%，且不高于ML无风险层'}
    for key,label in labels.items():
        state=verification['gates'].get(key)
        lines.append(f'| {label} | {"未完成评价" if state is None else "通过" if state else "未通过"} |')
    lines+=['','技术核验与研究收益门槛分别判断；门槛没有根据结果调整或豁免。','',
            '## 连续年度收益（10bp）','',
            '| 年份 | 三因子周频 | 三因子保留 | ML保留 | ML风险预算 |','|---|---:|---:|---:|---:|']
    for year,r in annual.iterrows():
        lines.append(f'| {year} | '+' | '.join(f'{r.get(p+"_10bp",float("nan")):.2%}' for p in NAMES)+' |')
    lines+=['','## 技术核验与失败证据','',
            f'项目测试101项通过（6项新特征、时间隔离、风险及模型重载测试），6条已有警告。'
            f'模型重放最大预测误差{verification["maximum_prediction_replay_error"]:.3g}。'
            f'训练标签成熟性、原核心/输入/模型指纹、目标代码与权重、行业目标约束、费用和逐日净值核验状态：{verification["status"]}。']
    lines+=['','独立目标重放剔除全部未来标签和未来日期注释后，四条路径目标股票与权重仍完全一致；这些注释未参与选择。']
    if flow:
        lines+=['',f'独立现金/应收/股数/待结算股份重建：{sum(r["sessions"] for r in flow["checks"]):,}个账户日、'
                f'{flow["year_boundaries"]}个评价期跨年边界通过；股数逐日精确一致，现金最大误差'
                f'{max(r["maximum_cash_error"] for r in flow["checks"]):.3g}元。']
    else:
        lines+=['','全部十二组独立账务重建尚未通过或不可完成，不能声称全面账务审计完成。']
    lines+=['','首轮风险测试因本机SciPy计算未使用的精度矩阵触发Windows原生异常0xc06d007e；'
            '根据官方文档关闭store_precision后，相同LedoitWolf协方差及风险约束测试通过。具体缺失DLL未定位，不声称全局依赖已修复。'
            '首轮实验在2018模型原生文件保存接口报“not available for writes”，工作区含中文路径；'
            '改用官方model_to_string及Python文件写入、model_str加载后，中文路径重载预测完全一致，三模型保存成功。'
            '失败准备目录及日志另存initial_model_save_failure，未覆盖。',
            '全量测试首次误收集旧提交包同名测试，产生24项收集冲突；明确当前tests目录后101项通过。'
            '进程清单查询因系统权限拒绝，已有启动会话确认退出、研究锁检查后才重启。所有实际日志保留。',
            '选择标签诊断首个只读合并因同名label_valid列被自动加后缀而失败，改为只取目标日期和股票键后核对成功；未改实验输出。',
            '模型保存与重载方法参考[LightGBM官方文档](https://lightgbm.readthedocs.io/en/v4.6.0/pythonapi/lightgbm.Booster.html)，'
            '协方差存储选项参考[scikit-learn官方文档](https://scikit-learn.org/stable/modules/generated/sklearn.covariance.LedoitWolf.html)。','']
    for s in summary['experiment_statuses']:
        if s['status']!='completed':
            lines.append(f'- {s["strategy"]}：{s["status"]}，{s.get("error","")}。见该组failure.txt。')
    lines+=['','## 执行偏离及剩余限制','',
            '| 路径10bp | 拒单数 | 沿用旧报价估值日 | 行业目标超限日 | 实际平均持仓数 |','|---|---:|---:|---:|---:|']
    for p in NAMES:
        if p+'_10bp' in stats.index:
            r=stats.loc[p+'_10bp']
            lines.append(f'| {NAMES[p]} | {int(r.rejected_orders)} | {int(r.stale_valuation_days)} | '
                         f'{int(r.industry_breach_days)} | {r.average_positions:.2f} |')
    lines+=['','停牌、涨跌停、容量、整手和T+1会使实际持仓偏离目标；账务重建通过不代表持仓可以即时成交。'
            '目标行业上限25%不等于实际每日保证。日线执行近似、历史ST/行业版本、剩余未知复权事件、固定20%红利税与退市零回收假设仍保留。',
            '2016—2025此前已查看，本轮受旧结果及诊断启发；按时间隔离训练只能防止直接未来泄漏，不能恢复独立封存测试。'
            '三年结果不足以宣称稳定可实盘。未运行2021—2025新候选、未接入券商。'
            '后续若推进，应依据本轮实际未通过条件另行形成可审阅设计；不自动调整参数挽救当前结果。','',
            '![连续账户净值](continuous_nav.png)','']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    fig,axes=plt.subplots(1,2,figsize=(13,4.8))
    for p in NAMES:
        label=p+'_10bp'
        if label not in stats.index:continue
        nav=pd.read_csv(OUT/label/'nav.csv',parse_dates=['date'])
        nav=nav.loc[nav.date.ge(pd.Timestamp('20171229'))]
        axes[0].plot(nav.date,nav.equity/1000000,label=p,linewidth=1.3)
    for bps in (0,10,30):
        label=f'ml_risk_{bps}bp'
        if label not in stats.index:continue
        nav=pd.read_csv(OUT/label/'nav.csv',parse_dates=['date'])
        nav=nav.loc[nav.date.ge(pd.Timestamp('20171229'))]
        axes[1].plot(nav.date,nav.equity/1000000,label=f'{bps}bp',linewidth=1.3)
    for ax,title in zip(axes,['Common pool, same inception, 10bp','ML risk overlay: cost scenarios']):
        ax.set(title=title,ylabel='Equity / initial capital')
        ax.axhline(1,color='grey',linewidth=.6,linestyle='--');ax.grid(alpha=.2);ax.legend(fontsize=8)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax.tick_params(axis='x',labelrotation=25)
    fig.tight_layout();fig.savefig(OUT/'continuous_nav.png',dpi=160);plt.close(fig)
    evidence=OUT/'verification_sources';evidence.mkdir(exist_ok=True)
    for name in ['verify_ml_risk.py','audit_ml_risk_flows.py','audit_continuous_flows.py','report_ml_risk.py']:
        shutil.copy2(ROOT/'scripts'/name,evidence/name)
    shutil.copy2(ROOT/'tests/test_ml_risk.py',evidence/'test_ml_risk.py')
    hashes={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in OUT.rglob('*') if p.is_file() and p.name!='output_sha256.json'}
    (OUT/'output_sha256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    print('Report saved; research gates passed:',success)


if __name__=='__main__':
    main()
