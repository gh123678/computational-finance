"""Strict adapters for the first (daily/monthly) section of French CSV archives."""
from pathlib import Path
import csv
import io
import re
import zipfile
import numpy as np
import pandas as pd


def read_french_zip(path, frequency):
    if frequency not in {"daily", "monthly"}:
        raise ValueError("frequency must be daily or monthly")
    digits = 8 if frequency == "daily" else 6
    with zipfile.ZipFile(path) as archive:
        members = [x for x in archive.namelist() if x.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("Expected exactly one CSV member")
        content = archive.read(members[0]).decode("utf-8-sig")
    rows = []
    for row in csv.reader(io.StringIO(content)):
        key = row[0].strip() if row else ""
        if re.fullmatch(r"\d{" + str(digits) + r"}", key):
            if len(row) != 5:
                raise ValueError("Unexpected French factor schema")
            rows.append([key, *[float(x) for x in row[1:]]])
        elif rows:
            break
    if not rows:
        raise ValueError("No dated factor data found")
    frame = pd.DataFrame(rows, columns=["date", "Mkt-RF", "SMB", "HML", "RF"])
    fmt = "%Y%m%d" if frequency == "daily" else "%Y%m"
    dates = pd.to_datetime(frame.pop("date"), format=fmt)
    frame.index = pd.DatetimeIndex(dates) if frequency == "daily" else pd.PeriodIndex(dates, freq="M")
    frame.index.name = "date"
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Duplicate or unordered factor dates")
    if not np.isfinite(frame.values).all() or (frame.values <= -99.99).any():
        raise ValueError("Missing/nonfinite French observations")
    # Published files are percentage points; all computations use decimal returns.
    return frame / 100.0


def monthly_panel(daily, monthly, ddof=0, aggregation="sum_centered_squares"):
    if ddof not in {0, 1}:
        raise ValueError("ddof must be 0 or 1")
    if daily.index.has_duplicates or not daily.index.is_monotonic_increasing:
        raise ValueError("Invalid daily chronology")
    expected = pd.period_range(monthly.index.min(), monthly.index.max(), freq="M")
    if not monthly.index.equals(expected.rename("date")):
        raise ValueError("Monthly factor data must be contiguous")
    groups = daily["Mkt-RF"].groupby(daily.index.to_period("M"))
    rv = groups.var(ddof=ddof).rename("rv")
    if aggregation == "sum_centered_squares":
        rv = rv * groups.count()
    elif aggregation != "mean_centered_squares":
        raise ValueError("Unsupported realized variance aggregation")
    panel = monthly[["Mkt-RF", "RF"]].rename(columns={"Mkt-RF": "market_excess", "RF": "rf"}).copy()
    panel["rv"] = rv
    panel["daily_count"] = groups.count()
    if panel[["rv", "daily_count"]].isna().any().any() or (panel.daily_count < 10).any():
        raise ValueError("Missing or abnormally short daily month")
    if (panel.rv <= 0).any():
        raise ValueError("Realized variance must be positive")
    panel["lag_rv"] = panel.rv.shift(1)
    return panel
