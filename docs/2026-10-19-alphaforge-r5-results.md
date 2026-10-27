# AlphaForge r5：来源映射修订固定实验结果

客户端北京时间2026-10-19。用户在完整r5方案交付后回复“=继续”，本轮按该批准实施；原提案的待批准文字保留为历史证据。

## 结论

终态：`full_cohort`。已启动6账户，完整完成6/6，独立核验跨年12/12。
实盘不启用。全市场2806只×790日的原16441条失败保持，局部补证不等于整个市场已认证；本轮也不是严格未见样本外或独立前向验证。

|账户|终态|已完成日|停止原因|
|---|---|---:|---|
|case_negative_retention_common200_0bp|completed|790||
|case_negative_retention_common200_10bp|completed|790||
|case_negative_retention_common200_30bp|completed|790||
|three_retention_case_common200_0bp|completed|790||
|three_retention_case_common200_10bp|completed|790||
|three_retention_case_common200_30bp|completed|790||

## 固定样本与来源关卡

逐字复用r3的273794形成键、154期、2806证券、两条路径目标及原因子/标签/IC/分层数值。未改变参数、股票、年份、方向、200门槛或成本；未重算或重选样本。
独立重建形成内部桥5475880条、标签内部桥1295326条，覆盖键547588；确认新增来源失败0条。原无效标签3015键保持，仅作诊断。
形成按信号日收盘截止（日期包含当天），标签按每桥后端日截止；账户盘前来源要求早于当天。日期级索引不冒称历史分钟级或盘前认证。
明细为`source_bridge_coverage.csv`、`source_bridge_failures.csv`、`source_bridge_trace.csv`；`preparation_audit.json`由独立实现重建覆盖、失败、来源版本、时点与报价，不调用新模拟器或新事件选择函数。


## 实际账户与冻结研究关卡

|账户|净收益|最大回撤|费用/元|滑点成本/元|累计换手|
|---|---:|---:|---:|---:|---:|
|case_negative_retention_common200_0bp|31.3624%|33.3319%|0.00|0.00|87.4182|
|case_negative_retention_common200_10bp|5.3614%|36.3260%|73882.16|133771.55|87.1824|
|case_negative_retention_common200_30bp|-10.8305%|38.2668%|67972.68|274342.30|86.9667|
|three_retention_case_common200_0bp|-4.0310%|34.2463%|0.00|0.00|91.5703|
|three_retention_case_common200_10bp|-23.5730%|39.1366%|64368.63|114439.30|91.4291|
|three_retention_case_common200_30bp|-36.3035%|46.1598%|59083.57|235475.50|91.2289|

六项冻结研究关卡：{"net_positive_10and30": false, "beats_same_pool_control": true, "drawdown_at_most_25pct": false, "two_positive_return_years": true, "rankIC_positive": true, "two_positive_rankIC_years": true}。
年度收益见`annual_returns.csv`，12跨年重建见`year_boundary_audit.csv`。逐日现金、股份、未上市、应收、费用、拒单与估值核验见`verification.json`及各账户原记录。

## 本轮映射与边界

普通跨缺价来源由原3项增至精确23键（20项纯现金）。7项转增税源未知及002470时点冲突仍按旧实际跨缺价/矛盾边界停止，不加入普通允许范围。000426实际现金0.019902，员工获授股份不归普通账户；理论7.190098与观测7.19不混同为舍入认证。
600781保留取消公开前的研究情景登记，取消公开后撤销未执行权益，不造现金、待收或普通除息估值；601258重整股份不给普通持有人，实际股份、未上市、活动义务或拟成交触及特殊行动阶段即停，不因有报价放行。
000977个人额度0.12与市场参考0.1177945分开；价格12.92、原日期不变。上市公告公开前待上市日期未知，随后更新。600999原7.46/0.3及日期不变，发行、实际结果及上市三份官方来源独立绑定；7月20日实际成功的日期级公告不能证明当天开盘前已知。
认购仍为原已批准的条件研究情景：依据先前发行额度、除权日扣现金、现金不足整单不认购、上市日锁/T+1；不冒称重现实际历史缴款或当日盘前已知成功。floor是研究近似，真实托管尾数排序和实际到账未认证。其它原无条款配股不因新来源而自动认购。

## 诊断、保全与后续限制

冻结IC及分层原值保存在`reused_r3/factor_ic.csv`、`factor_ic_summary.csv`和`factor_groups.csv`。它们是历史参考诊断；来源关卡失败时不能将原诊断升级为本版有效证据，也不能替代实际现金账户收益。
源码、输入、来源及各阶段指纹保留在`source_before`、`frozen_protocol.json`及阶段清单。旧保护清单成员合计3539项（重叠按各清单计数，不冒称独立文件数），结尾逐文件重验。最终清单`output_sha256.json`一次封存；原r1—r4、行情、源码及失败不覆盖。
实盘保持`blocked_by_unverified_data_and_forward_validation`，未接券商。数据来源和历史可得性、个人实配与税务、完整经济条款及独立前向验证仍有限制；本次固定案例结束不表示整个策略目标完成。

## 报告凭证工程修订e1

原结案程序因准备清单指纹与凭证字段不一致而拒绝封存，完整失败保留于`report_e1/original_report_failure.log`。原准备核验器复用了digest变量，误将最后一份复用标签的指纹存为准备清单指纹；原凭证与冻结源码保持不变。独立e1按完整成员范围重验全部准备字节，并分别绑定冻结源码、原r3复用及已独立审计的账户清单。校正证明为`report_e1/preparation_receipt_e1.json`，未重跑准备/账户或修改数值、数据和规则。此修订仅修复报告凭证，不改变六项收益关卡的失败结论。

[收益、成本、分层图与新旧前缀评估](C:/Users/Admin/Documents/ChatGPT/计算金融/docs/2026-10-19-alphaforge-r5-evaluation.md)另存，图表已视觉核对。
