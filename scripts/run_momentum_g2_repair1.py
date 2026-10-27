"""One authorized cohort: immutable freeze -> prepare/audit -> six accounts.

No broker, network, parameter grid or automatic retry. A stopped stage remains
on disk and cannot be overwritten by rerunning this command.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import sys
import traceback

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import momentum_g2_runtime as repair_runtime
repair_runtime.OUT = Path('D:/QuantResearchEvidence/medium_term_momentum_2018_2020_g2_r1_engineering_fix1')

from momentum_g2_runtime import (OUT, SPEC, SPEC_SHA, PLAN, DATA, META, MAPPING,
    START, END, BASELINE, utcnow, sha, read_json, persist, clean, status, exclusive,
    check_disk, check_g2_budget, check_g3_budget, root_active_seconds, source_closure, verify_frozen, write_table,
    read_table, make_manifest, verify_manifest)
from momentum_g2_events import EventBook, build_event_book, bound_source_inputs
from momentum_g2_prepare import prepare, PreparationError
from momentum_g2_selection import build_targets
from momentum_g2_account import simulate_account, AccountFailure
from momentum_g2_audit_repair1 import audit_preparation, audit_account
from quant_research.factors import weekly_schedule
from quant_research.rights import verified_rights
from quant_research.corporate_corrections import correct_limit_code_aliases

ORDER = [(p, b) for p in ('momentum', 'control') for b in (0, 10, 30)]
PREP = OUT / 'preparation'
DATE_COLUMNS = {'trade_date', 'signal_date', 'formation_date', 'execution_date',
    'window_start', 'signal_end', 'bridge_left', 'bridge_right', 'date',
    'first_execution_date', 'cash_pay', 'stock_pay', 'record_date', 'ex_date'}


def _dated(frame):
    for col in DATE_COLUMNS.intersection(frame.columns):
        frame[col] = pd.to_datetime(frame[col], errors='raise')
    return frame


def _read_market(name, columns):
    """Filter lexical dates before numeric conversion; never load future prices."""
    parts = []
    for chunk in pd.read_csv(DATA / (name + '.csv'), usecols=columns, dtype=str,
                             chunksize=150_000):
        keep = (chunk.trade_date.between(START, END) &
                chunk.ts_code.str.match(r'^(?:60\d{4}\.SH|00\d{4}\.SZ)$', na=False))
        parts.append(chunk.loc[keep].copy())
    result = pd.concat(parts, ignore_index=True)
    result['trade_date'] = pd.to_datetime(result.trade_date, format='%Y%m%d', errors='raise')
    return result


def load_context(*, prices=True):
    calendar_rows = pd.read_csv(DATA / 'calendar.csv', dtype=str)
    calendar_rows = calendar_rows.loc[calendar_rows.exchange.eq('SSE') &
        calendar_rows.is_open.eq('1') & calendar_rows.cal_date.between(START, END)]
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar_rows.cal_date, format='%Y%m%d')).sort_values()
    if calendar.has_duplicates or calendar.empty:
        raise ValueError('Duplicate/empty exchange calendar')
    schedule = weekly_schedule(calendar)
    schedule = schedule.loc[schedule.execution_date.between('2018-01-01', '2020-12-31')].reset_index(drop=True)
    mapping = read_json(MAPPING)
    dividends = pd.read_csv(DATA / 'dividend.csv', dtype=str)
    # No later implementation row is allowed to bring future final amounts into
    # this event book. Proposal ann_date is not an implementation fallback.
    ex = dividends.ex_date.fillna('')
    imp = dividends.imp_ann_date.fillna('')
    dividends = dividends.loc[((ex.between(START, END)) | (imp.between(START, END))) &
        dividends.ts_code.str.match(r'^(?:60\d{4}\.SH|00\d{4}\.SZ)$', na=False)].copy()
    rights = tuple(r for r in verified_rights() if r.ex <= pd.Timestamp('2020-12-31'))
    book = build_event_book(dividends, calendar, mapping, rights)
    universe = pd.read_csv(META / 'universe.csv', dtype=str)
    names = pd.read_csv(META / 'name_history.csv', dtype=str)
    industries = pd.read_csv(META / 'industry_history.csv', dtype=str)
    context = dict(full_calendar=calendar, calendar=calendar, schedule=schedule,
        universe=universe, names=names, name_history=names, industries=industries,
        dividends=dividends, event_inventory=book.to_inventory(), event_book=book,
        evidence=mapping, rights_catalog=[asdict(r) for r in rights], verify_source_files=True)
    if not prices:
        return context
    daily = _read_market('daily', ['ts_code', 'trade_date', 'open', 'high', 'low',
                                  'close', 'pre_close', 'vol', 'amount'])
    daily['close_text'], daily['pre_close_text'] = daily.close, daily.pre_close
    for col in ('open', 'high', 'low', 'close', 'pre_close', 'vol', 'amount'):
        daily[col] = pd.to_numeric(daily[col], errors='coerce')
    limits = _read_market('stk_limit', ['ts_code', 'trade_date', 'up_limit', 'down_limit'])
    limits, limit_alias_audit = correct_limit_code_aliases(limits)
    for col in ('up_limit', 'down_limit'):
        limits[col] = pd.to_numeric(limits[col], errors='coerce')
    if limits.duplicated(['ts_code', 'trade_date']).any():
        raise ValueError('Duplicate price-limit keys')
    daily = daily.merge(limits, on=['ts_code', 'trade_date'], how='left', validate='one_to_one')
    suspensions = _read_market('suspend_d', ['ts_code', 'trade_date', 'suspend_timing', 'suspend_type'])
    context.update(bars=daily, suspensions=suspensions, limit_alias_audit=limit_alias_audit)
    return context


def freeze():
    check_disk()
    check_g2_budget()
    if (OUT / 'frozen_protocol.json').exists():
        raise RuntimeError('Already frozen; inspect stage rather than duplicate')
    receipt = read_json(OUT / 'development_notes/integrated_tests.json')
    ready = read_json(OUT / 'development_notes/implementation_ready.json')
    if receipt['exit_code'] != 0 or not ready['all_source_owners_stopped']:
        raise RuntimeError('Source must be validated and stopped before freeze')
    for owner, seconds in ready['child_charges_seconds'].items():
        if seconds < 0 or seconds > read_json(OUT / 'authorization_and_budget.json')['G2_caps_seconds'][owner]:
            raise RuntimeError('Original child G2 budget exceeded: ' + owner)
    if sha(SPEC) != SPEC_SHA:
        raise RuntimeError('Approved design changed')
    seeds = list((ROOT / 'scripts').glob('momentum_g2_*.py'))
    seeds += [Path(__file__), ROOT / 'scripts/report_momentum_g2.py']
    seeds += list((ROOT / 'tests').glob('test_momentum_g2_*.py'))
    sources = source_closure(seeds)
    test_ended = datetime.fromisoformat(receipt['completed_utc'])
    if any(p.stat().st_mtime > test_ended.timestamp() for p in sources):
        raise RuntimeError('Source edited after validation; validate current source before freeze')
    sources = [*sources, SPEC, PLAN]
    inputs = [DATA / (n + '.csv') for n in ('daily', 'calendar', 'dividend', 'stk_limit', 'suspend_d')]
    inputs += [META / n for n in ('universe.csv', 'name_history.csv', 'industry_history.csv')]
    inputs += [DATA / 'manifest.json', MAPPING, MAPPING.parent / 'output_sha256.json']
    mapping = read_json(MAPPING)
    if read_json(MAPPING.parent / 'output_sha256.json').get(MAPPING.name) != sha(MAPPING):
        raise RuntimeError('Existing mapping does not bind its sealed parent manifest')
    binding = bound_source_inputs(mapping, MAPPING)
    for filename, expected in binding.items():
        if sha(filename) != expected:
            raise RuntimeError('Consumed source fact changed: ' + filename)
        inputs.append(Path(filename))
    hashes = {}
    for p in sorted(set(p.resolve() for p in inputs)):
        check_g2_budget()
        info = p.stat()
        hashes[str(p)] = dict(sha256=sha(p), bytes=info.st_size, mtime_ns=info.st_mtime_ns)
    source_hashes = {str(p.resolve()): sha(p) for p in sources}
    snapshot = OUT / 'source_snapshot'
    for p in sources:
        target = snapshot / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
    protocol = dict(approved_spec_sha256=SPEC_SHA, frozen_utc=utcnow().isoformat(),
        source_commit=__import__('subprocess').check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        sources=source_hashes, inputs=hashes, environment=dict(python=sys.version,
            pandas=pd.__version__, platform=platform.platform()),
        fixed_order=ORDER, minimum_pool=200, source_ready_sha256=sha(OUT / 'development_notes/implementation_ready.json'),
        tests_receipt_sha256=sha(OUT / 'development_notes/integrated_tests.json'),
        old_data_or_source_modified=False, broker=False, repair_count=0)
    persist(OUT / 'frozen_protocol.json', protocol)
    status('freeze', 'passed', sources=len(source_hashes), inputs=len(hashes))


def _write_preparation(data, summary):
    PREP.mkdir(exist_ok=False)
    for key, value in data.items():
        if key == 'event_inventory':
            persist(PREP / 'event_inventory.json', value.to_dict('records') if isinstance(value, pd.DataFrame) else value)
        elif isinstance(value, pd.DataFrame):
            write_table(PREP / (key + '.csv'), value)
    persist(PREP / 'summary.json', summary)
    make_manifest(PREP, OUT / 'preparation_manifest.json')


def prepare_stage():
    if PREP.exists() or (OUT / 'preparation_manifest.json').exists() or (OUT / 'runtime/preparation_attempt.json').exists():
        raise RuntimeError('Preparation already attempted; no duplicate run')
    check_g2_budget()
    frozen = verify_frozen()
    persist(OUT / 'runtime/preparation_attempt.json', dict(started_utc=utcnow().isoformat(), no_automatic_retry=True))
    context, data = None, {}
    def progress(row):
        check_g2_budget()
        status('prepare', 'running', progress=row)
    try:
        context = load_context()
        status('prepare', 'running', periods=len(context['schedule']))
        data = prepare(context['bars'], context['full_calendar'], context['schedule'],
            context['universe'], context['names'], context['industries'], context['event_book'], progress)
        selected = build_targets(data['feature_rows'], context['schedule'])
        data.update(ranked_features=selected['ranked_features'], selection_events=selected['selection_events'],
                    schedule=context['schedule'])
        data.update({f'targets_{p}': t for p, t in selected['targets'].items()})
        summary = dict(status='prepared', preparation_passed=True, passed=True,
            periods=len(context['schedule']), formation_rows=len(data['feature_rows']),
            minimum_pool=int(data['coverage'].common_pool.min()), accounts_started=0)
    except PreparationError as exc:
        data = dict(exc.partial, schedule=context['schedule'])
        data.setdefault('event_inventory', context['event_book'].to_inventory())
        data['failures'] = pd.DataFrame([dict(reason=exc.reason, detail=json.dumps(clean(exc.detail), default=str))])
        summary = dict(status='preparation_stopped', preparation_passed=False, passed=False,
                       reason=exc.reason, detail=exc.detail, accounts_started=0)
        persist(OUT / 'runtime/preparation_first_failure.json', dict(summary, traceback=traceback.format_exc()))
    except Exception as exc:
        summary = dict(status='preparation_stopped', preparation_passed=False, passed=False,
            reason='preparation_engineering_or_budget_exception', error_type=type(exc).__name__,
            detail=str(exc), accounts_started=0)
        persist(OUT / 'runtime/preparation_first_failure.json', dict(summary, traceback=traceback.format_exc()))
    data['event_inventory'] = context['event_book'].to_inventory() if context else []
    _write_preparation(data, summary)
    verify_frozen()
    status('prepare', summary['status'], result=summary)


def _read_preparation():
    verify_manifest(OUT / 'preparation_manifest.json')
    data = {p.stem: _dated(read_table(p)) for p in PREP.glob('*.csv')}
    data['event_inventory'] = read_json(PREP / 'event_inventory.json')
    data['summary'] = read_json(PREP / 'summary.json')
    return data


def verify_prepare_stage():
    if (OUT / 'preparation_audit.json').exists() or (OUT / 'runtime/preparation_audit_attempt.json').exists():
        raise RuntimeError('Preparation audit already performed')
    check_g2_budget()
    frozen = verify_frozen()
    persist(OUT / 'runtime/preparation_audit_attempt.json', dict(started_utc=utcnow().isoformat(), no_automatic_retry=True))
    data = _read_preparation()
    context = load_context()
    context['input_hashes'] = {p: row['sha256'] for p, row in frozen['inputs'].items()}
    context['event_inventory'] = data['event_inventory']
    targets = {p: data.get('targets_' + p, pd.DataFrame()) for p in ('momentum', 'control')}
    result = audit_preparation(context, data, targets if data['summary']['preparation_passed'] else None)
    persist(OUT / 'preparation_audit.json', result)
    persist(OUT / 'preparation_audit_manifest.json', {'preparation_audit.json': sha(OUT / 'preparation_audit.json')})
    check_g2_budget()
    verify_frozen()
    status('verify_prepare', result['status'], audit_consistent=result.get('audit_consistent'),
           accounts_allowed=result.get('accounts_allowed', False))


def accounts_stage():
    verify_frozen()
    data = _read_preparation()
    verify_manifest(OUT / 'preparation_audit_manifest.json')
    audit = read_json(OUT / 'preparation_audit.json')
    if not data['summary']['preparation_passed'] or not audit.get('accounts_allowed', False):
        raise RuntimeError('Formal preparation and independent audit must pass before accounts')
    if (OUT / 'accounts').exists() or (OUT / 'accounts_status.json').exists():
        raise RuntimeError('Account cohort already attempted; do not duplicate')
    persist(OUT / 'runtime/G2_phase_end.json', dict(ended_utc=utcnow().isoformat(), root_elapsed=check_g2_budget()))
    persist(OUT / 'runtime/G3_phase_start.json', dict(started_utc=utcnow().isoformat(), cap_seconds=28800))
    context = load_context()
    states = []
    for path, bps in ORDER:
        key = f'{path}_{bps}bp'
        if states and states[-1]['status'] != 'complete':
            states.append(dict(account=key, status='not_started'))
            continue
        verify_frozen(full_inputs=False)
        status('accounts', 'running', account=key)
        result = {}
        try:
            check_g3_budget()
            book = EventBook.from_inventory(context['full_calendar'], data['event_inventory'])
            def account_progress(date, count):
                check_g3_budget()
                status('accounts', 'running', account=key,
                       progress=dict(date=date, completed_sessions=count))
            result = simulate_account(context['bars'], context['full_calendar'], context['schedule'],
                data['targets_' + path], book, context['universe'],
                context['suspensions'], bps, account_progress)
            state = dict(account=key, status='complete')
        except AccountFailure as exc:
            result = exc.partial_result
            state = dict(account=key, status='stopped', reason=str(exc), date=exc.date)
            persist(OUT / 'runtime' / (key + '_first_failure.json'), dict(state, traceback=traceback.format_exc()))
        except Exception as exc:
            state = dict(account=key, status='stopped', reason=str(exc), error_type=type(exc).__name__)
            persist(OUT / 'runtime' / (key + '_first_failure.json'), dict(state, traceback=traceback.format_exc()))
        folder = OUT / 'accounts' / key
        folder.mkdir(parents=True, exist_ok=False)
        for name, value in result.items():
            if isinstance(value, pd.DataFrame):
                write_table(folder / (name + '.csv'), value)
            else:
                persist(folder / (name + '.json'), value)
        persist(folder / 'terminal.json', state)
        states.append(state)
        persist(OUT / 'runtime/accounts_latest.json', states, replace=True)
    persist(OUT / 'accounts_status.json', states)
    members = {p.relative_to(OUT).as_posix(): sha(p) for p in sorted((OUT / 'accounts').rglob('*')) if p.is_file()}
    members['accounts_status.json'] = sha(OUT / 'accounts_status.json')
    persist(OUT / 'accounts_manifest.json', members)
    verify_frozen()
    status('accounts', 'complete' if all(x['status'] == 'complete' for x in states) else 'stopped', states=states)


def verify_accounts_stage():
    check_g3_budget()
    verify_frozen()
    verify_manifest(OUT / 'accounts_manifest.json')
    if (OUT / 'accounts_audit.json').exists() or (OUT / 'runtime/accounts_audit_attempt.json').exists():
        raise RuntimeError('Account audit already performed')
    persist(OUT / 'runtime/accounts_audit_attempt.json', dict(started_utc=utcnow().isoformat(), no_automatic_retry=True))
    data = _read_preparation()
    context = load_context()
    context['event_inventory'] = data['event_inventory']
    states = read_json(OUT / 'accounts_status.json')
    audits = {}
    for state in states:
        if state['status'] == 'not_started':
            continue
        check_g3_budget()
        key = state['account']
        path, rest = key.rsplit('_', 1)
        bps = int(rest.removesuffix('bp'))
        folder = OUT / 'accounts' / key
        result = {p.stem: _dated(read_table(p)) for p in folder.glob('*.csv')}
        result.update({p.stem: read_json(p) for p in folder.glob('*.json')})
        try:
            audit = audit_account(context, result, data['targets_' + path], bps)
            check_g3_budget()
        except Exception as exc:
            audit = dict(status='audit_exception', passed=False, reason=str(exc),
                         error_type=type(exc).__name__, traceback=traceback.format_exc())
        audits[key] = audit
        persist(OUT / 'runtime/accounts_audit_latest.json', audits, replace=True)
        status('verify_accounts', 'running', account=key, audit_status=audit.get('status'))
        if audit['status'] in ('audit_exception', 'audit_failed'):
            break
    persist(OUT / 'accounts_audit.json', audits)
    persist(OUT / 'accounts_audit_manifest.json', {'accounts_audit.json': sha(OUT / 'accounts_audit.json')})
    verify_frozen()
    status('verify_accounts', 'complete', audited=len(audits))


def seal_case():
    """Close this case only after the report and runner lock are finished."""
    if (OUT / 'runtime/runner.lock').exists() or (OUT / 'SEAL.json').exists():
        raise RuntimeError('Active or already sealed case; no duplicate closure')
    verify_frozen()
    summary = read_json(OUT / 'summary.json')
    ready = read_json(OUT / 'development_notes/implementation_ready.json')
    g2 = read_json(OUT / 'runtime/G2_phase_end.json')
    children = ready['child_charges_seconds']
    phase = OUT / 'runtime/G3_phase_start.json'
    root_seconds = g2['root_elapsed'] if phase.exists() else root_active_seconds()
    charged_g2 = root_seconds + sum(children.values()) + 4017
    charged_g3 = (utcnow() - datetime.fromisoformat(read_json(phase)['started_utc'])).total_seconds() if phase.exists() else 0.
    persist(OUT / 'budget_final.json', dict(G1_seconds=5142.908161, G2_seconds=charged_g2,
        G2_original_cap_seconds=43200, G2_design_seconds=4017, root_G2_seconds=root_seconds,
        child_G2_seconds=children, G3_seconds=charged_g3, G3_original_cap_seconds=28800,
        family_seconds=5142.908161 + charged_g2 + charged_g3, family_cap_seconds=86400,
        human_interruption_evidence='runtime/human_interruptions.json',
        policy='Task wall segments summed; parallel overlap/waits included; no reset.'))
    members = make_manifest(OUT, OUT / 'output_sha256.json')
    verify_manifest(OUT / 'output_sha256.json')
    persist(OUT / 'SEAL.json', dict(sealed_utc=utcnow().isoformat(), status=summary['status'],
        member_count=len(members), output_manifest_sha256=sha(OUT / 'output_sha256.json'),
        parent_manifest_excludes=['output_sha256.json', 'SEAL.json'],
        old_data_modified=False, broker=False))
    print(json.dumps(dict(status=summary['status'], sealed_members=len(members)), flush=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', 'prepare', 'verify-prepare', 'accounts', 'verify-accounts', 'report', 'seal'])
    args = parser.parse_args()
    check_disk()
    if args.stage == 'seal':
        seal_case()
        return
    with exclusive(args.stage):
        try:
            if args.stage == 'report':
                from report_momentum_g2 import report
                report()
                if not (OUT / 'runtime/G2_phase_end.json').exists():
                    persist(OUT / 'runtime/G2_phase_end.json', dict(ended_utc=utcnow().isoformat(),
                        root_elapsed=check_g2_budget(), accounts_started=False))
            else:
                {'freeze': freeze, 'prepare': prepare_stage, 'verify-prepare': verify_prepare_stage,
                 'accounts': accounts_stage, 'verify-accounts': verify_accounts_stage}[args.stage]()
        except Exception as exc:
            failure = OUT / 'runtime' / (args.stage + '_exception_' + utcnow().strftime('%Y%m%dT%H%M%S%f') + '.json')
            persist(failure, dict(stage=args.stage, error_type=type(exc).__name__, reason=str(exc), traceback=traceback.format_exc()))
            stop = OUT / 'runtime/research_stop.json'
            if not stop.exists():
                persist(stop, dict(stage=args.stage, reason=str(exc), error_type=type(exc).__name__,
                    observed_utc=utcnow().isoformat(), exception_evidence=failure.relative_to(OUT).as_posix(),
                    accounts_allowed=False, no_automatic_retry=True))
            status(args.stage, 'exception', reason=str(exc))
            raise


if __name__ == '__main__':
    main()
