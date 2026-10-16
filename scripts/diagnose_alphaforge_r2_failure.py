"""Read saved r2 failures and frozen quotes; never run an account or repair data."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.adjustment_audit import MATERIAL_ADJUSTMENT_THRESHOLD
from quant_research.corporate_corrections import correct_actions
from quant_research.rights import verified_rights

DATA = ROOT / 'data/continuous_2016_2025_dividend_r1'
SOURCE = ROOT / 'output/continuous_2016_2025_dividend_r1'
OUT = ROOT / 'output/alphaforge_case_2018_2020_r2'
DESTINATION = OUT / 'failure_evidence'
CODE = '000998.SZ'
FAILURE_DAY = pd.Timestamp('2020-01-02')
DAYS = ('20191230', '20191231', '20200102', '20200103')
PRIMARY = 'case_negative_retention_common200'
EXPECTED_ERROR = 'Unexplained corporate action for held 000998.SZ on 2020-01-02'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def select_quotes(name):
    pieces = []
    for chunk in pd.read_csv(DATA / (name + '.csv'), dtype=str,
                             keep_default_na=False, chunksize=150000):
        selected = chunk.loc[chunk.ts_code.eq(CODE) & chunk.trade_date.isin(DAYS)].copy()
        if len(selected):
            pieces.append(selected)
    if not pieces:
        raise RuntimeError('Requested frozen source observations are absent: ' + name)
    result = pd.concat(pieces, ignore_index=True)
    if result.duplicated(['trade_date', 'ts_code']).any():
        raise RuntimeError('Ambiguous source security/date in ' + name)
    return result


def main():
    if DESTINATION.exists():
        raise RuntimeError('Existing failure evidence; inspect instead of overwriting')
    protocol = read_json(OUT / 'frozen_protocol.json')
    summary = read_json(OUT / 'summary.json')
    statuses = read_json(OUT / 'status.json')
    stage = read_json(OUT / 'experiment_stage.json')
    assert statuses == summary['experiment_statuses']
    assert stage['state'] == 'failed'
    expected_labels = {f'{PRIMARY}_{cost}bp' for cost in (0, 10, 30)}
    failed = [item for item in statuses if item['strategy'] in expected_labels]
    assert len(failed) == 3 and {item['strategy'] for item in failed} == expected_labels
    assert all(item['status'] == 'failed' and item['error'] == EXPECTED_ERROR for item in failed)
    assert not expected_labels.intersection(item['strategy'] for item in summary['experiments'])
    protected = [Path(__file__), DATA / 'manifest.json', DATA / 'daily.csv', DATA / 'adj_factor.csv',
                 DATA / 'dividend.csv', SOURCE / 'unexplained_adjustments.csv',
                 OUT / 'frozen_protocol.json', OUT / 'summary.json', OUT / 'status.json',
                 OUT / 'experiment_stage.json', OUT / 'experiment_protocol.json',
                 OUT / 'last_failure.json', OUT / 'preparation_status.json', OUT / 'preparation_audit.json',
                 OUT / 'feature_summary.json', OUT / 'schedule.csv', OUT / 'events.csv',
                 OUT / f'targets_{PRIMARY}.csv',
                 ROOT / 'quant_research/backtest.py', ROOT / 'quant_research/adjustment_audit.py',
                 ROOT / 'quant_research/corporate_corrections.py', ROOT / 'quant_research/rights.py']
    if (OUT / 'coverage_supplement.json').exists():
        protected += [OUT / 'coverage_supplement.json', OUT / 'coverage_by_year.csv']
    last_failure = read_json(OUT / 'last_failure.json')
    protected.append(OUT / last_failure['failure'])
    for item in failed:
        protected += [OUT / item['strategy'] / 'failure.txt',
                      OUT / item['strategy'] / 'historical_targets.csv']
    fingerprints = {str(path): sha(path) for path in protected}
    # Authenticate only consumed sources here, rather than repeating the full
    # independent preparation audit or re-running the simulated accounts.
    market_manifest = read_json(DATA / 'manifest.json')['files_sha256']
    for name in ('daily.csv', 'adj_factor.csv', 'dividend.csv'):
        assert fingerprints[str(DATA / name)] == market_manifest[name]
    for path in protected:
        try:
            relative = str(path.relative_to(ROOT))
        except ValueError:
            continue
        if relative in protocol['inputs']:
            assert fingerprints[str(path)] == protocol['inputs'][relative]
        if path.parent == ROOT / 'quant_research':
            assert fingerprints[str(path)] == protocol['source_sha256'][path.name]

    records = []
    for item in failed:
        folder = OUT / item['strategy']
        failure_text = (folder / 'failure.txt').read_text(encoding='utf-8')
        last_line = [line for line in failure_text.splitlines() if line.strip()][-1]
        assert last_line == 'ValueError: ' + EXPECTED_ERROR
        files = sorted(path.name for path in folder.iterdir() if path.is_file())
        for frame_name in ('nav.csv', 'orders.csv', 'holdings.csv', 'corporate_events.csv'):
            assert not (folder / frame_name).exists(), 'Unexpected saved primary frame: ' + frame_name
        assert sha(folder / 'historical_targets.csv') == sha(OUT / f'targets_{PRIMARY}.csv')
        records.append(dict(strategy=item['strategy'], error=item['error'],
                            failure_path=str(folder / 'failure.txt'),
                            failure_sha256=sha(folder / 'failure.txt'), terminal_error=last_line,
                            nav_exists=False, folder_files=files))

    daily, factor = select_quotes('daily'), select_quotes('adj_factor')
    quotes = daily.merge(factor, on=['ts_code', 'trade_date'], validate='one_to_one').sort_values('trade_date')
    assert set(quotes.trade_date) == set(DAYS) and len(quotes) == 4
    # The only existing factor correction for this security is bounded to
    # August 2018, so these four raw 2019/2020 factor values are unchanged.
    pairs = []
    for previous, current in zip(quotes.to_dict('records'), quotes.to_dict('records')[1:]):
        previous_factor = Decimal(previous['adj_factor'])
        current_factor = Decimal(current['adj_factor'])
        previous_close, reference = Decimal(previous['close']), Decimal(current['pre_close'])
        relative = float(current['adj_factor']) / float(previous['adj_factor']) - 1
        pairs.append(dict(previous_date=previous['trade_date'], current_date=current['trade_date'],
                          previous_close_text=previous['close'], current_pre_close_text=current['pre_close'],
                          raw_reference_equal=previous_close == reference,
                          raw_reference_gap_cny=str(reference - previous_close),
                          previous_adj_factor_text=previous['adj_factor'],
                          current_adj_factor_text=current['adj_factor'],
                          adj_factor_delta=str(current_factor - previous_factor),
                          adj_factor_relative_change=relative,
                          existing_material_threshold=MATERIAL_ADJUSTMENT_THRESHOLD,
                          exceeds_existing_guard_threshold=abs(relative) > MATERIAL_ADJUSTMENT_THRESHOLD))
    guard_pair = next(row for row in pairs if row['current_date'] == '20200102')
    assert guard_pair['exceeds_existing_guard_threshold']

    dividends = pd.read_csv(DATA / 'dividend.csv', dtype=str, keep_default_na=False)
    corrected, corrections = correct_actions(dividends.replace('', pd.NA))
    actions = corrected.loc[corrected.ts_code.eq(CODE) & corrected.div_proc.eq('实施') &
                            corrected.ex_date.le('20201231')].copy()
    action_records = actions.astype(object).where(actions.notna(), None).to_dict('records')
    relevant_rights = [dict(code=issue.code, record=issue.record.strftime('%Y-%m-%d'),
                            ex=issue.ex.strftime('%Y-%m-%d'), source=issue.source)
                       for issue in verified_rights() if issue.code == CODE]
    before = pd.Timestamp(guard_pair['previous_date'])
    explained_dividends = [row for row in action_records if row['ex_date'] and
                           before < pd.Timestamp(row['ex_date']) <= FAILURE_DAY]
    explained_rights = [row for row in relevant_rights if before < pd.Timestamp(row['ex']) <= FAILURE_DAY]
    assert not explained_dividends and not explained_rights
    existing = pd.read_csv(SOURCE / 'unexplained_adjustments.csv', dtype=str, keep_default_na=False)
    old_issue = existing.loc[existing.ts_code.eq(CODE) & existing.trade_date.eq('2020-01-02')].copy()
    assert len(old_issue) == 1

    targets = pd.read_csv(OUT / f'targets_{PRIMARY}.csv',
                          parse_dates=['signal_date', 'execution_date'], float_precision='round_trip')
    prior = targets.loc[targets.ts_code.eq(CODE) & targets.execution_date.lt(FAILURE_DAY)].sort_values('execution_date')
    assert len(prior)
    last = prior.iloc[-1]
    target_context = targets.loc[targets.ts_code.eq(CODE) &
                                 targets.execution_date.between('2019-12-01', '2020-01-10')].copy()
    last_target = dict(signal_date=last.signal_date.strftime('%Y-%m-%d'),
                       execution_date=last.execution_date.strftime('%Y-%m-%d'),
                       target_weight=float(last.target_weight), score=float(last.score),
                       actual_shares_not_saved=True)
    events = pd.read_csv(OUT / 'events.csv', dtype=str, keep_default_na=False)
    event_context = events.loc[events.code.eq(CODE) & events.event_date.between('2019-12-01', '2020-01-10')]
    preparation = read_json(OUT / 'preparation_audit.json')
    assert preparation['status'] == 'passed'
    coverage_check = None
    if (OUT / 'coverage_supplement.json').exists():
        supplement = read_json(OUT / 'coverage_supplement.json')
        annual = pd.read_csv(OUT / 'coverage_by_year.csv')
        feature = read_json(OUT / 'feature_summary.json')
        assert int(annual.original_rows.sum()) == feature['original_rows']
        assert int(annual.r2_valid_rows.sum()) == feature['common_rows']
        assert int(annual.r1_lost_rows.sum()) == supplement['summary']['r1_lost_rows'] == 65
        assert int(annual.r2_gained_rows.sum()) == supplement['summary']['r2_gained_rows'] == 4721
        coverage_check = dict(status='saved_summary_totals_match', original_rows=feature['original_rows'],
                              valid_rows=feature['common_rows'], r1_lost=65, r2_gained=4721,
                              no_duplicate_raw_preparation_audit=True)

    result = dict(recorded_at=datetime.now(timezone.utc).isoformat(), scope='Saved failure and frozen-source diagnosis only',
                  code=CODE, failure_date=FAILURE_DAY.strftime('%Y-%m-%d'),
                  primary_failures=records, same_error=True,
                  identical_failure_log_bytes=len({r['failure_sha256'] for r in records}) == 1,
                  no_primary_nav_saved=True, primary_return_available=False,
                  preparation_independently_verified=True,
                  guard_condition=dict(**guard_pair, registered_dividend_matches=explained_dividends,
                                       registered_rights_matches=explained_rights,
                                       source_code=str(ROOT / 'quant_research/backtest.py'),
                                       source_logic='The held-position guard checks material factor moves without registered effective actions before morning accounting or any current-day trading.'),
                  quote_observations=quotes.to_dict('records'), adjacent_reference_checks=pairs,
                  existing_unexplained_rows=old_issue.to_dict('records'),
                  registered_distributions=action_records, registered_rights=relevant_rights,
                  nearby_r2_registered_events=event_context.to_dict('records'),
                  latest_pre_failure_target=last_target, coverage_supplement_check=coverage_check,
                  interpretation=[
                      'The error establishes that the unchanged core encountered a held-position factor guard. Target rows are plans, not executed share counts.',
                      'The saved factor movement exceeds the existing 0.5% guard and no matching effective action is present in the existing distribution/rights registry for the interval.',
                      'A continuous saved raw-price reference is a diagnostic observation, not proof of no corporate action, a vendor error or a correction value.',
                      'After a simulation exception the adapter saves failure.txt but receives no returned NAV, holdings or order frames; no primary performance or position quantity can be reconstructed from these saved results.',
                      'Changing formation eligibility does not exempt existing holdings from the unchanged daily account guard.'
                  ],
                  remaining_unresolved=[
                      'Economic cause and independently supported treatment of the 2020-01-02 factor change.',
                      'Primary filled share quantities and partial NAV before failure were not saved; this diagnosis does not fabricate or rerun them.',
                      'Three primary account performance records and the full six-account comparison, strategy gates and twelve-boundary qualification are unavailable.',
                      'Any future data correction or handling-policy revision requires a separately reviewed frozen version; r2 is not silently restarted.'
                  ],
                  simulations_started=0, network_requests=0, source_or_rule_modifications=0)
    for path, expected in fingerprints.items():
        assert sha(Path(path)) == expected, 'Consumed source changed during diagnosis: ' + path
    DESTINATION.mkdir()
    quotes.to_csv(DESTINATION / 'raw_quote_adj.csv', index=False)
    pd.DataFrame(pairs).to_csv(DESTINATION / 'adjacent_reference_checks.csv', index=False)
    actions.to_csv(DESTINATION / 'registered_distributions.csv', index=False)
    old_issue.to_csv(DESTINATION / 'existing_unexplained.csv', index=False)
    target_context.to_csv(DESTINATION / 'target_context.csv', index=False)
    write_json(DESTINATION / 'failure_diagnosis.json', result)
    write_json(DESTINATION / 'inputs_sha256.json', fingerprints)
    text = ('# AlphaForge r2主账户失败证据\n\n'
            '三个主候选账户均因同一个持仓保护条件在2020-01-02中止；这不是已算出的亏损结论。'
            '主账户没有保存净值、订单或持股数，不能补造收益或数量。本诊断未运行账户、未联网、未修改规则。\n\n'
            f"000998.SZ的系数由{guard_pair['previous_adj_factor_text']}变为{guard_pair['current_adj_factor_text']}，"
            f"相对变化{guard_pair['adj_factor_relative_change']:.8%}，超过既有0.5%守卫。"
            f"上一实际收盘{guard_pair['previous_close_text']}元，当日pre_close={guard_pair['current_pre_close_text']}元；"
            f"Decimal参考价比较相等为{guard_pair['raw_reference_equal']}。该观察不能证明无行动、供应商错误或应修正的数值。\n\n"
            '旧未解释清单已列同一日期／证券。既有已实施分红与配股登记在两次报价之间没有匹配生效日，'
            '这只是登记覆盖内的事实，不是全部行动不存在的证明。核心在当日早间账务和交易前检查该条件，保持了原保护。\n\n'
            f"失败前最近形成目标为{last_target['signal_date']}，执行计划日{last_target['execution_date']}，"
            f"目标权重{last_target['target_weight']:.2%}。目标不是成交记录；实际股数未知。\n\n"
            '准备已通过独立核验，不能因此宣布账户工程验证全部通过。仍缺三个主账户结果、完整六账户比较、'
            '策略资格与12个跨年核验。对照账户的完成状态也不能替代主候选结果。后续经济原因及任何处理政策须另立版本审阅，'
            '不清空失败、不放宽持仓守卫、不自动重跑r2。\n\n'
            '详细原始字符串、相邻参考、登记行动、目标上下文及输入指纹保存在本目录。\n')
    (DESTINATION / 'report.md').write_text(text, encoding='utf-8')
    outputs = {path.relative_to(DESTINATION).as_posix(): sha(path)
               for path in sorted(DESTINATION.iterdir()) if path.is_file()}
    write_json(DESTINATION / 'output_sha256.json', outputs)
    print(json.dumps(dict(output=str(DESTINATION), artifacts=len(outputs),
                          guard_change=guard_pair['adj_factor_relative_change'],
                          raw_reference_equal=guard_pair['raw_reference_equal'],
                          latest_target=last_target, same_error=True, no_primary_nav=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
