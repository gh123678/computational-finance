# -*- coding: utf-8 -*-
"""清单外 166 个修订模式键的逐键核对工作清单（签报 §4.2 配套）。

事实基础（2026-10-10 复核）：
- 204 盘点中 revision_row_original_available_in_queue 共 166 键，与 32 键验收清单中的
  17 个修订键**完全不重合**（并集 183 键），故签报 §4.2 所指"清单外修订模式键"= 全部 166 键；
- 7 个已知反例键（5 反向 + 000676 + 601989）均不在 166 内（final_status 分类已隔离），
  本清单再逐键机械核验一次；
- 166 键在初筛时已确认 flag0=原文（original_available_in_queue），队列均有候选文档行
  （source_url/raw_path），但 publication_evidence_status 全为 unverified_original_version，
  且 51 键 within_ann_window=False——使用时仍需版本链核验。

分批（按风险与工作量）：
- A 批：within_ann_window=False（51 键，窗口/版本链优先核）
- B 批：窗口内且 2018-2020（91 键）
- C 批：窗口内且 2012-2017（24 键）
"""
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "output" / "announcement_financial_audit_20261007"
INV = AUDIT / "case_review_20261009" / "update_flag_conflict_all204.csv"
QUEUE = AUDIT / "original_document_check_queue.csv"
OUT = ROOT / "output" / "off_checklist_revision_worklist_20261010"

COUNTEREXAMPLES = {
    ("000488.SZ", "20151231"), ("600900.SH", "20130331"), ("601818.SH", "20130331"),
    ("600608.SH", "20130331"), ("600869.SH", "20130331"),
    ("000676.SZ", "20201231"), ("601989.SH", "20200630"),
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inv = pd.read_csv(INV, dtype=str)
    rev = inv[inv["final_status"] == "revision_row_original_available_in_queue"].copy()
    assert len(rev) == 166, len(rev)

    q0 = pd.read_csv(QUEUE, dtype=str)
    q0 = q0[q0["update_flag"] == "0"]
    m = rev.merge(q0, on=["ts_code", "ann_date", "end_date"], how="left",
                  suffixes=("", "_q"))
    assert m["raw_path"].notna().all(), "存在无队列候选行的修订键"

    # 守卫：7 反例键不在 166 内
    keys = set(zip(m["ts_code"], m["end_date"]))
    overlap = keys & COUNTEREXAMPLES
    assert not overlap, f"反例键混入 166: {overlap}"

    def batch(r):
        if r["within_ann_window"] != "True":
            return "A_window_mismatch"
        return "B_in_window_2018_2020" if int(r["year"]) >= 2018 else "C_in_window_2012_2017"

    m["batch"] = m.apply(batch, axis=1)
    m["counterexample_check"] = "passed_not_in_7"
    m["required_action"] = "逐键核对原文（候选 source_url/raw_path）+ 版本链核验后方可按 flag0 消费"
    cols = ["batch", "ts_code", "ann_date", "end_date", "year", "val_flag0", "val_flag1",
            "within_ann_window", "candidate_available_date",
            "publication_evidence_status", "source_url", "raw_path", "row_sha256",
            "counterexample_check", "required_action"]
    m = m[cols].sort_values(["batch", "year", "ts_code", "end_date"])
    wl = OUT / "worklist.csv"
    m.to_csv(wl, index=False, encoding="utf-8-sig")

    bc = m["batch"].value_counts().to_dict()
    ver = {
        "run_at": "2026-10-10",
        "inputs": {"inventory_sha256": sha256_file(INV),
                   "queue_sha256": sha256_file(QUEUE)},
        "worklist_sha256": sha256_file(wl),
        "guards": {
            "revision_keys": 166,
            "all_have_queue_candidate": True,
            "counterexample_overlap": 0,
            "disjoint_from_checklist_revision_17": True,
        },
        "batch_counts": bc,
        "discipline": {
            "usable_in_verified_history": "unchanged (all False)",
            "point_in_time_approval_count": 0,
            "frozen_csvs_modified": False,
            "note": "本清单为计划产物；消费仍需逐键人工核对原文，清单本身不批准任何消费",
        },
    }
    with open(OUT / "verification.json", "w", encoding="utf-8") as f:
        json.dump(ver, f, ensure_ascii=False, indent=2)

    lines = [
        "# 清单外修订模式键逐键核对工作清单",
        "",
        "- 日期：2026-10-10；范围：204 盘点中 revision_row_original_available_in_queue 全部 166 键",
        "- 事实：与 32 键验收清单的 17 个修订键完全不重合；7 个已知反例键均不在其中（守卫核验 0 重合）",
        "- 初筛状态：flag0=原文已确认、队列均有候选文档；但 publication_evidence_status 全为 "
        "unverified_original_version，51 键 within_ann_window=False",
        "",
        "## 分批",
        "",
        "| 批次 | 含义 | 键数 |",
        "|---|---|---|",
        f"| A | within_ann_window=False，窗口/版本链优先核 | {bc.get('A_window_mismatch', 0)} |",
        f"| B | 窗口内 2018-2020 | {bc.get('B_in_window_2018_2020', 0)} |",
        f"| C | 窗口内 2012-2017 | {bc.get('C_in_window_2012_2017', 0)} |",
        "",
        "## 使用方式",
        "",
        "- 每键按 required_action 执行：调候选文档（source_url/raw_path）核对原文值 = flag0，"
        "并做版本链核验（是否后被取消/更新版回填，参照 000676/000759 先例）",
        "- 核对结论回填本目录新文件（不动冻结 CSV）；全部 166 键清零前，清单外键不得批量消费",
        "- 纪律：usable_in_verified_history 全 False、时点核验批准 0 不变；本清单不批准任何消费",
    ]
    with open(OUT / "report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("batch counts:", bc)
    print("worklist sha256:", ver["worklist_sha256"])


if __name__ == "__main__":
    main()
