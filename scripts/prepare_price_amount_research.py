"""Prepare approved common200 pool; fail without relaxing training requirements."""
from pathlib import Path
import json
import os
import platform
import shutil
import traceback
import numpy as np
import pandas as pd
import scipy
import sklearn

from run_retention_development import ROOT, DATA, SOURCE, sha, read_subset
from quant_research.corporate_corrections import correct_adjustments
import announcement_financial_audit as audit
from price_amount_features import FEATURES, compute_asset
from price_amount_model import training_samples, fit_scales

OLD = ROOT / 'output/label_horizon_coverage_2018_2020_r1'
OUT = ROOT / 'output/price_amount_ridge_2018_2020_r1'
SPEC = ROOT / 'docs/superpowers/specs/2026-10-12-price-amount-ridge-design.md'
PLAN = ROOT / 'docs/superpowers/plans/2026-10-13-price-amount-ridge-implementation.md'
FIT_DATES = {2018: '2017-12-29', 2019: '2018-12-28', 2020: '2020-01-03'}
PATHS = ['three_retention_common200', 'gbm_trend_risk',
         'ridge_trend_retention', 'ridge_trend_risk']


def persist(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT / 'frozen_protocol.json').exists():
        raise RuntimeError('Existing preparation attempt; inspect rather than restart')
    if shutil.disk_usage(OUT.resolve()).free < 6 * 1024**3:
        raise RuntimeError('6GiB free-space floor reached')
    lock = OUT / 'preparation.lock'
    with lock.open('x', encoding='utf-8') as stream:
        json.dump(dict(pid=os.getpid(), stage='preparation'), stream)
    try:
        run()
    except Exception:
        (OUT / 'preparation_failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        persist('preparation_status.json', dict(state='failed', pid=os.getpid(),
                                                failure='preparation_failure.txt', models_started=False))
        raise
    finally:
        lock.unlink()


