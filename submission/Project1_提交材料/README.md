# 计算金融 Project 1 提交材料

## 建议阅览顺序

1. **最终报告**：`docs/2026-09-25-project1-report-v3.pdf`（9 页）。
2. **复现说明与数据字典**：`docs/project1-reproduction.md`。
3. **修正后因子诊断**：`output/project1_revision/2018`、`2019`、`2020`。
4. **年度策略结果**：`output/development_2018`、`development_2019`、`development_2020`，包含每年九组实验的净值、持仓、订单及成本归因。

## 目录

- `quant_research/`：数据、因子、股票池、组合、交易执行与会计实现。
- `scripts/`：年度核验、因子诊断重建和 PDF 生成入口。
- `tests/`：自动测试。
- `data/audit/`：历史股票、名称及行业元数据。
- `data/development_2018/`、`2019/`、`2020/`：三年实际使用的完整数据快照（含预热）；每个目录带 manifest.json。
- `output/`：对应实验、核验和诊断结果。
- `docs/`：最终报告、研究记录及来源索引；不包含旧版 PDF。
- `原项目说明.md`：项目原 README，补充数据获取、设计及研究进展。
- `文件清单_SHA256.json`：包内文件大小和校验值（清单自身除外）。

## 环境与离线核查

建议 Python 3.13；原研究测试环境和版本见 requirements-tested.txt。以下命令均在本 README 所在目录执行。依赖已安装后，使用所附数据不需要登录数据接口。

```powershell
python -m pip install -r requirements-report.txt
python -m pytest -q
python scripts/verify_annual.py --dataset development_2018
python scripts/verify_annual.py --dataset development_2019
python scripts/verify_annual.py --dataset development_2020
```

重算修正版因子诊断并生成报告：

```powershell
python scripts/rebuild_project1_diagnostics.py
python scripts/build_project1_report.py
```

报告生成使用 Windows 宋体和黑体；其他系统需要将脚本内的字体路径改为本机可嵌入的中文字体。无需重新生成 PDF 即可直接阅读报告、核查结果。

完整重跑交易实验：

```powershell
python -m quant_research.research --dataset development_2018
python -m quant_research.research --dataset development_2019
python -m quant_research.research --dataset development_2020
```

完整重跑会更新对应年度输出；随后可再次执行年度核验、诊断重建和报告生成。首次数据下载步骤见原项目说明，需要使用者自己的数据接口权限；提交包不含访问凭据。

## 结果与版本边界

三个年度为独立初始资金账户，不能将净值拼接为连续多年收益。提交版报告使用已保存并核验的年度交易结果；因子分组诊断已修正“删除未来标签缺失样本后重新分组”的问题，修订结果在 project1_revision 中。旧年度 factor_groups.csv 留作运行溯源，**最终因子诊断以 project1_revision 为准**。

年度 summary.json 的源码摘要对应原交易实验；project1_revision/manifest.json 单独记录修订诊断的来源与摘要。没有改写旧摘要来假称同一次运行。报告中的费用和滑点情景、历史元数据限制、未完成的验证/封存测试均保留说明。

本包仅收录报告相关的 2018—2020 年开发期材料。不包含凭据、Git 历史、接口响应缓存、临时文件、旧版报告或其他年份实验。
