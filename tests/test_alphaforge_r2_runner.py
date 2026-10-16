"""The raw-text adapter must retain source lexemes before numeric parsing."""
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_alphaforge_r2 as runner


def test_read_quotes_retains_raw_reference_lexemes(tmp_path, monkeypatch):
    (tmp_path/'daily.csv').write_text(
        'ts_code,trade_date,open,high,low,close,pre_close,vol,amount\n'
        '000001.SZ,20180102,10,10,10,1.00e1,10.000,100,1000\n'
        '000001.SZ,20180103,10,10,10,NA,NaN,100,1000\n'
        '000001.SZ,20180104,10,10,10,null,,100,1000\n', encoding='utf-8')
    calendar = pd.date_range('2018-01-02', periods=3)
    adjustments = pd.DataFrame(dict(ts_code=['000001.SZ']*3,
                                    trade_date=calendar,adj_factor=[1.]*3))
    monkeypatch.setattr(runner, 'DATA', tmp_path)
    monkeypatch.setattr(runner, 'read_subset', lambda name,codes:adjustments)
    monkeypatch.setattr(runner, 'correct_adjustments', lambda frame:(frame, []))
    bars, corrections = runner.read_quotes({'000001.SZ'}, calendar)
    assert bars.close_text.tolist() == ['1.00e1','NA','null']
    assert bars.pre_close_text.tolist() == ['10.000','NaN','']
    assert bars.close.iloc[0] == 10.
    assert bars.close.iloc[1:].isna().all()
    assert bars.pre_close.iloc[1:].isna().all()
    assert corrections == []
