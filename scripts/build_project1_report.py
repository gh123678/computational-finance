"""Build the reviewed nine-page Project 1 report from saved, verified results."""
from pathlib import Path
import json
import re
import sys
from xml.sax.saxutils import escape
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, Image, KeepTogether, Flowable

OUT = ROOT/'docs/2026-09-25-project1-report-v3.pdf'
ASSETS = ROOT/'tmp/project1_v3_assets'
ASSETS.mkdir(parents=True, exist_ok=True)
REV = ROOT/'output/project1_revision'
FONT = 'C:/Windows/Fonts/simhei.ttf'
pdfmetrics.registerFont(TTFont('Song', 'C:/Windows/Fonts/simsun.ttc', subfontIndex=0))
pdfmetrics.registerFont(TTFont('Hei', FONT))
pdfmetrics.registerFontFamily('Song', normal='Song', bold='Hei', italic='Song', boldItalic='Hei')
plt.rcParams.update({'font.family': FontProperties(fname=FONT).get_name(), 'axes.unicode_minus':False,
                     'font.size':9, 'axes.spines.top':False, 'axes.spines.right':False})
NAVY='#203e5c'
COLORS=['#355c82','#bb783c','#4c8378']
W=A4[0]-104
body=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=17,spaceAfter=8,wordWrap='CJK')
small=ParagraphStyle('small',parent=body,fontSize=8.5,leading=13,spaceAfter=6,textColor=HexColor('#555555'))
head=ParagraphStyle('head',fontName='Hei',fontSize=17,leading=24,spaceAfter=14,textColor=HexColor(NAVY))
sub=ParagraphStyle('sub',fontName='Hei',fontSize=11.5,leading=18,spaceBefore=10,spaceAfter=6,textColor=HexColor(NAVY))
cell=ParagraphStyle('cell',fontName='Song',fontSize=9,leading=13,wordWrap='CJK')
cellh=ParagraphStyle('cellh',parent=cell,fontName='Hei',textColor=HexColor(NAVY))
code=ParagraphStyle('code',fontName='Courier',fontSize=8,leading=12,spaceAfter=4)
story=[]
names={'momentum20':'20日动量','reversal5':'5日反转','lowvol20':'20日低波动'}
years=[2018,2019,2020]
data={}
for y in years:
    old=ROOT/f'output/development_{y}'
    d={'summary':json.loads((old/'summary.json').read_text(encoding='utf-8')),
       'quality':json.loads((REV/str(y)/'quality.json').read_text()),
       'ic':pd.read_csv(REV/str(y)/'factor_ic.csv',parse_dates=['signal_date']),
       'groups':pd.read_csv(REV/str(y)/'factor_groups.csv'),
       'coverage':pd.read_csv(REV/str(y)/'factor_coverage.csv'),
       'long':pd.read_csv(REV/str(y)/'formation_factors_long.csv'),
       'nav':pd.read_csv(old/'combined/nav.csv',parse_dates=['date']),
       'holdings':pd.read_csv(old/'combined/holdings.csv')}
    d['exp']={r['strategy']:r for r in d['summary']['experiments']}
    data[y]=d


def p(text,style=body):
    story.append(Paragraph(text.replace('−','-'),style))


def h(text):
    p(text,sub)


def page(title):
    if story: story.append(PageBreak())
    p(title,head)


def table(caption, rows, widths=None):
    cells=[[Paragraph(str(c).replace('−','-'),cellh if i==0 else cell) for c in row] for i,row in enumerate(rows)]
    t=Table(cells,colWidths=[W*x for x in widths] if widths else [W/len(rows[0])]*len(rows[0]),repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),HexColor('#eef3f7')),('LINEABOVE',(0,0),(-1,0),.8,HexColor(NAVY)),
                          ('LINEBELOW',(0,0),(-1,0),.5,HexColor(NAVY)),('LINEBELOW',(0,-1),(-1,-1),.7,HexColor(NAVY)),
                          ('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
                          ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6)]))
    story.append(KeepTogether([Paragraph(caption,small),t,Spacer(1,11)]))


def chart(fig,name,height,caption):
    path=ASSETS/f'{name}.png'
    fig.savefig(path,dpi=190,bbox_inches='tight',facecolor='white')
    plt.close(fig)
    story.append(Image(str(path),width=W,height=height,kind='proportional'))
    p(caption,small)


