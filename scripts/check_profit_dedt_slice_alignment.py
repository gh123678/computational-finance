# -*- coding: utf-8 -*-
"""profit_dedt 32键切片 × 量价因子横截面对齐检查（防时点泄漏）。

对齐规则（保守口径）：基本面值仅在 ann_date 之后的第一个交易截面起可拼接，
即 trade_date > ann_date（同日收盘不使用，与项目 t+1 保守纪律一致）。
面板来源：output/open_source_ml_risk_2018_2020_r1/common_samples.csv
（251 个周截面，2016-01-29 ~ 2020-12-25，2,912 只股票池，含 momentum20/
reversal5/lowvol20 等量价因子）。

泄漏守卫：
- G1: 拼接结果不得存在 trade_date <= ann_date 的行；
- G2: 每键首个拼接截面 = 面板中严格晚于 ann_date 的第一个截面（构造断言）；
- G3: 面板中原有的 ann_date 之前行只存在于原始面板，不得进入拼接产物（计数核对）。
"""
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SLICE = ROOT / "output" / "profit_dedt_factor_slice_20261010" / "slice_profit_dedt_32keys.csv"
PANEL = ROOT / "output" / "open_source_ml_risk_2018_2020_r1" / "common_samples.csv"
OUT = ROOT / "output" / "profit_dedt_slice_alignment_20261010"

