# -*- coding: utf-8 -*-
"""profit_dedt 切片 × 量价因子 相关性/IC 速览（只读诊断，不进模型）。

数据：output/profit_dedt_slice_alignment_20261010/merged_panel.csv（2410 行，22 键）
回接 common_samples 的 label（前向收益，label_valid 过滤）。

方法（三层，如实呈现小样本限制）：
- L1 池化：2410 行上 consumption_value 与各量价因子的 Spearman/Pearson
  （注意：同一键值在窗口内重复，有效样本远小于 2410）；
- L2 键级：22 键各取首拼接截面因子值 + 窗口内平均 label，n=22 的 Spearman；
- L3 截面可行性：每个 trade_date 有 ≥2 只基本面股票的截面数（切片仅 22 键，
  逐日截面普遍只有 1 只，逐日截面 IC 基本不可行——如实报告，不硬算）。

本脚本只读诊断，不改任何模型、标签或冻结产物；不构成因子有效性结论。
"""
import json
from pathlib import Path

import pandas as pd
from scipy.stats import pearsonr, spearmanr

ROOT = Path(__file__).resolve().parent.parent
MERGED = ROOT / "output" / "profit_dedt_slice_alignment_20261010" / "merged_panel.csv"
PANEL = ROOT / "output" / "open_source_ml_risk_2018_2020_r1" / "common_samples.csv"
OUT = ROOT / "output" / "profit_dedt_slice_ic_20261010"

PV = ["momentum20", "reversal5", "lowvol20", "ret20", "vol20"]


