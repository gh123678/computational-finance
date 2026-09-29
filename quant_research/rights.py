"""Verified rights issues under an explicit no-subscription research scenario.

Issues with registered terms (price/ratio/list_date) are subscribed per the
2026-09-29 design (docs/superpowers/specs/2026-09-29-rights-subscription-design.md):
cash is paid on the ex-date and allotted shares list on list_date. Issues without
terms keep the no-subscription scenario.
"""
from dataclasses import dataclass
import math
import pandas as pd


@dataclass(frozen=True)
class RightsIssue:
    code: str
    record: pd.Timestamp
    ex: pd.Timestamp
    source: str
    price: float = None       # subscription price per share, CNY
    ratio: float = None       # allotted shares per held share (realized ratio)
    list_date: pd.Timestamp = None  # listing date of allotted shares

    def __post_init__(self):
        if any(v is not None for v in (self.price, self.ratio, self.list_date)):
            if not (self.price is not None and self.ratio is not None and self.list_date is not None):
                raise ValueError('Rights terms require price, ratio and list_date together')
            if not (math.isfinite(self.price) and self.price > 0):
                raise ValueError('Invalid rights subscription price')
            if not (math.isfinite(self.ratio) and self.ratio > 0):
                raise ValueError('Invalid rights ratio')
            if self.list_date <= self.ex:
                raise ValueError('Rights listing date must follow the ex-date')


SSE_SOURCE = 'https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10061073/files/3434d1799d1145dc826c16c34bd097bf.pdf'
SSE_2018_SOURCE = 'https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170563/files/9f33f39ecb1c4546a88ec88b81105434.pdf'
SSE_2017_SOURCE = 'https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170564/files/300a2dcef0f0452794683bd1bfbf65b0.pdf'