def pct(v): return f'{v*100:.2f}%'


class Framework(Flowable):
    def __init__(self):
        super().__init__()
        self.width,self.height=W,47

    def draw(self):
        c=self.canv
        gap=17
        box=(W-4*gap)/5
        for i,label in enumerate(['数据接入','因子计算','目标组合','会计回测','评估诊断']):
            x=i*(box+gap)
            c.setFillColor(HexColor('#eef3f7'));c.setStrokeColor(HexColor(NAVY))
            c.roundRect(x,10,box,29,4,fill=1,stroke=1)
            c.setFillColor(HexColor(NAVY));c.setFont('Hei',10)
            c.drawCentredString(x+box/2,20,label)
            if i<4:
                c.line(x+box+2,24,x+box+gap-3,24)
                c.line(x+box+gap-7,27,x+box+gap-3,24)
                c.line(x+box+gap-7,21,x+box+gap-3,24)


page('A 股周频多因子策略研究')
p('计算金融 Project 1  |  研究平台与开发期实验报告  |  2026-09-25',small)
h('摘要')
p('本项目使用 AI 辅助搭建数据接入、因子计算、组合构建、逐日会计回测和评估诊断五个模块。研究对象为历史主板 A 股，采用日频数据、周频调仓、约20只股票、100万元初始资金与不加杠杆设定。三个价格因子为20日动量、5日反转和20日低波动。')
p('2018、2019、2020年分别进行九组独立资金实验，统一数据、股票池和执行规则。组合三年扣费收益见表1；在常规成本下均跑输同期沪深300价格指数。高换手造成明显成本拖累，但2018年在零交易成本下仍亏损，说明交易摩擦并非唯一原因。')
table('表1  三因子组合核心结果（各年独立账户）', [['年份','扣费收益','最大回撤','零交易成本收益','费用及滑点（万元）']]+[[str(y),pct(data[y]['exp']['combined']['total_return']),pct(data[y]['exp']['combined']['max_drawdown']),pct(data[y]['exp']['combined_zero_cost']['total_return']),f"{(data[y]['exp']['combined']['total_fees']+data[y]['exp']['combined']['total_slippage'])/1e4:.2f}"] for y in years],[.10,.19,.19,.25,.27])
h('研究问题与实验设计')
p('研究问题是：三个方向固定的价格因子等权合成后，能否在周频、小规模持仓与实际交易约束下保留收益？主要对照包括单因子、流动性选股、成本压力和排名缓冲。因子方向与窗口未按三年收益调优，本报告保留不利结果。')
story.append(Framework())
table('图1  模块连接与主要交付', [['模块','输入与输出'],['数据','原始接口响应 → 校验后的日线、复权信息与历史股票池'],['因子','过去价格 → 三因子值、形成日标准长表与截面分数'],['组合','截面分数 → 等权目标；现金缓冲与行业上限'],['回测','目标权重 → 订单、成交/拒单、持仓与逐日现金账本'],['评估','账本及标签 → 净值、风险、成本、IC与五分组诊断']],[.16,.84])
p('范围说明：三个年度不是连续账户，不计算拼接净值或多年复合年化。2021—2023年验证和2024—2025年封存测试尚未完成。课程评价关注计算、复现与解释，不以收益、Sharpe或IC达标作为条件。[1]',small)

page('1  数据、股票池与质量检查')
p('日线、复权因子、涨跌停、停牌、分红及沪深300价格指数来自Tushare接口。[2] 每年包含上年11月起的预热数据。股票池按形成日筛选历史主板、上市满120个交易日、未落入当时已公告ST/PT曾用名区间、且有唯一有效行业记录的股票；进一步要求三个因子完整且过去20日平均成交额至少2000万元。曾用名是事件区间表，不要求普通名称逐日连续覆盖。')
table('表2  数据范围与实际检查结果（含预热）',[['项目','2018','2019','2020'],
 ['历史股票数']+[str(data[y]['summary']['assets']) for y in years],
 ['日线记录数']+[f"{data[y]['quality']['rows']:,}" for y in years],
 ['评价交易日']+[str(data[y]['exp']['combined']['sessions']) for y in years],
 ['重复键 / 数值缺失']+[f"{data[y]['quality']['duplicate_keys']} / {data[y]['quality']['missing_numeric']}" for y in years],
 ['非正价格 / 负成交量额']+[f"{data[y]['quality']['nonpositive_prices']} / {data[y]['quality']['negative_volume_amount']}" for y in years],
 ['零成交量记录']+[str(data[y]['quality']['zero_volume_rows']) for y in years],
 ['隔离因子股票日']+[str(data[y]['quality']['quarantined_rows']) for y in years],
 ['缺涨跌停字段记录']+[str(data[y]['quality']['missing_price_limit_rows']) for y in years]],[.40,.20,.20,.20])
