"""Approved three annual paired models and twelve fixed common200 accounts."""
import json
import os
from pathlib import Path
import shutil
import traceback
import lightgbm as lgb
import numpy as np
import pandas as pd
import run_ml_risk as original
from prepare_price_amount_research import ROOT, DATA, SOURCE, OLD, OUT, PATHS, FIT_DATES, persist, sha, read_subset
from price_amount_features import FEATURES
from price_amount_model import fit_models, transform
from ml_risk_model import PARAMETERS, risk_scale
from retention_selector import select_retention
from quant_research.factors import rank_scores, FACTORS, weekly_schedule
import announcement_financial_audit as audit


def main():
    prepared = json.loads((OUT/'preparation_status.json').read_text(encoding='utf-8'))
    if prepared['state'] != 'completed':
        raise RuntimeError('Preparation not completed')
    if (OUT/'experiment_protocol.json').exists():
        raise RuntimeError('Existing experiment attempt; inspect before restarting')
    if shutil.disk_usage(OUT.resolve()).free < 6*1024**3:
        raise RuntimeError('6GiB free-space floor reached')
    lock = OUT/'experiment.lock'
    with lock.open('x', encoding='utf-8') as stream: json.dump(dict(pid=os.getpid()), stream)
    try:
        return run()
    except Exception:
        (OUT/'experiment_failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        persist('experiment_stage.json', dict(state='failed', failure='experiment_failure.txt', pid=os.getpid()))
        raise
    finally:
        lock.unlink()


def run():
    if lgb.__version__ != '4.6.0': raise RuntimeError('LightGBM version changed')
    prep_hashes = json.loads((OUT/'preparation_sha256.json').read_text(encoding='utf-8'))
    for n,h in prep_hashes.items():
        if sha(OUT/n) != h: raise RuntimeError('Prepared artifact changed: ' + n)
    protocol = json.loads((OUT/'frozen_protocol.json').read_text(encoding='utf-8'))
    for n,h in protocol['inputs'].items():
        if sha(ROOT/n) != h: raise RuntimeError('Frozen input changed: ' + n)
    core = {p.name:sha(p) for p in (ROOT/'quant_research').glob('*.py')}
    if core != protocol['source_sha256']: raise RuntimeError('Core changed')
    audit.verify_old()
    source = Path(original.__file__).read_text(encoding='utf-8')
    if sha(Path(original.__file__)) != json.loads((OLD/'frozen_protocol.json').read_text(encoding='utf-8'))['inputs']['scripts\\run_ml_risk.py']:
        raise RuntimeError('Original execution adapter changed')
    block = source[source.index('    all_codes=set().union'):source.index('    return int(any(s[')]
    block = '\n'.join(line[4:] if line.startswith('    ') else line for line in block.splitlines())
    (OUT/'simulation_adapter_block.py.txt').write_text(block, encoding='utf-8')
    shutil.copy2(Path(__file__), OUT/'source_before'/Path(__file__).name)
    persist('experiment_protocol.json', dict(runner_sha256=sha(Path(__file__)),
                adapter_sha256=sha(OUT/'simulation_adapter_block.py.txt'), prepared_manifest_sha256=sha(OUT/'preparation_sha256.json'),
                features=FEATURES, gbm_parameters=PARAMETERS, ridge=dict(alpha=10,solver='svd',fit_intercept=True),
                paths=PATHS, primary='ridge_trend_risk', costs=[0,10,30], lightgbm=lgb.__version__))
    models = {}; model_dir = OUT/'models'; model_dir.mkdir()
    for year in FIT_DATES:
        train = pd.read_csv(OUT/f'training/{year}.csv', float_precision='round_trip')
        scales = json.loads((OUT/f'training/scales_{year}.json').read_text(encoding='utf-8'))
        print('Fit paired Ridge/GBM', year, len(train), flush=True)
        persist('experiment_stage.json', dict(state='fitting', year=year, pid=os.getpid()))
        ridge, gbm = fit_models(train, scales)
        models[year] = (ridge, gbm, scales)
        persist(f'models/ridge_{year}.json', dict(coefficients=ridge.coef_.tolist(), intercept=float(ridge.intercept_),
                    features=FEATURES, alpha=10, solver='svd', training_sha256=sha(OUT/f'training/{year}.csv')))
        (model_dir/f'gbm_{year}.txt').write_text(gbm.booster_.model_to_string(), encoding='utf-8')
        # Saved coefficient predictions and Unicode-path GBM reload must agree before any account.
        matrix = transform(train, scales)
        np.testing.assert_allclose(matrix@ridge.coef_+ridge.intercept_, ridge.predict(matrix), rtol=0, atol=1e-12)
        reloaded = lgb.Booster(model_str=(model_dir/f'gbm_{year}.txt').read_text(encoding='utf-8'))
        np.testing.assert_allclose(reloaded.predict(matrix, num_threads=4), gbm.predict(matrix), rtol=0, atol=1e-12)
    samples = pd.read_csv(OUT/'common_samples.csv', parse_dates=['trade_date','D_end','reference_end'], float_precision='round_trip')
    returns = pd.read_csv(OUT/'returns.csv', parse_dates=['trade_date'], float_precision='round_trip').set_index('trade_date')
    calendar = pd.DatetimeIndex(returns.index)
    full = pd.read_csv(DATA/'calendar.csv', dtype={'cal_date':str})
    full_calendar = pd.DatetimeIndex(pd.to_datetime(full.loc[full.is_open.eq(1),'cal_date'])).sort_values()
    schedule = weekly_schedule(full_calendar[full_calendar >= '2015-11-01'])
    schedule = schedule.loc[schedule.execution_date.between('2018-01-01','2020-12-31')].reset_index(drop=True)
    groups = {d:g for d,g in samples.groupby('trade_date')}
    plans = {p:[] for p in PATHS}; previous = {p:set() for p in PATHS}
    predictions = []; ics = []; risks = []; events_all = []; covariance_hashes = {}
    for row in schedule.itertuples(index=False):
        d = row.signal_date; frame = groups[d].copy()
        ridge, gbm, scales = models[row.execution_date.year]
        matrix = transform(frame, scales)
        rp, gp = ridge.predict(matrix), gbm.predict(matrix)
        if not np.isfinite(rp).all() or not np.isfinite(gp).all(): raise RuntimeError('Nonfinite prediction')
        predictions.append(pd.DataFrame(dict(trade_date=d, execution_date=row.execution_date,
                                             ts_code=frame.ts_code.to_numpy(), ridge_prediction=rp, gbm_prediction=gp)))
        valid = frame.D_valid.to_numpy()
        for model, pred in [('ridge',rp),('gbm',gp)]:
            rank_ic = pd.Series(pred[valid]).corr(frame.loc[valid,'D_label'].reset_index(drop=True), method='spearman') if valid.sum()>1 else np.nan
            ics.append(dict(model=model, signal_date=d, execution_date=row.execution_date,
                            year=row.execution_date.year, eligible=len(frame), valid_labels=int(valid.sum()), rank_ic=rank_ic))
        scores = {'three_retention_common200': rank_scores(frame, FACTORS)}
        for path, pred in [('ridge_trend_retention',rp),('gbm_trend_risk',gp)]:
            score = frame[['trade_date','ts_code','industry']].copy()
            score['score'] = pd.Series(pred, index=frame.index).rank(method='average',pct=True)
            scores[path] = score
        selected = {}
        for path, score in scores.items():
            target, events = select_retention(score, previous[path])
            if target.empty: raise RuntimeError('No target: ' + path + '/' + str(d))
            selected[path] = target
            events['path'] = path; events['signal_date'] = d; events_all.append(events)
            previous[path] = set(target.ts_code)
        selected['ridge_trend_risk'] = selected['ridge_trend_retention'].copy()
        for path in ('ridge_trend_risk','gbm_trend_risk'):
            target = selected[path]; position = calendar.get_loc(d)
            scale, sigma, cov = risk_scale(returns.loc[calendar[position-59:position+1],target.ts_code],target.target_weight)
            file = OUT/f'covariance_{path}_{d:%Y%m%d}.npy'; np.save(file,cov); covariance_hashes[file.name] = sha(file)
            target['target_weight'] *= scale
            risks.append(dict(path=path,signal_date=d,scale=scale,forecast_volatility=sigma,
                              target_cash=1-target.target_weight.sum(),covariance_file=file.name))
        if set(selected['ridge_trend_risk'].ts_code) != set(selected['ridge_trend_retention'].ts_code):
            raise RuntimeError('Ridge codes differ across risk layer')
        for path, target in selected.items():
            t = target.copy(); t['signal_date'] = d; t['execution_date'] = row.execution_date; plans[path].append(t)
    targets = {p:pd.concat(rows,ignore_index=True) for p,rows in plans.items()}
    for p,t in targets.items(): t.to_csv(OUT/f'targets_{p}.csv',index=False)
    pd.concat(predictions,ignore_index=True).to_csv(OUT/'predictions.csv',index=False)
    pd.concat(events_all,ignore_index=True).to_csv(OUT/'selection_events.csv',index=False)
    pd.DataFrame(ics).to_csv(OUT/'rank_ic.csv',index=False)
    pd.DataFrame(risks).to_csv(OUT/'risk_budget.csv',index=False)
    persist('covariance_sha256.json',covariance_hashes)
    persist('experiment_stage.json',dict(state='accounts',pid=os.getpid()))
    codes = set().union(*(set(t.ts_code) for t in targets.values()))
    bars = read_subset('daily',codes).merge(read_subset('adj_factor',codes),on=['trade_date','ts_code'],validate='one_to_one')
    bars = bars.loc[bars.trade_date.isin(calendar)].copy()
    bars, adjustment_corrections = original.correct_adjustments(bars)
    metadata = pd.read_csv(ROOT/'data/audit/universe.csv',dtype=str)
    sectors = pd.read_csv(ROOT/'data/audit/industry_history.csv',dtype=str)
    # Reuse the byte-fingerprinted historical simulation adapter and original core unchanged.
    namespace = dict(vars(original)); namespace.update(locals()); namespace.update(OUT=OUT,PATHS=PATHS,persist=persist)
    exec(compile(block,str(Path(original.__file__))+'#frozen_account_adapter','exec'),namespace)
    failed = any(s['status'] != 'completed' for s in namespace['statuses'])
    persist('experiment_stage.json',dict(state='failed' if failed else 'completed',pid=os.getpid(),
                                         accounts=len(namespace['statuses']),independent_verification_pending=True))
    audit.verify_old()
    return int(failed)


if __name__ == '__main__': raise SystemExit(main())