def _verified_rights():
    # Dates document realized accounting events, never an eligibility filter.
    rows = [('600008.SH', '20200918', '20200929'),
            ('600419.SH', '20200103', '20200114'),
            ('600999.SH', '20200709', '20200720'),
            ('601162.SH', '20200310', '20200319'),
            ('601555.SH', '20200312', '20200323'),
            ('603269.SH', '20200717', '20200728'),
            ('603633.SH', '20200710', '20200721')]
    result = [RightsIssue(c, pd.Timestamp(r), pd.Timestamp(e), SSE_SOURCE) for c, r, e in rows]
    extra = [
        # Final results read on 2026-09-28; registration and ex dates explicit.
        ('000661.SZ', '20160418', '20160427', 'https://static.cninfo.com.cn/finalpage/2016-04-27/1202249012.PDF'),
        ('000686.SZ', '20160406', '20160415', 'https://static.cninfo.com.cn/finalpage/2016-04-15/1202179746.PDF'),
        ('000797.SZ', '20160127', '20160205', 'https://static.cninfo.com.cn/finalpage/2016-02-05/1201971622.PDF'),
        ('002101.SZ', '20160412', '20160421', 'https://static.cninfo.com.cn/finalpage/2016-04-21/1202211591.PDF'),
        ('002258.SZ', '20160115', '20160126', 'https://static.cninfo.com.cn/finalpage/2016-01-26/1201938507.PDF'),
        ('002363.SZ', '20160121', '20160201', 'https://static.cninfo.com.cn/finalpage/2016-02-01/1201954100.PDF'),
        ('600489.SH', '20160513', '20160524', 'https://static.cninfo.com.cn/finalpage/2016-05-24/1202335054.PDF'),
        ('600743.SH', '20160712', '20160721', 'https://static.cninfo.com.cn/finalpage/2016-07-21/1202492627.PDF'),
        ('601099.SH', '20160114', '20160125', 'https://static.cninfo.com.cn/finalpage/2016-01-25/1201936414.PDF'),
        ('601377.SH', '20151228', '20160107', 'https://static.cninfo.com.cn/finalpage/2016-01-07/1201897631.PDF'),
        ('000404.SZ', '20170518', '20170531', 'https://static.cninfo.com.cn/finalpage/2017-05-31/1203571491.PDF'),
        ('000977.SZ', '20170718', '20170727', 'https://static.cninfo.com.cn/finalpage/2017-07-27/1203736747.PDF'),
        ('002673.SZ', '20170329', '20170411', 'https://static.cninfo.com.cn/finalpage/2017-04-11/1203274632.PDF'),
        ('600089.SH', '20170531', '20170609', 'https://static.cninfo.com.cn/finalpage/2017-06-09/1203603207.PDF'),
        ('600405.SH', '20170526', '20170608', 'https://static.cninfo.com.cn/finalpage/2017-06-08/1203599316.PDF'),
        ('002166.SZ', '20190408', '20190417', 'https://static.cninfo.com.cn/finalpage/2019-04-17/1206042220.PDF'),
        ('002185.SZ', '20190702', '20190711', 'https://static.cninfo.com.cn/finalpage/2019-07-11/1206438427.PDF'),
        ('002202.SZ', '20190320', '20190329', 'https://static.cninfo.com.cn/finalpage/2019-03-29/1205954988.PDF'),
        ('600113.SH', '20190225', '20190306', 'https://static.cninfo.com.cn/finalpage/2019-03-06/1205876928.PDF'),
        ('600360.SH', '20190403', '20190415', 'https://static.cninfo.com.cn/finalpage/2019-04-15/1206017319.PDF'),
        ('601012.SH', '20190408', '20190417', 'https://static.cninfo.com.cn/finalpage/2019-04-17/1206042055.PDF'),
        # 2017-2018 realized issues verified against issuer disclosures or SSE factbooks.
        ('002074.SZ', '20171116', '20171127', 'https://static.cninfo.com.cn/finalpage/2017-12-04/1204186050.PDF'),
        ('002466.SZ', '20171215', '20171226', 'https://static.cninfo.com.cn/finalpage/2018-01-02/1204289097.PDF'),
        ('600057.SH', '20171219', '20171228', SSE_2017_SOURCE),
        ('600803.SH', '20180201', '20180212', SSE_2018_SOURCE),
        ('603636.SH', '20180312', '20180321', SSE_2018_SOURCE),
        ('002775.SZ', '20180323', '20180403', 'https://static.cninfo.com.cn/finalpage/2018-04-03/1204575806.PDF'),
        ('600256.SH', '20180319', '20180410', SSE_2018_SOURCE),
        ('002350.SZ', '20180517', '20180528', 'https://static.cninfo.com.cn/finalpage/2018-05-15/1204942591.PDF'),
        ('000563.SZ', '20180716', '20180725', 'https://static.cninfo.com.cn/finalpage/2019-04-26/1206105170.PDF'),
        ('600380.SH', '20180928', '20181016', SSE_2018_SOURCE),
        ('600219.SH', '20181023', '20181101', SSE_2018_SOURCE),
        ('002017.SZ', '20190219', '20190228', 'https://static.cninfo.com.cn/finalpage/2019-02-28/1205854477.PDF'),
        ('600459.SH', '20190220', '20190301', 'https://static.cninfo.com.cn/finalpage/2019-03-01/1205858519.PDF'),
        ('002466.SZ', '20191217', '20191226', 'https://static.cninfo.com.cn/finalpage/2019-12-26/1207194799.PDF'),
        ('002884.SZ', '20200320', '20200331', 'https://static.cninfo.com.cn/finalpage/2020-03-18/1207380864.PDF'),
        ('000728.SZ', '20201013', '20201022', 'https://pdf.dfcfw.com/pdf/H2_AN202010211422799690_1.pdf'),
        ('000750.SZ', '20200103', '20200114', 'https://static.cninfo.com.cn/finalpage/2021-03-20/1209419463.PDF'),
        ('000977.SZ', '20200310', '20200319', 'https://static.cninfo.com.cn/finalpage/2020-03-19/1207383380.PDF'),
        ('600919.SH', '20201208', '20201217', 'https://static.cninfo.com.cn/finalpage/2020-12-04/1208849526.PDF'),
        # 2026-09-24 经 iFinD 原始价格、停牌记录与一手公告交叉核验后补充（复牌日均为除权基准日）：
        ('000088.SZ', '20200810', '20200819', 'http://disc.static.szse.cn/download/disc/disk02/finalpage/2020-08-06/03cf29d4-6de7-4ece-867f-84388c183462.PDF'),
        ('000885.SZ', '20200804', '20200813', 'http://disc.static.szse.cn/download/disc/disk02/finalpage/2020-07-31/fa4d1529-df74-44a5-b40d-d5a72cae8838.PDF'),
        ('000901.SZ', '20200226', '20200306', 'http://static.cninfo.com.cn/finalpage/2020-03-02/1207331590.PDF'),
        ('002500.SZ', '20200616', '20200629', 'http://disc.static.szse.cn/download/disc/disk02/finalpage/2020-06-12/08bff09f-99c5-454b-87f7-229ec8695bb1.PDF'),
        ('002788.SZ', '20200908', '20200917', 'http://disc.static.szse.cn/download/disc/disk02/finalpage/2020-09-04/0e805cd9-e4ac-431b-8bfa-29c80e76f1e8.PDF'),
    ]
    return result + [RightsIssue(c, pd.Timestamp(r), pd.Timestamp(e), source) for c, r, e, source in extra]


# Subscription terms registered 2026-09-29 from primary announcements (subscribe-on-registration
# design; all other issues keep the no-subscription scenario):
# ('600999.SH', '20200709'): 招商证券 A 股配股，价格 7.46 元/股，10 配 3，认购率 99.26% 未触发
#   缩配，获配 = 登记日持股 × 0.3 向下取整（发行结果公告 2020-075）；获配股份 2020-07-31 上市
#   （上市公告书 2020-076）。
# ('000977.SZ', '20200310'): 浪潮信息配股，价格 12.92 元/股；公告披露实际配股比例相当于
#   每 10 股配售 1.177945 股（拟 10 配 1.2，认购不足等比缩配，发行结果公告 1207383380）；
#   获配股份 2020-03-27 上市（上市公告书 2020-020）。
TERMS = {
    ('600999.SH', '20200709'): (7.46, 0.3, '20200731'),
    ('000977.SZ', '20200310'): (12.92, 0.1177945, '20200327'),
}


def verified_rights():
    issues = _verified_rights()
    keyed = {(i.code, i.record.strftime('%Y%m%d')): i for i in issues}
    for (code, record), (price, ratio, list_date) in TERMS.items():
        issue = keyed[(code, record)]
        keyed[(code, record)] = RightsIssue(issue.code, issue.record, issue.ex, issue.source,
                                            price=price, ratio=ratio, list_date=pd.Timestamp(list_date))
    return list(keyed.values())
