"""Run the completed HW03 experiments; never substitute synthetic A1 data."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta
import experiments_gbm as experiments
import returns_analysis

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,help='Lawfully obtained frozen MSFT_prices.csv')
    p.add_argument('--seed',type=int,default=21603)
    args=p.parse_args()
    if args.seed<0: p.error('seed must be nonnegative')
    execution={'China_Standard_Time':datetime.now(timezone(timedelta(hours=8))).isoformat(),'master_seed':args.seed}
    if args.input:
        provenance=json.loads((ROOT/'data/provenance.json').read_text(encoding='utf8'))
        returns_analysis.run(args.input,provenance['analyzed_csv_sha256'],seed=args.seed)
        execution['A1']='completed with frozen input hash verified'
    else:
        execution['A1']='not run: supply --input with the lawful frozen CSV; simulation is not a replacement'
        print(execution['A1'])
    experiments.MASTER_SEED=args.seed
    experiments.RESULTS.mkdir(exist_ok=True)
    experiments.FIGURES.mkdir(exist_ok=True)
    execution['A2']=experiments.run_a2()
    execution['A3']=experiments.run_a3()
    (ROOT/'results/driver_execution.json').write_text(json.dumps(execution,indent=2),encoding='utf8')

if __name__=='__main__': main()
