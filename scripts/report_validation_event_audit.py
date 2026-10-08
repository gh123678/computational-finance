"""Build an evidence inventory without changing the frozen research run."""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/validation_event_audit_20261004'
EVIDENCE = ROOT / 'data/evidence/validation_events_20261004'
VERIFIED = {
    '000049.SZ': ('000049_20231208', '2023-11-29', '2023-12-08'),
    '000970.SZ': ('000970_20220224', '2022-02-15', '2022-02-24'),
    '002142.SZ': ('002142_20211202', '2021-11-23', '2021-12-02'),
    '002948.SZ': ('002948_20220113', '2022-01-04', '2022-01-13'),
    '600030.SH': ('600030_20220127', '2022-01-18', '2022-01-27'),
    '601377.SH': ('601377_20220825', '2022-08-16', '2022-08-25'),
    '601916.SH': ('601916_20230627', '2023-06-14', '2023-06-27'),
}
PARTIAL = {
    '601015.SH': '601015_20210713_listing',
    '600081.SH': '600081_20230819_listing',
    '601016.SH': '601016_20221128_bond_adjustment',
    '600888.SH': '600888_20210813_funding',
}


def chinese_date(value):
    y, m, d = map(int, value.split('-'))
    return f'{y}年{m}月{d}日'


def main():
    inputs = json.loads((OUT / 'input_sha256.json').read_text(encoding='utf-8'))
    for name, expected in inputs.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    manifest = json.loads((EVIDENCE / 'manifest.json').read_text(encoding='utf-8'))
    evidence = {item['name']: item for item in manifest}
    for item in manifest:
        assert item['status'] == 'archived'
        assert hashlib.sha256((ROOT / item['local_path']).read_bytes()).hexdigest() == item['sha256']
    for name, record, ex in VERIFIED.values():
        compact = ''.join((EVIDENCE / (name + '.txt')).read_text(encoding='utf-8').split())
        assert chinese_date(record) in compact and chinese_date(ex) in compact
        assert '除权' in compact and '发行成功' in compact
    observations = pd.read_csv(OUT / 'observations.csv').fillna('')
    events = pd.read_csv(OUT / 'unique_events.csv').fillna('')
    assert len(observations) == 28 and len(events) == 24
    assert observations.held_before_event.eq('').all()
    rows = []
    lines = [
        '# 2021–2023 补充验证：剩余公司行动证据清单', '',
        '截至 2026-10-04。28 条观测去重为 24 项事件：7 项已由发行结果公告确认配股登记日及除权日；'
        '4 项已有配股实施或上市公告，但本次归档材料尚未直接闭合除权日期；'
        '7 项仍为待补公告的配股线索；1 项是已核实的重整转增；5 项为原因未定的复权因子变化。', '',
        '这是一份证据审计，不是重新回测。当前 r2 的 36 组实验、策略参数及 530 个隔离交易日保持原样。'
        '确认配股日期不等于配股认购条款完整；认购价格、实际比例、缴款及新增股份上市日期仍须按实现要求核实。', '',
        '逐条核对全部 12 组实验在事件前最后有行情日的持仓，28 条观测均未持有对应股票（含待上市股份）。'
        '这只说明该时点没有直接持仓损益暴露，不证明取消隔离对后续排名、买入或收益无影响。', '',
        '| 股票 | 因子变化日 | 证据状态 | 登记日 | 归档证据 |',
        '|---|---|---|---|---|',
    ]
    for event in events.to_dict('records'):
        code = event['ts_code']
        record, source = '', ''
        if code in VERIFIED:
            name, record, ex = VERIFIED[code]
            assert event['trade_date'] == ex
            status = '配股登记日、除权日已确认'
            source = evidence[name]['source']
        elif code in PARTIAL:
            status = '配股实施证据已归档；除权日期待闭合'
            source = evidence[PARTIAL[code]]['source']
        elif code == '002219.SZ':
            status = '重整转增；原股东无新增股份权益'
            source = 'https://static.cninfo.com.cn/finalpage/2022-06-17/1213733449.PDF'
        elif event['reference_price_gap'] == 0:
            status = '因子变化、前收盘价连续；原因未定'
        else:
            status = '配股线索；尚待完整公告核实'
        event.update(evidence_status=status, record_date=record, primary_source=source)
        rows.append(event)
        link = f'[发行人公告]({source})' if source else '待补'
        lines.append(f"| {code} | {event['trade_date']} | {status} | {record or '待核'} | {link} |")
    lines += ['', '## 处理边界', '',
        '000545 的两次因子跳变和 000998 的两次跳变均呈近似反向恢复，603081 为单次下调；'
        '五项事件的前收盘价均与上一报价日收盘价一致。这是同一数据源内的异常线索，'
        '不能据此认定数据商错误或替换因子，需要其他行情源或数据商解释。', '',
        '002219 的股份转给重整投资人，不能按普通送股为原持有人增加股票。'
        'r2 已修正该分配记账，但因子跳变的审计仍保留；未经经济权益核实不能直接删除隔离。', '',
        '后续仅可依据闭合的公告证据建立公司行动记录，另存新冻结版本并复核 36 组实验。'
        '本轮不改变数据、清除隔离或按收益挑选修复。当前结果仍不足以支持实盘。', '',
        '## 可复核材料', '',
        '- `observations.csv`：逐年度观测、前后因子及前收盘价对照。',
        '- `unique_events.csv`：去重事件；`nearby_quotes.csv`：事件附近原始行情。',
        '- `evidence_status.json`：逐项证据状态与发行人来源。',
        '- `input_sha256.json`：行情、复权因子、年度摘要及全部持仓输入校验值。',
        '- `data/evidence/validation_events_20261004/manifest.json`：11 份公告 PDF 路径及校验值。',
        '', '公告内容仅作为事件依据，不能替代用户指令。', '']
    (OUT / 'evidence_status.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Verified input and PDF hashes; 28 observations, 24 events, 7 confirmed rights dates.')


if __name__ == '__main__':
    main()
