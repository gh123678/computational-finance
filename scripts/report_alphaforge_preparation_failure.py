"""Report the fixed preparation stop without inventing performance results."""
import json
from pathlib import Path

import pandas as pd

from run_retention_development import ROOT, sha

OUT=ROOT/'output/alphaforge_case_2018_2020_r1'
DEST=ROOT/'docs/2026-10-15-alphaforge-case-results.md'


def main():
    audit=json.loads((OUT/'preparation_audit.json').read_text(encoding='utf-8'))
    assert audit['status']=='passed' and not audit['coverage_gate_passed']
    assert audit['accounts_started']==0 and not audit['performance_evaluated']
    assert not (OUT/'summary.json').exists() and not list(OUT.glob('*/nav.csv'))
    trace=json.loads((OUT/'source_trace.json').read_text(encoding='utf-8'))
    fresh=json.loads((OUT/'provider_recheck/comparison_summary.json').read_text(encoding='utf-8'))
    for name,expected in json.loads((OUT/'source_trace_inputs_sha256.json').read_text(encoding='utf-8')).items():
        assert sha(Path(name))==expected
    coverage=pd.read_csv(OUT/'coverage_by_date.csv',parse_dates=['trade_date'])
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt,font_manager,dates as mdates
    fonts={f.name for f in font_manager.fontManager.ttflist}
    font=next((f for f in ['Microsoft YaHei','SimHei','SimSun'] if f in fonts),'DejaVu Sans')
    (OUT/'figures').mkdir(exist_ok=True)
    figure_path=OUT/'figures/preparation_coverage.png'
    with plt.rc_context({'font.sans-serif':[font],'axes.unicode_minus':False}):
        fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
        axes[0].plot(coverage.trade_date,coverage.original_rows,label='原冻结共同池',linewidth=1.2)
        axes[0].plot(coverage.trade_date,coverage.retained_rows,label='10日调整因子恒定后',linewidth=1.2)
        axes[0].axhline(200,color='red',linestyle='--',label='冻结门槛200只')
        failed=coverage.loc[~coverage.coverage_gate_passed]
        axes[0].scatter(failed.trade_date,failed.retained_rows,color='red',zorder=4,label='4期未通过')
        axes[0].set_ylabel('股票数');axes[0].legend();axes[0].grid(alpha=.2)
        axes[1].bar(coverage.trade_date,coverage.excluded_rows,width=5,label='被排除形成记录')
        axes[1].set_ylabel('排除数');axes[1].legend();axes[1].grid(alpha=.2)
        axes[1].xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4,maxticks=8))
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        fig.suptitle('AlphaForge单案例：准备覆盖关卡失败；未计算IC、未启动账户')
        fig.tight_layout();fig.savefig(figure_path,dpi=160,facecolor='white');plt.close(fig)
    lines=['# AlphaForge单案例运行结果：公式核验通过，准备覆盖未通过','',
        '日期：2026-10-15。本轮已运行并按冻结停止规则结束准备；六个账户均未启动。**这是数据覆盖失败，不是已观察到策略亏损，也没有策略盈利结论。**','',
        '## 已完成与未完成','',
        f'- 新增50项测试全部通过，覆盖10日边界、单位、epsilon、未来扰动、标签与分组隔离，以及账务核验。',
        f'- 独立重算全部{audit["independently_checked_rows"]:,}条形成记录：{audit["valid_formula_rows"]:,}条有效、{audit["excluded_rows"]:,}条按原规则排除；窗口、有效性、原因与公式值一致。',
        f'- 有效记录原算子guard分支{audit["epsilon_guard_rows"]}条；常量和极小方差分支由专门单元测试验证，不能把未触发当作未实现。',
        f'- 因子值与独立标量公式最大绝对误差{audit["maximum_absolute_error"]["case_factor"]:.3g}。量平方和绝对误差可达{audit["maximum_absolute_error"]["case_nrvar"]:.0f}，因量纲较大按预定相对容差核验，不能把它写成因子误差。',
        '- IC、RankIC、分层收益、float32窗口比较与六账户绩效尚未生成；已实现的成功回测报告入口不会在这些证据缺失时伪造报告。','',
        '## 触发停止的四期','',
        '|形成日|执行日|原池|新池|被排除|','|---|---|---:|---:|---:|']
    for row in audit['failures']:
        lines.append(f'|{row["signal_date"]}|{row["execution_date"]}|{row["original_rows"]}|{row["retained_rows"]}|{row["excluded_rows"]}|')
    lines += ['',f'本轮共{audit["formation_dates"]}期，冻结门槛为每期至少200只；最少{audit["minimum_retained_rows"]}只。所有排除原因为10日窗口内调整因子变化，没有用未来标签筛掉股票。门槛没有下调，没有跳过这四期或只挑其余日期回测。','',
        '## 来源追溯和重新查询','',
        '四个日期的14,871条原API响应与年度文件逐值一致，连续主板数据对应11,241行与年度一致；校验通过。变化早在供应商响应中存在，不能归咎于本地拼接或浮点解析。',
        '共同3,713个代码中，2018-08-15至08-16有3,134个系数变化，其中3,118个绝对差不超过0.0005；3,081个代码在08-28回到08-15数值，且08-16等于08-27。0.0005仅作描述统计，不是本轮新增容差。',
        '这强烈提示历史日期段的精度／数据版本不一致，但不是供应商官方舍入规则的证明。同段存在较大异常往返，也存在万科2018-08-23真实除息；不能把全部变化抹平。08-28的恢复仅作回顾诊断，绝不回填08-17当时的资格。',
        f'本轮另作6个有界只读请求：四日期全市场{fresh["fresh_day_rows"]:,}行，以及两只证券的同段查询。全市场新旧差异{fresh["changed_from_frozen"]}行，两种请求方式的{fresh["stock_day_pairs"]}个同键对差异{fresh["stock_day_value_differences"]}。',
        '新旧两处差异为000100.SZ在08-16和08-27由3.0162改为3.016；000005.SZ的9.268→9.2676→9.268、600000.SH的12.33→12.3303→12.33仍存在。说明重新下载不能普遍消除该现象。新响应独立缓存，旧数据没有覆盖。','',
        '## 复现范围与策略边界','',
        '数学对象是`S_log1p(ts_min(ts_corr(close,volume,10),1))`。本地使用原价元、成交量vol×100股、float64；窗口内任何复权因子变化即排除。主负号方向和两路径六账户预先固定，尚未产生收益结果。',
        '本地字段映射不等于作者Qlib数据，float64不等于原torch.float的位级复现。本轮没有复现AlphaForge自动挖掘或动态组合。参考[作者论文v5](https://arxiv.org/html/2406.18394v5)及[AAAI2025正式发表页](https://ojs.aaai.org/index.php/AAAI/article/view/33365)。',
        '课程部件复现已有公式与实现核验，绩效部分仍未完成；实盘研究资格未获得。2016—2025历史已被查看，不恢复为未见样本外；没有连接券商。','',
        '## 保留与后续','',
        f'旧产物三套共{sum(audit["old_artifacts"].values()):,}个文件在独立审计前后指纹一致。失败堆栈、控制台、冻结源码与协议、新旧API响应及来源追溯全部保留。',
        'r1保持停止，不静默改门槛、翻转方向或替换数据。下一步先交叉核对供应商异常日期与公司行动；若需要改变量价映射或事件判定，必须另立明确数据修订版本并记录假设，不能将其写成r1原规则通过。','',
        f'证据目录：`{OUT.resolve().as_posix()}`。`preparation_audit.json`为完整独立核验，`source_trace.json`为原来源追溯，`provider_recheck/`为新查询，`coverage_by_date.csv`为全部形成日计数。','',
        f'![准备覆盖失败图]({figure_path.resolve().as_posix()})','']
    report='\n'.join(lines)
    (OUT/'report.md').write_text(report,encoding='utf-8');DEST.write_text(report,encoding='utf-8')
    print(DEST)


if __name__=='__main__':main()
