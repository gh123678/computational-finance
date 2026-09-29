# Project 1 修订版复现说明

## 交付与版本

- 报告：`2026-09-25-project1-report-v3.pdf`，保留 v2 供比较。
- 因子卡：报告第 3 页，包含公式、字段、窗口、假设、方向、缺失处理及失效情形。
- 新诊断：`output/project1_revision/2018`、`2019`、`2020`。
- 旧交易实验：`output/development_年份/`；本次不改动交易账本和策略收益。
- 修订清单：`output/project1_revision/manifest.json`，记录旧结果摘要、输入因子、当前诊断代码及新输出的 SHA-256。

本次修订修复形成日分组逻辑，未来标签缺失不再触发重新分组。IC 和 Rank IC 不变；各期分组收益重新计算。零交易成本从滑点压力曲线中移除。旧结果的源码摘要代表原运行版本，不能用它声称本次诊断使用旧版源码。

## 只重建修订诊断与报告

在项目根目录运行；需要已存在的三个年度数据快照、原有实验输出和历史元数据。脚本先校验快照与元数据摘要，不下载网络数据。

```powershell
python scripts/rebuild_project1_diagnostics.py
python scripts/build_project1_report.py
```

报告生成额外需要 `matplotlib` 和 `reportlab`，采用 Windows 的宋体与黑体；其他系统须更改脚本中的字体路径为可嵌入的中文字体。其余研究依赖见 `requirements-tested.txt`。

## 完整实验复现

先按 README 设置合法的数据访问权限，运行账户探测与历史元数据审计。已有完整快照时不需要重新下载；否则逐年使用 `python -m quant_research.download --dataset development_2018`，将年份替换为 2019、2020。禁止把私人凭据打包进作业。

```powershell
python -m pip install -r requirements-tested.txt
python -m pip install reportlab
python -m pytest -q
python -m quant_research.research --dataset development_2018
python -m quant_research.research --dataset development_2019
python -m quant_research.research --dataset development_2020
python scripts/verify_annual.py --dataset development_2018
python scripts/verify_annual.py --dataset development_2019
python scripts/verify_annual.py --dataset development_2020
python scripts/rebuild_project1_diagnostics.py
python scripts/build_project1_report.py
```

完整运行会刷新对应年度结果及源码摘要。只重建诊断不会执行交易仿真。2024—2025 年不在本次处理范围。

## 文件与字段字典

| 文件 | 字段及定义 |
|---|---|
| formation_factors_long.csv | date：形成日；asset：证券代码；factor：因子名；value：原始因子值（小数）。只含历史状态、完整因子和流动性筛选后的形成日样本，不是完整日频价格表。 |
| factor_ic.csv | signal_date/entry/exit：形成、进入、退出日；factor：因子；n_formed：形成日样本数；n：有效收益标签数；label_coverage=n/n_formed；ic/rank_ic：相关系数。 |
| factor_groups.csv | signal_date/factor/group：形成日、因子、固定组号；n_formed：原组人数；n：标签有效人数；mean_forward_return：组内有效样本等权前向收益，小数。 |
| factor_coverage.csv | historical_eligible：历史状态筛选后人数；nonmissing：该因子非缺失人数；coverage=nonmissing/historical_eligible；selected：三因子共同完整且流动性达标人数。 |
| quality.json | 当前研究输入的记录数、重复键、数值缺失、非法价格量额、零成交量、隔离行和缺涨跌停字段数量。 |
| 年度 nav.csv | date、cash、stock_value、bonus_value、receivable、equity：逐日权益组成；fees/slippage_cost：当日费用及滑点；turnover：买卖额/交易前权益。金额单位元。 |
| 年度 holdings.csv | date、ts_code、shares、pending_shares、mark、value、weight、industry：持仓、待上市股份、估值与行业。 |

日线原始量单位为手、成交额单位为千元，价格为元/股。程序在容量计算边界将成交额乘 1000 转为元。原始数据保持不变，公司行动更正在研究读取层处理。

## 诊断规则

三个因子使用相同的已筛选股票池。未来标签为相邻两次周频执行日的复权开盘价收益，节假日使实际交易日跨度变化。相关系数至少需要 10 个有效标签，且因子及收益均不是常数；否则记缺失。

形成日按因子平均百分位秩分组，组号为 `ceil(rank * 5)`，并列不强制拆组。未来标签缺失不会改变组号；每组至少 2 个有效标签才报告均值，否则记缺失。空组仍输出，便于区分样本不足与零收益。报告的年度组收益为各期组均值的等权平均，高低组价差按同一期先相减再平均。

## 验证记录

本次 65 项自动测试通过；三个年度各九组实验通过年度核验。净值恒等式最大绝对误差约 2.33e-10 元。验证涵盖现金和持仓非负、评价交易日、月收益复合、费用归因与订单费用一致性。它不是对全部市场数据或成交假设的全面认证。

共享完整行情前应自行核对数据授权；不能分享完整快照时，可提供获准的小样本及获取步骤。本文不宣称数据供应商授权已完成核验。
