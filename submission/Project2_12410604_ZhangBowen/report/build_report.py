"""Build the editable Chinese report from verified machine-readable results."""
from pathlib import Path
import argparse
import csv
import json
import sys
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether
from latex_math import prepare_formulas, LatexEquation, merge_vector_formulas

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/"results"
BLUE=colors.HexColor("#1b5878")
INK=colors.HexColor("#22313e")
MUTED=colors.HexColor("#586a76")


def read_csv(name):
    with (RESULTS/name).open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


def load(name):
    return json.loads((RESULTS/name).read_text(encoding="utf-8"))


def register_fonts():
    font=Path("C:/Windows/Fonts/simfang.ttf")
    heading=Path("C:/Windows/Fonts/simhei.ttf")
    if font.exists() and heading.exists():
        pdfmetrics.registerFont(TTFont("BodyCN",str(font)))
        pdfmetrics.registerFont(TTFont("HeadingCN",str(heading)))
        return "BodyCN","HeadingCN"
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light","STSong-Light"


def build(output=None):
    body,heading=register_fonts()
    latex_records=prepare_formulas(ROOT/"report")
    latex_placements=[]
    summary=load("summary.json")
    audit=load("independent_verification.json")
    p1audit=load("p1_independent_verification.json")
    p1integration=load("p1_integration_evidence.json")
    checks=read_csv("manual_checks.csv")
    sensitivities={r["variant"]:r for r in read_csv("sensitivities.csv")}
    holdout=read_csv("holdout_metrics.csv")
    boot=load("bootstrap.json")
    config=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
    core=summary["core_regression"]
    metrics=summary["original_managed_metrics"]
    market=summary["original_market_metrics"]
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle("CN",fontName=body,fontSize=10.2,leading=16,textColor=INK,spaceAfter=8,wordWrap="CJK"))
    styles.add(ParagraphStyle("SmallCN",parent=styles["CN"],fontSize=8.6,leading=12.5,spaceAfter=6))
    styles.add(ParagraphStyle("CellCN",parent=styles["CN"],fontSize=8.6,leading=12,spaceAfter=0))
    styles.add(ParagraphStyle("H1CN",fontName=heading,fontSize=22,leading=28,textColor=BLUE,spaceAfter=17,wordWrap="CJK"))
    styles.add(ParagraphStyle("H2CN",fontName=heading,fontSize=13,leading=19,textColor=BLUE,spaceBefore=8,spaceAfter=9,wordWrap="CJK"))
    styles.add(ParagraphStyle("TitleCN",fontName=heading,fontSize=30,leading=42,textColor=BLUE,spaceAfter=22,wordWrap="CJK"))
    styles.add(ParagraphStyle("Equation",fontName="Helvetica",fontSize=10,leading=16,textColor=BLUE,leftIndent=12,spaceAfter=8))
    story=[]
    def p(text,style="CN"):
        story.append(Paragraph(text,styles[style]))
    def title(number,text):
        if story:story.append(PageBreak())
        p(f"{number:02d}  {text}","H1CN")
    def h(text):p(text,"H2CN")
    def eq(key,number):story.append(LatexEquation(key,latex_records[key],latex_placements,number))
    def code(text):p(escape(text),"Equation")
    def table(headers,rows,widths=None):
        data=[[Paragraph(escape(str(x)),styles["CellCN"]) for x in headers]]
        data.extend([[Paragraph(escape(str(x)),styles["CellCN"]) for x in row] for row in rows])
        t=Table(data,colWidths=widths or [507/len(headers)]*len(headers),repeatRows=1,hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e5eef3")),
                               ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f5f8fa")]),
                               ("LINEBELOW",(0,0),(-1,0),.7,BLUE),("VALIGN",(0,0),(-1,-1),"TOP"),
                               ("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),
                               ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        story.append(t);story.append(Spacer(1,9))
    def figure(name,width=507):
        item=Image(str(RESULTS/"figures"/name))
        item.drawHeight=item.imageHeight/item.imageWidth*width
        item.drawWidth=width
        story.append(item);story.append(Spacer(1,7))
    def row(strategy,cost=10,spread=0):
        return next(r for r in holdout if r["strategy"]==strategy and int(r["cost_bps"])==cost and int(r["financing_spread_bps"])==spread)
    def f(value,d=3):return f"{float(value):.{d}f}"
    def pct(value,d=2):return f"{float(value)*100:.{d}f}%"

    story.append(Spacer(1,40))
    p("CF2026 · PROJECT 2 · V3 · LaTeX","H2CN")
    p("波动率管理组合\n核心结论复现与风险约束扩展".replace("\n","<br/>"),"TitleCN")
    p("Volatility-Managed Portfolios<br/>Moreira &amp; Muir (2017)","H2CN")
    p(f"Zhang Bowen　|　学号 {config['student_id']}<br/>计算金融　|　2026年10月20日")
    story.append(Spacer(1,18))
    h("研究结论")
    p(f"在1065个月的共同口径下，使用上一月实现方差的倒数调整市场风险敞口，本次得到年化alpha {core['alpha_annual_pct']:.2f}%（HC1标准误{core['alpha_se_annual_pct']:.2f}），市场beta {core['beta']:.3f}；管理组合夏普{metrics['sharpe']:.3f}，高于市场{market['sharpe']:.3f}。原表的正alpha和风险调整后改善方向得到复现，数值存在可见差异。")
    a,b=row("uncapped"),row("cap2")
    p(f"扩展至2016-2024年历史后续窗口，在相同10bp单边成本下，将仓位限制在2倍，最大回撤由{pct(a['max_drawdown_total'])}降为{pct(b['max_drawdown_total'])}，夏普由{f(a['sharpe'])}升为{f(b['sharpe'])}；年化复合收益约为{pct(b['cagr_total'])}，低于市场的{pct(row('market')['cagr_total'])}。风险目标得到改善，收益领先市场的目标没有实现。")
    h("阅读索引")
    table(["页码","内容"],[["2-3","原文、复现边界、公式、时点和P1接入"],["4-5","原/新结果并排与差异归因"],["6-8","固定上限、成本、融资与不确定性"],["9-10","独立核验、复现入口、限制与来源"],["11","v2平台接入证据、逐笔样本与修订验收"]],[65,442])
    p("本报告为有限范围的研究复现；精确月端点与原始历史数据版本未经作者确认。所有表格和图由包内代码和数据快照生成。","SmallCN")

    title(2,"原文与复现边界")
    h("完整来源与核心问题")
    p("Moreira, A. &amp; Muir, T. (2017). Volatility-Managed Portfolios. <i>The Journal of Finance</i>, 72(4), 1611-1644. DOI: 10.1111/jofi.12513。研究通过按上一月实现方差倒数缩放组合，考察风险调整后表现。本文只复现市场因子的单因子回归，不将结论扩展为全部因子或实盘结果。")
    table(["项目","原文目标","本次对应"],[
        ["核心图表","Table I, Panel A, 第1列；原PDF第9页（期刊1619页）","alpha、SE、beta、N、R-squared与RMSE并排比较"],
        ["辅助表","Table II 市场夏普0.42、管理0.51；Table V管理0.52","两个印刷值分别保留，不混成单一精确目标"],
        ["时期","1926-2015，N=1065；未明确具体月端点","1926-08至2015-04；由首个可用方差月及N推断"],
        ["数据","French日/月频市场超额收益及RF","2024-12 FIZ日/月快照；CIZ同窗控制替换"],
        ["推断","异方差调整标准误","主报HC1；HC0与HAC(6)为补充检查"],
        ["交易","原表主回归不扣成本、无杠杆上限","主比较保持；可交易账户约束单列扩展"]
    ],[62,215,230])
    h("哪些差异不能被默认为一致")
    p("2024年FIZ数据并非作者2015年使用的原始版本。French会重构历史序列，2025年起切换为CIZ。共同日期上的FIZ/CIZ对照能检验本次版本变化，不能证明已完全解释与论文原表的残差。")
    p("原文式(2)以22交易日表示一个月，本次采用自然月全部实际交易日及实际月均值；真实天数不同会改变相对权重。原文的精确月端点、日历执行细节和稳健标准误小样本修正均作为补充约定保留，另做敏感性。")
    p("正式方案、目标值、补充假设及题目逐条对应见docs/protocol.md；原文核对记录和来源指纹见docs/paper_sources.md。","SmallCN")

    title(3,"公式、时点与P1接入")
    p("令f为市场超额收益，RF为无风险月收益，n为某月实际交易日数。原始文件以百分数给值，进入系统后统一除以100。日数据用于波动度量，月数据用于月度持有收益，二者不互相连乘替代。")
    eq("variance",1)
    eq("weights",2)
    eq("scale",3)
    p(f"先完成自然月聚合，再将RV位移一个月。主样本c={summary['scale']:.10f}，使两组超额收益样本标准差相等；绝对误差仅{summary['core_variance_match_absolute_error']:.2e}。c来自完整主样本，是原文脚注6中的事后波动归一化，不能把绝对仓位和收益解释为当时已知。")
    h("研究回归与指标口径")
    eq("regression",4)
    eq("annualization",5)
    eq("metrics",6)
    p("年化alpha及其标准误以百分数/年报告，beta不年化。夏普使用月超额收益。RMSE按原表的线性年化回归单位报告，不能当作通常的年化风险标准差。总收益包含RF；CAGR和回撤使用含初始1元的总收益净值。")
    eq("wealth",7)
    h("复用与新增的明确边界")
    p("原P1数据读取、样本登记、期间汇总、月收益重建与费用分析实际运行；新增月度信号与后端通过P1目标及四表接口衔接。原函数和完整冻结源文件随包留档，13组实验的接入证据集中在第11页。原A股股数执行约束不适用于本题，未被冒用。","SmallCN")

    title(4,"原表与本次结果并排")
    names={"n":"有效月数 N","alpha_annual_pct":"alpha（%/年）","alpha_se_annual_pct":"alpha标准误（%/年）","beta":"市场beta","beta_se":"beta标准误","r_squared":"R-squared","rmse_paper_units":"RMSE（原表单位）","sharpe":"管理组合夏普"}
    comparisons=read_csv("comparison.csv")
    table(["指标","原文","本次","本次 - 原文"],[[names[r["metric"]],f(r["paper"],3),f(r["reproduction"],3),f(r["difference"],3)] for r in comparisons],[180,100,110,117])
    p("原值来源：Table I Panel A第1列（期刊1619页）；夏普来源Table II（1622页）。本文不是逐位复刻：alpha差约0.09个百分点/年，beta与R-squared也有可见差异。","SmallCN")
    figure("original_comparison.png")
    h("可以支持的结论")
    p(f"本次alpha t值为{core['alpha_t']:.2f}，市场beta低于1，管理组合夏普{metrics['sharpe']:.3f}高于市场{market['sharpe']:.3f}，与目标结论方向一致。该回归检验与夏普差检验不是同一件事；不能把正alpha直接当作夏普差已显著或可执行策略必然盈利的证明。")
    p("中间月度因子、日数、RV、lag_RV、权重与管理收益完整保存在results/original_monthly.csv；逐月资金净值另见original_account.csv。","SmallCN")

    title(5,"先核查错误，再解释差异")
    h("公式修订留痕")
    initial=json.loads((ROOT/"audit/variance_mean_initial/original_regression.json").read_text(encoding="utf-8"))
    p(f"初版使用中心化平均平方，alpha={initial['alpha_annual_pct']:.4f}%/年；核对原文式(2)后改为平方和，alpha={core['alpha_annual_pct']:.4f}%/年。平均平方虽更接近原表，也未被选为主版本。初版配置、结果及逐月证据完整留在audit/variance_mean_initial。")
    wanted=[("baseline_FIZ_ddof0","平方和主版本"),("mean_squared_daily_deviations","平均平方"),("variance_ddof1","ddof=1调整"),("month_end_2015_12","延至2015-12"),("start_1927_01","改从1927-01开始"),("daily_CIZ_only","仅替换日数据"),("monthly_CIZ_only","仅替换月数据"),("both_CIZ","日/月同时CIZ")]
    table(["单项对照","N","alpha %/年","夏普"],[[label,sensitivities[key]["n"],f(sensitivities[key]["alpha_annual_pct"]),f(sensitivities[key]["sharpe"])] for key,label in wanted],[223,60,112,112])
    h("数据版本证据与交互")
    base=float(sensitivities["baseline_FIZ_ddof0"]["alpha_annual_pct"])
    dd=float(sensitivities["daily_CIZ_only"]["alpha_annual_pct"])-base
    mm=float(sensitivities["monthly_CIZ_only"]["alpha_annual_pct"])-base
    both=float(sensitivities["both_CIZ"]["alpha_annual_pct"])-base
    p(f"1065个共同月中，月超额收益有{summary['vintage_monthly_changed_count']}项变化，上一月RV有{summary['vintage_lag_rv_changed_count']}项变化。仅换日数据使alpha变化{dd:+.4f}个百分点，仅换月数据{mm:+.4f}，同时替换为{both:+.4f}。交互残差为{both-dd-mm:+.6f}个百分点，不能把单项影响机械相加。混合版本仅用于诊断，不是正式主数据。")
    h("时点、估计和未解释部分")
    lag=sensitivities["two_month_lag"];common=sensitivities["two_month_common_baseline"]
    p(f"在同为1064个月的窗口中，把信号额外延迟一月，alpha由{float(common['alpha_annual_pct']):.3f}%降至{float(lag['alpha_annual_pct']):.3f}%，表明时间对齐具有实质影响。HC0/HC1及HAC(6)只改变推断，不改变点估计，详见standard_error_sensitivity.csv。")
    p("仍未解释：作者当年原始日/月快照、精确月端点，以及固定22日与自然月落实细节。已有对照不足以将全部原表差异唯一归因于数据版本。下一步需要作者原代码与原始快照，逐月对齐后再比较。","SmallCN")

    title(6,"原窗口：风险与仓位证据")
    figure("original_cumulative.png")
    p(f"总收益包含RF，起始净值1，纵轴为对数。相同超额收益波动率下，管理组合CAGR为{pct(metrics['cagr_total'])}，市场为{pct(market['cagr_total'])}；最大回撤分别为{pct(metrics['max_drawdown_total'])}和{pct(market['max_drawdown_total'])}。这些是本次事后归一化的附加诊断，并非论文Table I原值。","SmallCN")
    figure("original_weights.png")
    p(f"主样本平均风险资产敞口{metrics['average_weight']:.2f}倍、最大{metrics['maximum_weight']:.2f}倍。极端杠杆提示原表无上限结果不应直接解释为普通账户可实施的收益。由此提出固定2倍上限，以限制低方差月份过度暴露。")
    p("上限不再重新归一化，因此扩展的波动率可以不同于原方案。风险约束、费用和融资均单独记录，不把事后改变后的表现充当原文复现结果。","SmallCN")

    title(7,"自主扩展：2倍上限与同口径对照")
    p("2016-01至2024-12共108个月。c固定为原主样本估计，不使用后续收益再校准；2015-05至12也不另行估计。该窗口为历史后续评价，数据在2026年取得，不是实际提前封存的前向检验。唯一策略改变是以下2倍上限，不重新缩放，也不搜索最佳上限。")
    eq("cap",8)
    figure("holdout_nav.png")
    table(["10bp成本","CAGR总收益","超额夏普","最大回撤","年换手"],[[label,pct(row(name)["cagr_total"]),f(row(name)["sharpe"]),pct(row(name)["max_drawdown_total"]),f(row(name)["annualized_turnover"],2)] for name,label in [("market","市场"),("uncapped","无上限"),("cap2","2倍上限")]],[100,105,100,105,97])
    h("改进是否达到目标")
    p(f"2倍上限将最大回撤由{pct(a['max_drawdown_total'])}降至{pct(b['max_drawdown_total'])}，年换手由{float(a['annualized_turnover']):.2f}降至{float(b['annualized_turnover']):.2f}；夏普提高{float(b['sharpe'])-float(a['sharpe']):.3f}。但CAGR略低于无上限，更低于市场；因此只能说风险和换手目标改善，不能声称综合收益占优。")
    h("月度执行的定义")
    p("每组从现金开始，首笔进场计费；后续按持有风险资产的收益漂移计算成交额。目标是扣费后财富的风险资产比例。市场全仓持有时只产生初始进场交易。费用方程解析求解，独立核验另用二分求根和风险资产/现金账重建；无期末平仓费。")

    title(8,"成本、融资与不确定性")
    p("设交易前风险资产权重为d，扣费后目标为w，单边费率为k，交易费占交易前财富的比例为下式。求解要求费用和目标组合可行，卖出分支的分母为正。","SmallCN")
    eq("fees",9)
    table(["单边成本","方案","CAGR","超额夏普","最大回撤"],[[f"{cost}bp",label,pct(row(name,cost)["cagr_total"]),f(row(name,cost)["sharpe"]),pct(row(name,cost)["max_drawdown_total"])] for cost in [0,10,30] for name,label in [("uncapped","无上限"),("cap2","2倍上限")]],[80,110,105,105,107])
    p("所有费用组使用相同样本、c和目标生成规则。扩大交易成本会降低收益；30bp时两种管理方案仍然保留，未因不利结果删去。该模型按月末理想成交计算，不包含市场冲击、保证金追缴或同月内强制减仓。")
    h("融资利差独立变化")
    table(["10bp + 200bp/年借款利差","CAGR","超额夏普","最大回撤"],[[label,pct(row(name,10,200)["cagr_total"]),f(row(name,10,200)["sharpe"]),pct(row(name,10,200)["max_drawdown_total"])] for name,label in [("uncapped","无上限"),("cap2","2倍上限")]],[215,97,98,97])
    p("RF以外的200bp融资成本只对正借款余额收取，保持其他设定不变。这是风险敏感性，不是从样本挑出的最优利差。")
    eq("net_return",10)
    p("上式的lambda是小数形式的年借款利差，按12个月分摊。净超额收益等于扣除成本后的总收益减RF。","SmallCN")
    h("配对分块bootstrap")
    ci=boot["original_managed_minus_market"];co=boot["holdout_cap2_minus_uncapped_10bp"]
    table(["夏普差","点估计","95%区间"],[["原窗口：管理 - 市场",f(ci["difference"]),f"[{ci['ci95_low']:.3f}, {ci['ci95_high']:.3f}]"],["后续10bp：上限 - 无上限",f(co["difference"]),f"[{co['ci95_low']:.3f}, {co['ci95_high']:.3f}]"]],[270,90,147])
    p("12个月循环分块、配对重抽样2000次，种子20261020/20261021。两个区间均包含0，故夏普改善的统计确定性有限。区间没有同时修正所有敏感性比较，属于探索性证据；1065个月与108个月的结果也不能假定处于同一市场分布。")

    title(9,"小样本与独立核验")
    h("从原始日记录手算到下月权重")
    table(["持有月 / 形成月","日数","RV平方和","权重","管理超额收益"],[[r["investment_month"]+" / "+r["variance_month"],r["daily_count"],f"{float(r['sum_centered_squares']):.7f}",f(r["weight"],4),pct(r["managed_excess"],3)] for r in checks],[160,43,100,92,112])
    p("上述RV由脚本显式遍历每日收益、计算月均值，再将偏差平方相加；不是调用主引擎的方差函数。data/sample_daily_for_manual_check.csv提供所有参与日记录，results/manual_checks.csv保留均值、平方和、c/RV、下月市场收益和误差。单一市场因子没有横截面排序分组，核验对象改为时点、标量权重与逐月收益。")
    h("实际运行证据")
    table(["证据","本次状态","核对内容"],[
        ["单元检查","34项通过","原21项，以及源码一致性、实际函数调用、精细RF、目标合约与导出账务"],
        ["独立复算",f"{audit['checks_passed']}项通过","原始ZIP、RV、c、权重、回归、11组后续账户与绩效"],
        ["P1接入独立核算",f"{p1audit['checks_passed']}项通过","13组实验、3318条目标；由导出成交/现金重建净值与持仓"],
        ["双重账务","通过","主代码解析解；核验代码二分求根、现金与风险资产逐月结算"],
        ["数据完整性","4份ZIP的SHA通过","source_manifest逐项核对；无密码或API密钥"],
        ["P1复用","每组逐月收益对账通过","原monthly_returns确实参与计算，最大误差接近浮点精度"]
    ],[100,110,297])
    p("独立核验仅使用标准库和NumPy，不导入主引擎、pandas、statsmodels或P1。它确认本次实现和快照之间的一致性，不能认证数据供应商的历史事实，或证明作者未披露设定与本次相同。")
    p("日志：results/tests.txt、independent_verification.json、manual_checks.json、run_log.txt；版本：results/environment.json与代码SHA清单。","SmallCN")

    title(10,"复现、限制与来源")
    h("离线复现入口")
    code("python -m pip install -r requirements-tested.txt")
    code("python -m p1_platform --output reproduced_results")
    code("python -m pytest tests p1_platform -q")
    code("python scripts/independent_verify.py")
    code("python scripts/verify_p1_integration.py")
    code("python scripts/manual_checks.py")
    code("python report/build_report.py")
    p("默认读取随包快照，无需联网或账号。--output另写重算结果，便于保留提交版；独立核验脚本默认核对results，可用--results指定另一个输出目录。数据下载脚本只是可选来源更新入口，不覆盖不同内容的冻结文件。报告重建需要reportlab与可用中文字体；PDF已预生成。")
    h("实质局限与下一步")
    p("第一，月端点为推断，原始作者快照及精确22日落实未知，不能称为完全数值复现。第二，当前数据重构历史，后续窗口不是当时提前登记的真实前向测试。第三，全样本归一化的主样本c含未来信息；后续固定c只能排除该窗口内的再校准。第四，研究因子不等于某个可直接交易的ETF；月内杠杆、融资、冲击与保证金约束仍未覆盖。第五，单一市场和一个上限不足以证明跨市场稳定性。下一步优先获取作者代码/快照，随后才是在独立时点数据与具体工具上做前向验证。")
    h("可追溯来源")
    p('1. Moreira &amp; Muir (2017), <i>The Journal of Finance</i> 72(4), 1611-1644. <link href="https://doi.org/10.1111/jofi.12513" color="#1b5878">doi.org/10.1111/jofi.12513</link>。目标：式(1)(2)、脚注6、Tables I/II/V。',"SmallCN")
    p('2. 作者公开版本：<link href="https://amoreira2.github.io/alan-moreira.github.io/VolPortfolios_published.pdf" color="#1b5878">Moreira-hosted published PDF</link>；已核对的本地源SHA见docs/paper_sources.md。压缩包提供完整引用和来源链接。',"SmallCN")
    p('3. Kenneth French Data Library：<link href="https://mba.tuck.dartmouth.edu/pages/Faculty/ken.french/data_library_202412_archive.html" color="#1b5878">2024-12 FIZ archive</link>；<link href="https://mba.tuck.dartmouth.edu/pages/faculty/Ken.French/data_library.html" color="#1b5878">current library and FIZ/CIZ notice</link>。4份日/月ZIP快照与获取信息在data/。',"SmallCN")
    p('4. 课程任务：随包sources/CF2026_Project2.pdf。需求逐条映射在docs/protocol.md；文件SHA清单验证提交内容完整性。',"SmallCN")
    h("结论")
    p("在明确补充假设下，复现支持原研究正alpha与较高风险调整后表现的方向。2倍上限在后续窗口降低回撤和换手，但未实现高于市场的收益；其夏普改善区间包含0。数据、代码和不利结果全部保留，结论限定在本次方法、样本与成本口径。")

    title(11,"v2：P1平台接入证据与验收")
    p("第二版补强实际接入，不改变研究参数或用新收益替换旧结论。原P1函数原样抽取为冻结内核，French观测经P1读取、样本登记后生成P1目标表，月度执行通过backend适配输出四表，再调用原P1分析与12期绩效适配。原股票执行约束不适用于研究因子。")
    table(["实际路径","复用/扩展与证据"],[
        ["1. 来源 -> P1读取","4张p1_inputs因子观测表；原read_market实际读取，保留日RF精度"],
        ["2. 样本 -> 目标表","原dataset_config拒绝未登记样本；targets保留signal_date/execution_date/ts_code/target_weight"],
        ["3. 目标 -> 月度后端","验证同日/未来形成、缺月、重复及未知工具；新后端只接收验证后的目标权重"],
        ["4. 后端 -> P1四表","13组nav/orders/holdings/corporate_events表；逐笔成交与现金/指数单位可反算"],
        ["5. 原分析 -> 月度绩效","原summarize期间指标与cost_breakdown逐笔核对；原monthly_returns实际对账"]
    ],[135,372])
    h("目标表样本：2016年10bp的2倍上限方案")
    demo=read_csv("p1_runs/holdout_cap2_10bp/targets.csv")[:3]
    table(["持有月","形成日","执行日","目标风险权重"],[[r["month"],r["signal_date"][:10],r["execution_date"][:10],f(r["target_weight"],5)] for r in demo],[95,135,135,142])
    p("形成日均早于执行日，方差仅来自上一月。执行日为理想月边界的首个源交易日标签，价格是合成指数记账价，raw_open为空；未核验真实开盘及首日隔夜收益可实现性。该可分割研究指数不是股票/ETF，月内保证金等未覆盖。","SmallCN")
    h("验收证据与修订边界")
    p(f"本次{p1integration['experiment_count']}组实验共{p1integration['target_rows_total']}条目标。独立脚本不导入平台或引擎，核对原P1文件/函数SHA，并从导出成交、风险单位与现金逐月复算，{p1audit['checks_passed']}项通过；新旧核心结果的比较记录在audit/v1_to_v2_comparison.json。")
    p("冻结完整源文件在p1_platform/reference，精确抽取代码在legacy.py；可用function_provenance.json核对逐个函数段。legacy.summarize的252日年化输出明确丢弃，只核对不依赖年化的总收益、回撤、现金、费用和换手；月度年化由适配器执行。")
    p("这比v1仅共享绩效模块更完整地满足“数据导入、信号接口、回测与绩效分析”的平台接入要求；仍不主张复用了不适用的A股股数引擎。","SmallCN")

    def canvas_page(canvas,doc):
        canvas.saveState()
        w,h=A4
        canvas.setStrokeColor(colors.HexColor("#cedae1"));canvas.line(44,43,w-44,43)
        canvas.setFont(body,8);canvas.setFillColor(MUTED)
        canvas.drawString(44,29,"CF2026 Project 2 | 12410604 | Volatility-Managed Portfolios")
        canvas.drawRightString(w-44,29,f"{doc.page}")
        canvas.restoreState()
    destination=ROOT/(output or "report/Project2_Report_v3.pdf")
    destination.parent.mkdir(parents=True,exist_ok=True)
    base_dir=ROOT/"report/.latex_tmp";base_dir.mkdir(exist_ok=True)
    base_pdf=base_dir/"report_base.pdf"
    doc=SimpleDocTemplate(str(base_pdf),pagesize=A4,leftMargin=44,rightMargin=44,topMargin=40,bottomMargin=57,
                          title="Project 2: Volatility-Managed Portfolios",author="Zhang Bowen, 12410604")
    doc.build(story,onFirstPage=canvas_page,onLaterPages=canvas_page)
    evidence=merge_vector_formulas(base_pdf,destination,latex_records,latex_placements)
    (RESULTS/"latex_render_verification.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    print(destination)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default=None,help="Optional new PDF path, e.g. report/rebuilt.pdf")
    build(parser.parse_args().output)
