"""Run the included real-data factor sample offline."""
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from quant_research.factors import compute_factors
folder=ROOT/'data/sample'
bars=pd.read_csv(folder/'bars.csv',dtype={'trade_date':str,'ts_code':str})
calendar=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(folder/'calendar.csv',dtype=str).trade_date))
actual=compute_factors(bars,calendar)
expected=pd.read_csv(folder/'expected_factors.csv',dtype={'ts_code':str},parse_dates=['trade_date'])
pd.testing.assert_frame_equal(actual,expected,check_dtype=False,check_exact=False,rtol=1e-10,atol=1e-12)
out=ROOT/'output/sample';out.mkdir(parents=True,exist_ok=True)
actual.to_csv(out/'factors.csv',index=False)
print(f'PASS: {bars.ts_code.nunique()} assets, {len(calendar)} sessions, {len(actual)} factor rows match expected values.')
print('This engineering sample does not reproduce full-universe strategy returns.')
