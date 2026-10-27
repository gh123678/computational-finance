# v2：P1实际接入、冻结内核与适配边界

原仓库取用版本：`cb7e6a8c24b9ea8063fc6445aa990b540254b57e`，不修改原Project1文件。入口：`python -m p1_platform --output reproduced_results`；`run_project.py`为相同流程的便捷入口。

## 完整调用链

1. French ZIP解析后，`load_factor_observations`以原百分数和P1日期/标识字段保存4张明确的因子观测表，实际调用从P1原样抽取的`read_market`读入，再还原小数收益。日RF有超过两位小数的精度，不按显示位数截断；每个值与原ZIP对账。
2. `register_datasets`登记主/后续样本，原P1 `dataset_config`参与选择，保留未知样本拒绝和返回配置副本的行为。
3. 信号生成P1目标表：`signal_date, execution_date, ts_code, target_weight`，另留持有月、lag_rv与backend。形成日取上一月源数据最后一天，执行日取本月首个源数据日。
4. `run_experiment`验证目标后按`backend=monthly_factor`分发，新增后端只接收验证后的目标权重；主入口没有绕过接口的并行执行路径。
5. 输出P1的`nav/orders/holdings/corporate_events`四表。原`summarize`实际计算期间收益、回撤、现金、费用和换手并对账；252日年化输出丢弃。原`cost_breakdown`汇总逐笔费用，原`monthly_returns`在12期绩效适配中还原月收益。

## 原样复用与来源

`attribution.py`整文件逐字节复制；`legacy.py`中的read_market、dataset_config、summarize函数段原样抽取，仅增加导入与P2登记字典。`reference/`附三个完整冻结P1源文件供离线核对，不导入其中其他模块。`function_provenance.json`记录完整文件与函数段SHA、原行号；测试和独立程序实际校验指纹。`performance.py`是12期年化和总/超额收益分离的显式适配。

## 运行证据

`results/p1_inputs/`保存4张P1实际读入的表。`p1_integration_evidence.json`记录13组、3318条目标。每个`results/p1_runs/<实验名>/`包含targets、nav、orders、holdings、corporate_events、cost_breakdown及contract_audit：可查看形成/执行日期、目标权重、成交单位/方向/价格/费用、月末风险资产、现金与净值。公司行动空表表示研究指数收益已含相关因素，不再重复入账。

`scripts/verify_p1_integration.py`只用标准库和NumPy，不导入主引擎或平台；从导出成交累计指数单位与现金，再按源收益/RF逐月重建，16715项核验通过。34项单元检查验证实际调用、精细RF、异常目标拒绝及导出账务；原331项数值复算仍保留。

## 真实经济边界

`FRENCH_US_MARKET_RESEARCH_INDEX`是可分割研究指数记账单位，不是真实股票或ETF。新增后端允许RF借款，符合论文杠杆研究定义；原A股整手、T+1、涨跌停、容量及行业限制不适用，四表已明确标记。月末理想成交、月内保证金和市场冲击仍是局限。

执行日是理想月边界的首个源交易日标签，价格是合成研究指数的月边界记账价格；`raw_open`为空，没有取得真实首日开盘价。官方月收益仍按完整月计算。形成日严格在先能排除当月方差前视，但不能证明真实开盘可以赚取整段月收益，首日隔夜缺口和末日即时调仓可实现性未核验。

研究设定和结论不变；新旧逐项比较见`audit/v1_to_v2_comparison.json`。v2改善接口接入与核查性，不把工程改造当成新的收益发现。
