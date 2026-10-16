"""Finalize bounded source evidence; no market requests or research reruns."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,shutil,subprocess,sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from run_alphaforge_r2 import verify_inputs,sha

OUT=Path('D:/QuantResearchEvidence/alphaforge_000998_crosscheck_20261016_r1')
R2=ROOT/'output/alphaforge_case_2018_2020_r2'


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    assert not (OUT/'output_sha256.json').exists(),'Do not overwrite final evidence'
    remaining=OUT/'official_remaining9';collection=read(remaining/'collection.json')
    assert len(collection['records'])==9 and sum(r['pages'] for r in collection['records'])==34
    notes={
        '1207232848':'Jan8 price-movement notice concerns Jan3/6/7 and issuer self-check; not an implemented shareholder distribution.',
        '1207224865':'Management sale of existing shares, including Jan2 transaction; conditional future bonus/conversion wording is not a realized distribution.',
        '1207219664':'Corporate derivatives control policy, not issuer equity entitlement terms.',
        '1207219663':'Independent opinion on foreign-exchange derivatives and related bank business, with signatures.',
        '1207219662':'Prior independent recognition of related foreign-exchange derivative proposal; not shareholder cash/stock rights.',
        '1207219661':'Jan20 shareholder meeting with Jan13 voting record date, one foreign-exchange proposal and blank authorization/voting forms; meeting record date is not ex-rights.',
        '1207219660':'Related foreign-exchange derivative business with CITIC Bank; counterparty profile/financials and transaction approval, not ordinary shareholder distribution.',
        '1207219659':'Company foreign-exchange hedging authorization and risk/accounting controls, not ordinary shareholder cash or shares.',
        '1207207647':'Company treasury investment principal/return and fundraising account closure; 2016 private issuance is historical context, not Jan2 issue or share cancellation.'}
    reviewed=[]
    for row in collection['records']:
        number=row['announcement_id'];assert row['state'].startswith('downloaded')
        assert sha(remaining/'pdf'/f'{number}.pdf')==row['sha256']
        reviewed.append(dict(announcement_id=number,title=row['title'],url=row['url'],
            pages_visually_viewed=list(range(1,row['pages']+1)),body_read=True,observation=notes[number],
            explanatory_ordinary_shareholder_implementation_terms_observed=False))
    write(remaining/'visual_review.json',dict(status='completed',pdfs=9,pages_actually_viewed=34,
        method='All rendered pages inspected in nine original-resolution labelled contact sheets',records=reviewed,
        initial_helper_failure='Text-length >100 guard rejected short signature/form pages; images were present. Removed that inappropriate heuristic, then inspected all34 pages; no source modified.',
        no_absence_of_all_actions_certification=True))
    (remaining/'report.md').write_text('# 剩余9份官方正文补核验\n\n9份、34页已全部逐图阅读，原title-only清单保持不改。具体页码和语义见visual_review.json。管理层减持／假设送转条款、股东大会投票登记日、公司理财回款／历史发行分别判读；本范围未观察到解释目标日普通股股东权利变化的实施条款。有限窗口与当前原件不能证明全部历史行动和版本完整。\n',encoding='utf-8')
    prior=verify_inputs(read(R2/'frozen_protocol.json'))
    preserved=read(R2/'output_sha256.json')
    for name,digest in preserved.items():assert sha(R2/name)==digest,name
    phase=read(OUT/'source_followup.json');representation=read(OUT/'adjusted_representation_review/representation_review.json')
    assert representation['quote_pairs']==24 and representation['qfq_minus_raw_all_pairs']=='-0.132'
    index=pd.read_csv(OUT/'official_actions/window_official_index_review.csv',dtype=str,keep_default_na=False)
    for i,row in index.iterrows():
        if row.announcement_id in notes:
            pages=next(r['pages'] for r in collection['records'] if r['announcement_id']==row.announcement_id)
            index.loc[i,'classification_basis']='body_visual_review_supplement'
            index.loc[i,'pdf_downloaded']='True';index.loc[i,'pdf_pages_actually_viewed']='|'.join(str(n) for n in range(1,pages+1))
    assert len(index)==13 and index.pdf_downloaded.eq('True').all()
    index.to_csv(OUT/'combined_official_window_review.csv',index=False)
    # This is an explicitly transcribed structured summary of already read gh
    # output, not claimed to be a raw HTTP response or a supplier confirmation.
    write(OUT/'github_issue_review.json',dict(evidence_kind='Structured summary of gh CLI reads',
        searches=['000998 repo:waditu/tushare','复权因子 2020 repo:waditu/tushare'],
        reads=[dict(number=1929,url='https://github.com/waditu/tushare/issues/1929',state='OPEN',comments=0,
                    scope='User report about2018 and001914; no supplier reply; not this case confirmation'),
               dict(number=1555,url='https://github.com/waditu/tushare/issues/1555',state='CLOSED',
                    scope='Another user fixed date alignment in his000002 example; current project already joins date/security keys')],
        external_message_sent=False))
    docs=['docs/2026-10-16-000998-data-source-followup.md',
        'docs/2026-10-16-000998-adjustment-representation-followup.md',
        'docs/2026-10-16-000998-vendor-reproduction.md']
    sources=['scripts/diagnose_000998_source_boundary.py','scripts/recheck_000998_2020_vendor.py',
        'scripts/report_000998_source_followup.py','scripts/compare_000998_adjusted_quotes.py',
        'scripts/collect_000998_remaining_notices.py',str(Path(__file__).resolve().relative_to(ROOT))]
    snapshot=OUT/'source_final';snapshot.mkdir()
    for name in docs+sources+['README.md','docs/research-progress.md','docs/strategy-completion-roadmap.md']:
        shutil.copy2(ROOT/name,snapshot/Path(name).name)
    shutil.copy2(ROOT/docs[1],OUT/'final_report.md')
    write(OUT/'latest_summary.json',dict(recorded_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        state='bounded_source_review_completed_with_unresolved_canonical_factor',
        phase1_snapshot='source_followup.json',independent_adjusted_prices_obtained=True,
        independent_same_definition_canonical_adjustment_factors_obtained=False,
        qfq_constant_offset_observed='-0.132 on24 printed quote pairs',
        hfq_affine_description=representation['hfq_affine_description'],
        source_boundary_days=43,raw_vendor_cache_examples=5,fresh_tushare_queries=2,
        official_window_records=13,official_window_bodies_read=13,official_window_pages_viewed=43,
        additional_annual_and_distribution_pages_viewed=7,total_official_pdfs=15,total_pages_viewed=50,
        previous_official_title_only_count=9,remaining_title_only_in_this_window=0,
        all_historical_actions_absent_certified=False,point_in_time_vintages_certified=False,
        old_ifind_assertion_reproducible_in_checked_168_files=False,wind_usable_data_obtained=False,
        current_data_fix_or_guard_revision_supported_for_implementation=False,
        model_or_account_reruns=0,source_data_changed=False,broker_connected=False,external_message_sent=False,
        prior_artifacts_verified=prior,r2_artifacts_preserved=len(preserved),overall_strategy_goal_achieved=False,
        latest_report=str(ROOT/docs[1]),reproduction_question_sheet=str(ROOT/docs[2]),
        report_sha256=sha(OUT/'final_report.md'),source_snapshot_sha256={p.name:sha(p) for p in snapshot.iterdir()}))
    files={p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file()}
    write(OUT/'output_sha256.json',files)
    assert all(sha(OUT/name)==digest for name,digest in files.items())
    print(json.dumps(dict(evidence_files=len(files),prior_artifacts_preserved=sum(prior.values())+len(preserved),
        official_pages_reviewed=50,canonical_correction_certified=False),ensure_ascii=False))


if __name__=='__main__':main()
