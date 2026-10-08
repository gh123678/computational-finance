# 开源量化模型与策略调研（2026-10-06）

## 本地问题与调研结论

现有保留门槛实验降低换手69.77%，但2016—2020基准累计−8.68%、30bp压力−30.93%；2018零成本仍−28.99%。结果只证明机械降换手有效，没有证明收益预测足够或市场风险受到控制。[本地实验](../output/retention_threshold_development_2016_2020_r1/report.md)

推荐从开源项目学习可复现的收益预测、时间隔离验证与风险预算。先检验模型预测，再单独检验风险覆盖层，两者共享原现金股数账本。没有导入开源项目的演示净值或承诺A股盈利。

## 核查的原始项目

| 项目 | 核查的具体内容 | 对当前研究的用处 | 适配限制 |
|---|---|---|---|
| Microsoft Qlib | LightGBM/Alpha158配置、价量特征生成器、TopkDropout源码 | 从固定等权打分转向学习收益关系，保留有限换股思路 | 示例市场、成交价格、费用、资金和标签都与本项目不同 |
| Cvxportfolio | 成本模型、风险目标、LongOnly及TurnoverLimit约束 | 组合决策需要同时考虑收益、风险及成交代价 | 默认股票成本面向美国；换手采用半L1范数，与我们的累计双边定义不同 |
| skfolio | WalkForward、标签重叠清除、权重漂移、LedoitWolf估计器 | 用过去训练、未来预测；风险估计使用收缩协方差 | 顺序验证仍须接回真实股数、停牌、涨跌停和公司行动 |
| Riskfolio-Lib | 原仓库和官方文档中的CVaR、风险平价和组合优化 | 作为后续尾部风险模型参考 | 优化风险度量不能保证实际最大回撤；部分求解器及方法需要额外依赖 |
| FinRL | 官方训练/测试示例及环境入口 | 可学习强化学习环境分层 | 本轮不选用，训练及奖励设计会同时增加多个变量，当前没有证据优于较简单监督模型 |

原始来源：[Qlib配置](https://github.com/microsoft/qlib/blob/be725493eb1a6bbb42bf11b37aa7669f59610ff1/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml)、[Qlib策略](https://github.com/microsoft/qlib/blob/be725493eb1a6bbb42bf11b37aa7669f59610ff1/qlib/contrib/strategy/signal_strategy.py)、[Qlib特征](https://github.com/microsoft/qlib/blob/be725493eb1a6bbb42bf11b37aa7669f59610ff1/qlib/contrib/data/loader.py)；[Cvxportfolio成本](https://www.cvxportfolio.com/en/stable/costs.html)及[约束](https://www.cvxportfolio.com/en/stable/constraints.html)；[skfolio模型选择](https://skfolio.org/user_guide/model_selection.html)及[协方差估计](https://skfolio.org/generated/skfolio.moments.LedoitWolf.html)；[Riskfolio原仓库](https://github.com/dcajasn/Riskfolio-Lib)及[官方文档](https://riskfolio-lib.readthedocs.io/en/latest/)；[FinRL官方示例](https://github.com/AI4Finance-Foundation/FinRL/blob/master/docs/source/start/quick_start.rst)。

## 已定位的关键差异

Qlib示例配置是CSI300、50只股票、每次drop5、1亿元、收盘价成交；其Alpha158默认标签是下一日至再下一日的收盘价格收益。本项目为100万元、主板历史股票池、周频、真实股数及开盘执行。其模型参数也不能视为适合我们的最优值。[配置与源码](https://github.com/microsoft/qlib/blob/be725493eb1a6bbb42bf11b37aa7669f59610ff1/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml)、[标签定义](https://github.com/microsoft/qlib/blob/be725493eb1a6bbb42bf11b37aa7669f59610ff1/qlib/contrib/data/handler.py)

Cvxportfolio提供交易代价与风险一起进入目标的做法，但百分位排名不是货币收益，不能直接与手续费相减。其半L1换手也不能直接与我们买卖两边求和的换手比较。股票成本默认不适用于A股佣金、印花税及整手；实际费用继续由原引擎结算。[成本说明](https://www.cvxportfolio.com/en/stable/costs.html)、[TurnoverLimit定义](https://www.cvxportfolio.com/en/stable/constraints.html)

skfolio文档说明按时间前进的验证、去除跨分割边界的重叠标签，以及在顺序路径中传播期末权重。我们还需传播现金、股数与待结算权益，不能只连续拼接权重收益。[原文](https://skfolio.org/user_guide/model_selection.html)

## 可行性与版本记录

GitHub API核查的版本及许可：

| 仓库 | 检索时提交 | API许可字段 |
|---|---|---|
| microsoft/qlib | be725493eb1a6bbb42bf11b37aa7669f59610ff1 | MIT |
| cvxgrp/cvxportfolio | 351c782b9b8b395c1a5f886b77e0d55f1bc9396e | GPL-3.0 |
| skfolio/skfolio | c682f70a19fedf753cfe65ac9815e9c00470d0ba | BSD-3-Clause |
| dcajasn/Riskfolio-Lib | 7b1b26ac9760974c12ecefe290a9d3bd37b66b7a | BSD-3-Clause |

许可来自各原仓库API及源码标头，若复用源码需保留对应许可。本轮仅调研，没有复制上述库的实现。[Qlib](https://github.com/microsoft/qlib)、[Cvxportfolio许可](https://github.com/cvxgrp/cvxportfolio/blob/351c782b9b8b395c1a5f886b77e0d55f1bc9396e/LICENSE)、[skfolio](https://github.com/skfolio/skfolio)、[Riskfolio](https://github.com/dcajasn/Riskfolio-Lib)

本地已有scikit-learn；LightGBM、Qlib、cvxpy及skfolio尚未安装。日行情已有open/high/low/close/vol/amount，具备构建价量特征的原始字段。需要继续验证复权、成交量单位、60日连续窗口及已知异常隔离，未声称数据已完整适配Alpha158。本轮没有安装依赖、训练模型或改变策略。

## 推荐调整

采用Qlib启发的监督收益预测与小型价量特征集，不直接迁移其全套回测。保留已经验证的换股限制作为控制变量；用收缩协方差估计持仓组合波动，增加可持现金的风险预算覆盖层。将无覆盖层与有覆盖层作为预先固定的两条候选，避免同时改变模型与风险后无法解释结果。

这是本项目的研究判断，不是这些开源项目已证明的盈利策略。具体候选、时间隔离、成本情景及门槛见[已确认方案](superpowers/specs/2026-10-06-open-source-ml-risk-design.md)。按该方案的十二组开发期实验已完成，技术核验通过、收益门槛未全部通过；实际结果见[实验报告](../output/open_source_ml_risk_2018_2020_r1/report.md)，不能以开源项目声誉替代盈利证据。

## 检索与失败记录

使用agent-reach的GitHub/gh CLI路由，检索原项目、读取配置与源文件，并通过官方文档交叉核对。doctor将GitHub标为未认证警告，但本次仓库搜索及API读取实际成功，未要求用户配置登录。初次仓库搜索的JSON字段nameWithOwner不受本机gh search repos支持，更正为fullName后成功。Exa未配置，网页检索使用现有浏览工具；skfolio一个示例地址返回Internal Error，改读官方模型选择页面。未根据失败网页推测内容。agent-reach更新检查显示v1.5.0已是最新，未更新安装。

2016—2025已经使用，任何按本调研重设计的历史结果仍属于探索性验证，不能重新命名为新封存测试。最终需要设计冻结后的后续模拟观察。
