"""Describe verified independent-year experiments without pooling their NAVs."""
import hashlib
import json
from pathlib import Path


project = Path(__file__).resolve().parents[1]
lines = ['# 开发期逐年对照', '',
         '各年独立以 100 万元现金开始，包含上年末因子预热。下表不能视为连续持仓的多年收益或最大回撤，也不能直接用于计算多年复合年化收益。', '',
         '尚未完成 2021—2023 年验证及 2024—2025 年封存测试。', '',
         '| 年份 | 三因子收益 | 最大回撤 | 费用及滑点 | 零交易成本收益 | 排名缓冲收益 | 缓冲成本降幅 |',
         '|---|---:|---:|---:|---:|---:|---:|']
sources, missing = {}, []
for year in range(2016, 2021):
    folder = project / 'output' / f'development_{year}'
    path, check = folder / 'summary.json', folder / 'verification.json'
    if not path.exists() or not check.exists():
        missing.append(str(year))
        continue
    verification = json.loads(check.read_text(encoding='utf-8'))
    if (verification.get('status') != 'passed' or
            verification.get('summary_sha256') != hashlib.sha256(path.read_bytes()).hexdigest()):
        missing.append(str(year))
        continue
    summary = json.loads(path.read_text(encoding='utf-8'))
    data = {x['strategy']: x for x in summary['experiments']}
    base, zero, buffer = [data[key] for key in ('combined', 'combined_zero_cost', 'combined_rank_buffer40')]
    cost = base['total_fees'] + base['total_slippage']
    reduction = 1 - (buffer['total_fees'] + buffer['total_slippage']) / cost
    lines.append(f"| {year} | {base['total_return']:.2%} | {base['max_drawdown']:.2%} | {cost:,.2f} 元 | {zero['total_return']:.2%} | {buffer['total_return']:.2%} | {reduction:.2%} |")
    sources[str(year)] = dict(summary_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                              verification_sha256=hashlib.sha256(check.read_bytes()).hexdigest())
lines += ['', '未完成完整回测与核验的年份：' + ('、'.join(missing) or '无') + '。', '',
          '零交易成本仍保留红利税情景及交易限制。不同成本情景会改变整数股、现金和后续成交路径，收益差不能简单等同于手续费。', '',
          '排名缓冲固定为退出排名 40；未根据逐年结果扫描参数。完整诊断、公司行动、订单和来源摘要见各年度报告。', '']
output = project / 'output/development_comparison'
output.mkdir(parents=True, exist_ok=True)
(output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
(output / 'sources.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')
print('\n'.join(lines))
