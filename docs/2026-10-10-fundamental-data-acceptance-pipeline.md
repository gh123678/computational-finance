# 基本面数据验收管线（Fundamental Data Acceptance Pipeline）

版本：v1.0　日期：2026-10-10　基线提交：7a720f2　状态：生效

本文档把 2026-10-07 至 2026-10-09 执行的"四轮候选采集 + 机器初筛 + OCR 辅助定性"沉淀为可重跑的标准流程。将来启用任何基本面因子之前，照本文档执行；数据商接口数据刷新、票池扩展或报告期扩展后，也按本文档重跑。

## 1. 目的与适用范围

**要解决的问题**：数据商财务接口（`forecast` / `fina_indicator` / `fina_audit`）对同一 `(ts_code, ann_date, end_date)` 键可能同时返回 `update_flag=0`（当时披露值）与 `update_flag=1`（后续修订值）两行。修订值可能回填到原始公告日。若不加甄别地用作因子输入，会把"未来才知道的修订"泄漏进历史截面，或把单位/口径错误带入筛选阈值。

**本管线的产出**：
1. 每个冲突键的定性结论（修订模式 / 提取失败 / 真差异 / 其他）；
2. 未决键的人工核对验收清单（含候选 PDF 与最近原文值）；
3. 一份明确的启用门槛：门槛未过，任何因子不得消费受影响字段。

**适用字段**：当前全量冲突盘点针对 `fina_indicator.profit_dedt`（扣非净利润）。其他字段接入时按同一管线执行，阈值与容差另行校准。

## 2. 不可违反的纪律

以下规则在任何一轮都不允许放松，脚本与人工操作共同遵守：

1. `usable_in_verified_history` 全部维持 `False`，直到人工逐版本时点核验通过；时点核验批准数保持 0。
2. 冻结产物不得改动：策略数据集（`data/continuous_2016_2025` 等）、原文核对队列（`original_document_check_queue.csv`）、已封存实验结果。采集与初筛只新增证据目录。
3. 提取失败不等于数据差异；缺失与失败不解释为无风险。
4. OCR 只作辅助证据；任何 OCR 改判必须人工复核页面上下文后才可并入结论。
5. 验收门槛未通过前，任何基本面因子不得消费 `profit_dedt`。
6. 纯量价策略数据集不消费上述字段，本管线的结论不改变其可用性，也不借本管线回改任何已发布结果。

## 3. 输入与前置条件

| 项 | 位置 | 说明 |
|---|---|---|
| 接口原始记录 | `data/announcement_financial_audit_2013_2020_r1/fina_indicator_records.csv` 等 | 8,736 个股票/接口单元下载结果（2,912 只股票 × 3 接口） |
| 审计工作目录 | `output/announcement_financial_audit_20261007/` | 队列、各轮证据、初筛与裁定产物 |
| 原文核对队列 | `output/.../original_document_check_queue.csv` | 2,306 行（2,307 含表头），冻结，只读 |
| Python 环境 | `.venv_ml_risk`（项目虚拟环境） | 需 pandas、PyMuPDF（fitz）、numpy、rapidocr-onnxruntime |
| 测试基线 | `tests/` | 130 项（2026-10-10 实测 130 passed） |

下载层工程要求（重跑采集时）：独立缓存、限速 1.3 秒、满页日期细分、有限重试、断点续传、旧结果 SHA-256 哈希检查；令牌经 DPAPI 解密且不得写入源码或输出。

## 4. 管线各阶段

各脚本均在仓库根目录以 `python scripts/<name>.py` 运行。每阶段列出目的、关键输入与产出；产出目录相对 `output/announcement_financial_audit_20261007/`。

### 阶段 0：接口采集

- 脚本：`scripts/announcement_financial_audit.py`
- 产出：三个接口原始 JSON（按请求哈希缓存）、`download_status.json`、记录汇总 CSV。
- 通过标准：8,736/8,736 单元完成；成功空结果记为成功，不等于权限失败；显式保存 `update_flag` 字段。

