"""Read-only acceptance snapshot for frozen strategy and financial audit deliverables."""
from pathlib import Path
import json
import pandas as pd
import announcement_financial_audit as audit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/strategy_delivery_gates_20261012_r1'


def main():
    if OUT.exists():raise RuntimeError('Snapshot exists; do not overwrite')
    OUT.mkdir();inputs={}
    def read(p):
        inputs[str(p.relative_to(ROOT))]=audit.sha(p)
        return json.loads(p.read_text(encoding='utf-8'))
    base=ROOT/'output/announcement_financial_audit_20261007'
    probe=read(base/'probe_20261007T030541Z.json')
    permissions=[dict(api=r['api'],status=r['status'],rows=r['rows']) for r in probe]
    assert {r['api'] for r in permissions}=={'forecast','fina_indicator','fina_audit'}
    assert all(r['status']=='success' for r in permissions)
    counts=[]
    for api in ['forecast','fina_indicator','fina_audit']:
        p=base/f'{api}_records.csv';inputs[str(p.relative_to(ROOT))]=audit.sha(p)
        frame=pd.read_csv(p,dtype=str,keep_default_na=False)
        dates=pd.to_datetime(frame.ann_date,format='%Y%m%d',errors='coerce')
        window=dates.between(pd.Timestamp('2013-01-01'),pd.Timestamp('2020-12-31'))
        counts.append(dict(api=api,raw_rows=len(frame),in_announcement_window_rows=int(window.sum()),
            invalid_announcement_date_rows=int(dates.isna().sum()),raw_stock_codes=frame.ts_code.nunique()))
    download=read(base/'download_status.json')
    analysis=read(base/'analysis_status.json')
    assert download['state']=='completed' and download['completed_units']==8736
    assert sum(r['raw_rows'] for r in counts)==analysis['raw_rows']
    assert sum(r['in_announcement_window_rows'] for r in counts)==analysis['ann_window_rows']
    latest=read(ROOT/'output/latest_financial_report_coverage_20261012_r1/summary.json')
    content=read(ROOT/'output/unanchored_conflict_pages_20261012_r1/summary.json')
    comparisons=ROOT/'output/label_horizon_coverage_2018_2020_r1/comparison.csv'
    inputs[str(comparisons.relative_to(ROOT))]=audit.sha(comparisons)
    frame=pd.read_csv(comparisons).set_index('strategy')
    metrics={k:dict(total_return=float(frame.loc[k,'total_return']),max_drawdown=float(frame.loc[k,'max_drawdown']))
        for k in ['D_risk_0bp','D_risk_10bp','D_risk_30bp','D_retention_10bp','three_retention_10bp','A_risk_10bp']}
    profit=metrics['D_risk_10bp']['total_return']>0 and metrics['D_risk_30bp']['total_return']>0
    relative=metrics['D_risk_10bp']['total_return']>max(metrics['three_retention_10bp']['total_return'],metrics['A_risk_10bp']['total_return'])
    risk=metrics['D_risk_10bp']['max_drawdown']<=.25 and metrics['D_risk_10bp']['max_drawdown']<=metrics['D_retention_10bp']['max_drawdown']
    assert not profit and not relative and risk
    requirements=[
        dict(requirement='Three financial API permissions',state='verified',scope='Successful actual probes, including successful empty forecast response',evidence='probe_20261007T030541Z.json'),
        dict(requirement='Fixed 2912-code API acquisition',state='verified',scope='8736 acquisition units complete; not original-publication coverage',evidence='download_status.json and raw record counts'),
        dict(requirement='Financial announcement-window inventory',state='verified',scope='Window membership recomputed over all three raw record files',evidence='api_counts.json'),
        dict(requirement='Latest report candidate coverage at signals',state='verified_diagnostic_only',scope='492205 rows / 43799 report-date keys; no value selection',evidence='latest_financial_report_coverage_20261012_r1'),
        dict(requirement='Latest profit conflict content references',state='verified_content_only',scope='61 required conflicts with PDF observations; not all 608 three-interface conflict groups',evidence='unanchored_conflict_pages_20261012_r1'),
        dict(requirement='All fixed originals, all-interface conflicts and risk-case release identities',state='incomplete',scope='Narrow fields/PDFs do not establish complete required records and version sequences',evidence='fixed-sample-review-report.md / financial audit spec'),
        dict(requirement='Historical public availability and revisions',state='not_passed',scope='Historical approvals remain zero; full version identity and cancellation effects unknown',evidence='latest and content summary historical_approvals'),
        dict(requirement='Frozen D cost and return evaluation',state='failed',scope='10bp and 30bp net returns negative; both relative-return conditions fail',evidence=str(comparisons.relative_to(ROOT))),
        dict(requirement='Frozen D drawdown condition',state='verified',scope='10bp drawdown meets its own 25% condition; cannot compensate return failure',evidence=str(comparisons.relative_to(ROOT))),
        dict(requirement='Independent unseen evaluation',state='incomplete',scope='2016-2025 already inspected; exploratory chronological evaluation is not sealed OOS',evidence='open-source ML risk design'),
        dict(requirement='Frozen forward simulation and operations delivery',state='incomplete',scope='No approved new viable candidate or completed independent forward-observation acceptance',evidence='strategy-completion-roadmap.md'),
        dict(requirement='Strategy final delivery',state='incomplete',scope='Current non-enablement decision supported; full requested strategy/operating package not complete',evidence='strategy-completion-roadmap.md'),
    ]
    audit.write_json(OUT/'api_counts.json',counts);audit.write_json(OUT/'permissions.json',permissions)
    audit.write_json(OUT/'frozen_candidate_metrics.json',metrics)
    audit.write_json(OUT/'requirements.json',requirements)
    summary=dict(financial_raw_rows=analysis['raw_rows'],financial_window_rows=analysis['ann_window_rows'],
        latest_required_report_keys=43799,keys_with_current_pdf_content_claim=content['required_keys_with_pdf_claim'],
        financial_historical_approvals=0,financial_history_gate_passed=False,
        candidate_D_positive_net_return_gate=profit,candidate_D_relative_return_gate=relative,candidate_D_drawdown_gate=risk,
        current_strategy_enablement='do_not_enable',overall_goal_complete=False,new_models=0,new_backtests=0)
    assert latest['historical_approvals']==content['historical_approvals']==0
    for p,h in inputs.items():assert audit.sha(ROOT/p)==h,p
    audit.write_json(OUT/'summary.json',summary);audit.write_json(OUT/'input_sha256.json',inputs)
    audit.write_json(OUT/'verification.json',dict(inputs_unchanged=True,old_experiments=audit.verify_old(),source_sha256=audit.sha(Path(__file__))))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
