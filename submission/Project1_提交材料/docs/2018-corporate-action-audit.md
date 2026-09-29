# 2018 年公司行动与数据映射核验

2026-09-25：以 0.5% 为重大复权变化阈值，2017 年末预热至 2018 年末共发现 13 项变化。11 项为已实现配股；另外两项属于 000998.SZ 同一段复权因子先改变后恢复的数据错误。修正与登记后，未解释清单为 0。

## 已登记配股

| 股票 | 登记日 | 除权日 | 一手来源 |
|---|---|---|---|
| 002074.SZ 国轩高科 | 2017-11-16 | 2017-11-27 | [配股股份变动及上市公告](https://static.cninfo.com.cn/finalpage/2017-12-04/1204186050.PDF) |
| 002466.SZ 天齐锂业 | 2017-12-15 | 2017-12-26 | [配股新增股份上市公告](https://static.cninfo.com.cn/finalpage/2018-01-02/1204289097.PDF) |
| 600057.SH 象屿股份 | 2017-12-19 | 2017-12-28 | [上交所 2017 年配股概况](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170564/files/300a2dcef0f0452794683bd1bfbf65b0.pdf) |
| 600803.SH 新奥股份 | 2018-02-01 | 2018-02-12 | [上交所 2018 年配股概况](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170563/files/9f33f39ecb1c4546a88ec88b81105434.pdf) |
| 603636.SH 南威软件 | 2018-03-12 | 2018-03-21 | [上交所 2018 年配股概况](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170563/files/9f33f39ecb1c4546a88ec88b81105434.pdf) |
| 002775.SZ 文科园林 | 2018-03-23 | 2018-04-03 | [配股发行结果公告](https://static.cninfo.com.cn/finalpage/2018-04-03/1204575806.PDF) |
| 600256.SH 广汇能源 | 2018-03-19 | 2018-04-10 | [上交所 2018 年配股概况](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170563/files/9f33f39ecb1c4546a88ec88b81105434.pdf) |
| 002350.SZ 北京科锐 | 2018-05-17 | 2018-05-28 | [配股说明书及发行日程](https://static.cninfo.com.cn/finalpage/2018-05-15/1204942591.PDF) |
| 000563.SZ 陕国投 A | 2018-07-16 | 2018-07-25 | [2018 年报中的发行结果公告清单](https://static.cninfo.com.cn/finalpage/2019-04-26/1206105170.PDF) |
| 600380.SH 健康元 | 2018-09-28 | 2018-10-16 | [上交所 2018 年配股概况](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170563/files/9f33f39ecb1c4546a88ec88b81105434.pdf) |
| 600219.SH 南山铝业 | 2018-10-23 | 2018-11-01 | [上交所 2018 年配股概况](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170563/files/9f33f39ecb1c4546a88ec88b81105434.pdf) |

统一沿用不认购情景：不凭复权因子增加持股，不扣认购款，原始价格中的摊薄损失保留。这只是保守研究情景，不代表实盘配股决定。

## 非普通股东分配与数据更正

- 000912.SZ 泸天化：Tushare 分红表把重整资本公积转增列作每股 1.6803419 股。公司[重整进展公告](https://static.cninfo.com.cn/finalpage/2018-08-03/1205254635.PDF)说明股份登记至管理人账户并用于偿债、投资人与处置，原股东没有获得该股份；因此排除普通送转会计。
- 000998.SZ 隆平高科：2018-08-16 至 2018-08-27 的因子由 11.1070 暂降至 10.8142，并于 2018-08-28 精确恢复。原始行情前收连续，分红表只有 2018-07-16 的现金分红，无对应股本事件。代码仅在三个有行情的日期把因子恢复为 11.1070，并保存原值和日期；若字段不再精确匹配会立即中止。
- 001914.SZ 招商积余：深交所[代码变更公告](https://www.szse.cn/disclosure/notice/general/t20191211_572534.html)确认 000043.SZ 于 2019-12-16 变更为 001914.SZ。数据商对变更前历史日线使用新旧两套代码，却只把涨跌停保留在旧代码。研究层为新代码复制变更日前的对应记录，并拒绝任何键冲突。

原始 CSV 与摘要不改写；所有更正仅在研究读取层发生，详情写入 `output/development_2018/corporate_action_corrections.json`。重大复权阈值固定为 0.5%，日常四位小数精度修订不再被误判为公司行动，未知且达到阈值的持仓事件仍会中止回测。
