"""Append one issuer-verified gross dividend; preserve every original input."""
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'data/continuous_2016_2025'
OUT = ROOT/'data/continuous_2016_2025_dividend_r1'
SOURCE = ROOT/'output/continuous_event_audit_20261005/evidence/001323_20250603.pdf'
SOURCE_SHA256 = '2ca23a1b4e67b8294a75e2d7604ca570ff26a11680253ba1900a5f1abacffaa6'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_record(frame):
    if (frame.ts_code.eq('001323.SZ') & frame.ex_date.eq('20250609')).any():
        raise ValueError('Dividend already exists; never double count')
    row = {key: '' for key in frame.columns}
    row.update(ts_code='001323.SZ', end_date='20241231', ann_date='20250603',
               div_proc='实施', stk_div='0.0', stk_bo_rate='0.0', stk_co_rate='0.0',
               cash_div_tax='1.0', record_date='20250606', ex_date='20250609',
               pay_date='20250609', imp_ann_date='20250603')
    # cash_div is a vendor net amount; actual withholding varies by holder.
    # The ledger uses gross cash_div_tax and its predeclared fixed tax scenario.
    assert set(row)==set(frame.columns)
    return row


def main():
    if OUT.exists():
        raise ValueError('Revision directory exists; inspect instead of overwriting')
    assert digest(SOURCE)==SOURCE_SHA256, 'Issuer evidence changed'
    manifest=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
    for file, expected in manifest['files_sha256'].items():
        assert digest(BASE/file)==expected, file
    selected=[]
    for chunk in pd.read_csv(BASE/'daily.csv',chunksize=100000,dtype={'trade_date':str}):
        selected.append(chunk.loc[chunk.ts_code.eq('001323.SZ') & chunk.trade_date.isin(['20250606','20250609'])])
    quotes=pd.concat(selected,ignore_index=True)
    assert len(quotes)==2 and quotes[['open','close']].gt(0).all().all()
    for folder in (ROOT/'output/continuous_2016_2025').iterdir():
        path=folder/'holdings.csv'
        if path.exists():
            held=pd.read_csv(path,dtype={'date':str})
            row=held.loc[held.date.eq('2025-06-06') & held.ts_code.eq('001323.SZ')]
            assert row.empty or (row.shares.eq(0)&row.pending_shares.eq(0)).all(), folder.name
    old=pd.read_csv(BASE/'dividend.csv',dtype=str).fillna('')
    row=add_record(old)
    OUT.mkdir()
    for file in manifest['files_sha256']:
        shutil.copy2(BASE/file, OUT/file)
    buffer=io.StringIO(newline='')
    writer=csv.DictWriter(buffer,fieldnames=list(old.columns),lineterminator='\n')
    writer.writerow(row)
    original=(BASE/'dividend.csv').read_bytes()
    assert original.endswith(b'\n')
    with (OUT/'dividend.csv').open('ab') as target:
        target.write(buffer.getvalue().encode('utf-8'))
    new=pd.read_csv(OUT/'dividend.csv',dtype=str).fillna('')
    pd.testing.assert_frame_equal(new.iloc[:-1].reset_index(drop=True),old)
    assert new.iloc[-1].to_dict()==row
    for file in manifest['files_sha256']:
        if file!='dividend.csv':
            assert digest(OUT/file)==digest(BASE/file)
    revision=dict(source_url='https://static.cninfo.com.cn/finalpage/2025-06-03/1223733350.PDF',
                  source_sha256=SOURCE_SHA256,added_record=row,
                  reference_cash_reduction=0.9833939,gross_cash_entitlement=1.0,
                  base_manifest_sha256=digest(BASE/'manifest.json'),
                  base_files_sha256=manifest['files_sha256'],
                  input_change='Only appended one dividend; other files byte-identical')
    (OUT/'revision.json').write_text(json.dumps(revision,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest.update(dataset=OUT.name,title='2016–2025连续账户公告分红修订r1',revision=revision)
    manifest['files_sha256']={file:digest(OUT/file) for file in manifest['files_sha256']}
    manifest['row_counts']['dividend']=len(new)
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Revision complete: one dividend appended; every other input byte-identical')


if __name__=='__main__':
    main()
