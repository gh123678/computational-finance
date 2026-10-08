"""Report all registered validation years, including incomplete/failed runs."""
import hashlib
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(revision='initial'):
    suffix = '' if revision == 'initial' else '_' + revision
    run = ROOT / 'output' / ('validation_run_20261004' + suffix)
    statuses = json.loads((run / 'status.json').read_text(encoding='utf-8'))
    by_dataset = {x['dataset']: x for x in statuses}
    protocol = json.loads((run / 'frozen_protocol.json').read_text(encoding='utf-8'))
    changed = [name for name, digest in protocol['code_sha256'].items()
               if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    if changed:
        raise ValueError('Frozen code changed: ' + ', '.join(changed))
    lines = ['# 2021—2023 固定规则补充验证', '',
             '每年独立以 100 万元现金起步；不得拼接为连续账户收益。2024—2025 已经查看过，本轮不称为新的封存测试。', '',
             '| 年份 | 状态 | 周频组合收益 | 双周组合收益 | 双周最大回撤 | 双周 30bp 收益 | 双周费用及滑点 |',
             '|---|---|---:|---:|---:|---:|---:|']
    sources = {}
    comparisons = []
    for dataset in protocol['datasets']:
        year = dataset.rsplit('_', 1)[-1]
        item = by_dataset.get(dataset, dict(status='not_started', stage='not_started'))
        folder = ROOT / 'output' / dataset
        if item['status'] != 'verified':
            lines.append(f"| {year} | {item['status']} / {item.get('stage', '')} | — | — | — | — | — |")
            continue
        path = folder / 'summary.json'
        summary = json.loads(path.read_text(encoding='utf-8'))
        expected_source = {Path(name).name: value for name, value in protocol['code_sha256'].items()}
        if summary['source_sha256'] != expected_source:
            raise ValueError(f'{dataset}: summary source differs from frozen code')
        for name, value in summary['data_manifest']['files_sha256'].items():
            if hashlib.sha256((ROOT / 'data' / dataset / name).read_bytes()).hexdigest() != value:
                raise ValueError(f'{dataset}: market data changed: {name}')
        for name, value in summary['metadata_sha256'].items():
            if hashlib.sha256((ROOT / 'data/audit' / name).read_bytes()).hexdigest() != value:
                raise ValueError(f'{dataset}: universe metadata changed: {name}')
        verification = json.loads((folder / 'verification.json').read_text(encoding='utf-8'))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if verification['status'] != 'passed' or verification['summary_sha256'] != digest:
            raise ValueError(f'{dataset}: verification does not match summary')
        experiments = {x['strategy']: x for x in summary['experiments']}
        weekly, biweekly, stress = (experiments[label] for label in
                                   ['combined', 'combined_biweekly', 'combined_biweekly_slip30'])
        cost = biweekly['total_fees'] + biweekly['total_slippage']
        comparisons.append((year, weekly, biweekly, stress))
        lines.append(f"| {year} | 12 组核验通过 | {weekly['total_return']:.2%} | {biweekly['total_return']:.2%} | {biweekly['max_drawdown']:.2%} | {stress['total_return']:.2%} | {cost:,.2f} 元 |")
        sources[dataset] = dict(summary_sha256=digest, verification=verification['status'])
    if len(comparisons) == len(protocol['datasets']):
        positive = lambda index: sum(row[index]['total_return'] > 0 for row in comparisons)
        lines += ['', '## 本轮观察', '',
                  f'三个独立年度中，周频正收益 {positive(1)}/3 年，双周加缓冲正收益 {positive(2)}/3 年，双周 30bp 压力正收益 {positive(3)}/3 年。', '',
                  '双周与缓冲可以减少换手和成本，但仍有亏损年份。不能从这三年直接推出实盘可行，也不据此重选因子或参数。']
    lines += ['', '## 数据证据修订', '',
              '初始运行因分红或重整记录冲突中止，日志和冻结记录单独保留。第二版仅修正公告确认的事件身份与金额，策略规则未改。', '',
              '中国太保 2021、兖矿能源 2022、青岛啤酒 2023 排除已包含在总额中的特别股息；恒康医疗 2022 重整股份不分配给旧股东；兖矿能源 2023 合并两笔现金、保留送股。', '',
              '证据及文件校验值见 [公告修订记录](../../docs/2026-10-04-validation-data-corrections.md)。', '',
              '## 全部实验及异常', '']
    if revision == 'r3':
        lines += ['本版在 r2 之上只补充 18 项公告确认的配股日期；没有新增认购条款或调参。'
                  '旧版年度文件保存在 r2/annual_snapshot。见 [配股修订证据](../../docs/2026-10-04-validation-rights-corrections.md)。', '']
    for dataset in protocol['datasets']:
        item = by_dataset.get(dataset, dict(status='not_started'))
        if item['status'] != 'verified':
            stage = item.get('stage', 'download')
            log_path = run / f'{dataset}_{stage}.log'
            lines += [f"### {dataset}：{item['status']}", '',
                      '尚无完整、核验通过的年度结果。日志末段如下：', '', '```text']
            if log_path.exists():
                lines += log_path.read_text(encoding='utf-8', errors='replace').splitlines()[-12:]
            lines += ['```', '']
            continue
        summary = json.loads((ROOT / 'output' / dataset / 'summary.json').read_text(encoding='utf-8'))
        lines += [f'### {dataset}', '',
                  f"未解释复权变化 {summary['unexplained_adjustments']} 条，隔离股票日 {summary['quarantined_factor_rows']}，涨跌停字段缺口 {summary['missing_price_limit_rows']} 条。", '',
                  '| 实验 | 收益 | 最大回撤 | 累计双边换手 | 拒单数 | 行业超限天数 | 旧价估值天数 |',
                  '|---|---:|---:|---:|---:|---:|---:|']
        for e in summary['experiments']:
            lines.append(f"| {e['strategy']} | {e['total_return']:.2%} | {e['max_drawdown']:.2%} | {e['gross_turnover']:.2f} | {e['rejected_orders']} | {e['industry_breach_days']} | {e['stale_valuation_days']} |")
        lines += ['']
    if revision == 'r3' and len(comparisons) == 3:
        old_root = ROOT / 'output/validation_run_20261004_r2/annual_snapshot'
        old_protocol = json.loads((old_root.parent / 'frozen_protocol.json').read_text(encoding='utf-8'))
        modified = [name for name, digest in protocol['code_sha256'].items()
                    if old_protocol['code_sha256'].get(name) != digest]
        if modified != ['quant_research\\rights.py'] and modified != ['quant_research/rights.py']:
            raise ValueError(f'Unexpected r3 core changes: {modified}')
        snapshot_manifest = json.loads((old_root / 'manifest.json').read_text(encoding='utf-8'))
        for item in snapshot_manifest.values():
            if hashlib.sha256((ROOT / item['snapshot']).read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('Old annual snapshot changed: ' + item['snapshot'])
        lines += ['## r2 → r3 全部实验对照', '',
                  '仅登记公告日期，解除相关已解释事件的因子隔离。以下变化包含后续排名和买入影响，'
                  '不能只看事件前旧持仓。原始行情及元数据校验值须一致。', '',
                  '| 年份 | 实验 | r2 收益 | r3 收益 | 差异（百分点） | 未认购事件 | 认购事件 |',
                  '|---|---|---:|---:|---:|---:|---:|']
        changes = []
        for dataset in protocol['datasets']:
            old = json.loads((old_root / dataset / 'summary.json').read_text(encoding='utf-8'))
            new = json.loads((ROOT / 'output' / dataset / 'summary.json').read_text(encoding='utf-8'))
            if (old['data_manifest']['files_sha256'] != new['data_manifest']['files_sha256']
                    or old['metadata_sha256'] != new['metadata_sha256']):
                raise ValueError(f'{dataset}: data changed across evidence-only revisions')
            previous = {e['strategy']: e for e in old['experiments']}
            for e in new['experiments']:
                before = previous[e['strategy']]
                delta = e['total_return'] - before['total_return']
                changes.append(dict(dataset=dataset, strategy=e['strategy'],
                                    old_return=before['total_return'], new_return=e['total_return'],
                                    delta_return=delta,
                                    rights_not_subscribed=e['rights_not_subscribed'],
                                    rights_subscribed=e['rights_subscribed']))
                lines.append(f"| {dataset[-4:]} | {e['strategy']} | {before['total_return']:.2%} | "
                             f"{e['total_return']:.2%} | {delta*100:+.4f} | "
                             f"{e['rights_not_subscribed']} | {e['rights_subscribed']} |")
        (run / 'r2_r3_comparison.json').write_text(json.dumps(changes, indent=2), encoding='utf-8')
        lines += ['', '此前七年度输出没有重跑。新增 2023-12-08 配股记录落入 2024 年实验的预热窗口，'
                  '不能宣称旧版年度结果与当前代码一致或不受该修订影响。', '']
    lines += ['## 研究边界', '',
              '双周实验同时包含排名缓冲 40，差异不能全部归因于调仓频率；年度实验是补充验证，没有预先新增收益达标门槛。', '',
              '本轮不根据结果改因子方向、调仓周期或阈值。历史 ST 事件完整性和行业发布版本仍未独立确认；配股除权日扣款、固定红利税和退市零回收仍为研究情景。', '',
              '缺少完整年度时不汇总成通过结论；未来需连续账户、历史覆盖复核和前向模拟成交证据。']
    (run / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (run / 'report_sources.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')
    print('\n'.join(lines[:12]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', choices=['initial', 'r2', 'r3'], default='initial')
    main(parser.parse_args().revision)
