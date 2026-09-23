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
        ('002466.SZ', '20191217', '20191226', 'https://static.cninfo.com.cn/finalpage/2019-12-26/1207194799.PDF'),
        ('002884.SZ', '20200320', '20200331', 'https://static.cninfo.com.cn/finalpage/2020-03-18/1207380864.PDF'),
        ('000728.SZ', '20201013', '20201022', 'https://pdf.dfcfw.com/pdf/H2_AN202010211422799690_1.pdf'),
        ('000750.SZ', '20200103', '20200114', 'https://static.cninfo.com.cn/finalpage/2021-03-20/1209419463.PDF'),
        ('000977.SZ', '20200310', '20200319', 'https://static.cninfo.com.cn/finalpage/2020-03-19/1207383380.PDF'),
        ('600919.SH', '20201208', '20201217', 'https://static.cninfo.com.cn/finalpage/2020-12-04/1208849526.PDF'),
    ]
    return result + [RightsIssue(c, pd.Timestamp(r), pd.Timestamp(e), source) for c, r, e, source in extra]