### 阶段 1：机器初筛（r1 + r2）

- r1 脚本：`scripts/screen_profit_dedt_candidates.py`
  - 输入：`fina_indicator_records.csv`、已下载候选文档文本（`remaining_evidence_r1`、`remaining_evidence_r2_fixed_r1`）。
  - 产出：`auto_screen_20261008/`（profit_dedt_screen.csv、profit_dedt_screen_row_level.csv、auto-screen-report.md）。
  - 口径：对 1,085 行有候选的记录做 1,865 次文档级扣非净利润比对；行级记录匹配状态，供按键聚合。
- r2 脚本：`scripts/screen_forecast_audit_candidates.py`
  - 产出：`auto_screen_20261009/`（forecast 42 行、fina_audit 46 行，288 次字段级检查）。
  - 注意：fina_audit 的扫描件可能无文本层，签字差异需复核为误捕后再定性。
- 通过标准：产生"差异候选"与"定位失败"两类清单；初筛只产生字段级证据，不升级任何核验计数。

### 阶段 2：冲突键盘点

- 脚本：`scripts/inventory_update_flag_conflicts.py`
- 输入：`fina_indicator_records.csv`、r1 行级初筛结果、策略票池 `data/continuous_2016_2025/daily.csv`。
- 产出：`case_review_20261009/update_flag_conflict_all204.csv`、`update_flag_conflict_out_of_queue.csv`、`update-flag-conflict-inventory.md`。
- 口径：同一键 `update_flag=0` 与 `=1` 数值不一致即入列；数值一致的 88,318 键属正常版本冗余，不构成冲突。
- 通过标准：全部冲突键与原文核对队列对齐，确认无"队外"键。

### 阶段 3：逐案裁决（r1 候选）

- 脚本：`scripts/build_profit_dedt_case_review.py` → `scripts/finalize_profit_dedt_adjudication.py` → `scripts/classify_update_flag_conflict_keys.py` → `scripts/refine_adjudication_update_flag.py`
- 产出：`case_review_20261009/`（case-review-report.md、case_cards.txt、case_cards_round2.txt、case_adjudication.csv、case_flags.csv、true-difference-case-cards.md、root-cause-update-flag-report.md）。
- 关键根因（本轮实证）：122 条差异候选中 28 条为提取假象、6 键为版本链问题，余下 80 键里 78 键实为数据商修订行——**同键 flag=0 行与原文精确一致**。这确立了"修订模式"主假设：flag=0 = 当时披露原文值，flag=1 = 后续修订。
- 通过标准：每个差异候选有明确类别；真差异与版本链未决进入后续定向检索。

### 阶段 4：第三轮采集与初筛（补窗口缺口）

- 脚本：`scripts/collect_update_flag_conflict_evidence.py` → `scripts/screen_update_flag_conflict_round3.py`
- 目的：对 100 个无候选键补采。缺口归因先行：58 个键对公告日在 2021 年（2020 年报季），落在首轮窗口外；40 个精确日期索引无匹配；9 个文档已下载但上轮结果缺 `row_keys` 未被读取。
- 采集策略：取消公告日窗口上限（覆盖 2021 公告日）；数据商 `ann_date` 无精确匹配时逐日加宽至 ±5 天，每份文档记录索引日与偏离天数。
- 产出：`update_flag_conflict_evidence_20261009/`（documents、responses、results、status.json）、`auto_screen_20261009_conflict_keys/`。
- 通过标准：33 键（66 行）完成初筛；28 键确认修订模式（flag=0 匹配原文，抽样 6/6 人工核对通过，无一例反向）；仍无候选的键对全部登记进入阶段 6。

### 阶段 5：真差异键的更正版 / 重发版定向检索

