# A 股周频多因子研究

面向 100 万元资金、每周集中操作一次的股票策略研究。策略方向已经确认：动量、反转、低波动，约 20 只股票，不加杠杆。

**当前是研究基础与数据审计版本，还不是可实盘策略。没有完整历史回测或收益结论。**

## 已实现

- Tushare 官方 HTTPS 接入、私有凭据读取、限速、重试、分页与原始响应校验缓存。
- 账户接口探测，历史上市/退市名单、名称区间与行业区间覆盖审计。
- 三个过去数据因子，交易日缺失处理、截面排名、等权及行业上限目标组合。
- 单笔交易会计函数：费用、整手、现金约束、T+1、停牌、涨跌停拒单和事前成交额容量限制。
- 固定 2020 年历史小样本的“行情 → 因子 → 历史目标权重”集成验证。

## 运行

在本目录执行，Python 3.10 及以上：

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
python -m quant_research.probe
python -m quant_research.audit
python -m quant_research.pilot
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

## 尚未完成的实盘研究环节

1. 历史 ST 替代数据的完整性验证；行业区间的当时可得性验证。
2. 全股票池数据审计，以及退市、分红送转、到账和税务的逐日账本。
3. 完整回测调度器、实际成交后组合约束检查、按生效日期加载费用规则。
4. 开发/验证/样本外实验，基准对比、IC 分组、压力测试与报告。
5. 前向模拟下单记录和实际执行偏差评估。

`execution.py` 是独立的单笔执行基础函数，不是完成的回测引擎。默认费率仅是可变的研究情景，不代表用户券商实际收费，也不能贯穿所有历史时期。`factors.py` 的选股函数要求调用方先完成当时股票池过滤；行业上限约束的是目标权重，不能保证成交后权重。

设计细节见 `docs/superpowers/specs/2026-09-23-weekly-equity-design.md`。
