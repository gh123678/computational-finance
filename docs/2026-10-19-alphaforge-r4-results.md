# AlphaForge r4：实际账户范围固定实验结果

按客户端北京时间2026-10-19记录运行与结果。主人2026-10-18明确“批准”后实施；原r4提案中的待批准字样为保留的历史快照。

## 终态

- 已启动1账户，完整完成0/6；独立核对跨年0/12。
- 全市场库存仍为未通过：2806只×790日，原16441条失败完整保留。条件性账户准入不等于数据认证。
- 273794形成键、154期、两条路径目标和R_week诊断逐字引用r3；无重训、重算因子、换股或调参。

|账户|终态|已完成日|失败|
|---|---|---:|---|
|case_negative_retention_common200_0bp|failed|211|000426.SZ 2018-08-15: unreviewed_distribution_across_quote_gap|
|case_negative_retention_common200_10bp|not_started|0||
|case_negative_retention_common200_30bp|not_started|0||
|three_retention_case_common200_0bp|not_started|0||
|three_retention_case_common200_10bp|not_started|0||
|three_retention_case_common200_30bp|not_started|0||

## 独立核验与证据

核验凭证：`partial_verification.json`。其status=passed_partial_evidence_only。部分证据通过不表示完整六账户通过。
来源映射：`evidence_mapping.json`、`event_mapping_validation.json`。原r3全量库存与失败在`reused_r3`；每个已尝试账户留计划目标、逐日守卫、义务、账本、订单、持仓及失败现场。
源码快照在`source_before`；输入、阶段及最终哈希分别为`frozen_protocol.json`、`preparation_sha256.json`、`accounts_sha256.json`与`output_sha256.json`。
保护清单成员总计2522（原1924+r3 105+补证493），本轮末尾逐文件重验。

## 与r3的边界比较

r3全市场任何失败即不开户，结果0账户。r4获明确批准后保留这些失败，现金零股份起步，仅对真实敞口、活动义务与拟成交做硬门；价格缓存不为未持有股票虚构资产。卖出后的现金应收保留，尚未执行股份权利仍需价格。跨缺价普通分派只准已核三项，未知项仍停。
600480仅补配股日期身份，无认购条款注入；9股状态按公开时点推进，不用后来恢复回填。所有源金额、理论陈旧估值与观测参考分别记录，不认证交易所精确参考价或托管到账。

## 绩效与启用限制

首次失败按冻结规则终止整组；剩余账户未启动。完整净收益/成本比较、回撤/年收益与六项研究关卡未评估；已完成部分净值不能当作三年绩效。冻结IC是参考诊断，不能当作现金账户收益。

引用冻结R_week主信号平均RankIC=0.065966824230，有效153期；分层与年度诊断保留在reused_r3/factor_groups.csv和factor_ic_summary.csv，未重新挑选。

实盘保持`blocked_by_unverified_data_and_forward_validation`，未连接券商。全市场历史身份、经济条款及独立前向验证仍未完成；本轮是条件性回顾单案例，不是可启用策略。
