# 双周调仓降换手方案设计（2026-09-29）

## 背景

周频三因子组合（combined）年换手约 94 倍，每周近乎整仓更换；零成本口径样本外两年 +24.80% / +37.27%，但基准成本（佣金 0.03%、滑点 10 bps）下成本侵蚀达 23—25 个百分点，滑点 30 bps 情景即转负。既有排名缓冲 40 仅降成本 4.2%，无效。症结在"每周全量重选"，而非阈值。

## 目标

在不动因子定义、不动会计/执行模块的前提下，用双周调仓把基准成本收益在开发期五年（2016–2020）内提升到：

1. **门槛一**：基准成本下五年中至少 3 年为正；
2. **门槛二**：平均成本侵蚀（零成本 − 基准成本）从约 20 个百分点降到 12 个百分点以内。

通过门槛后，对 2024–2025 封存数据各跑一次一次性确认，之后不再回看调整。

## 方法论约束（用户已确认）

- 只在开发期 2016–2020 上开发与比较；2024–2025 对新方案仅作一次性确认，确认前不用于选参数。
- 不扫描任何阈值：排名缓冲 exit_rank=40 为既有事前登记值，沿用不变。
- 既有九个实验（combined、momentum20、reversal5、lowvol20、liquidity_control、combined_slip30、combined_slip50、combined_zero_cost、combined_rank_buffer40）作为回归对照，代码路径与结果不变。

## 设计

### 调度（quant_research/factors.py）

`weekly_schedule(calendar)` 增加隔周参数：信号仍按周形成，但只把隔周的 (signal_date → 下一周首个交易日) 对保留为再平衡周；非再平衡周不交易、持仓不动。新增独立函数 `biweekly_schedule(calendar)`，`weekly_schedule` 行为不变。

### 选择逻辑

双周实验沿用既有 `select_buffered_targets`（exit_rank=40），持仓在两周窗口内自然保留，无需新逻辑。

### 实验矩阵（quant_research/research.py）

开发期每年在既有九组之外追加两组（先跑基准成本与零成本，滑点组视结果决定）：

- `combined_biweekly`：基准成本（佣金 0.03%、滑点 10 bps），双周调仓 + 排名缓冲 40；
- `combined_biweekly_zero_cost`：同上的零交易成本诊断。

单因子实验保持周频不变。样本外确认阶段同两组。

### 账务核验（scripts/verify_annual.py）

期望实验集合追加 `combined_biweekly` 与 `combined_biweekly_zero_cost`。其余核验逻辑（NAV 恒等式、最低现金、月度收益、成本归因、目标权重与因子快照一致性）对新实验同样适用，因为双周目标仍是周频因子快照的子集。

### 输出与文档

- 开发期五年重跑（`python -m quant_research.research --dataset development_YYYY` + `python scripts/verify_annual.py --dataset development_YYYY`）；
- 门槛评估写入 `docs/2026-09-29-biweekly-design.md` 的结论节；通过后再跑 `out_of_sample_2024/2025`；
- README 顶部"最新"段更新。

## 不做（YAGNI）

- 不改因子定义与计算窗口；
- 不动 execution/backtest/accounting 会计模块；
- 不扫描缓冲阈值或调仓周期其他取值；
- 不引入偏离阈值调仓等更复杂机制；
- 不改 2024–2025 既有输出。

## 风险

- 双周频率下 5 日反转信号时效变差，combined 在部分年份可能不升反降——此时如实记录阴性结果，不进入样本外确认。
- 换手下降后容量限制（participation 0.005）与现金缓冲的交互仍需账务核验兜底。
