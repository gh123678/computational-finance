"""Verified rights issues under an explicit no-subscription research scenario."""
from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class RightsIssue:
    code: str
    record: pd.Timestamp
    ex: pd.Timestamp
    source: str


SSE_SOURCE = 'https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10061073/files/3434d1799d1145dc826c16c34bd097bf.pdf'
SSE_2018_SOURCE = 'https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170563/files/9f33f39ecb1c4546a88ec88b81105434.pdf'
SSE_2017_SOURCE = 'https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170564/files/300a2dcef0f0452794683bd1bfbf65b0.pdf'


def verified_rights():
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
