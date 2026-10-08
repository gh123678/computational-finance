"""Compare preserved annual outputs and report ten independent accounts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'output/annual_refresh_20261004'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    frozen = read(RUN / 'frozen_protocol.json')
    current = {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / 'quant_research').glob('*.py'))}
    assert frozen['code_sha256'] == current
    validation = read(ROOT / 'output/validation_run_20261004_r3/frozen_protocol.json')
    assert validation['code_sha256'] == current
    calendar_checks = read(RUN / 'calendar_scope_verification.json')
    assert calendar_checks['verifier_sha256'] == digest(ROOT / 'scripts/verify_annual.py')
    assert len(calendar_checks['checks']) == 10
    assert all(c['exit_code'] == 0 for c in calendar_checks['checks'])
    for name, expected in frozen['snapshot_sha256'].items():
        assert digest(ROOT / name) == expected, name
    statuses = {s['dataset']: s for s in read(RUN / 'status.json')}
    validation_status = {s['dataset']: s for s in read(ROOT / 'output/validation_run_20261004_r3/status.json')}
    ordered = [*[f'development_{y}' for y in range(2016, 2021)],
               *[f'validation_{y}' for y in range(2021, 2024)],
               'out_of_sample_2024', 'out_of_sample_2025']
    sources, comparisons, rows = {}, [], []
    lines = ['# 2016–2025 同版本年度结果核验', '',
             '十个年度均以 100 万元独立起步，各含 12 组固定实验。年度收益不能拼成连续账户。'
             '2016–2020 是开发数据，2021–2023 是补充验证，2024–2025 已查看并复用，不能称为新的封存测试。', '',
             '本轮保存此前七年完整输出后，只用校验值一致的本地数据重跑，不下载、不调参。'
             '三年补充验证沿用已完成的 r3。所有年度必须与同一核心代码指纹匹配，并通过当前账务与调仓核验。', '',
             '| 年份 | 状态 | 周频收益 | 双周加缓冲收益 | 双周回撤 | 双周 30bp 收益 | 未解释观测 | 隔离股票日 |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    expected_code = {Path(k).name: v for k, v in current.items()}
    for dataset in ordered:
        year = dataset[-4:]
        status = (validation_status if dataset.startswith('validation_') else statuses).get(dataset, {})
        if status.get('status') != 'verified':
            lines.append(f"| {year} | {status.get('status', '未开始')} | — | — | — | — | — | — |")
            continue
        folder = ROOT / 'output' / dataset
        summary = read(folder / 'summary.json')
        verification = read(folder / 'verification.json')
        assert summary['source_sha256'] == expected_code, dataset
        assert verification['status'] == 'passed'
        assert verification['summary_sha256'] == digest(folder / 'summary.json')
        for name, expected in summary['data_manifest']['files_sha256'].items():
            assert digest(ROOT / 'data' / dataset / name) == expected
        for name, expected in summary['metadata_sha256'].items():
            assert digest(ROOT / 'data/audit' / name) == expected
        old_folder = (ROOT / 'output/validation_run_20261004_r2/annual_snapshot' / dataset
                      if dataset.startswith('validation_') else RUN / 'annual_snapshot' / dataset)
        old = read(old_folder / 'summary.json')
        assert old['data_manifest']['files_sha256'] == summary['data_manifest']['files_sha256']
        assert old['metadata_sha256'] == summary['metadata_sha256']
        experiments = {e['strategy']: e for e in summary['experiments']}
        previous = {e['strategy']: e for e in old['experiments']}
        assert len(experiments) == 12 and experiments.keys() == previous.keys()
        for label, e in experiments.items():
            p = previous[label]
            comparisons.append(dict(dataset=dataset, strategy=label,
                old_return=p['total_return'], new_return=e['total_return'],
                return_delta=e['total_return']-p['total_return'],
                old_drawdown=p['max_drawdown'], new_drawdown=e['max_drawdown'],
                old_cost=p['total_fees']+p['total_slippage'],
                new_cost=e['total_fees']+e['total_slippage'],
                old_turnover=p['gross_turnover'], new_turnover=e['gross_turnover']))
        weekly, bw, stress = [experiments[k] for k in ('combined', 'combined_biweekly', 'combined_biweekly_slip30')]
        lines.append(f"| {year} | 12 组核验通过 | {weekly['total_return']:.2%} | {bw['total_return']:.2%} | "
                     f"{bw['max_drawdown']:.2%} | {stress['total_return']:.2%} | {summary['unexplained_adjustments']} | "
                     f"{summary['quarantined_factor_rows']} |")
        rows.append(dict(dataset=dataset, weekly=weekly, biweekly=bw, stress=stress,
                         unexplained=summary['unexplained_adjustments'], quarantined=summary['quarantined_factor_rows']))
        sources[dataset] = dict(summary_sha256=digest(folder / 'summary.json'),
                               verification_sha256=digest(folder / 'verification.json'),
                               old_summary_path=str((old_folder / 'summary.json').relative_to(ROOT)))
    if len(rows) == 10:
        changes = [c for c in comparisons if abs(c['return_delta']) > 1e-12]
        lines += ['', '## 版本对照', '',
                  f'十年共 120 组实验核验通过；其中 {len(changes)} 组年度收益发生变化。'
                  '此前七年度的基准为本轮完整保存的旧结果，补充三年的基准为 r2 快照。', '',
                  '全部实验的收益、回撤、费用和换手对照保存在 `comparison.json`。'
                  '校验要求新旧原始行情及历史股票池元数据一致；收益变化不用于重新选择参数。', '']
        positive_bw = sum(r['biweekly']['total_return'] > 0 for r in rows)
        positive_stress = sum(r['stress']['total_return'] > 0 for r in rows)
        lines += [f'这十个独立年度中，双周加缓冲基准成本正收益 {positive_bw}/10 年，'
                  f'30bp 滑点压力正收益 {positive_stress}/10 年。'
                  '开发数据和已经查看的数据混合汇总仅用于描述，不能当作独立样本外成功率或未来盈利概率。', '']
        lines += ['| 年份 | 原未解释观测 | 新未解释观测 | 原隔离股票日 | 新隔离股票日 |',
                  '|---|---:|---:|---:|---:|']
        for row in rows:
            dataset = row['dataset']
            old = read(ROOT / sources[dataset]['old_summary_path'])
            lines.append(f"| {dataset[-4:]} | {old['unexplained_adjustments']} | {row['unexplained']} | "
                         f"{old['quarantined_factor_rows']} | {row['quarantined']} |")
    lines += ['', '## 核验日期范围修正', '',
              '2025 和 2016 首次核验因双周日期不一致中止。核验程序误用从 2010 年起的完整交易日历决定双周轮次，'
              '研究程序按已规定的预热窗口起算。现在将核验日历限制到该窗口，仍严格要求形成日、执行日和成交日匹配。'
              '没有改变策略或交易账本；十年度均由修正后的核验程序再次检查。', '',
              '原核验程序、初次失败日志和修正前状态保留；最终核验程序指纹及十年度退出码见 '
              '`calendar_scope_verification.json`。', '', '## 研究边界', '',
              '双周方案同时使用排名缓冲 40，改善不能全部归于调仓周期。'
              '年度账户没有跨年延续持仓、现金、配股或分红权益，不能推导十年实际复利收益。', '',
              '历史 ST 事件完整性、行业版本当时可得性尚未独立确认；配股现金时点、固定红利税、退市零回收和成交成本仍为研究情景。'
              '未知公司行动继续隔离并对持仓中止。账务核验通过不等于具备实盘条件。', '',
              '后续需要跨年连续账户验证及前向模拟成交记录。本轮没有接入券商或下单。', '']
    (RUN / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    (RUN / 'comparison.json').write_text(json.dumps(comparisons, indent=2), encoding='utf-8')
    (RUN / 'report_sources.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')
    print('\n'.join(lines[:18]))
    print('Verified annual accounts:', len(rows))


if __name__ == '__main__':
    main()
