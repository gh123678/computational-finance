"""Summarize bounded new evidence without repairing frozen market data."""
import json
from pathlib import Path
from decimal import Decimal
from datetime import datetime,timezone
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from run_alphaforge_r2 import verify_inputs,sha

OUT=Path('D:/QuantResearchEvidence/alphaforge_000998_crosscheck_20261016_r1')
R2=ROOT/'output/alphaforge_case_2018_2020_r2'
DOC=ROOT/'docs/2026-10-16-000998-data-source-followup.md'


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    if (OUT/'source_followup.json').exists() or DOC.exists():
        raise RuntimeError('Existing evidence summary; inspect without overwriting')
    prior=verify_inputs(read(R2/'frozen_protocol.json'))
    frozen=read(R2/'output_sha256.json')
    for name,expected in frozen.items():assert sha(R2/name)==expected,name
    checked={}
    for folder,name in [('local_provenance','output_sha256.json'),('method_review','manifest.json'),
        ('official_actions','output_sha256.json'),('independent_ifind','output_sha256.json')]:
        manifest=read(OUT/folder/name)
        if 'files_sha256' in manifest:manifest=manifest['files_sha256']
        if 'files' in manifest and isinstance(manifest['files'],dict):manifest=manifest['files']
        for file,digest in manifest.items():assert sha(OUT/folder/file)==digest,(folder,file)
        checked[folder]=len(manifest)
    query=read(OUT/'vendor_refresh/query_results.json')
    payload={}
    for item in query['queries']:
        assert item['state']=='completed' and item['rows']==6
        data=item['data'];frame=pd.DataFrame(data['items'],columns=data['fields'])
        assert frame.ts_code.eq('000998.SZ').all() and not frame.trade_date.duplicated().any()
        assert data.get('has_more') is False
        payload[item['api']]=frame.set_index('trade_date')
    assert set(payload)=={'daily','adj_factor'}
    dates=set(payload['daily'].index)
    source_files=[ROOT/'data/development_2020/daily.csv',ROOT/'data/development_2020/adj_factor.csv']
    source_hashes={str(p):sha(p) for p in source_files}
    def selected(path):
        rows=[]
        for chunk in pd.read_csv(path,dtype=str,keep_default_na=False,chunksize=150000):
            rows.append(chunk.loc[chunk.ts_code.eq('000998.SZ')&chunk.trade_date.isin(dates)])
        result=pd.concat(rows,ignore_index=True)
        assert len(result)==6 and not result.trade_date.duplicated().any()
        return result
    reference=selected(source_files[0]);factors=selected(source_files[1])
    reference=reference.set_index('trade_date');factors=factors.set_index('trade_date')
    observations=[]
    for date,row in payload['daily'].sort_index().iterrows():
        original=reference.loc[date]
        for field in ('open','high','low','close','pre_close','vol','amount'):
            assert Decimal(str(row[field]))==Decimal(str(original[field])),(date,field)
        assert Decimal(str(payload['adj_factor'].loc[date,'adj_factor']))==Decimal(str(factors.loc[date,'adj_factor']))
        observations.append(dict(trade_date=date,**row.to_dict(),adj_factor=float(payload['adj_factor'].loc[date,'adj_factor'])))
    tencent=read(OUT/'public_quotes/tencent_corrected_arity_record.json')
    assert tencent['status']==200 and tencent['response']['code']==0
    series=tencent['response']['data']['sz000998']['day']
    assert len(series)==6 and len({r[0] for r in series})==6
    independent=[]
    # Explicit interpretation of provider's day-array positions. Do not use
    # its extra current qt/prec/market fields as historical observations.
    for day,opening,closing,high,low,volume in series:
        date=day.replace('-','');raw=payload['daily'].loc[date]
        for name,value in [('open',opening),('close',closing),('high',high),('low',low)]:
            assert Decimal(value)==Decimal(str(raw[name])),(date,name)
        independent.append(dict(trade_date=date,open=opening,close=closing,high=high,low=low,
            tencent_volume_field=volume,tushare_vol=str(raw['vol']),price_comparisons_equal=True,
            volume_equality_claimed=False))
    pd.DataFrame(observations).to_csv(OUT/'fresh_vendor_comparison.csv',index=False)
    pd.DataFrame(independent).to_csv(OUT/'independent_price_comparison.csv',index=False)
    official=read(OUT/'official_actions/official_review.json')
    assert official['compensation_notice']['cash_amount_cny']==7334500
    assert official['compensation_notice']['ordinary_shareholder_cash_distribution'] is False
    wind=read(OUT/'wind_probe_attempt3/response.json')
    assert wind['ok'] is False and wind['error']['code']=='NETWORK_ERROR'
    assert 'dev.msh.team' in wind['error']['agent_action']
    record=dict(recorded_at=datetime.now(timezone.utc).isoformat(),scope='Bounded source and official-event diagnosis only',
        result='same vendor discontinuity confirmed; economic explanation and supported correction remain unknown',
        local_cross_year_stitch_cause_refuted=True,overlap_days=43,saved_vendor_cache_examples=5,
        fresh_vendor_queries=2,fresh_vendor_dates=6,fresh_daily_numeric_fields_compared=42,
        fresh_adjustment_values_compared=6,independent_price_dates=6,independent_price_comparisons=24,
        independent_adjustment_series_obtained=False,
        tencent_mapping='day positions: date,open,close,high,low,volume; empty adjustment flag. Volume precision/units not certified; current qt/market/prec excluded',
        official_current_index_records=13,official_window_full_pdf_reviews=4,official_window_title_only_reviews=9,
        official_pdfs_downloaded=6,official_pdf_pages_visually_reviewed=16,
        january_compensation_to_issuer_not_shareholder=True,all_corporate_actions_absent_certified=False,
        previous_ifind_assertion_reproducible_in_checked_scope=False,ifind_old_files_checked=168,
        wind_state='runtime SDK private-host DNS failure before usable data; credentials/entitlements not verified',
        data_correction_approved=False,frozen_rule_revision_approved=False,
        new_factor_model_or_account_run=False,broker_connected=False,
        protected_prior_files=sum(prior.values()),protected_r2_files=len(frozen),subdirectory_manifests_checked=checked,
        fresh_comparison_source_sha256=source_hashes,
        report_adapter_repair='Initial selected excerpt ended before20200106; read six dates from frozen annual source instead; original report attempt preserved')
    assert {str(p):sha(p) for p in source_files}==source_hashes
    (OUT/'source_followup.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    text='''# 000998数据断点：原缓存、官方公告与独立价格补核验

2026-10-16。结论：**已确认断点存在于供应商返回内部，不能归因于本地跨年拼接；尚无足够证据决定正确复权值或解除持仓守卫。**本轮没有改数据、运行账户或恢复r2自动跟进。r2的三主账户失败结论保留。

## 已收敛的原因范围

1. 2019和2020年度文件的43个重叠交易日，000998日线各字段与复权因子逐字符串相同，因子比值恒为1。2020单个年度文件自身已含2019-12-31的11.267与2020-01-02的10.97。连续构建器先拒绝不一致重叠，再按正式年份取行，不能用归一化年度基准解释本例。
2. 五份旧API缓存经请求key、payload校验和及文件哈希核对，均已保留副本。其中四次全市场日期请求于2026-09-23的十秒范围内取得；另有2026-10-04的单股范围请求。同一断点不依赖本次r2或这次下载。
3. 本轮对新日期窗口2019-12-27至2020-01-06只做两次Tushare查询（adj_factor、daily，各6日），不是重复原2018六次探测。新返回与2020原源的42个日线数值字段、6个系数全部相同：12-31仍11.267，01-02仍10.97。重复一致不认证经济上正确，也不认证当年不可修订版本。
4. 腾讯公开接口返回同六日的未复权day序列，按明确记录的日期／开／收／高／低字段位置比较，24项价格均一致。01-02开15.78、收16.18；上一交易日收14.71，与Tushare当日pre_close14.71一致。腾讯量字段为整数，Tushare含小数，本轮不声称量或单位认证。响应附带的当前qt／market／prec没有用作历史数据。它不是独立复权因子序列。

原价收盘收益约9.9932%，用供应商两个系数计算的调整收盘收益约7.0938%，相差约−2.8994个百分点。这是数据语义差异，不能当作主策略收益或损失。

## 官方公告能确认什么

精确发行人当前巨潮索引在2019-12-20至2020-01-10返回13项，hasMore=false；仅认证这次响应未分页截断。其中4份正文完整逐图、其余9份只检查标题。另取2019年报与实际分派正对照，共6份PDF、实际逐图16页；没有声称读完245页年报。

- [2020-01-02利润补偿款进展公告](https://static.cninfo.com.cn/finalpage/2020-01-02/1207214903.PDF)明确：上市公司收到湖南新大新支付的第三期733.45万元补偿款，受款人为公司，**不是普通股股东派息**。落款2019-12-31与当前索引披露日2020-01-02分开保存。
- [2018年度权益分派实施公告](https://static.cninfo.com.cn/finalpage/2019-07-09/1206432689.PDF)明确：登记2019-07-12，除息及委托代派现金2019-07-15，每10股2.001741元，不能移到2020-01-02。
- [2019年年报](https://static.cninfo.com.cn/finalpage/2020-04-29/1207665194.PDF)对应页记录2019年度拟不派息／送转及年初年末股本相同；该报告后来披露，只用于此次历史诊断，不提前用于形成资格，也不排除2020年的其他事件。
- 相邻董事会决议和异动公告已按保存范围阅读，未给出解释该日股东分配的条款。公司自查声明不等于独立证明“当日不存在任何行动”。

## 纠正旧证据的强度与本轮真实失败

旧报告曾称iFinD也有同幅跳变并确认无行动。此次限定检查wind-plugin-test全部168文件，没有找到000998的有效返回；两份指定iFinD价格输出分别是接口不存在和缺参数错误，另有的贵州茅台记录及Wind ADJ测试不属于该股票／日期。因此，**这条旧说法在已检查范围不能重放，不能继续当作已认证事实**；没有推断全盘不存在原件，也没有据此判定任何供应商对错。旧报告和原错误文件不覆盖。

腾讯第一次请求缺末尾空复权参数，返回bad params；保留后仅纠正参数数目，再次返回6日数据。新浪历史页跳转当前行情，没有目标历史行；网页工具的读取失败也不算价格证据。

为取得独立调整序列，查找插件目录未找到适用的iFinD／Wind行情集成，不把同名Windsor营销插件当金融Wind。随后尝试本机已存在Wind专用CLI：文档的@文件语法不被当前实现接受；按回执验证参数argv后，发现默认python3是Windows Store别名。仅对本次进程设WIND_PYTHON指向已有解释器，业务参数／日期／工具未变。最终依赖安装尝试因私有SDK源dev.msh.team无法解析而失败，**没有得到Wind价格或复权数据，也没有验证其服务权限**。没有改凭据、系统设置或切换其他高成本代理服务，未把运行错误当成空行情。

## 当前处理与可审阅修订条件

[Tushare A股因子定义](https://tushare.pro/document/2?doc_id=28)和[复权行情定义](https://tushare.pro/document/2?doc_id=146)没有在已读页解释本次下降。pro_bar前复权终点依赖end_date，不等于原始adj_factor应跨年重基准；单源桥接也反驳本例纯拼接假说。

目前保持原守卫与r2停止状态。下一项有效证据应是：供应商可指认的错行／版本纠正，或口径明确、可重放的独立复权序列与真实权益依据。不能凭参考价连续、没搜到行动或未来恢复，直接把10.97改成11.267。

条件性方案已写在method_review/candidate_revision_review.md：A取得可定位正确值及区间的纠正后另立数据版，并重新核对因子、标签及相同六账户；B取得供应商表示变化且真实权益不变的正面证据后，另审事件／守卫语义；C证据不足继续停止。三者均未实现或批准，不能按收益选路。不能事后拉黑股票、删日、提高阈值，或把已完成对照晋升主候选。

原四套1,486项、r2另128项输出指纹复核保持。整体策略目标仍未完成，没有连接券商。
'''
    entries=[('机器可读汇总',OUT/'source_followup.json'),('原缓存与跨年来源',OUT/'local_provenance/report.md'),
        ('官方原件核对',OUT/'official_actions/review.md'),('旧iFinD范围核对',OUT/'independent_ifind/report.md'),
        ('方法与条件性修订',OUT/'method_review/candidate_revision_review.md'),('最新供应商返回',OUT/'vendor_refresh/query_results.json'),
        ('独立原价比较',OUT/'independent_price_comparison.csv'),('原r2失败报告',ROOT/'docs/2026-10-16-alphaforge-r2-results.md')]
    text+='\n## 证据入口\n\n'+''.join(f'- [{label}]({path.resolve().as_posix()})\n' for label,path in entries)
    (OUT/'report.md').write_text(text,encoding='utf-8');DOC.write_text(text,encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':main()
