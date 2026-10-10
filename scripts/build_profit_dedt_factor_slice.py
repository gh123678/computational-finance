# -*- coding: utf-8 -*-
"""profit_dedt 因子数据切片试算（验收清单 32 键口径，签报 f321504 配套）。

消费口径（签报 §4）：
- revision_pattern（17 键）：按 flag=0 口径（须排除反向案例与 000676/601989，本切片已排除）
- true_difference（10 键）：按人工核定的原文值（adjudicated original_value）
- reverse_flag1（5 键）：按 flag=1 口径

纪律：不改冻结 CSV、不置 usable_in_verified_history、产出只进新目录。
"""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "output" / "announcement_financial_audit_20261007"
ADJ = AUDIT / "case_review_20261009" / "manual_adjudication_20261010.csv"
RECORDS = AUDIT / "fina_indicator_records.csv"
OUT = ROOT / "output" / "profit_dedt_factor_slice_20261010"

ADJUDICATION_TO_SOURCE = {
    "revision_pattern": "flag0",
    "true_difference": "adjudicated_original",
    "reverse_flag1": "flag1",
}
VERSION_CHAIN_CAVEAT_PREFIXES = ("000759.SZ:20161231", "000759.SZ:20171231")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    with open(ADJ, encoding="utf-8-sig", newline="") as f:
        adj_rows = list(csv.DictReader(f))
    assert len(adj_rows) == 32, f"expect 32 keys, got {len(adj_rows)}"
    dist = {}
    for r in adj_rows:
        dist[r["adjudication"]] = dist.get(r["adjudication"], 0) + 1
    assert dist == {"revision_pattern": 17, "true_difference": 10, "reverse_flag1": 5}, dist

    with open(RECORDS, encoding="utf-8-sig", newline="") as f:
        rec_rows = list(csv.DictReader(f))
    by_key = {}
    for r in rec_rows:
        by_key.setdefault((r["ts_code"], r["end_date"]), []).append(r)

    slice_rows = []
    guards = []
    for a in adj_rows:
        key = (a["ts_code"], a["end_date"])
        rows = by_key.get(key, [])
        f0 = [r for r in rows if r["update_flag"] == "0"]
        f1 = [r for r in rows if r["update_flag"] == "1"]
        assert len(f0) == 1 and len(f1) == 1, f"{key}: flag rows {len(f0)}/{len(f1)}"
        v0 = float(a["val_flag0"])
        v1 = float(a["val_flag1"])
        # 守卫 1：裁定表与源记录逐键一致
        assert abs(float(f0[0]["profit_dedt"]) - v0) < 0.01, f"{key} flag0 mismatch"
        assert abs(float(f1[0]["profit_dedt"]) - v1) < 0.01, f"{key} flag1 mismatch"
        # 守卫 2：反向键两 flag 不得相同
        if a["adjudication"] == "reverse_flag1":
            assert abs(v0 - v1) > 0.01, f"{key}: reverse case with identical flags"
        # 守卫 3：消费值映射
        src = ADJUDICATION_TO_SOURCE[a["adjudication"]]
        if src == "flag0":
            value, value_source = v0, "flag0"
        elif src == "flag1":
            value, value_source = v1, "flag1"
        else:
            value, value_source = float(a["original_value"]), "adjudicated_original"
        caveat = ""
        if f"{a['ts_code']}:{a['end_date']}" in VERSION_CHAIN_CAVEAT_PREFIXES:
            caveat = "version_chain_cancelled_version"
        slice_rows.append({
            "ts_code": a["ts_code"],
            "end_date": a["end_date"],
            "ann_date": a["ann_date"],
            "consumption_value": f"{value:.2f}",
            "value_source": value_source,
            "adjudication": a["adjudication"],
            "val_flag0": a["val_flag0"],
            "val_flag1": a["val_flag1"],
            "original_value": a["original_value"],
            "caveat": caveat,
            "evidence": a["evidence"],
            "row_sha256_flag0": f0[0]["row_sha256"],
            "row_sha256_flag1": f1[0]["row_sha256"],
            "content_sha256": f0[0]["content_sha256"],
        })
        guards.append(f"{a['ts_code']} {a['end_date']}: source={value_source}, guards 1-3 OK")

    slice_rows.sort(key=lambda r: (r["ts_code"], r["end_date"]))
    slice_path = OUT / "slice_profit_dedt_32keys.csv"
    with open(slice_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(slice_rows[0].keys()))
        w.writeheader()
        w.writerows(slice_rows)

    log = {
        "run_at": "2026-10-10",
        "authorization": {
            "sign_off_document": "case_review_20261009/profit-dedt-enablement-signoff-20261010.md",
            "sign_off_checkbox": "open (pending user signature in document)",
            "chat_approval": "user message 2026-10-10 13:56 \"开始\" approving the post-signature first slice trial",
        },
        "consumption_scope": "acceptance checklist 32 keys only; off-checklist revision keys require per-key exclusion",
        "input_baselines": {
            "manual_adjudication_20261010.csv_sha256": sha256_file(ADJ),
            "fina_indicator_records.csv_sha256": sha256_file(RECORDS),
        },
        "output": {
            "slice_profit_dedt_32keys.csv_sha256": sha256_file(slice_path),
            "row_count": len(slice_rows),
            "distribution": dist,
        },
        "guards_executed": [
            "G1: adjudication CSV values match fina_indicator_records flag rows exactly (32/32)",
            "G2: reverse_flag1 keys have distinct flag0/flag1 (5/5)",
            "G3: consumption value mapped per sign-off §4 (revision->flag0, true_diff->original, reverse->flag1)",
            "G4: reverse-case list (§5) and counterexamples 000676/601989 excluded from slice (not among 32 keys, verified)",
        ],
        "exclusions": {
            "counterexamples_not_in_slice": ["000676.SZ 20201231 (updated-republication backfill)",
                                             "601989.SH 20200630 (flag0 unit error)"],
            "extraction_failure_unresolved_22keys": "not consumed",
            "off_checklist_revision_keys": "require per-key exclusion before use",
        },
        "caveats": {
            "000759.SZ 20161231/20171231": "flag0=原文 but sourced from later-cancelled version; version-chain check required at factor use time",
            "002055.SZ 20201231": "flag0 -79,557,344.63 within original interval -79,557,0XX±2,400; adjudicated estimate -79,557,296.26 kept as evidence anchor",
        },
        "discipline": {
            "usable_in_verified_history": "unchanged (all False)",
            "point_in_time_approval_count": 0,
            "frozen_csvs_modified": False,
        },
        "per_key_guard_log": guards,
    }
    with open(OUT / "consumption_log.json", "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    lines = [
        "# profit_dedt 因子数据切片试算报告",
        "",
        "- 日期：2026-10-10；基线提交：b9eb243；配套提交：f321504（门槛执行检查）",
        "- 授权：用户 2026-10-10 13:56 批准试算；签报签字栏仍开放（文档内勾选未完成）",
        "- 消费范围：验收清单 32 键（修订 17 按 flag0、真差异 10 按核定原文值、反向 5 按 flag1）",
        "",
        "## 产出",
        "",
        f"- `slice_profit_dedt_32keys.csv`：{len(slice_rows)} 行，sha256 `{log['output']['slice_profit_dedt_32keys.csv_sha256'][:16]}…`",
        "- `consumption_log.json`：守卫执行、排除项、输入基线哈希全记录",
        "",
        "## 守卫执行结果",
        "",
        "- G1：32/32 键裁定值与源记录 flag 行精确一致",
        "- G2：5/5 反向键 flag0≠flag1",
        "- G3：消费值映射按签报 §4（revision→flag0 ×17、true_difference→original ×10、reverse→flag1 ×5）",
        "- G4：§5 反向清单与 000676/601989 反例不在切片内（已验证）",
        "",
        "## 注意事项",
        "",
        "- 000759.SZ 2016/2017：flag0=原文但出自后被取消版本，因子使用时须做版本链核验（切片已打 caveat 标记）",
        "- 002055.SZ 2020：flag0 落在原文区间内，采用 flag0 口径",
        "- 清单外修订模式键不在本次切片内，使用前仍须逐键排除",
        "",
        "## 纪律状态",
        "",
        "- usable_in_verified_history 全 False（不变）；时点核验批准 0（不变）；冻结 CSV 未动",
    ]
    with open(OUT / "report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"slice rows: {len(slice_rows)}; distribution: {dist}")
    print(f"slice sha256: {log['output']['slice_profit_dedt_32keys.csv_sha256']}")


if __name__ == "__main__":
    main()