p('检查覆盖当前研究输入的重复键、数值缺失、价格与成交量额合法性；不等于所有历史数据已完整。原始行保留，不统一删除缺失值；零成交量行不用于价格因子计算，因子按交易日历对齐，窗口不完整则记缺失。缺涨跌停字段的订单被拒绝。上述检查不能替代价格事件逐项核验。',small)
table('表3  字段与单位',[['字段','含义与口径'],['trade_date / ts_code','交易日期 / 证券代码；组合键唯一'],['open / close','原始开盘价 / 收盘价，元/股'],['vol / amount','成交量（手）/ 成交额（千元）；计算容量时将成交额乘1000转为元'],['adj_factor','乘法累计复权因子，无量纲'],['date, asset, factor, value','形成日因子长表：日期、证券、因子名、原始因子值；缺失不填零']],[.34,.66])
h('价格与公司行动口径')
p('信号使用收盘价乘累计复权因子；收益标签使用开盘价乘相同复权因子。固定参考日归一化只改变价格尺度，不改变比率收益。组合会计使用原始价、真实股数、应收红利和待上市红股，分别处理确认与到账；不把复权价用于真实成交。')
p('原始快照不改写，公司行动与代码映射修正在读取层登记。2020年仍有145条跨年复权变化按规则隔离，共2900个股票日；抽样跨源核对提示数据口径问题，但不能证明所有股票均无公司行动，亦不能推断所有数据源都有同类问题。详细事件来源与尚未补齐事项见研究记录。[3–5]',small)

page('2  因子卡与组合构建')
p('三个因子均约定分数越高、预期收益越高；该方向是待检验假设。C表示收盘价乘累计复权因子，r表示由C计算的单日简单收益。低波动采用样本标准差（ddof=1）。')
cards=[('20日动量 momentum20','C(t) / C(t-20) - 1','价格强势可能延续。','close、adj_factor；连续21个交易日价格。','趋势反转、追涨拥挤、短期均值回归。'),
       ('5日反转 reversal5','-(C(t) / C(t-5) - 1)','短期超跌可能反弹。','close、adj_factor；连续6个交易日价格。','持续下跌、信息冲击、买入受限和高换手。'),
       ('20日低波动 lowvol20','-std(r(t-19), ..., r(t))','较低波动资产可能表现稳健。','close、adj_factor；连续20个收益，需21个价格。','强势高波动行情、旧价或停牌造成虚假低波动。')]
for title,formula,hyp,fields,fail in cards:
    h(title)
    table('因子定义与使用约定',[['要素','说明'],['公式',formula],['假设 / 方向',hyp+' 方向为正。'],['字段与窗口',fields],['缺失处理','缺任一所需交易日、零成交量导致窗口缺口或复权异常隔离时记缺失；不填零。'],['可能失效',fail]],[.19,.81])
h('从因子值到可执行目标')
p('先确定当时可得股票池，再取三个因子完整且流动性达标的共同样本。对各因子做截面百分位排名，并列值取平均秩；三项排名等权平均。按分数选约20只，单只目标权重为98%/20=4.9%，保留2%现金，目标行业权重上限25%。未选满时保留现金；实际权重可能因价格漂移或拒单偏离目标。')
p('每周最后一个交易日收盘形成信号，下一周首个交易日开盘执行。因子公式、选股逻辑与会计模块分离；新增因子仍需补充定义、配置和验证，当前并非任意公式自动注册系统。',small)

