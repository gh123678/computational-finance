"""Preserve the 23-event review scope and quantify pre-change holding exposure."""
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.rights import verified_rights


def main():
    baseline = ROOT / 'output/development_comparison/before_rights_20260928'
    registry = {(r.code, r.ex.strftime('%Y-%m-%d')): r for r in verified_rights()}
    rows, sources = [], {}
    for year in (2016, 2017, 2019, 2020):
        folder = baseline / f'development_{year}'
        events = pd.read_csv(folder / 'unexplained_adjustments.csv')
        holdings = {}
        for child in folder.iterdir():
            path = child / 'holdings.csv'
            if path.is_file():
                holdings[child.name] = pd.read_csv(path)
                sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        for event in events.itertuples(index=False):
            exposed = []
            for strategy, frame in holdings.items():
                hit = frame.loc[frame.ts_code.eq(event.ts_code) &
                                frame.date.between(event.prior_date, event.trade_date)]
                if ((hit.shares + hit.pending_shares) > 0).any():
                    exposed.append(strategy)
            right = registry.get((event.ts_code, event.trade_date))
            rows.append(dict(year=year, code=event.ts_code, prior_date=event.prior_date,
                             event_date=event.trade_date, factor_change=event.relative_change,
                             prior_run_exposed_strategies=exposed,
                             status='verified_rights' if right else 'unresolved',
                             record_date=right.record.strftime('%Y-%m-%d') if right else None,
                             source=right.source if right else None))
    assert len(rows) == 23, 'Review baseline unexpectedly changed'
    output = ROOT / 'output/development_comparison/action_review_20260928.json'
    output.write_text(json.dumps(dict(
        scope='Pre-change daily holdings from prior quoted date through event date, inclusive; no intraday exposure inference',
        events=rows, holdings_sha256=sources), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(rows)} reviewed; {sum(r["status"] == "verified_rights" for r in rows)} verified rights; '
          f'{sum(bool(r["prior_run_exposed_strategies"]) for r in rows)} with daily holding exposure')


if __name__ == '__main__':
    main()
