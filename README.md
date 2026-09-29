# A 股周频多因子研究

最新（2026-09-29 二）：双周调仓降换手方案完成开发与一次性确认。开发期五年（2016–2020）门槛双过：双周 combined 基准成本 4/5 年为正（+2.53 / +0.44 / -43.03 / +20.58 / +7.84%，周频仅 0/5 为正），平均成本侵蚀 11.12pp ≤ 12pp，年换手约 94 倍降到约 44 倍。2024–2025 一次性确认：+4.07% / +11.88%（周频 +1.27% / +12.72%），侵蚀降至约 11.3–11.7pp，账务核验全部通过；2018 年仍深亏，净效果两年基本打平、回撤略降，仍非实盘条件。见 [双周方案设计与结果](docs/superpowers/specs/2026-09-29-biweekly-design.md)。

最新（2026-09-29）：2024—2025 样本外验证完成。用冻结参数在封存窗口（`out_of_sample_2024` / `out_of_sample_2025`）跑完整九组实验，账务核验全部通过：基准成本 combined 收益 +1.27%（2024，最大回撤 24.47%）与 +12.72%（2025，最大回撤 10.60%），优于开发期五年全部负收益；零成本口径 +24.80% / +37.27%，信号有效性在封存数据上复现。但成本侵蚀约 23—25 个百分点，滑点 30 bps 情景即转负，尚不具备实盘条件。样本期公司行动歧义条目已逐一经公告取证登记更正。详见 [样本外结果](docs/2026-09-29-out-of-sample-results.md)。

2026-09-28：修正历史股票池对 `namechange` 的错误解释。该表是曾用名事件区间，不是连续名称主表；现在仅按形成日前已公告的活动 ST/PT 区间排除股票。五个年度 45 组已重跑并通过账务核验，三因子收益依次为 -9.27%、-12.53%、-44.18%、-9.67%、-1.81%。逐日 ST 真值接口需要 3000 积分，当前 2000 积分账户无法独立复核全部风险警示事件。连续账户和样本外验证尚未完成，当前版本未达到实盘条件。见 [股票池审计](docs/2026-09-28-universe-history-audit.md) 与 [公司行动核验](docs/2026-09-28-corporate-action-review.md)。

2026-09-27 更新：2017 年九组实验及账务核验完成，主策略 -10.20%、最大回撤 14.33%；五项复权变化仍隔离待核验。当前进度见 [2017 研究记录](docs/2017-development-results.md) 和 [逐年对照](output/development_comparison/report.md)。下方较早记录保留当时实验背景。

## Project 1 修订报告（2026-09-25）

最新报告为 [Project 1 v3](docs/2026-09-25-project1-report-v3.pdf)，配套 [复现说明与字段字典](docs/project1-reproduction.md)。本次修正未来标签缺失后的因子分组逻辑，补齐诊断与形成日长表，保持已有交易账本不变。修订诊断位于 `output/project1_revision/`，由 `scripts/rebuild_project1_diagnostics.py` 重建；PDF 由 `scripts/build_project1_report.py` 生成。原版报告保留供比较。

面向 100 万元资金、每周集中操作一次的股票策略研究。策略方向已经确认：动量、反转、低波动，约 20 只股票，不加杠杆。

**已完成 2016—2020 五个独立年度、每年九组开发期诊断实验，当前版本未达到实盘条件。2018 年在零交易成本下仍亏损 30.46%，尚无样本外收益证据。**

## 已实现

- Tushare 官方 HTTPS 接入、私有凭据读取、限速、重试、分页与原始响应校验缓存。
- 账户接口探测，历史上市/退市名单、名称区间与行业区间覆盖审计。
- 三个过去数据因子，交易日缺失处理、截面排名、等权及行业上限目标组合。
- 单笔交易会计函数：费用、整手、现金约束、T+1、停牌、涨跌停拒单和事前成交额容量限制。
- 固定 2020 年历史小样本的“行情 → 因子 → 历史目标权重”集成验证。
- 逐日现金/真实股数/分红应收/待上市红股账本，周频成交与拒单日志，历史生效费率。
- 2020 年第四季度主板 A 股数据、三个单因子及组合比较、流动性对照、滑点压力测试、IC 与分组诊断。
- 2020 全年评价、2019 年末预热、零交易成本诊断、12 个月收益和交易成本归因。
- 有来源的重整事件修正、配股不认购情景、全股票池未解释复权变动清单。
- 未解释复权变化的 20 日因子隔离，以及唯一一档事前登记的排名缓冲低换手诊断。

## 运行

在本目录执行，Python 3.10 及以上：

```powershell
python -m pip install -r requirements.txt
python -m pytest tests -q
python -m quant_research.probe
python -m quant_research.audit
python -m quant_research.pilot
python -m quant_research.download
python -m quant_research.research
python -m quant_research.download --dataset development_2020 --interval 0.4
python -m quant_research.research --dataset development_2020
python scripts/verify_2020.py
python -m quant_research.download --dataset development_2019 --interval 0.4 --workers 12
python -m quant_research.research --dataset development_2019
python -m quant_research.download --dataset development_2018 --interval 0.4 --workers 12
python -m quant_research.research --dataset development_2018
python scripts/verify_annual.py --dataset development_2018
python scripts/verify_annual.py --dataset development_2019
python scripts/verify_annual.py --dataset development_2020
python scripts/compare_development_years.py
```

`probe` 某接口无权限时返回非零退出码，并保留逐项报告。`audit` 必须先于 `pilot` 运行。原始数据有缓存，再次运行审计与样本优先复用缓存；`probe` 总是重新访问接口。