page('3  IC、覆盖率与时间稳定性')
p('标签为下一周首日复权开盘至再下一周首日复权开盘的简单收益，持有期随节假日变化。Pearson IC衡量线性相关，Rank IC使用平均秩计算Spearman相关。有效标签不足10个或因子/收益为常数时记缺失。三年分别有50、51、50个可评价形成日；当前标签区间相邻而不重叠。')
rows=[['年/因子','有效N中位数','IC均值 / 标准差','Rank IC均值 / 标准差','因子覆盖率']]
for y in years:
    for f,n in names.items():
        v=data[y]['ic'].loc[data[y]['ic'].factor.eq(f)]
        c=data[y]['coverage'].loc[data[y]['coverage'].factor.eq(f)]
        rows.append([f'{y} / {n}',f'{v.n.median():.0f}',f'{v.ic.mean():+.4f} / {v.ic.std():.4f}',f'{v.rank_ic.mean():+.4f} / {v.rank_ic.std():.4f}',pct(c.coverage.mean())])
table('表4  逐期相关系数的均值与样本标准差',rows,[.23,.15,.23,.25,.14])
p('覆盖率分母为形成日通过历史状态筛选的资产数，分子为其中该因子非缺失数，表内为各期比例的等权平均。IC仅在三因子共同完整且流动性达标的样本上计算；因此有效N不能作为全市场覆盖率。逐期有效数、形成样本数和标签覆盖率均随CSV交付。',small)
fig,axes=plt.subplots(3,1,figsize=(8,4.6),sharex=True)
for ax,(f,n) in zip(axes,names.items()):
    v=pd.concat([data[y]['ic'].loc[data[y]['ic'].factor.eq(f)] for y in years]).sort_values('signal_date')
    ax.plot(v.signal_date,v.ic,color=COLORS[0],lw=.85,label='IC')
    ax.plot(v.signal_date,v.rank_ic,color=COLORS[1],lw=.85,label='Rank IC')
    ax.axhline(0,color='gray',lw=.5); ax.set_ylabel(n)
axes[0].legend(ncol=2,loc='upper right',fontsize=8)
fig.tight_layout()
chart(fig,'ic',240,'图2  三因子逐周IC与Rank IC（开发期，未作显著性检验）')
p('动量三年平均IC均为负，反转与低波动均值为正，但时间波动较大。相关系数不是收益率或预测准确率；全截面未扣费的相关性也不能直接推导20只股票的扣费收益。',small)

page('4  因子分布与五分组收益')
rows=[['年份','动量 P10 / P50 / P90','反转 P10 / P50 / P90','低波动 P10 / P50 / P90']]
for y in years:
    row=[str(y)]
    for f in names:
        q=data[y]['long'].loc[data[y]['long'].factor.eq(f),'value'].quantile([.1,.5,.9])
        row.append(' / '.join(f'{v*100:.2f}' for v in q))
    rows.append(row)
table('表5  形成日共同样本的原始因子分布（单位：%，股票日合并分位数）',rows,[.10,.30,.30,.30])
p('低波动数值是负的日收益标准差，不能与动量的区间收益直接比较。分布包含所有形成日样本，包括最后一个无完整未来标签的形成日；只用于描述，不作为独立样本的统计检验。',small)
p('五组在形成日按因子平均百分位秩固定：组号=ceil(排名×5)。同值使用同一平均秩，不强制拆组。随后核对未来标签，缺失不补零、不重新分组；各组至少2个有效标签才计算均值。组1最低、组5最高。')
rows=[['年/因子','组1','组2','组3','组4','组5','5−1（百分点）']]
group_values={}
for y in years:
    for f,n in names.items():
        v=data[y]['groups'].loc[data[y]['groups'].factor.eq(f)]
        g=v.groupby('group').mean_forward_return.mean().reindex(range(1,6))
        piv=v.pivot(index='signal_date',columns='group',values='mean_forward_return')
        spread=(piv[5]-piv[1]).mean()
        group_values[y,f]=g
        rows.append([f'{y} / {n}']+[f'{x*100:+.2f}%' for x in g]+[f'{spread*100:+.2f}'])
table('表6  修正后五分组平均前向收益（逐期组均值的等权平均）',rows,[.22,.12,.12,.12,.12,.12,.18])
fig,axes=plt.subplots(1,3,figsize=(8,2.5))
for ax,(f,n) in zip(axes,names.items()):
    for y,color in zip(years,COLORS): ax.plot(range(1,6),group_values[y,f]*100,marker='o',ms=3,color=color,label=str(y))
    ax.set_title(n); ax.set_xticks(range(1,6)); ax.axhline(0,color='gray',lw=.5)