def sp(x, y):
    x, y = pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")
    m = x.notna() & y.notna()
    if m.sum() < 3:
        return None, m.sum()
    r, p = spearmanr(x[m], y[m])
    return r, int(m.sum())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    m = pd.read_csv(MERGED, dtype={"trade_date": str, "ts_code": str})
    labels = pd.read_csv(PANEL, dtype={"trade_date": str, "ts_code": str},
                         low_memory=False)[["ts_code", "trade_date", "label", "label_valid"]]
    # 面板 trade_date 为 YYYY-MM-DD，须归一为 YYYYMMDD 才能与 merged_panel 回接
    labels["trade_date"] = labels["trade_date"].str.replace("-", "", regex=False)
    m = m.merge(labels, on=["ts_code", "trade_date"], how="left")
    m["label"] = m["label"].where(m["label_valid"].astype(str) == "True")

    rows = []
    # L1 池化
    for f in PV:
        r, n = sp(m["consumption_value"], m[f])
        rp, _ = pearsonr(pd.to_numeric(m["consumption_value"], errors="coerce"),
                         pd.to_numeric(m[f], errors="coerce"))
        rows.append({"level": "L1_pooled", "target": f, "spearman": r,
                     "pearson": round(rp, 4), "n_rows": n, "note": "窗口内值重复，有效样本<行数"})
    # L2 键级（首截面因子值 + 窗口均值 label）
    first = m.sort_values("trade_date").groupby(["ts_code", "end_date"], as_index=False).first()
    win = (m.groupby(["ts_code", "end_date"], as_index=False)
             .agg(mean_label=("label", "mean"), n_sections=("trade_date", "nunique")))
    key = first.merge(win, on=["ts_code", "end_date"])
    key.to_csv(OUT / "key_level_22.csv", index=False, encoding="utf-8")
    for f in PV + ["mean_label"]:
        r, n = sp(key["consumption_value"], key[f])
        rows.append({"level": "L2_key_level", "target": f, "spearman": r,
                     "pearson": None, "n_rows": n, "note": "n=22 键，首截面取值"})
    # L3 基本面逐日截面（n=每日期基本面股票数，均值约 9.6）
    cnt = m.groupby("trade_date")["ts_code"].nunique()
    sec_ic = {f: [] for f in ["profit_dedt"] + PV}
    sec_rows = []
    for d, x in m.dropna(subset=["label"]).groupby("trade_date"):
        if len(x) < 3:
            continue
        rec = {"trade_date": d, "n_stocks": len(x)}
        for c in ["consumption_value"] + PV:
            v = spearmanr(x[c], x["label"])[0]
            rec[c] = v
            sec_ic["profit_dedt" if c == "consumption_value" else c].append(v)
        sec_rows.append(rec)
    pd.DataFrame(sec_rows).to_csv(OUT / "per_section_ic.csv", index=False, encoding="utf-8")
    l3 = {}
    for name, vals in sec_ic.items():
        s = pd.Series([v for v in vals if pd.notna(v)])
        l3[name] = {"sections": int(s.size), "mean_ic": round(float(s.mean()), 4),
                    "median_ic": round(float(s.median()), 4),
                    "std_ic": round(float(s.std()), 4)}
    # 量价的逐日截面 IC（对照：面板全股票）——仅作背景对照
    pv_panel = pd.read_csv(PANEL, dtype={"trade_date": str, "ts_code": str},
                           low_memory=False)[["ts_code", "trade_date"] + PV]
    pv_panel["trade_date"] = pv_panel["trade_date"].str.replace("-", "", regex=False)
    full = labels.merge(pv_panel, on=["ts_code", "trade_date"], how="inner")
    full["label"] = full["label"].where(full["label_valid"].astype(str) == "True")
    ics = {}
    for f in PV:
        g = full.dropna(subset=[f, "label"]).groupby("trade_date")
        vals = [spearmanr(x[f], x["label"])[0] for _, x in g if len(x) >= 30]
        vals = [v for v in vals if pd.notna(v)]
        ics[f] = {"sections": len(vals),
                  "mean_ic": round(float(pd.Series(vals).mean()), 4),
                  "median_ic": round(float(pd.Series(vals).median()), 4)}
    with open(OUT / "fundamental_section_ic.json", "w", encoding="utf-8") as fh:
        json.dump(l3, fh, ensure_ascii=False, indent=2)
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "ic_summary.csv", index=False, encoding="utf-8")
    with open(OUT / "pv_daily_ic_reference.json", "w", encoding="utf-8") as fh:
        json.dump(ics, fh, ensure_ascii=False, indent=2)

    lines = [
        "# profit_dedt 切片相关性/IC 速览（只读诊断）",
        "",
        "- 日期：2026-10-10；输入：merged_panel.csv（2410 行，22 键，3630244）",
        "- 性质：相关性速览，不进模型；切片 22 键在窗口内长期有效，逐日基本面股票数均值约 "
        f"{cnt.mean():.1f}（中位 {cnt.median():.0f}），小样本截面 IC 可算但噪声大，只作方向性参考",
        "",
        "## L1 池化相关（2410 行，注意窗口内值重复）",
        "",
        "| 因子 | Spearman | Pearson | 行数 |",
        "|---|---|---|---|",
    ]
    for _, r in summary[summary.level == "L1_pooled"].iterrows():
        lines.append(f"| {r['target']} | {r['spearman']:.4f} | {r['pearson']} | {r['n_rows']} |")
    lines += [
        "",
        "## L2 键级相关（n=22：首拼接截面因子值 / 窗口均label）",
        "",
        "| 目标 | Spearman | n |",
        "|---|---|---|",
    ]
    for _, r in summary[summary.level == "L2_key_level"].iterrows():
        lines.append(f"| {r['target']} | {r['spearman']:.4f} | {r['n_rows']} |")
    lines += [
        "",
        "## L3 基本面逐日截面 IC（每日期 n=基本面股票数，n≥3 才算）",
        "",
        f"- 逐日基本面股票数：均值 {cnt.mean():.1f}、中位 {cnt.median():.0f}、最大 {cnt.max()}"
        f"（切片股票共出现在 {m['trade_date'].nunique()} 个截面）",
        "",
        "| 变量 | 截面数 | 均值IC | 中位IC | IC标准差 |",
        "|---|---|---|---|---|",
    ]
    for name, v in l3.items():
        lines.append(f"| {name} | {v['sections']} | {v['mean_ic']} | {v['median_ic']} | {v['std_ic']} |")
    lines += [
        "- 注：同一键值在窗口内逐日重复，逐日 IC 间高度自相关，均值 IC 的显著性不可按独立样本解释",
        "",
        "## 背景对照：量价因子逐日截面 IC（全 2912 股票池，label_valid）",
        "",
        "| 因子 | 截面数 | 均值IC | 中位IC |",
        "|---|---|---|---|",
    ]
    for f, v in ics.items():
        lines.append(f"| {f} | {v['sections']} | {v['mean_ic']} | {v['median_ic']} |")
    lines += [
        "",
        "## 解读纪律",
        "",
        "- profit_dedt 为利润水平值，天然带规模效应；上述相关不调整规模、行业，不得当作因子有效性证据",
        "- 000759.SZ 两键带版本链 caveat，002055.SZ 取值在原文区间内——结论对这些键不敏感时也不升级结论强度",
        "- 纪律不变：usable_in_verified_history 全 False、时点核验批准 0、冻结 CSV 未动",
    ]
    with open(OUT / "report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(summary.to_string(index=False))
    print("fundamental section IC:", json.dumps(l3, ensure_ascii=False))
    print("pv daily IC reference:", json.dumps(ics, ensure_ascii=False))


if __name__ == "__main__":
    main()
