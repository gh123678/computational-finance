# Project 2 复现协议与需求对应

日期：2026-10-20。范围：复现一项核心研究结论，保留不能精确解释的差异；不以提高收益为目标调参。

## 文献与目标

Moreira, A. & Muir, T. (2017), *Volatility-Managed Portfolios*, Journal of Finance 72(4), 1611-1644，DOI 10.1111/jofi.12513。原文完整来源见 paper_sources.md。主目标为 Table I Panel A 第1列市场组合：alpha=4.86%/年、HC标准误=1.56、beta=0.61、beta标准误=0.05、N=1065、R²=0.37、RMSE=51.39。辅助目标为 Table II 市场夏普0.42、管理组合0.51；Table V 将后者记为0.52，分别保留。

## 样本与补充假设

- 主比较：1926-08至2015-04，1065个月。原文仅写1926-2015；起止月由首个可用方差月及N推断，不能称为作者确认日期。不通过扫描端点来逼近原值；另报告延至2015-12及改从1927-01开始的敏感性。
- 主数据：French 2024-12 FIZ历史日频/月频同版本快照；不是作者当年的数据。CIZ当前日/月频在同窗口替换，分日频、月频及二者共同变化，检验数据重构敏感性。
- 所有收益由百分数除以100一次。月度收益直接使用官方月度文件；不以日超额收益连乘替代月超额收益。
- 主方差采用原文式(2)的日超额收益中心化平方和。原文以22交易日表示一个月；本次用每个自然月全部实际交易日和实际均值，是明确的落地约定。除以当月天数的平均平方另列敏感性。
- 观察到的交易日不足10天、重复、缺失、不连续月份或非正方差，均报错，不补零或向前填充。

## 核心公式与时点

$$
\bar f_t=\frac{1}{n_t}\sum_{d\in\mathcal D_t}f_d,
\qquad RV_t=\sum_{d\in\mathcal D_t}(f_d-\bar f_t)^2.
$$

$$
w_{t+1}=\frac{c}{RV_t},\qquad
f^{\mathrm{VM}}_{t+1}=w_{t+1}f_{t+1}.
$$

先按完整自然月计算再位移一月。月t的收益和方差不影响月t的目标权重。

$$
c=\frac{s_{\mathcal T}(f_t)}{s_{\mathcal T}(f_t/RV_{t-1})},\qquad
s_{\mathcal T}(x)=\sqrt{\frac{1}{T-1}\sum_{t\in\mathcal T}(x_t-\bar x)^2}.
$$

标准差均使用相同主样本和1个自由度修正。c为整段样本的事后波动率归一化，遵循原文脚注6；收益、alpha和绝对仓位不可解释为当时已知，夏普不受正的常数缩放影响。无仓位上限、无成本、融资按RF。

$$
f_t^{\mathrm{VM}}=\alpha_m+\beta f_t+\varepsilon_t.
$$

alpha及其标准误乘1200变为百分数/年；beta不年化。HC1为异方差稳健推断的明确补充约定，同时给HC0、HAC(6)。

$$
\mathrm{SR}_{\mathrm{ann}}=\sqrt{12}\frac{\bar f^{\mathrm{VM}}}{s_{\mathcal T}(f^{\mathrm{VM}})},\qquad
\mathrm{RMSE}_{\mathrm{paper}}=1200\sqrt{\frac{\sum_{t\in\mathcal T}\hat\varepsilon_t^2}{T-2}}.
$$

RMSE为原表的线性年化回归单位，不能解释为通常的年化波动率。

## 主动改进与对照

固定c为上述1926-08至2015-04估值，2015-05至12不再重估。历史后续窗口2016-01至2024-12共108个月；不是当时登记、实时盲测或原始时点数据库上的预测承诺。

$$
w_t^{\mathrm{cap}}=\min\left\{\frac{c}{RV_{t-1}},2\right\}.
$$

不再缩放到相同波动率。2倍是事先选定的风险约束，无参数搜索；原文还讨论1倍/1.5倍限制，本次2倍属于自主扩展。每个成本档0/10/30bp均比较市场、无上限、2倍上限，同样从现金开始。市场策略首次买入同样计费，持有全市场时不产生再平衡交易。

交易成本按照实际月末漂移后的风险资产持仓计算，目标定义为扣费后财富的比例。设交易前权重为d、目标为w、费率为k，求解费用比例：

$$
\phi_t=k\left|w_t(1-\phi_t)-d_t\right|.
$$

交易后风险指数与现金分别承担市场总收益和RF；额外融资利差仅对借款部分，单独做200bp/年的敏感性。净总收益和净超额收益为：

$$
R_t^{\mathrm{net}}=(1-\phi_t)\left[1+r_t^f+w_tf_t-\frac{\lambda}{12}\max(w_t-1,0)\right]-1,
\qquad f_t^{\mathrm{net}}=R_t^{\mathrm{net}}-r_t^f.
$$

无期末平仓费用。该执行模型是本次扩展，不声称与论文Table IV简化目标权重差成本完全一致，也不包含保证金追缴及日内止损。

v2接口中的执行日为首个源交易日标签，实际经济假设仍是理想月边界成交并承担完整月收益。没有真实首日开盘报价，orders.raw_open留空；形成日先于执行日不认证月末即时成交或首日隔夜收益的可实现性。

## 核验、错误留痕和不确定性

- 初版采用平均平方，核对原文后修正为平方和。初版config、月度记录、回归和比较表保存在audit/variance_mean_initial，不删除不利或未改善结果。
- v2实际复用P1的read_market、dataset_config、summarize、monthly_returns和cost_breakdown；统一目标和后端输出P1四表，路径见docs/p1_integration.md。原summarize只核对期间指标，12期年化另算。原始股票账本不适用。完整冻结源文件及函数SHA见p1_platform/function_provenance.json。
- 单元检查涵盖单位、日期、过去信息、同波动归一化、稳健协方差、成本、现金/风险资产独立账务和破产拒绝。
- 独立核验脚本直接重读原始ZIP，用NumPy重算，不导入主引擎、pandas、statsmodels或P1。逐月现金账务以二分求根重建，而非照抄主代码解析解。
- 夏普差使用配对循环分块bootstrap，12个月块、2000次，主种子20261020；cap2相对无上限使用20261021。95%百分位区间为探索性不确定性描述，不是挑选最优策略的检验。

## 逐项提交要求映射

| 题目要求 | 交付位置 |
|---|---|
| 理解文献及未说明项 | report/Project2_Report_v3.pdf 第2-3页；report/formulas.tex；docs/paper_sources.md；本协议 |
| 接入P1并标记复用/新增 | python -m p1_platform；p1_platform/reference/；docs/p1_integration.md；results/p1_runs/；报告第11页 |
| 小样本公式手算及中间结果 | results/manual_checks.csv；data/sample_daily_for_manual_check.csv；tests/ |
| 数据、配置、版本和实际证据 | data/source_manifest.json；config.json；results/environment.json；results/*verification*.json |
| 原/新目标图表并排、关键差值 | results/comparison.csv；results/figures/original_comparison.png；报告第4页 |
| 差异归因及敏感性 | results/sensitivities.csv；standard_error_sensitivity.csv；vintage_monthly_differences.csv；报告第5页 |
| 改进方案、同口径对照 | results/holdout_*；报告第6-8页 |
| 依赖、入口、数据快照、限制、演示 | README.md；requirements*.txt；data/raw/；docs/demo.md；报告第9-10页 |

说明：协议记录本次设定及修订，不宣称在任何历史收益发生前预登记。