axes[0].set_ylabel('平均前向收益（%）'); axes[2].legend(fontsize=7)
fig.tight_layout()
chart(fig,'groups',160,'图3  分组收益形状；高低价差不等于可执行多空净收益')
m=json.loads((REV/'manifest.json').read_text(encoding='utf-8'))
p('修正核验：三年分别有'+ '、'.join(str(m['years'][str(y)]['missing_labels']) for y in years)+'个形成日股票样本缺少完整收益标签。旧实现删除后重排；新版保留原组归属。IC均值未改变，组收益已重新计算。动量高低价差三年为负，反转和低波动为正；单调性应结合全部五组判断，不能只看两端。',small)

page('5  回测配置与绩效')
p('单边滑点基准为10bp，佣金万三且每笔最低5元；开发期卖出印花税千一、双边过户费十万分之二。执行保留T+1、100股整手、停牌及涨跌停拒单、事前成交额参与度上限0.5%。滑点按价格最小变动单位向不利方向取整，低价股实际比例可能高于名义值。')
labels=[('combined','三因子等权'),('momentum20','动量单因子'),('reversal5','反转单因子'),('lowvol20','低波动单因子'),('liquidity_control','高流动性对照'),('combined_zero_cost','三因子：零交易成本'),('combined_slip30','三因子：30bp滑点'),('combined_slip50','三因子：50bp滑点'),('combined_rank_buffer40','三因子：排名缓冲40')]
table('表7  九组实验累计扣费收益（零成本行为诊断例外）',[['实验','2018','2019','2020']]+[[label]+[pct(data[y]['exp'][key]['total_return']) for y in years] for key,label in labels],[.43,.19,.19,.19])
metrics=[('annualized_return','年化收益'),('annualized_volatility','年化波动'),('sharpe_rf0','Sharpe（rf=0）'),('max_drawdown','最大回撤'),('gross_turnover','累计双边换手（倍）')]
rows=[['三因子指标','2018','2019','2020']]
for key,label in metrics:
    rows.append([label]+[(f"{data[y]['exp']['combined'][key]:.2f}" if key in ['sharpe_rf0','gross_turnover'] else pct(data[y]['exp']['combined'][key])) for y in years])
rows.append(['实际最大单股权重']+[pct(data[y]['holdings'].weight.max()) for y in years])
rows.append(['平均持仓数']+[f"{data[y]['nav'].loc[data[y]['nav'].date.dt.year.eq(y),'position_count'].mean():.1f}" for y in years])
table('表8  主组合风险与持仓指标',rows,[.43,.19,.19,.19])
p('年化收益=(期末/期初)^(252/N)−1；年化波动=日收益样本标准差×√252；Sharpe=√252×日收益均值/标准差，假设同频无风险收益为0。换手采用当日买卖成交额/交易前开盘权益，表内为全年求和。实际最大单股权重为收盘持仓权重最大值。',small)
fig,ax=plt.subplots(figsize=(8,2))
for y,color in zip(years,COLORS):
    v=data[y]['nav'].loc[data[y]['nav'].date.dt.year.eq(y)]
    ax.plot(np.arange(len(v)),v.equity/1e6,label=str(y),color=color,lw=1)
ax.set_xlabel('各年评价期交易日序号'); ax.set_ylabel('净值（初始=1）'); ax.legend(ncol=3,fontsize=8);fig.tight_layout()
chart(fig,'nav',120,'图4  各年独立账户净值，未拼接为连续多年账户')

page('6  成本、压力测试与自主扩展')
p('显式费用按实际成交逐笔收取，未成交不扣费；佣金存在最低收费，不能仅用固定买卖费率完整表达。滑点反映在成交价格及净值中，成本归因时另行统计，不能再次扣减净值。零交易成本实验同时关闭佣金、印花税、过户费和滑点，仍保留红利税情景及交易约束。')
fig,ax=plt.subplots(figsize=(8,2.6))
for y,color in zip(years,COLORS):
    vals=[data[y]['exp'][k]['total_return']*100 for k in ['combined','combined_slip30','combined_slip50']]
    ax.plot([10,30,50],vals,marker='o',label=str(y),color=color)
