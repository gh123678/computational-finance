# AlphaForge r3固定研究结果

用户于2026-10-17在具体设计和批准问题后回复“继续”，批准完整有预检硬门的条件性研究。原r1/r2及数据、源码和失败保留。

**本页仅报告实际阶段。实盘启用保持关闭，参考价收益不等于股份账户总收益。**

- 准备状态：completed。
- 守卫预检：False。
- 实际账户尝试：0／6；完成0组。
- 终态：blocked_guard。

本轮237项相关工程测试通过（110项r3新测试、127项旧案例回归）；源码编译及独立账户执行体比对通过。最终保全检查确认1,924项旧产物、冻结输入、原核心源码和两份阶段指纹清单均保持，无运行锁和账户产物。此处工程测试通过不等于数据或策略通过。

## 数据预检观察

预检扫描固定证券完整账户日历，按冻结上市／退市日期、逐日停牌、原价参考和已登记现金／股份行动检查；不按实际持仓筛异常，也不以孤立A变化作新经济判定。
具体字段和计数以[guard_summary.json](D:/QuantResearchEvidence/alphaforge_case_2018_2020_r3/guard_summary.json)为准：

```json
{
  "passed": false,
  "failure_count": 16441,
  "fixed_security_count": 2806,
  "account_sessions": 790,
  "security_session_rows": 2216740,
  "calendar_start": "2017-10-09",
  "calendar_end": "2020-12-31",
  "seed_session": "2017-09-29",
  "lifecycle_counts": {
    "listed": 2159805,
    "pre_listing": 54366,
    "post_delisting": 2558,
    "scheduled_delisting": 11
  },
  "decision_counts": {
    "continuous_reference": 2113005,
    "outside_lifecycle": 56924,
    "stale_mark_registered_suspension": 28958,
    "stop": 11325,
    "registered_action_reference": 6289,
    "listing_initial_anchor": 228,
    "zero_recovery_write_off": 11
  },
  "failure_reason_counts": {
    "equity_date_in_missing_quote_interval": 8047,
    "missing_initial_seed": 138,
    "missing_prior_close_for_stale_mark": 6733,
    "missing_quote_without_daily_suspension": 1286,
    "missing_prior_close_for_reference": 138,
    "unexplained_reference_change": 99
  },
  "event_count": 9986,
  "accounts_started": 0,
  "performance_computed": false,
  "economic_terms_certified": false,
  "enable_status": "blocked_by_unverified_data_and_forward_validation",
  "input_fingerprint": "edacd61c28a1b8c0dfb6c39269d42041d957210dfbfc9aaee34b696c61957aa6"
}
```

16,441是失败原因记录数，对应11,325个停止证券日、279只股票和613个开市日；一个证券日可能同时记录多个原因，后续日也可能重复受同一初始缺口影响，不能称为16,441个独立供应商错误。

六账户未启动；没有主候选实际净值、收益、费用、回撤或十二跨年完成结论。下文已计算的参考价标签／IC不能冒充实际账户收益；守卫摘要的performance_computed=false指该阶段没有计算账户绩效。

## 参考价标签诊断

形成层核对的是2018—2020年154个信号截面的指定窗口；账户预检则扫描自2017-10-09起全部固定证券的790个开市日。因此形成记录通过与全域账户预检停止可以同时成立。本轮尚无实际持仓，不能把停止证券直接当作账户亏损来源。

标签为R_week，先固定形成记录和分层再连接未来数据；缺标签不影响主计划目标。

|信号|期间|有效周数|平均IC|平均RankIC|
|---|---|---:|---:|---:|
|case_signal|all|153|0.039661|0.065967|
|case_signal|2018|51|0.045556|0.066900|
|case_signal|2019|52|0.045228|0.076338|
|case_signal|2020|50|0.027859|0.054229|
|three_score|all|153|0.014726|0.038999|
|three_score|2018|51|0.013224|0.034346|
|three_score|2019|52|0.007668|0.030699|
|three_score|2020|50|0.023600|0.052378|

