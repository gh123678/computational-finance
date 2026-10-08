# 配股证据闭合与 r3 修订（2026-10-04）

18 项配股登记日及除权日均由发行成功结果公告确认。22 条跨年观测因此有明确配股身份；原 28 条观测剩余 6 条（5 项原因未定的因子变化及 1 项重整）继续按原规则审计与隔离。

本次仅补充 rights.py 中的事实事件登记，沿用用户已确认的配股处理设计：无完整认购条款的事件维持不认购情景，原始股价摊薄损失保留；不推定认购价、实际比例或上市日期。是否影响收益必须重跑后评估，不能由旧版事件前无持仓推断。

旧版 r2 的 297 个年度输出文件已复制到 output/validation_run_20261004_r2/annual_snapshot，逐文件校验值一致。新版本在 r3 冻结后重跑三年 36 组实验，不调整因子、成本或调仓参数。原始数据文件不变。

| 股票 | 登记日 | 除权日 | 发行结果依据 |
|---|---|---|---|
| 000049.SZ | 2023-11-29 | 2023-12-08 | [公告](https://static.cninfo.com.cn/finalpage/2023-12-08/1218545401.PDF) |
| 000065.SZ | 2022-04-01 | 2022-04-14 | [公告](https://static.cninfo.com.cn/finalpage/2022-04-14/1212912102.PDF) |
| 000970.SZ | 2022-02-15 | 2022-02-24 | [公告](https://static.cninfo.com.cn/finalpage/2022-02-24/1212443412.PDF) |
| 002142.SZ | 2021-11-23 | 2021-12-02 | [公告](https://static.cninfo.com.cn/finalpage/2021-12-02/1211763892.PDF) |
| 002948.SZ | 2022-01-04 | 2022-01-13 | [公告](https://www.qdccb.com/images/ag_gsgg/2022/01/26/44A37D760B7C3D35965A654E4B2EADC7.pdf) |
| 600030.SH | 2022-01-18 | 2022-01-27 | [公告](https://www.citics.com/newsite/tzzgx/ggyth/gg/aggg/202201/P020220328648174712581.pdf) |
| 600081.SH | 2023-08-01 | 2023-08-10 | [公告](https://static.cninfo.com.cn/finalpage/2023-08-10/1217501773.PDF) |
| 600459.SH | 2022-12-13 | 2022-12-22 | [公告](https://static.cninfo.com.cn/finalpage/2022-12-22/1215418022.PDF) |
| 600888.SH | 2021-04-12 | 2021-04-21 | [公告](https://static.cninfo.com.cn/finalpage/2021-04-21/1209736447.PDF) |
| 600909.SH | 2021-06-01 | 2021-06-10 | [公告](https://static.cninfo.com.cn/finalpage/2021-06-10/1210209866.PDF) |
| 600958.SH | 2022-04-20 | 2022-04-29 | [公告](https://static.cninfo.com.cn/finalpage/2022-04-29/1213214263.PDF) |
| 601015.SH | 2021-06-29 | 2021-07-08 | [公告](https://static.cninfo.com.cn/finalpage/2021-07-08/1210437971.PDF) |
| 601016.SH | 2022-11-17 | 2022-11-28 | [公告](https://static.cninfo.com.cn/finalpage/2022-11-28/1215213853.PDF) |
| 601108.SH | 2022-03-30 | 2022-04-12 | [公告](https://static.cninfo.com.cn/finalpage/2022-04-12/1212886504.PDF) |
| 601236.SH | 2021-07-26 | 2021-08-04 | [公告](https://static.cninfo.com.cn/finalpage/2021-08-04/1210651292.PDF) |
| 601377.SH | 2022-08-16 | 2022-08-25 | [公告](https://static.cninfo.com.cn/finalpage/2022-08-25/1214390207.PDF) |
| 601555.SH | 2021-12-14 | 2021-12-23 | [公告](https://static.cninfo.com.cn/finalpage/2021-12-23/1211991537.PDF) |
| 601916.SH | 2023-06-14 | 2023-06-27 | [公告](https://www.czbank.com/cn/investor/announcements_3867/202306/P020230626637994950210.pdf) |

公开公告仅作为事件证据。未解释异常不做推测修复，重整转增不冒充配股。原 r2 审计清单与证据保留，新增 11 份 PDF 校验值见 data/evidence/validation_events_20261004/manifest_remaining.json。

## 验证记录

项目测试使用 tests 目录运行，79 项通过。首次全目录收集误包含历史提交副本，造成同名模块冲突；限定当前项目后，默认临时目录写入权限又导致 5 项初始化失败，指定工作区内的独立临时目录后全部通过。没有修改测试来绕过失败。

证据复核可运行 `python -m scripts.verify_validation_rights_evidence`；原始事件审计对应 r2 快照位置保存于 `output/validation_event_audit_20261004/preserved_input_locations.json`。

## r3 实际结果

三年 36 组实验和账务核验全部通过，全部收益与 r2 完全一致。各年剩余 2 条观测、40 个隔离股票日，总计 6 条、120 个股票日；原始行情及元数据校验值相同。没有触发配股认购或未认购记账。所有 18 份发行结果 PDF 日期及原事件审计输入已再次复核。完整对照见 [r3 报告](../output/validation_run_20261004_r3/report.md)。此前七年度实验未重跑，其中 2024 的预热期包含本次新增的 2023-12-08 配股事件，不能声称旧版与当前源码一致。
