"""Quote-representation diagnosis only, with no factor replacement or trading."""
from pathlib import Path
from decimal import Decimal
import json
import hashlib
import numpy as np
import pandas as pd

ROOT=Path('D:/QuantResearchEvidence/alphaforge_000998_crosscheck_20261016_r1')
OUT=ROOT/'adjusted_representation_review'
FIELDS=('open','close','high','low')


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if OUT.exists():raise RuntimeError('Existing representation evidence; inspect without repeating')
    OUT.mkdir()
    source_paths={kind:ROOT/'public_quotes'/name for kind,name in [
        ('raw','tencent_corrected_arity_record.json'),('qfq','tencent_qfq_record.json'),('hfq','tencent_hfq_record.json')]}
    inputs={str(path):sha(path) for path in source_paths.values()}
    quotes={}
    for kind,path in source_paths.items():
        result=read(path);assert result['status']==200 and result['response']['code']==0
        field={'raw':'day','qfq':'qfqday','hfq':'hfqday'}[kind]
        series=result['response']['data']['sz000998'][field]
        assert len(series)==6 and len({row[0] for row in series})==6
        quotes[kind]={row[0]:dict(zip(FIELDS, map(Decimal,row[1:5]))) for row in series}
    assert set(quotes['raw'])==set(quotes['qfq'])==set(quotes['hfq'])
    rows=[]
    for date in sorted(quotes['raw']):
        for field in FIELDS:
            raw=quotes['raw'][date][field];qfq=quotes['qfq'][date][field];hfq=quotes['hfq'][date][field]
            rows.append(dict(date=date,field=field,raw=str(raw),qfq=str(qfq),hfq=str(hfq),
                qfq_minus_raw=str(qfq-raw),qfq_div_raw=float(qfq/raw),hfq_div_raw=float(hfq/raw)))
    frame=pd.DataFrame(rows)
    assert len(frame)==24 and set(frame.qfq_minus_raw)=={'-0.132'}
    # Descriptive affine representation of already observed quote pairs, not
    # a forecast model, strategy fit or an inferred vendor canonical factor.
    raw=frame.raw.astype(float).to_numpy();backward=frame.hfq.astype(float).to_numpy()
    design=np.column_stack([raw,np.ones_like(raw)])
    coefficients=np.linalg.lstsq(design,backward,rcond=None)[0]
    residual=float(np.max(np.abs(design@coefficients-backward)))
    before,after='2019-12-31','2020-01-02'
    returns={kind:float(quotes[kind][after]['close']/quotes[kind][before]['close']-1) for kind in quotes}
    vendor=read(ROOT/'vendor_refresh/query_results.json')
    data=next(item['data'] for item in vendor['queries'] if item['api']=='adj_factor')
    factors={row[data['fields'].index('trade_date')]:Decimal(str(row[data['fields'].index('adj_factor')])) for row in data['items']}
    reinvested=quotes['raw'][after]['close']*factors['20200102']/(quotes['raw'][before]['close']*factors['20191231'])-1
    record=dict(scope='Retrospective independent quote representation, not same-definition return or corporate-action certification',
        quote_pairs=24,days=6,qfq_minus_raw_all_pairs='-0.132',qfq_constant_offset_observed=True,
        hfq_affine_description=dict(slope=float(coefficients[0]),intercept=float(coefficients[1]),
            maximum_printed_price_residual=residual,provider_algorithm_certified=False,
            fit_is_descriptive_not_strategy_or_forecast=True),
        observed_jan02_close_changes=returns,tushare_multiplicative_adjusted_close_change=float(reinvested),
        raw_hfq_ratios_are_not_certified_canonical_factors=True,independent_adjusted_price_series_obtained=True,
        independent_same_definition_canonical_adjustment_factors_obtained=False,
        using_qfq_or_hfq_as_historical_eligibility_or_features=False,point_in_time_vintage_certified=False,
        all_actions_absent_certified=False,old_data_or_account_results_modified=False,inputs_sha256=inputs)
    frame.to_csv(OUT/'quote_pairs.csv',index=False)
    (OUT/'representation_review.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    text=f'''# 独立复权报价：口径诊断

本轮追加取得腾讯同六日qfqday和hfqday，均为本次查询返回，未当成历史时点不可修订版本。原始、前复权、后复权的开／收／高／低共24对逐项连接；响应的当前qt、market、prec字段不用。

**腾讯前复权在这24对报价中均等于原价减0.132。**这不是Tushare以单个乘法因子计算的同一表示。前复权价／原价会随原价水平变化，不能把这个比值当作当日公司行动或Tushare正确系数。

腾讯后复权打印报价可用同一个描述性仿射映射 `H ≈ {coefficients[0]:.9f} × P + {coefficients[1]:.9f}` 表达全部24点，最大残差约{residual:.3e}报价单位。这里只描述已观察数值，不认证供应商算法、舍入方式或真实权益，亦不将这两个数用于交易模型或数据修正。

2019-12-31到2020-01-02收盘变化：原价{returns['raw']:.6%}；腾讯前复权{returns['qfq']:.6%}；腾讯后复权{returns['hfq']:.6%}；Tushare原价乘adj_factor为{float(reinvested):.6%}。这些是不同表示的价格比值，不是同口径总收益或账户收益，不直接比较谁更准确。

已观察的腾讯前复权24点固定平移、后复权近似统一仿射关系，没有呈现需要把本窗口分成两个价格映射区间的证据；这只是针对本次返回的有限数值观察。它加强了跨源复权口径需要分别核对的理由，不证明当日绝无行动，不推出哪一段Tushare系数该改。

结论：取得独立复权**报价**，尚未取得与Tushare分红再投定义一致、可认证正确值的独立复权**因子**。没有回填、替换数据、运行账户、调参数或改变r2停止状态。
'''
    (OUT/'report.md').write_text(text,encoding='utf-8')
    assert {str(path):sha(path) for path in source_paths.values()}==inputs
    manifest={p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file()}
    (OUT/'output_sha256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':main()