![R_week参考价诊断，非账户收益](D:/QuantResearchEvidence/alphaforge_case_2018_2020_r3/figures/reference_rank_ic.png)

![R_week参考价诊断，非账户收益](D:/QuantResearchEvidence/alphaforge_case_2018_2020_r3/figures/reference_groups.png)

## 真实失败

失败发生于precheck阶段；完整错误：[日志](D:/QuantResearchEvidence/alphaforge_case_2018_2020_r3/failure_precheck_20261017T114714.txt)。数据守卫失败，按冻结规则在账户前停止；账户策略关卡未能评估，不重跑失败研究、缩池或修改规则。

## 核验与限制

- 测试证据：[237项工程测试](D:/QuantResearchEvidence/alphaforge_case_2018_2020_r3/engineering_tests.json)；保全证据：[最终只读检查](D:/QuantResearchEvidence/alphaforge_case_2018_2020_r3/final_preservation_check.json)。测试记录形成于准备开始前，其当时的research_preparation_started=false不是当前终态。
- 独立准备核验：passed。
- 独立守卫核验：passed，表示独立复算确认失败结果一致（guard_passed=false），不表示数据守卫通过。
- 完整账户核验：not_completed。
- 固定母池间接依赖旧A资格与隔离，新R_week完整内部桥与旧D端点标签不同；同源pre_close、行动经济覆盖、历史版本和公告日内时间未全量认证。
- 已登记行动及原不认购／固定红利税／陈旧估值／退市零回收均是研究场景，不是完整真实交易权利保证。
- 原公式、负方向、10日、200只及成本／留仓／行业规则不调整；主计划目标须精确保持r2，独立前向评价未完成。

方案：[批准设计](C:/Users/Admin/Documents/ChatGPT/计算金融/docs/superpowers/specs/2026-10-16-alphaforge-reference-r3-design.md)；批准和执行顺序：[实施记录](C:/Users/Admin/Documents/ChatGPT/计算金融/docs/superpowers/plans/2026-10-17-alphaforge-r3-implementation.md)。

## 失败归因与下一步证据

已完成只读去重和六类最早案例核对，完整证据见[失败归纳、案例与补证清单](D:/QuantResearchEvidence/alphaforge_case_2018_2020_r3/failure_review/review.md)。以下是不同问题的关系，不能逐项相加当独立异常数量。

- **初始化与停牌兼容问题。**138只缺少冻结指定的2017-09-29收盘锚点，其中135只当天原停牌表有S。随后129只积累6,733条不能陈旧估值记录，同批138只首次报价时各报一次不能衔接参考。这是同一缺口的级联；真实停牌日通常没有成交日线，不能直接补造报价，也未擅用更早成交初始化。
- **权益跨缺口证据不足。**8,047条停止记录归并为305个登记行动身份，而非8,047次公司行动。4,117条所引用权益日期全部早于账户起点，是缺锚点后的保守区间库存；305个身份也没有因此取得经济真实性认证。
- **逐日交易状态证据不足。**1,286条缺同日S记录只涉及9只股票。需要区分长期停牌、暂停上市、终止交易与接口覆盖，不能拿后来恢复交易反填过去。
- **复牌参考衔接未闭合。**99条差异全部在跨多个开市日的报价缺口之后；98条区间内已有登记除权／息事件。000756.SZ相差0.03与区间登记派现的算术一致只是线索；600480.SH在2019-06-20的0.03差额没有区间登记ex，仍需原始参考及公告补证。不据差额猜分红或改容差。

下一步先按清单核对138只起点库存、9只历史交易状态、去重行动条款和600480.SH的原始依据。此处交付的是补证队列，不是r4规则、重跑或实盘批准；r3按既定停止规则结案，整体策略仍未完成。

真实准备独立核验产生了pandas将来版本兼容警告，当前2.3.3运行及数值核验通过，冻结源码未修改；警告与数据守卫停止分开记录于[运行说明](D:/QuantResearchEvidence/alphaforge_case_2018_2020_r3/runtime_notes.json)。保存的控制台片段仅为尾部，不声称完整运行转录。
