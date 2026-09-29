# 计算金融 Project 1 精简提交包

## 先看这里

最终报告：**docs/2026-09-25-project1-report-v3.pdf**（9页）。本包包含完整研究源码、测试、最终报告、关键数据字典与来源记录，以及2018—2020年共27组实验的结果文件。

为控制提交体积，本包不含全量日线、复权、涨跌停、停牌、分红快照，以及大型日频因子表和形成日因子长表。保留了每个年度的原始数据清单和SHA-256、历史元数据、日历与基准数据。**精简包不能直接重新执行全量年度回测、年度核验或报告重建**；这些步骤需先恢复下述完整数据和中间文件。

## 包内可以直接做的事情

1. 阅读PDF报告。
2. 核对`output/development_2018`、`development_2019`、`development_2020`中全部九组实验的净值、订单、持仓、目标权重、成本归因和月收益。
3. 阅读修正后的`output/project1_revision/年份/`中的IC、五分组、覆盖率、质量检查结果。旧年度诊断文件只用于溯源，最终诊断以project1_revision为准。
4. 离线运行完整自动测试，以及随包提供的真实行情因子小样本。

```powershell
python -m pip install -r requirements-tested.txt
python -m pytest -q
python scripts/run_submission_sample.py
```

小样本包含5只股票、60个交易日、300条行情，仅验证因子计算，不代表全市场策略绩效。选择规则及数据来源见`data/sample/sample_info.json`，不依据收益表现选股。`expected_factors.csv`为预期输出，运行后自动对比并输出检查结果。更多交易、会计、未来数据隔离与诊断测试见tests目录。

## 如需完整重跑

- 使用自己的Tushare权限设置`TUSHARE_TOKEN`环境变量（本包不含任何访问凭据）。
- 保留随包提供的`data/audit/`历史元数据；不要用今日成分替代历史状态。
- 按`原项目说明.md`的数据获取步骤，下载以下三个已登记开发年度：

```powershell
python -m quant_research.download --dataset development_2018
python -m quant_research.download --dataset development_2019
python -m quant_research.download --dataset development_2020
python -m quant_research.research --dataset development_2018
python -m quant_research.research --dataset development_2019
python -m quant_research.research --dataset development_2020
python scripts/verify_annual.py --dataset development_2018
python scripts/verify_annual.py --dataset development_2019
python scripts/verify_annual.py --dataset development_2020
python scripts/rebuild_project1_diagnostics.py
```

新下载数据可能因供应商历史修订而与原快照不同。原快照清单在`data/development_年份/manifest.json`，下载前保留原清单副本以便比较；提交文件清单也记录了其摘要。必须区分“重跑同一份原始快照”和“重新获取修订后的数据”。

如需重新生成PDF，安装`requirements-report.txt`中的依赖，并运行`python scripts/build_project1_report.py`。生成器需要上述步骤补齐的因子长表；中文字体路径按操作系统调整。直接阅读随包PDF不需要执行这些步骤。

## 目录及版本说明

- quant_research、scripts、tests：实现与检查入口。
- data/sample：可运行的真实行情小样本及预期因子结果。
- data/audit：历史股票、名称和行业元数据。
- data/development_年份：原数据文件清单、交易日历及基准。
- output/development_年份：完整策略结果账本和原运行摘要。
- output/project1_revision：修正后的因子诊断结果；为减小体积省略大型formation_factors_long.csv。
- docs：最终报告、详细复现说明、公司行动记录及来源索引。
- 文件清单_SHA256.json：**本精简包实际包含的文件**和校验值。年度manifest和修订manifest可能列出本包未附带的大型文件，它们是完整研究运行的溯源记录，不是精简包库存。

原项目说明和PDF中的完整复现命令描述完整研究环境；精简包能直接运行的步骤以本README为准。三年收益来自三个独立资金账户，不能拼接为连续多年净值。本包不含旧版PDF、凭据、Git历史、原始接口响应缓存和其他年份实验。
