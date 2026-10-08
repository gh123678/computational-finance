"""Independently check stored rank decomposition and paired forward means."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/continuous_rank_turnover_20261006'


def sha(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            result.update(block)
    return result.hexdigest()


def main():
    fingerprints=json.loads((OUT/'input_sha256.json').read_text(encoding='utf-8'))
    for name,expected in fingerprints.items():
        assert sha(ROOT/name)==expected,name
    exits=pd.read_csv(OUT/'exit_rank_components.csv')
    eligible=exits.loc[exits.current_eligible]
    rebuilt=eligible[['momentum20_rank_change','reversal5_rank_change','lowvol20_rank_change']].mean(axis=1)
    assert np.allclose(rebuilt,eligible.combined_score_change,rtol=0,atol=1e-12)
    observations=pd.read_csv(OUT/'forward_observations.csv',parse_dates=['signal_date'])
    means=observations.groupby(['strategy','signal_date','horizon','role']).forward_return.mean().unstack('role')
    means=means.dropna(subset=['entry','exit'])
    difference=means.entry-means.exit
    saved=pd.read_csv(OUT/'paired_forward_returns.csv',parse_dates=['signal_date']).set_index(['strategy','signal_date','horizon'])
    assert difference.index.equals(saved.index)
    assert np.allclose(difference,saved.entry_minus_exit,rtol=0,atol=1e-12)
    summary=pd.read_csv(OUT/'forward_summary.csv').set_index(['strategy','horizon','role'])
    grouped=observations.groupby(['strategy','horizon','role']).forward_return
    assert np.array_equal(grouped.count().reindex(summary.index),summary.valid)
    assert np.array_equal(grouped.size().reindex(summary.index),summary.total)
    assert np.allclose(grouped.mean().reindex(summary.index),summary.mean_return,rtol=0,atol=1e-12)
    check=json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    check['post_analysis_validation']=dict(status='passed',
        input_files=len(fingerprints),eligible_exit_rows=len(eligible),paired_dates=len(saved),
        checks=['全部记录的输入指纹复核通过','三因子排名变化均值与保存的综合得分变化一致',
                '从逐股票未来标签独立聚合，配对差和覆盖率与摘要一致'],
        verifier_sha256=sha(Path(__file__)))
    (OUT/'verification.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf-8')
    outputs={path.name:sha(path) for path in OUT.iterdir() if path.is_file() and path.name!='output_sha256.json'}
    (OUT/'output_sha256.json').write_text(json.dumps(outputs,indent=2),encoding='utf-8')
    print(json.dumps(check['post_analysis_validation'],ensure_ascii=False))


if __name__=='__main__':
    main()