- 脚本：`scripts/collect_and_screen_corrections.py` → `scripts/collect_and_screen_corrections_r2.py` → `scripts/find_republication_versions.py`
- 目的：对真差异未决键检索发行人更正公告、更新后年报与版本链重发版，区分"数据商口径差异"与"发行人确实修订"。
- 产出：`correction_evidence_20261009/`、`_r2/`、`version_chain_evidence_20261009/`。
- 本轮结果：000676.SZ 20201231 经更新后 2020 年报解决——数据商把更新后重发版回填为 flag=0（**回填警示案例**，修订模式键使用 flag=0 前需版本链核验）；其余键无发行人更正，维持未决。
- 通过标准：每个真差异键有"存在更正 / 不存在更正"的明确结论与证据存档。

### 阶段 6：第四轮采集与初筛（发行人列表 API 补齐）

- 脚本：`scripts/collect_issuer_listing_evidence.py` → `scripts/screen_issuer_listing_round4.py`
- 目的：对剩余 65 个键对（67 键）改用发行人列表接口补齐候选文档（144 份），清零候选文档缺口。
- 产出：`issuer_listing_evidence_20261009/`、`auto_screen_20261009_issuer_listing/`。
- 注意：发行人列表可能暴露招股披露场景——键的 `ann_date` 可能是招股意向书披露日而非年报披露日（见 002781.SZ 三键案例），定性时先确认披露场景再比对数值。

### 阶段 7：OCR 辅助裁定（图像表格兜底）

- 脚本：`scripts/ocr_adjudicate_unresolved.py`
- 目的：对文本提取失败的键，用 rapidocr-onnxruntime 对候选 PDF 页面 OCR，查找扣非净利润数值；页面结果按 PDF 缓存。
- 产出：`ocr_adjudication_20261009/`（ocr_adjudication.csv、ocr_adjudication_summary.json、ocr_cache/）。
- 判定口径：`flag0_ocr_match` / `flag1_ocr_match`（0.5 元容差内精确匹配）、`ocr_value_found_no_flag_match`、`ocr_no_value`。
- 本轮结果：36 键、273 页；4 键改判（全部人工复核上下文后并入）：
  - 000851.SZ 20201231：OCR 命中已取消版本年报叙述段 -196,380,050.17 元 = flag=0 → 修订模式；
  - 002781.SZ 20121231 / 20131231 / 20141231：招股意向书扣非表 11,984.42 / 12,417.65 / 14,724.63 万元 = flag=0 × 10⁴ → 修订模式，同时纠正披露场景误判。
- 通过标准：改判必须逐键人工复核上下文；`usable_in_verified_history` 仍全 False。

### 阶段 8：终版状态合并

- 脚本：`scripts/finalize_update_flag_conflict_status.py`
- 输入：r1 裁决、r1/r3/r4 初筛、更正版检索、OCR 裁定。
- 产出：`case_review_20261009/update_flag_conflict_all204.csv` 的 `final_status` 列终版。
- 通过标准：204 键全部有终版定性，分类合计与盘点一致。

### 阶段 9：验收清单生成

- 脚本：`scripts/build_acceptance_checklist.py`
- 产出：`case_review_20261009/fundamental-factor-acceptance-checklist.md`（人工可读）与 `acceptance_checklist.csv`（机器可读，含每键候选 PDF 文件名与最近原文值）。
- 通过标准：每个未决键至少一份候选 PDF 可人工核对；清单键数与未决键数一致。

### 阶段 10：验证门禁

- 命令：项目虚拟环境 `python -m pytest tests/ -q`
- 通过标准：130 项全部通过（基线 2026-10-10 实测 130 passed，6 条既有警告）；冻结产物哈希与提交 7a720f2 一致；`original_document_check_queue.csv` 行数与内容不变。

## 5. 定性词表

| 类别 | 含义 | 处置 |
|---|---|---|
| revision_row_original_available_in_queue | flag=1 为修订行；同键 flag=0 与原文精确一致 | 允许使用 flag=0 口径（附版本链核验） |
| cleared_extraction_artifact | 提取器定位错误，API 值与原文一致 | 关闭，无需处理 |
| unresolved_true_difference | 原文与 API 两版本均对不上 | 入验收清单，人工核对 |
| unresolved_version_chain | 已取得更正前版本，更正后版本未取得 | 定向检索；仍无则入验收清单 |
| not_found_in_candidate_text / screened_rX_extraction_not_found | 候选文本中两个版本的值都定位不到 | 证据不足，不得认定为差异；OCR 兜底后仍失败则入验收清单 |
| document_period_mismatch_excluded | 候选文档期次不符被排除 | 补充正确期次候选后重筛 |