ax.set_xticks([10,30,50]);ax.set_xlabel('单边滑点（bp）；其他费率保持一致');ax.set_ylabel('累计收益（%）');ax.axhline(0,color='gray',lw=.5);ax.legend(ncol=3);fig.tight_layout()
chart(fig,'stress',163,'图5  仅含10/30/50bp的滑点压力测试；零交易成本不放入该曲线')
table('表9  常规成本归因与排名缓冲对照',[['指标','2018','2019','2020'],
 ['显式费用（万元）']+[f"{data[y]['exp']['combined']['total_fees']/1e4:.2f}" for y in years],
 ['滑点损耗（万元）']+[f"{data[y]['exp']['combined']['total_slippage']/1e4:.2f}" for y in years],
 ['成交 / 拒单笔数']+[f"{data[y]['exp']['combined']['filled_orders']} / {data[y]['exp']['combined']['rejected_orders']}" for y in years],
 ['缓冲后的成本降幅']+[pct(1-(data[y]['exp']['combined_rank_buffer40']['total_fees']+data[y]['exp']['combined_rank_buffer40']['total_slippage'])/(data[y]['exp']['combined']['total_fees']+data[y]['exp']['combined']['total_slippage'])) for y in years],
 ['缓冲收益增量（百分点）']+[f"{100*(data[y]['exp']['combined_rank_buffer40']['total_return']-data[y]['exp']['combined']['total_return']):+.2f}" for y in years]],[.43,.19,.19,.19])
h('自主扩展：用排名缓冲减少换手')
p('问题：每周重新选择20只股票导致频繁替换。实现：保留上期目标中仍位于前40名的股票，再按分数补足；行业、资金及执行规则不变。这是已登记的一档规则，没有按结果扫描阈值。验证：三年成本仅下降约4%—7%，收益改善有限，未改变主要判断。缓冲保留的是上期目标名单，可能与拒单后的实际持仓不同。')
p('2020年成本归因中，新建与退出仓位合计约99.85%，原持仓数量调整约0.15%；因此单纯取消小额调权不足以解决高换手。零成本与常规成本的收益差还包含资金、整手和后续成交路径变化，不能当作同一交易路径直接加回手续费。')
h('因子对照的正确解读')
p('2018和2020年，三因子收益均高于三个单因子；2019年低波动单因子优于组合。因此不能声称组合始终不如最优成分，也不能据此认定等权合成普遍有效。同期沪深300价格指数分别为−25.31%、+36.07%、+27.21%，仅作为不含股息和成本的市场背景；正的零成本收益不等于正的超额收益。',small)

page('7  复现、验证与交付说明')
p('运行环境为Python，依赖版本见requirements-tested.txt。数据下载需要合法的数据访问权限；已有快照的研究与诊断重算可以离线执行。凭据不随作业交付。主配置位于datasets.py、backtest.py与research.py，固定年度窗口防止误用封存期。')
h('从已有快照复现（在项目根目录运行）')
for cmd in ['python -m pip install -r requirements-tested.txt','python -m pip install reportlab','python -m pytest -q',
 'python -m quant_research.research --dataset development_2018',
 'python -m quant_research.research --dataset development_2019',
 'python -m quant_research.research --dataset development_2020',
 'python scripts/verify_annual.py --dataset development_2018',
 'python scripts/verify_annual.py --dataset development_2019',
 'python scripts/verify_annual.py --dataset development_2020',
 'python scripts/rebuild_project1_diagnostics.py','python scripts/build_project1_report.py']:
    p(escape(cmd),code)
p('若没有快照，先按README完成账户探测与历史元数据审计，再执行对应年度的download入口。年度原始文件清单及校验值在data/development_年份/manifest.json；不得用当前股票名单替代历史元数据。',small)
table('表10  结果与可定位证据',[['交付','位置 / 内容'],['年度实验','output/development_年份/summary.json；各策略目录下的nav、orders、holdings、targets和cost_attribution'],['修正版诊断','output/project1_revision/年份/：IC、分组、覆盖率、质量检查及formation_factors_long.csv'],['修订溯源','output/project1_revision/manifest.json：旧结果摘要、因子输入、新脚本及新输出的SHA-256'],['质量与事件','各年度corporate_action_corrections.json、unexplained_adjustments.csv及execution_data_coverage.csv'],['运行说明','README.md；docs/project1-reproduction.md；数据字段见本报告表3']],[.23,.77])
h('本次检查与结果边界')
maxerr=max(c['maximum_nav_identity_error'] for y in years for c in json.loads((ROOT/f'output/development_{y}/verification.json').read_text())['checks'])
p(f'当前65项自动测试通过，包括未来数据隔离、公司行动、T+1、拒单，以及新增的“未来标签缺失不能改变原组归属”测试。逐年核验检查27组实验的交易日、净值恒等式、非负现金与股数、月收益复合和成本一致性；现有核验最大净值恒等式误差为{maxerr:.2e}元。')
p('本次以已保存且校验通过的年度交易结果为绩效来源，重新计算三年的因子诊断，未重新执行全部交易仿真。原年度summary.json保留原运行时源码摘要；修订manifest另外记录本次代码与输入输出摘要，不把两次运行混为同一版本。',small)