def run():
    old = json.loads((OLD / 'frozen_protocol.json').read_text(encoding='utf-8'))
    core = {p.name: sha(p) for p in (ROOT / 'quant_research').glob('*.py')}
    if core != old['source_sha256']:
        raise RuntimeError('Frozen core changed')
    audit.verify_old()
    sources = [SPEC, PLAN, Path(__file__), ROOT/'scripts/price_amount_features.py',
               ROOT/'scripts/price_amount_model.py', ROOT/'scripts/run_retention_development.py',
               ROOT/'scripts/retention_selector.py', ROOT/'scripts/ml_risk_model.py',
               ROOT/'tests/test_price_amount_research.py']
    inputs = sources + [OLD/'common_samples.csv', OLD/'frozen_protocol.json', DATA/'manifest.json',
                        DATA/'daily.csv', DATA/'adj_factor.csv', DATA/'calendar.csv', DATA/'benchmark.csv',
                        SOURCE/'unexplained_adjustments.csv']
    inputs += [ROOT/'data/audit'/n for n in old['metadata_sha256']]
    fingerprints = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    manifest = json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))['files_sha256']
    for n in ('daily.csv', 'adj_factor.csv', 'calendar.csv', 'benchmark.csv'):
        if sha(DATA/n) != manifest[n]:
            raise RuntimeError('Frozen data changed: ' + n)
    for n, h in old['metadata_sha256'].items():
        if sha(ROOT/'data/audit'/n) != h:
            raise RuntimeError('Frozen metadata changed: ' + n)
    persist('frozen_protocol.json', dict(primary='ridge_trend_risk', paths=PATHS,
                costs=[0,10,30], initial_cash=1000000, features=FEATURES, training_dates=52,
                minimum_samples_per_date=200, ridge_alpha=10, solver='svd', fit_dates=FIT_DATES,
                source_sha256=core, inputs=fingerprints, financial_fields_consumed=False,
                versions=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
                              sklearn=sklearn.__version__, scipy=scipy.__version__),
                approval='Human reply 批准 on2026-10-13; automatic continuations are not approval'))
    snap = OUT/'source_before'; snap.mkdir()
    for p in sources: shutil.copy2(p, snap/p.name)
    for p in (ROOT/'quant_research').glob('*.py'): shutil.copy2(p, snap/p.name)
    full = pd.read_csv(DATA/'calendar.csv', dtype={'cal_date':str})
    full_calendar = pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    calendar = full_calendar[(full_calendar >= '2015-11-01') & (full_calendar <= '2020-12-31')]
    columns = ['trade_date','ts_code','industry','D_label','D_valid','D_end','reference_end',
               'momentum20','reversal5','lowvol20','feature_valid']
    base = pd.read_csv(OLD/'common_samples.csv', usecols=columns,
                       parse_dates=['trade_date','D_end','reference_end'], float_precision='round_trip')
    base = base.rename(columns={'feature_valid':'old_feature_valid'})
    if base.duplicated(['trade_date','ts_code']).any() or not base.old_feature_valid.all():
        raise RuntimeError('Invalid original common pool')
    codes = set(base.ts_code)
    persist('preparation_status.json', dict(state='reading_quotes', pid=os.getpid(), codes=len(codes)))
    print('Load frozen quotes and original D labels', flush=True)
    bars = read_subset('daily', codes).merge(read_subset('adj_factor', codes),
                                           on=['ts_code','trade_date'], validate='one_to_one')
    bars = bars.loc[bars.trade_date.isin(calendar)].copy()
    bars, corrections = correct_adjustments(bars)
    issues = pd.read_csv(SOURCE/'unexplained_adjustments.csv', parse_dates=['trade_date'])
    dates = {c: set(g.trade_date) for c,g in base.groupby('ts_code')}
    issue_dates = {c:g.trade_date.tolist() for c,g in issues.groupby('ts_code')}
    parts = []; returns = {}
    for i,(code, group) in enumerate(bars.groupby('ts_code', sort=True)):
        features, r = compute_asset(group, calendar, dates[code], issue_dates.get(code, []))
        features['ts_code'] = code; parts.append(features); returns[code] = r
        if (i+1) % 500 == 0:
            print('Feature assets', i+1, flush=True)
            persist('preparation_status.json', dict(state='features', pid=os.getpid(), completed_assets=i+1))
    features = pd.concat(parts, ignore_index=True)
    merged = base.merge(features, on=['trade_date','ts_code'], validate='one_to_one', how='left')
    if len(merged) != len(base) or merged.feature_valid.isna().any():
        raise RuntimeError('Incomplete feature alignment')
    merged[['trade_date','ts_code','feature_valid','long_quarantined','feature_reason',
            'valid_quote_count_200','current_amount_cny']].to_csv(OUT/'feature_coverage.csv', index=False)
    common = merged.loc[merged.feature_valid].copy()
    common.to_csv(OUT/'common_samples.csv', index=False)
    pd.DataFrame(returns, index=calendar).rename_axis('trade_date').to_csv(OUT/'returns.csv')
    persist('feature_summary.json', dict(original_rows=len(base), common200_rows=len(common),
                reasons=merged.feature_reason.value_counts().to_dict(), adjustment_corrections=corrections))
    audits = []
    (OUT/'training').mkdir()
    for year, day in FIT_DATES.items():
        training, record = training_samples(common, day)
        scales = fit_scales(training)
        training.to_csv(OUT/f'training/{year}.csv', index=False)
        persist(f'training/scales_{year}.json', scales)
        audits.append(dict(year=year, **record))
        persist('training_audit.json', audits)
        print('Prepared training', year, len(training), record['dates'], flush=True)
    for p,h in fingerprints.items():
        if sha(ROOT/p) != h: raise RuntimeError('Input changed during preparation: ' + p)
    audit.verify_old()
    persist('preparation_status.json', dict(state='completed', pid=os.getpid(), models_started=False,
                                            prepared_years=3, common200_rows=len(common)))
    files = {p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*')
             if p.is_file() and p.name != 'preparation.lock'}
    persist('preparation_sha256.json', files)


if __name__ == '__main__': main()