已知反例（修订模式使用前必须排除）：
- **回填确认**（000676.SZ 20201231）：flag=0 可能是数据商回填的更新后重发版，不是当时披露原文值；
- **单位错误反例**（601989.SH）：唯一的反向案例，flag=1 为原文且 flag=0 是单位错误；
- **披露场景错配**：键的 ann_date 对应招股意向书（002781.SZ ×3），数值单位为万元，需 ×10⁴ 比对。

## 6. 启用基本面因子的验收门槛

全部满足才允许因子消费 `profit_dedt`：

1. 验收清单全部键完成人工核对并定性（当前 32 键：10 真差异未决 + 22 提取失败未决）；
2. 166 个修订模式键仅使用 flag=0 口径，且 000676 / 601989 两例完成版本链与单位核验；
3. `python -m pytest tests/ -q` 全量通过；
4. 冻结产物哈希不变，队列文件未动；
5. 核对结论回填清单并重新生成验收文档，人工签字（勾选）确认。

任一不满足：因子不得上线；已确认部分也只作证据存档，不进入特征工程。

## 7. 当前状态快照（2026-10-10，提交 7a720f2）

204 个冲突键终版分布：

| 定性 | 数量 | 占比 |
|---|---|---|
| 修订模式（flag=0 = 当时披露原文值） | 166 | 81.4% |
| 提取失败未决 | 22 | — |
| 真差异未决 | 10 | — |
| 提取伪影 | 2 | — |
| 版本链未决 | 1 | — |
| 周期错配 | 1 | — |
| 回填确认 | 1 | — |
| 单位错误反例 | 1 | — |

配套状态：验收清单 36 → 32 键（OCR 轮改判 4 键）；候选文档缺口清零；130 测试通过；`usable_in_verified_history` 全 False；时点核验批准 0；冻结输出与队列文件未动；纯量价策略数据集不受影响。

## 8. 工程故障与教训（重跑时预防）

1. 进度文件替换 WinError 5：首轮 70 单元后进程退出，71 个完成缓存保留；修复=有限重试 + 缓存续跑，协议变更记入 protocol.json，不改数据范围。
2. 中文路径/UTF-8：清单文件曾被默认 GBK 解码中止；修复=显式 `encoding="utf-8"`，读取与写出全部显式声明。
3. DPAPI 解密：普通环境解密失败，需用户环境；令牌不得输出或写入工具源码。
4. 交易所个别链接 Internal Error：保留检索线索，不标记原文读取通过。
5. pandas 空列拼接 FutureWarning：非失败，记录日志，不改变数据。
6. 断点续传必须先做旧结果哈希检查，避免重复启动覆盖已完成单元。

## 9. 重跑清单（Runbook）

- [ ] 阶段 0：采集完成，8,736/8,736，哈希检查通过
- [ ] 阶段 1：r1/r2 初筛产出，无报错
- [ ] 阶段 2：204 键（或新基线）盘点与队列对齐
- [ ] 阶段 3：差异候选逐案定性，真差异/版本链未决登记
- [ ] 阶段 4：窗口外键对 ±5 天补采，初筛
- [ ] 阶段 5：真差异键更正版检索，结论存档
- [ ] 阶段 6：发行人列表补齐，候选缺口清零
- [ ] 阶段 7：OCR 兜底，改判逐键人工复核
- [ ] 阶段 8：终版状态合并，分类合计自洽
- [ ] 阶段 9：验收清单生成，每键有候选 PDF
- [ ] 阶段 10：130 测试通过 + 冻结哈希校验
- [ ] 门槛评审：未决键清零后才允许因子消费字段
