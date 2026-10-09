"""盘点 fina_indicator update_flag 冲突键（profit_dedt 双版本值不一致）。

产出（写入 output/announcement_financial_audit_20261007/case_review_20261009/）：
- update_flag_conflict_all204.csv    全部值不一致冲突键清单
- update_flag_conflict_out_of_queue.csv  未进入初筛（无候选文档）的键清单

口径：同一 (ts_code, ann_date, end_date) 下同时存在 update_flag=0 与 =1
且两者 profit_dedt 数值不同。数值一致的 88,318 个双行键属正常版本冗余。
"""
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
AUDIT = BASE / "output" / "announcement_financial_audit_20261007"
OUT = AUDIT / "case_review_20261009"


def load_conflict_keys() -> pd.DataFrame:
    fr = pd.read_csv(AUDIT / "fina_indicator_records.csv", dtype=str, encoding="utf-8")
    fr["v"] = pd.to_numeric(fr["profit_dedt"], errors="coerce")
    rows = []
    for (ts, ad, ed), grp in fr.groupby(["ts_code", "ann_date", "end_date"]):
        f0 = grp.loc[grp["update_flag"] == "0", "v"].dropna().unique()
        f1 = grp.loc[grp["update_flag"] == "1", "v"].dropna().unique()
        if len(f0) > 0 and len(f1) > 0 and abs(f0[0] - f1[0]) > 1e-6:
            rows.append((ts, ad, ed, f0[0], f1[0]))
    ck = pd.DataFrame(rows, columns=["ts_code", "ann_date", "end_date", "val_flag0", "val_flag1"])
    ck["abs_diff"] = (ck["val_flag0"] - ck["val_flag1"]).abs()
    denom = ck[["val_flag0", "val_flag1"]].abs().max(axis=1).replace(0, pd.NA)
    ck["rel_diff_pct"] = (ck["abs_diff"] / denom * 100).round(4)
    ck["year"] = ck["end_date"].str[:4]
    return ck


def main() -> None:
    ck = load_conflict_keys()
    print(f"value-differing conflict keys: {len(ck)}")

    rl = pd.read_csv(
        AUDIT / "auto_screen_20261008" / "profit_dedt_screen_row_level.csv",
        dtype=str, encoding="utf-8",
    )
    screened = set(zip(rl["ts_code"], rl["ann_date"], rl["end_date"]))
    ck["screened"] = [
        (t, a, e) in screened for t, a, e in zip(ck["ts_code"], ck["ann_date"], ck["end_date"])
    ]
    print(f"screened: {int(ck['screened'].sum())}, not screened: {int((~ck['screened']).sum())}")

    daily = pd.read_csv(
        BASE / "data" / "continuous_2016_2025" / "daily.csv",
        usecols=["ts_code"], dtype=str, encoding="utf-8",
    )
    universe = set(daily["ts_code"].unique())
    ck["in_strategy_universe"] = ck["ts_code"].isin(universe)

    OUT.mkdir(parents=True, exist_ok=True)
    ck.sort_values("rel_diff_pct", ascending=False).to_csv(
        OUT / "update_flag_conflict_all204.csv", index=False, encoding="utf-8-sig"
    )
    ck[~ck["screened"]].sort_values("rel_diff_pct", ascending=False).to_csv(
        OUT / "update_flag_conflict_out_of_queue.csv", index=False, encoding="utf-8-sig"
    )
    print("saved to", OUT)


if __name__ == "__main__":
    main()
