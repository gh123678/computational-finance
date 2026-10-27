# CF2026 Project 2 v3：波动率管理组合复现（LaTeX公式版）

Zhang Bowen · 12410604 · 2026-10-20 · 保留v2研究内核，更新数学排版

**先阅读 `report/Project2_Report_v3.pdf`。** 11页报告中的10组数学公式均由真正的LaTeX编译为矢量内容，包含分式、上下标、求和、根号及分段函数；可编辑源码为`report/formulas.tex`。研究内核、参数、数据、P1接入及计算结果保持v2不变，配置中的delivery_version=2指该研究内核版本，v3是本次数学排版版。

## 结果与范围

选题：Moreira & Muir (2017), *Volatility-Managed Portfolios*, Journal of Finance 72(4), 1611-1644，DOI [10.1111/jofi.12513](https://doi.org/10.1111/jofi.12513)。目标为Table I Panel A的市场组合，并核对Table II夏普。

主复现1926-08至2015-04，1065个月：年化alpha **4.9535%**（原表4.86%），HC1标准误1.5683，beta0.60065，R²0.36078；超额夏普0.51588，市场0.41805。方向复现，非逐位数值复刻。精确月端点是与N一致的推断，未经作者确认。主方差是每日收益去均值后的平方和；初版平均平方的结果保留在`audit/variance_mean_initial/`。

自主扩展2016-2024：固定2015-04以前的c，2倍上限不重缩放，比较相同0/10/30bp单边费用。10bp下无上限/2倍上限最大回撤37.26%/23.00%，夏普0.501/0.615；CAGR9.128%/9.114%，市场14.288%。上限降低风险但未超过市场，夏普差bootstrap区间包含0。该窗口使用后取得的历史数据，不是当时提前封存的前向盲测。

## 运行

Python **3.10或以上**；本次实际测试环境为3.13，精确版本见`results/environment.json`。在解压后的项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-tested.txt
python -m p1_platform --output reproduced_results
python scripts/independent_verify.py --results reproduced_results
python scripts/verify_p1_integration.py --results reproduced_results
python -m pytest tests p1_platform -q
```

如精确版本在当前Python不可安装，可使用`requirements.txt`的兼容范围；需要再次运行检查，不应直接假定与提交环境等价。报告和正式结果已经预生成，只阅读无需安装。

`python run_project.py`默认重建`results/`，建议用上面的`--output`保留提交证据。主入口校验全部原始ZIP的SHA；不联网，不更新数据。可选`python scripts/download_data.py`从官方来源获取快照，发现同名不同内容时拒绝覆盖；已冻结的manifest也拒绝覆盖。数据所有权归原来源，不包含任何私人金融账号数据。

复核正式提交结果与小样本：

```powershell
python scripts/independent_verify.py
python scripts/verify_p1_integration.py
python scripts/manual_checks.py
python scripts/verify_manifest.py
```

报告重建：

```powershell
python report/build_report.py
```

Windows优先使用系统仿宋/黑体字体并嵌入PDF。其他系统回退到ReportLab的STSong-Light；已交付PDF无需重建字体环境。报告内容依赖`results/`中的正式结果及核验记录。`run_all.ps1`可顺序重建正式结果、检查、手算和报告（Windows需要允许本地脚本执行）。

数学公式源码在`report/latex_math.py`的FORMULAS中，报告用pdfLaTeX生成的PDF矢量公式，并非截图或普通文本模拟。随包提供10个已编译公式及源码/指纹；公式未修改时可离线重建报告，无需本地TeX。修改公式则需要pdfLaTeX及standalone/amsmath/amssymb/xcolor。`report/formulas.tex`是汇总的标准LaTeX文档，可在TeX编辑器中单独编辑、编译。若报告正被阅读器占用，可另存：`python report/build_report.py --output report/rebuilt.pdf`。

## 文件导航

| 位置 | 内容 |
|---|---|
| `report/Project2_Report_v3.pdf` | 11页中文报告，10组LaTeX矢量公式；第11页保留v2接入验收 |
| `report/build_report.py` | 报告可编辑源文件，读取真实结果 |
| `report/formulas.tex` | 所有公式的标准LaTeX源码 |
| `report/latex_math.py` | 报告公式源码、编译与矢量嵌入 |
| `report/latex_formulas/` | 10个已编译矢量公式及TeX源码/指纹 |
| `results/latex_render_verification.json` | 公式资源、数量和页码检查 |
| `docs/protocol.md` | 复现协议、补充假设、要求逐条映射 |
| `docs/paper_sources.md` | 原文完整引用、目标值核对及来源指纹 |
| `docs/p1_integration.md` | P1实际复用与本次新增边界 |
| `docs/demo.md` | 5分钟演示提纲和常见问题 |
| `sources/` | 课程任务原件、官方来源说明快照和引用 |
| `data/raw/` | 4份French官方ZIP，FIZ/CIZ各日/月频 |
| `data/source_manifest.json` | 获取时间、官方URL、字节数、SHA |
| `data/sample_daily_for_manual_check.csv` | 4个形成月的日收益手算样本 |
| `src/` | 严格数据适配、逆方差信号、回归与按月自融资执行 |
| `p1_platform/` | 5个P1原函数实际运行、冻结源文件、月度后端与目标/结果接口 |
| `results/p1_inputs/` | 4张经P1原read_market实际读入的观测表 |
| `results/p1_runs/` | 13组实验的目标、成交、净值、持仓、事件与费用证据 |
| `results/p1_independent_verification.json` | 从3318条目标与成交/现金重建账户的16715项核验 |
| `results/comparison.csv` | 原表、本次值与差值并排 |
| `results/sensitivities.csv` | 方差定义、样本、来源与时点敏感性 |
| `results/holdout_*` | 全部11组后续账户及汇总 |
| `results/independent_verification.json` | 331项独立复算记录 |
| `results/manual_checks.*` | 核心公式显式手算及误差 |
| `results/figures/` | 可独立查看的研究图 |
| `results/tests.txt` | 实际34项检查输出 |
| `audit/v1_to_v2_comparison.json` | 原压缩包与v2的参数、数据和13组账户逐项比较 |
| `audit/variance_mean_initial/` | 公式修订前的配置、数值和月度证据 |
| `FILE_MANIFEST.json` | 最终文件SHA清单 |

## 方法边界

P1原read_market、dataset_config、summarize及attribution.py中的monthly_returns/cost_breakdown实际参与路径，函数和完整源文件可用SHA核对。13组经统一目标表与月度后端输出P1四表，形成日严格早于执行日。原summarize的252日年化输出丢弃，年化由12期适配负责。P1原A股整手、T+1、涨跌停及容量规则不冒充为美国研究指数规则。c在主样本中依原文使用事后等波动归一化，后续窗口冻结；超额收益用于夏普和回归，RF包含在净值/复利/回撤中。成本按持仓漂移后的成交额收取，期末不平仓；融资按RF，另列200bp借款利差。

本项目未获得作者原始2015数据快照和精确月端点。自然月实际交易日与原式22日的落实差异明确保留；未扫描端点或搜索最优上限来逼近目标。结果不能作为具体工具的实盘可行性或未来收益承诺。

本项目由AI协助实现、资料核对与报告整理；不宣称为未使用辅助工具的独立人工完成。提交前请阅读报告并确认课程对工具使用与署名的要求。