page('8  局限、结论与参考资料')
h('仍需解决的限制')
p('数据方面：2000积分账户无法调用需要3000积分的逐日ST名单，曾用名风险区间的完整性及行业区间当时可得版本仍未独立验证，可能造成选择偏差。跨源抽样不足以证明全量数据正确。')
p('执行方面：日线不能还原开盘排队与盘中停牌。红利税固定为20%，退市按零回收处理，配股采用不认购情景。配股认购及资金安排未实现。行业上限作用于目标权重，成交后的实际权重另行监控。')
p('统计方面：三个开发年度既不代表连续账户，也不是样本外证据。本报告未进行正式显著性检验；横截面相关、时间依赖以及多次比较仍需谨慎处理。三个因子均来自价格，不意味着三类独立信息。')
h('结论与下一步')
p('本项目已实现主要投研模块，保留了可核对的数据、交易账本及诊断输出。当前周频三因子组合的主要问题是高换手成本和收益表现缺乏跨年稳定性；排名缓冲的改善幅度不足。这个负面结果仍能用于检验框架与解释策略机制，不能据此生成实盘投资结论。')
p('后续顺序为补齐开发期资料和事件来源，预先固定降低换手的候选规则，再开展2021—2023年验证；满足预先登记的验证条件后才打开2024—2025年封存测试。本次未访问封存数据。')
h('参考资料与内部证据索引')
refs=[
 '[1] 课程材料：CF2026_Project1.pdf。重点参见第9页因子卡、第12—15页诊断与绩效、第18—19页评价与交付要求。',
 '[2] Tushare Pro，日线行情接口文档。<link href="https://tushare.pro/document/2?doc_id=27" color="#355c82">接口说明（可点击）</link>。行情字段与单位按接口约定；分红等接口索引见项目README及年度报告。',
 '[3] 项目研究记录：docs/2018-corporate-action-audit.md。逐项列出配股、重整、字段更正及证券代码映射的事件日期和一手来源。',
 '[4] 项目研究记录：docs/2019-corporate-action-audit.md。记录已核验配股及仍待补齐的发行结果公告，保留未解释事项。',
 '[5] 项目年度记录：docs/2026-09-23-annual-results.md；docs/2018-development-results.md；docs/2019-development-results.md。对应原始结果、限制及核验历史。',
 '[6] 深圳证券交易所，证券代码变更相关公告（2019-12-11）。<link href="https://www.szse.cn/disclosure/notice/general/t20191211_572534.html" color="#355c82">公告链接</link>。历史映射处理见[3]；本次未重新在线核验公告内容。',
 '[7] 本次诊断修订记录：output/project1_revision/manifest.json。报告表4—6和图2—3来自修订后的CSV；表1、7—9及图4—5来自已有年度实验输出。'
]
for r in refs:p(r,small)
p('AI辅助范围：代码组织、异常检查、实验结果整理、文字与版式修订。数值由本地数据与脚本生成，不能用AI文字解释替代计算和来源核验。',small)


def footer(canvas,doc):
    canvas.saveState()
    canvas.setFont('Song',8)
    canvas.setFillColor(HexColor('#666666'))
    canvas.drawString(52,A4[1]-30,'计算金融 Project 1 | A 股周频多因子研究')
    canvas.drawRightString(A4[0]-52,A4[1]-30,'开发期实验 · 修订版 v3')
    canvas.setStrokeColor(HexColor('#b9c8d5'));canvas.line(52,A4[1]-37,A4[0]-52,A4[1]-37)
    canvas.drawCentredString(A4[0]/2,25,f'{doc.page}')
    canvas.restoreState()


doc=SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=52,leftMargin=52,topMargin=54,bottomMargin=45,
                      title='A股周频多因子策略研究 - Project 1',author='Project 1 研究报告')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT)
