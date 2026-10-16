"""Evidence-only cross-check report and explicitly hypothetical pool comparison."""
import json
from pathlib import Path
import hashlib

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
EVENT=Path('D:/QuantResearchEvidence/alphaforge_event_crosscheck_20261016_r1')
METHOD=Path('D:/QuantResearchEvidence/alphaforge_method_evidence_20261016_r1')
PREVIEW=Path('D:/QuantResearchEvidence/alphaforge_filter_preview_20261016_r1_attempt2')
OUT=Path('D:/QuantResearchEvidence/alphaforge_event_review_20261016_r1')
SPEC=ROOT/'docs/superpowers/specs/2026-10-16-alphaforge-event-filter-r2-design.md'
REPORT=ROOT/'docs/2026-10-16-alphaforge-event-crosscheck.md'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    events=json.loads((EVENT/'crosscheck.json').read_text(encoding='utf-8'))
    proposal=json.loads((PREVIEW/'preview.json').read_text(encoding='utf-8'))
    check=json.loads((PREVIEW/'boolean_parsing_check.json').read_text(encoding='utf-8'))
    assert events['strategy_accounts_started']==0 and not events['labels_read']
    assert not proposal['factor_values_computed'] and not proposal['labels_or_returns_read']
    frame=pd.read_csv(PREVIEW/'coverage_preview.csv')
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt,font_manager
    import numpy as np
    available={f.name for f in font_manager.fontManager.ttflist}
    font=next((f for f in ['Microsoft YaHei','SimHei','SimSun'] if f in available),'DejaVu Sans')
    figure=OUT/'coverage_comparison.png'
    with plt.rc_context({'font.sans-serif':[font],'axes.unicode_minus':False}):
        fig,ax=plt.subplots(figsize=(12,6))
        x=np.arange(len(frame));width=.25
        for i,(column,label) in enumerate([('original_rows','原冻结共同池'),('r1_retained','r1严格系数变化过滤'),
                ('static_reference_and_cached_action','候选条件静态覆盖预览')]):
            bars=ax.bar(x+(i-1)*width,frame[column],width,label=label)
            ax.bar_label(bars,fontsize=9,padding=3)
        ax.axhline(200,color='red',linestyle='--',linewidth=1,label='固定门槛200只（不变）')
        ax.set_xticks(x,labels=frame.signal_date);ax.set_ylabel('形成记录数')
        ax.set_title('四期数据条件可行性：未计算收益，未批准或运行r2')
        ax.legend(loc='upper right',fontsize=9);ax.grid(axis='y',alpha=.2)
        ax.set_ylim(0,float(frame.original_rows.max())*1.23)
        fig.text(.02,.015,'静态预览不认证事件历史版本；仅四期，不能代替全154期准备或真实账户绩效。',fontsize=9)
        fig.tight_layout(rect=(0,.04,1,1));fig.savefig(figure,dpi=160,facecolor='white');plt.close(fig)
    lines=['# AlphaForge数据交叉核验与r2候选方案','',
        '2026-10-16。**已完成源数据／事件交叉核验；支持修改研究过滤假设的可行性讨论，不证明供应商已修复或策略盈利。r1仍停止，r2未获批准、未启动。**','',
        '## 本轮新结果','',
        f'固定四个失败形成日的原池并集{events["failed_pool_union_codes"]:,}只，在2018-08-01至09-10完成{events["primary_adjacent_checks"]:,}次相邻开市日核对。精确系数变化共{events["exact_adj_factor_changes"]:,}次：','',
        '|分类|次数|能说明什么|','|---|---:|---|',
        '|原价参考连续，无缓存行动匹配|2,611|未观测到参考价断点；不证明无行动或只是舍入|',
        '|原价参考不连续，匹配已实施分红|87|与登记的除息相符；不能一刀切抹去系数变化|',
        '|缺相邻报价|1|无法判断连续性，不能补造价格|','',
        '8月16日分别有1,304次连续无匹配、7次分红匹配；8月28日有1,307次连续无匹配、1次分红匹配和1次缺报价。两端相等或后来恢复，只能用于本次回顾诊断，不能回填更早形成资格。','',
        '命名案例分层核对：000011在原池，3.502→3.495→3.502两端原价参考连续；000545和000998不在本轮四期原池并集，作为额外案例保留。000545两端缺相邻原价，不能称连续；000998在8月16日缺报价，8月28日17.30与pre_close17.30相等。',
        '正对照000002在8月23日：上一开市日close23.92、当日pre_close23.02，相差0.90元，匹配缓存现金分红，系数137.3001→142.668。这里的价格与行动字段匹配不是完整历史公告版本认证。','',
        '## 字段和方法核对','',
        '[Tushare官方daily文档](https://tushare.pro/document/2?doc_id=27)将pre_close列为昨收价【除权价】。[深交所2011年规则解读](https://www.szse.cn/disclosure/notice/t20110118_500654.html)也说明除权息日行情前收盘为除权息参考价。两者支持本轮比较的语义，但参考价相等只能说明记录精度下无可见差异。',
        '[2017年深交所问答](https://investor.szse.cn/knowledge/listings/publish/t20170503_538541.html)解释权益分派、公积金转增和配股可导致股本变动；不能只查现金分红就宣称覆盖全部行动。本轮原始及已有纠正后的实施分红记录均为90条，另核对既有配股登记；未登记或未取得历史版本的行动仍是覆盖限制。',
        '在已读三份Tushare官方文档及四次定向检索中，未取得所需的通用小数位、舍入或历史不可修订规则。只能说本轮没有找到，不能说这种规则不存在。',
        'Qlib官方默认字段与作者自定义采集/转换存在需要解释的映射差别；不据raw开关名称认证同口径，也不据此断言作者整个模型有错误。本项目仍是数学部件复现与本地适配。','',
        '## 不读取收益的候选覆盖预览','',
        '为审阅具体修订而检查候选条件：保留原价和成交量，窗口内部9次转换要求参考价连续，另排除缓存匹配行动。这是静态可行性预览，不是批准后的历史可投资池；当前缓存不认证当时事件版本。只检查四期，不能据此宣布全154期通过。','',
        '|形成日|原池|r1保留|候选条件静态保留|','|---|---:|---:|---:|']
    for row in frame.itertuples(index=False):
        lines.append(f'|{row.signal_date}|{row.original_rows}|{row.r1_retained}|{row.static_reference_and_cached_action}|')
    lines+=['',
        '另一条显式字符串布尔解析和逐行聚合核验覆盖5,094条形成记录、45,846次内部转换，与预览逐字段一致。原CSV的混合类型警告已核对为42,171个布尔与24个缺失值；没有把字符串False当True或将缺失当连续。',
        '未读取D_label、D_valid、因子值或策略收益；未计算新因子、IC、净值或启动账户。200只门槛、10日窗口、方向和六账户规则均没有修改。','',
        '## 建议与需要审阅的决定','',
        '建议另立r2：保留原始close、真实成交股数和原公式，把排除条件改为原价参考变化、截止形成日已公开且已生效的登记行动，缺有效参考仍排除；孤立系数变化只作审计标记。原common200未知事件隔离继续保留。',
        '不建议本轮改成合成复权价量：它会把有争议的系数直接引入特征，并改变量的经济含义。此推荐是对数据与方法匹配的判断，尚无收益证据。',
        f'完整规则、时点限制、未知风险、验证和原绩效关卡已写入[r2待审阅设计]({SPEC.as_posix()})。这是股票池排除政策变更，不能悄悄作为r1修复。批准后才实施r2全154期准备及六账户；不因静态覆盖提高就预判收益。','',
        '## 保留和真实限制','',
        'r1的63条产物及旧665／295／463条清单在本地审计前后均一致；原始行情和旧规则未改。新证据分别保存在event_crosscheck、method_evidence、exchange_semantics、filter_preview及本review目录，均位于D:/QuantResearchEvidence。',
        '覆盖预览初次因误用来源manifest文件名而在输入读取前失败，脚本与失败记录保留在filter_preview_20261016_r1；改为实际output_sha256.json后在独立attempt2运行。预览未复用失败目录。',
        '交易所网页工具读取超时，官方直连HTTP200并实际读取HTML正文成功；Qlib官方HTML直连超时，使用官方网页内容及同版本官方data.rst佐证。失败不解释为网页或数据不存在。',
        '没有证明所有公司行动均可在历史形成时识别，也没有恢复2016—2025独立未见样本身份；本轮不接券商。','',
        f'![候选覆盖预览]({figure.as_posix()})','']
    text='\n'.join(lines);REPORT.write_text(text,encoding='utf-8');(OUT/'report.md').write_text(text,encoding='utf-8')
    inputs=[EVENT/'crosscheck.json',METHOD/'method_review.json',PREVIEW/'preview.json',
            PREVIEW/'boolean_parsing_check.json',PREVIEW/'coverage_preview.csv',SPEC,Path(__file__)]
    (OUT/'inputs_sha256.json').write_text(json.dumps({str(p):sha(p) for p in inputs},ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'output_sha256.json').write_text(json.dumps({p.name:sha(p) for p in OUT.iterdir() if p.is_file()},indent=2),encoding='utf-8')
    print(REPORT)


if __name__=='__main__':main()
