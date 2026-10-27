"""Download a public Yahoo chart response for personal course analysis.

No account, paid subscription, browser cookie or access-control bypass is used.
Raw vendor data are kept outside the distributable submission by default.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pandas as pd

START, END, SYMBOL = "2021-10-14", "2026-10-14", "MSFT"

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fetch(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    stamp = lambda s: int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())
    params = dict(period1=stamp(START), period2=stamp("2026-10-15"), interval="1d", events="div,splits")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (personal academic analysis)"})
    with urlopen(req, timeout=45) as response:
        raw = response.read()
        status = response.status
    obj = json.loads(raw)
    if obj["chart"].get("error"):
        raise ValueError(obj["chart"]["error"])
    x = obj["chart"]["result"][0]
    dates = pd.to_datetime(x["timestamp"], unit="s", utc=True).tz_convert("America/New_York").strftime("%Y-%m-%d")
    frame = pd.DataFrame({"Date": dates, "AdjClose": x["indicators"]["adjclose"][0]["adjclose"]})
    frame = frame.loc[frame.Date.between(START, END)].sort_values("Date")
    if frame.empty or frame.Date.iloc[0] != START or frame.Date.iloc[-1] != END:
        raise ValueError("Provider did not supply the required frozen window; never invent missing observations.")
    raw_path, csv_path = output / "MSFT_yahoo_raw.json", output / "MSFT_prices.csv"
    raw_path.write_bytes(raw)
    frame.to_csv(csv_path, index=False, float_format="%.10f", lineterminator="\n")
    now = datetime.now(timezone.utc)
    record = dict(symbol=SYMBOL, provider="Yahoo Finance public chart interface", request_url=url,
        historical_interface="https://finance.yahoo.com/quote/MSFT/history/",
        retrieved_at_utc=now.isoformat(), retrieved_at_china=now.astimezone(timezone(__import__('datetime').timedelta(hours=8))).isoformat(),
        http_status=status, currency=x["meta"]["currency"], exchange=x["meta"].get("fullExchangeName"),
        timezone="America/New_York", requested_start=START, requested_end=END,
        actual_start=frame.Date.iloc[0], actual_end=frame.Date.iloc[-1], rows=len(frame),
        selected_field="indicators.adjclose[0].adjclose -> AdjClose",
        adjustment="Provider-adjusted for splits and dividend distributions, as of retrieval; not an unadjusted traded price or a point-in-time corporate-action database.",
        adjustment_reference="https://in.help.yahoo.com/kb/adjusted-close-sln28256.html",
        raw_sha256=sha256(raw_path), analyzed_csv_sha256=sha256(csv_path),
        csv_encoding="UTF-8", csv_serialization="Date,AdjClose; ten decimal places; LF line endings",
        raw_redistribution="Redistribution rights were not established; raw response and full price CSV are retained privately, omitted from the ZIP. No public redistribution license is asserted.",
        grader_access_route="Use the public historical interface or this downloader for personal course access. Compare the exact analyzed CSV hash before reproducing A1; a vendor revision is a different input, not an exact reproduction.",
        terms_reference="https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html")
    (output / "provenance.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(fetch(args.output), indent=2))