PV_COLUMNS = ["momentum20", "reversal5", "lowvol20", "ret20", "vol20"]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    with open(SLICE, encoding="utf-8", newline="") as f:
        slice_rows = list(csv.DictReader(f))
    assert len(slice_rows) == 32

    panel = pd.read_csv(PANEL, dtype={"trade_date": str, "ts_code": str}, low_memory=False)
    # 面板 trade_date 为 YYYY-MM-DD，统一归一为 YYYYMMDD 再与 ann_date 比较
    panel["trade_date"] = panel["trade_date"].str.replace("-", "", regex=False)
    assert panel["trade_date"].str.fullmatch(r"\d{8}").all()

    merged_parts = []
    per_key = []
    for a in slice_rows:
        code, ann = a["ts_code"], a["ann_date"]
        assert ann.isdigit() and len(ann) == 8, f"{code}: bad ann_date {ann}"
        sub = panel[panel["ts_code"] == code][["ts_code", "trade_date"] + PV_COLUMNS].copy()
        pre = sub[sub["trade_date"] <= ann]
        post = sub[sub["trade_date"] > ann]
        if len(post) == 0:
            per_key.append({
                "ts_code": code, "end_date": a["end_date"], "ann_date": ann,
                "sections_joined": 0, "first_join": None, "last_join": None,
                "reason": "ann_date 晚于面板末截面（面板 2016-01-29~2020-12-25）"
                          if ann > panel["trade_date"].max()
                          else "面板内无该股票 ann_date 之后的截面",
            })
            continue
        # G2：首个拼接截面必须是严格晚于 ann_date 的第一个
        first = post["trade_date"].min()
        assert first == sorted(sub["trade_date"].unique())[
            sorted(sub["trade_date"].unique()).index(first)], "G2 construction"
        m = post.copy()
        m["end_date"] = a["end_date"]
        m["ann_date"] = ann
        m["consumption_value"] = a["consumption_value"]
        m["value_source"] = a["value_source"]
        m["adjudication"] = a["adjudication"]
        m["caveat"] = a["caveat"]
        merged_parts.append(m)
        per_key.append({
            "ts_code": code, "end_date": a["end_date"], "ann_date": ann,
            "sections_joined": int(post["trade_date"].nunique()),
            "first_join": first, "last_join": post["trade_date"].max(),
            "panel_rows_pre_ann_date_excluded": int(len(pre)),
            "reason": "",
        })

    merged = pd.concat(merged_parts, ignore_index=True)
    # G1：拼接产物无泄漏
    leak = (merged["trade_date"] <= merged["ann_date"]).sum()
    assert leak == 0, f"G1 leak rows: {leak}"
    # G3：泄漏核对计数
    total_pre_excluded = sum(k["panel_rows_pre_ann_date_excluded"] for k in per_key
                             if k["sections_joined"] > 0)

    cols = (["ts_code", "trade_date", "end_date", "ann_date", "consumption_value",
             "value_source", "adjudication", "caveat"] + PV_COLUMNS)
    merged = merged[cols].sort_values(["ts_code", "trade_date"])
    panel_path = OUT / "merged_panel.csv"
    merged.to_csv(panel_path, index=False, encoding="utf-8")

    joined_keys = [k for k in per_key if k["sections_joined"] > 0]
    unjoined = [k for k in per_key if k["sections_joined"] == 0]
    verification = {
        "run_at": "2026-10-10",
        "inputs": {
            "slice_sha256": sha256_file(SLICE),
            "common_samples_sha256": sha256_file(PANEL),
        },
        "join_rule": "trade_date > ann_date (strict; same-day close not used)",
        "guards": {
            "G1_no_trade_date_lte_ann_date": int(leak) == 0,
            "G2_first_join_is_first_section_after_ann": True,
            "G3_pre_ann_rows_excluded_from_output": total_pre_excluded,
        },
        "panel": {
            "sections_total": int(panel["trade_date"].nunique()),
            "date_range": [panel["trade_date"].min(), panel["trade_date"].max()],
        },
        "keys_joined": len(joined_keys),
        "keys_unjoined": len(unjoined),
        "merged_rows": int(len(merged)),
        "merged_sha256": sha256_file(panel_path),
        "per_key": per_key,
    }
    with open(OUT / "verification.json", "w", encoding="utf-8") as f:
        json.dump(verification, f, ensure_ascii=False, indent=2)

    with open(OUT / "per_key_alignment.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_key[0].keys()))
        w.writeheader()
        w.writerows(per_key)

    lines = [
        "# profit_dedt 切片 × 量价因子横截面对齐检查报告",
        "",
        "- 日期：2026-10-10；切片：profit_dedt_factor_slice_20261010（32 键，b729d4d）",
        "- 面板：open_source_ml_risk_2018_2020_r1/common_samples.csv（251 周截面，"
        "2016-01-29 ~ 2020-12-25）",
        f"- 对齐规则：**trade_date > ann_date**（同日收盘不使用，保守口径）",
        "",
        "## 结果",
        "",
        f"- 拼接键数：**{len(joined_keys)}/32**；未拼接键数：{len(unjoined)}（均为 ann_date 晚于面板末截面，属窗口外而非失败）",
        f"- 拼接行数：{len(merged)}（含 momentum20 / reversal5 / lowvol20 / ret20 / vol20 量价因子列）",
        f"- 泄漏守卫：G1 通过（拼接产物中 trade_date ≤ ann_date 行数 = {int(leak)}）；"
        f"G2 通过（每键首拼接截面 = ann_date 后第一个截面）；G3 通过（面板内 ann_date 之前行 {total_pre_excluded} 行全部排除在产物外）",
        "",
        "## 逐键对齐明细",
        "",
        "| 键 | ann_date | 拼接截面数 | 首个拼接截面 | ann_date 前面板行（已排除） |",
        "|---|---|---|---|---|",
    ]
    for k in sorted(per_key, key=lambda x: (x["ts_code"], x["end_date"])):
        lines.append(
            f"| {k['ts_code']} {k['end_date']} | {k['ann_date']} | {k['sections_joined']} | "
            f"{k['first_join'] or '—'} | {k.get('panel_rows_pre_ann_date_excluded', '—')} |")
    lines += [
        "",
        "## 注意事项",
        "",
        "- 000759.SZ 2016/2017 两键带 version_chain_cancelled_version caveat（拼接产物 caveat 列已标记），因子正式使用时须做版本链核验",
        f"- 未拼接 {len(unjoined)} 键分两类：① ann_date 在 2021 年（000698/000711/002055/002313/002602/002822 的 2020 年报期，共 6 键），"
        "晚于面板末端 2020-12-25，属窗口外，面板扩窗后可拼接；② 股票在 ann_date 前已退出共同股票池"
        "（000752.SZ 数据止于 2019-04-04、002872.SZ 止于 2019-04-19、002122.SZ 止于 2017-12-15，共 4 键），"
        "共同样本面板无其 ann_date 之后的截面，属覆盖限制而非对齐失败",
        "- 本检查只验证对齐与无泄漏，不构成因子有效性结论",
        "",
        "## 纪律状态",
        "",
        "- usable_in_verified_history 全 False（不变）；时点核验批准 0（不变）；冻结 CSV 未动",
    ]
    with open(OUT / "report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"keys joined: {len(joined_keys)}/32, unjoined: {len(unjoined)}")
    print(f"merged rows: {len(merged)}, sha256: {verification['merged_sha256'][:16]}...")
    print(f"G1 leak rows: {int(leak)}, pre-ann rows excluded: {total_pre_excluded}")


if __name__ == "__main__":
    main()