当前机器已在 `.secrets/tushare.dpapi` 保存 Windows 当前用户加密的凭据。其他机器可设置本地 `TUSHARE_TOKEN` 环境变量；不要写入脚本、提交 Git 或在共享日志中输出。环境变量优先于加密文件。受限运行环境可能无法加载 Windows 用户的解密配置，需要在正常用户终端运行。程序只连接官方 Tushare API，不连接券商。

## 输出与含义

- `output/data_probe.json`：小请求成功/空响应/失败，不能证明多年历史完整。
- `output/history_audit.json`：抽查历史股票池中名称和行业覆盖。
- `data/audit/`：基础信息、历史名称、行业区间，含当前及历史退出股票。
- `output/historical_integration_sample/summary.json`：固定样本的运行规模与限制。
- `output/historical_integration_sample/factors.csv`：历史因子计算结果。
- `output/historical_integration_sample/historical_targets_NOT_LIVE.csv`：2020 年的样本目标权重，**不是当前买入清单**。

样本以 2020-09-30 的名称及行业区间选择每个行业代码排序第一只，最多 30 只，之后取 2020 年第四季度行情。该规则仅用于集成验证，样本不代表全市场，不能用其收益评价策略。2024—2025 的封存测试期行情尚未用于选因子或调参。

`download` 和 `research` 是后续全市场开发期实验，区别于早期 30 只集成样本。结果见 `output/development_2020q4/report.md`；数据范围 3022 只历史主板 A 股、179577 条日线，预热后回测为 2020-11-09 至 2020-12-31，共 39 个交易日。首日收益以前一交易日初始现金为基准。三因子组合扣费收益 -6.20%，并非可实盘的正向验证。

年度报告见 [output/development_2020/report.md](output/development_2020/report.md)：3044 只历史主板 A 股、835827 条日线（含预热），2020 年共 243 个交易日。隔离复权异常后，三因子收益 3.26%、最大回撤 14.87%；零交易成本诊断为 29.13%；单边 30/50 基点滑点下为 -13.13%/-27.63%。排名缓冲 40 候选收益 3.89%，但成本仅下降 4.2%，不足以解决高换手。详细判断见 [年度研究记录](docs/2026-09-23-annual-results.md)。

`download` 只允许已登记的数据窗口（含年度实验所需的 2019 年末预热），使用共用限速器、响应缓存和文件摘要；失败日期单独记录，可重跑补齐。`research` 校验数据摘要后本地运行，不需要解密凭据或联网。因子方向与参数未按结果调整；配股会计情景在实际数据暴露缺口后补充，变更过程见实验登记。

## 尚未完成的实盘研究环节

1. 历史 ST 替代数据的完整性验证；行业区间的当时可得性验证。
2. 年度数据的 150 条复权异常已于 2026-09-24 全部定性：5 条为一手公告确认的配股除权（已按不认购情景补登记，九组结果不变），其余 145 条集中在 2020-01-02，经 iFinD 原始价格与复权序列交叉核验为数据商复权因子跨年 artifact（更换数据源不能消除）。相关 2900 个股票日仍按事前规则隔离；新增 `return_consistency_check` 逐日监控复权与原始收益背离。之后可扩大历史时期。
3. 核验实际成交模型、公司行动特殊情形与券商佣金。退市零回收、固定 20% 红利税、配股不认购均为情景；配股现金安排尚未实现。已记录实际行业超限和旧价估值天数。
4. 开发/验证/样本外实验，基准对比、IC 分组、压力测试与报告。
5. 前向模拟下单记录和实际执行偏差评估。

`execution.py` 是单笔执行函数，`accounting.py` 管理公司行动，`backtest.py` 组合成日频账本，`research.py` 串联全流程。佣金和红利税仍为研究情景；历史印花税和过户费按生效日期切换。`factors.py` 的选股函数要求调用方先完成当时股票池过滤；行业上限约束的是目标权重，不能保证成交后权重。未识别的持仓复权变化会使回测失败，不用复权价格冒充真实股数交易。

设计细节见 `docs/superpowers/specs/2026-09-23-weekly-equity-design.md`。

## 2019 年扩展（2026-09-24）

已补齐 2018 年 11 月至 2019 年末的 286 个交易日，并完成 2019 年 244 个交易日的九组独立资金实验。三因子扣费收益 -7.67%、最大回撤 30.85%；零交易成本情景收益 15.76%。排名缓冲收益 -5.79%，费用及滑点仅下降 4.45%，高换手问题跨年持续。见 [逐年对照](output/development_comparison/report.md) 与 [2019 研究记录](docs/2019-development-results.md)。

`development_2016` 至 `development_2020` 均已完成全量下载、统一口径回测和年度核验。年度实验各自以 100 万元起步，不代表连续多年账户。2024—2025 年仍封存。通用年度核验检查真实交易日、因子来源、现金股数、净值恒等式、月收益及成本；对照脚本只收录核验摘要与结果摘要一致的年份。

## 2018 年扩展（2026-09-25）

完成 2017 年 11 月至 2018 年末的 286 个交易日下载，以及 2018 年 243 个交易日的九组独立资金实验。三因子收益 -43.59%、最大回撤 44.97%；零交易成本收益 -29.96%；排名缓冲收益 -43.16%，成本下降 7.27%。11 项配股由发行人公告或上交所年鉴核验，另修正一项不属于原股东分配的重整转增、一段可逆的数据商复权因子错误和一项历史证券代码映射。修正后未解释重大复权变化与涨跌停缺口均为 0。见 [2018 研究记录](docs/2018-development-results.md) 与 [公司行动核验](docs/2018-corporate-action-audit.md)。
