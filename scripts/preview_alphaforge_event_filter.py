"""Outcome-free four-date coverage preview, never an investable-universe repair."""
from pathlib import Path
import hashlib
import json

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=Path('D:/QuantResearchEvidence/alphaforge_event_crosscheck_20261016_r1')
OUT=Path('D:/QuantResearchEvidence/alphaforge_filter_preview_20261016_r1_attempt2')
R1=ROOT/'output/alphaforge_case_2018_2020_r1'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    paths=[Path(__file__),EVIDENCE/'all_adjacent_open_day_checks.csv',EVIDENCE/'crosscheck.json',
           EVIDENCE/'output_sha256.json',R1/'feature_coverage.csv',R1/'preparation_audit.json',R1/'output_sha256.json']
    before={str(p):sha(p) for p in paths}
    for folder in [EVIDENCE,R1]:
        for name,expected in json.loads((folder/'output_sha256.json').read_text(encoding='utf-8')).items():
            assert sha(folder/name)==expected,str(folder/name)
    checks=pd.read_csv(paths[1],dtype={'ts_code':str,'trade_date':str},
                       usecols=['scope','ts_code','trade_date','previous_quote_present','current_quote_present',
                       'raw_close_pre_close_equal_exact','implemented_dividend_raw_row_count',
                       'implemented_dividend_after_existing_corrections_row_count','verified_rights_match'])
    checks=checks.loc[checks.scope.eq('failed_pool_union')].copy()
    for column in ['previous_quote_present','current_quote_present','verified_rights_match']:
        assert checks[column].isin([True,False]).all()
    checks['trade_date']=pd.to_datetime(checks.trade_date)
    checks['observed_reference_continuous']=checks.previous_quote_present & checks.current_quote_present & checks.raw_close_pre_close_equal_exact.eq(True)
    # Cached action matches make this a conservative static preview only.
    # It does not certify that every record/version was historically available.
    checks['cached_action_match']=(checks.implemented_dividend_raw_row_count.gt(0)
        | checks.implemented_dividend_after_existing_corrections_row_count.gt(0) | checks.verified_rights_match)
    indexed=checks.set_index(['ts_code','trade_date'])
    assert not indexed.index.has_duplicates
    failures=json.loads(paths[5].read_text(encoding='utf-8'))['failures']
    days=pd.DatetimeIndex(sorted(checks.trade_date.unique()))
    formation=pd.read_csv(paths[4],dtype={'ts_code':str},usecols=['trade_date','ts_code','case_valid'],parse_dates=['trade_date'])
    rows=[];summary=[]
    for item in failures:
        t=pd.Timestamp(item['signal_date']);i=days.get_loc(t)
        assert i>=9
        internal=days[i-8:i+1]
        frame=formation.loc[formation.trade_date.eq(t)]
        for row in frame.itertuples(index=False):
            keys=pd.MultiIndex.from_product([[row.ts_code],internal])
            q=indexed.reindex(keys)
            complete=q.observed_reference_continuous.notna().all()
            reference_ok=bool(complete and q.observed_reference_continuous.all())
            no_cached_event=bool(complete and not q.cached_action_match.any())
            rows.append(dict(ts_code=row.ts_code,signal_date=t,r1_retained=bool(row.case_valid),
                observed_reference_continuous_9=reference_ok,
                no_cached_action_in_9=no_cached_event,
                static_preview_retained=reference_ok and no_cached_event))
        selected=pd.DataFrame(rows).loc[lambda f:f.signal_date.eq(t)]
        summary.append(dict(signal_date=t,original_rows=len(frame),r1_retained=int(frame.case_valid.sum()),
            observed_reference_only=int(selected.observed_reference_continuous_9.sum()),
            static_reference_and_cached_action=int(selected.static_preview_retained.sum()),
            minimum_200_static_preview=bool(selected.static_preview_retained.sum()>=200)))
    pd.DataFrame(rows).to_csv(OUT/'formation_preview.csv',index=False)
    pd.DataFrame(summary).to_csv(OUT/'coverage_preview.csv',index=False)
    assert before=={str(p):sha(p) for p in paths}
    result=dict(status='completed',scope='Four-date static coverage feasibility only; not an approved historical universe',
        dates=[{k:(v.strftime('%Y-%m-%d') if isinstance(v,pd.Timestamp) else v) for k,v in r.items()} for r in summary],
        internal_transition_count=9,first_day_prior_transition_excluded_from_test=True,
        labels_or_returns_read=False,factor_values_computed=False,accounts_started=0,
        r1_modified=False,source_sha256=before,
        limitations=['Only the four failed dates were previewed, not all154 dates.',
            'Cached action matches do not certify historical record versions or complete event coverage.',
            'No cached event and equal reference prices do not prove no corporate action.',
            'This does not establish that supplier adjustment changes were rounding.',
            'Changing the frozen exclusion policy requires a separate reviewed r2 design.'])
    (OUT/'preview.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in OUT.iterdir() if p.is_file()},indent=2),encoding='utf-8')
    print(json.dumps(result['dates'],ensure_ascii=False))


if __name__=='__main__':main()
