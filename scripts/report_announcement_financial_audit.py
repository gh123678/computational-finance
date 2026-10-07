"""Render a clearly incomplete audit snapshot, or its download-stage closeout."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import announcement_financial_audit as audit

def main(final_snapshot=False):
    out=audit.OUT
    if final_snapshot:
        if (out/'download.lock').exists():raise RuntimeError('Downloader still owns lock; do not produce closeout')
        audit.analyze(audit.initialize())
    state=json.loads((out/'download_status.json').read_text(encoding='utf-8'))
    analysis=json.loads((out/'analysis_status.json').read_text(encoding='utf-8'))
    protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    done=state['completed_units'];total=state['total_units']
    phase='数据下载完成，原文时点核验尚未完成' if state['state']=='completed' else '数据下载尚未完成'
    if state['state']=='stopped':phase='数据下载已停止，需查看失败原因'
    report=f'''# 公告财务数据审计进度

状态：**{phase}**。截至下载状态文件时间 {state['at']}（UTC）。这不是策略回测或财务审计通过报告。

## 已完成

- 用户确认设计已提交，提交号364ae51。固定范围{len(protocol['codes'])}只股票，{total}个股票/接口单元。
- forecast、fina_indicator、fina_audit三个普通接口均实际成功；forecast小请求为空，属于成功空结果，不等于权限失败。
- 显式取到财务修订标志update_flag，默认指标返回曾省略该字段。同一期原始/修订标志可能数值相同，不能仅凭标志证明已保存真实初始版本。
- 独立缓存、限速1.3秒、满页日期细分、有限重试、断点续传和旧结果哈希检查已实施。6项必要测试通过，包括Windows临时读锁重试。
- 当前完成{done}/{total}个下载单元。实时状态见download_status.json；日志见download_run_repaired.log。避免重复启动。

## 分析快照与限制

分析时间 {analysis['at']}（UTC）；该快照扫描{analysis['completed_units']}个已完成单元，共{analysis['raw_rows']}条记录。公告窗口内{analysis['ann_window_rows']}条，窗口外或公告日期无效{analysis['outside_or_invalid_ann_rows']}条。同日同报告期内容差异记录{analysis['same_date_conflict_rows']}条，原文核查队列{analysis['document_queue_rows']}条。下载同时推进，快照数量不代表最终全市场数量。

**与原始公告逐版本核验通过的记录仍为0。** 所有API候选均标注unverified_original_version，禁止直接视作可信历史财务输入。API候选覆盖不是原文核验覆盖。

财务指标过滤按报告期运行：即使查询终点为20201231，也可能返回2021年才公告的2020年报。原始响应保留，截面候选单独按公告日截断。预告可早于报告期结束；不能套用已公布财报的日期约束。后续修订内容不能挂回首次公告日。

金额：预告万元转元已验证。指标profit_dedt保留原值，尚未与原文逐条确认单位；不依据它建立筛选阈值。缺失与失败不解释为无风险。

原文线索及已记录访问失败见[primary_evidence_notes.md](primary_evidence_notes.md)。原文公布日期冲突、后续监管引用和原始公告分开；未取得初始版本时保持未知。

已完成两例原文数值检查，见[version-conflict-case-report.md](version-conflict-case-report.md)和evidence/field_checks.csv：晨鸣纸业同日两个指标版本中，原报告支持标志1的扣非净利润，标志0数值不一致；平安银行预告区间与增长率一致，上年利润基数差4万元。字段匹配未升级为完整记录时点核验通过，原因尚待查明，不自动设置容差放行。

## 本轮真实失败及修复

普通环境DPAPI解密失败；获准Windows用户环境后解密成功，令牌未输出或写入工具源码。第一轮下载70个状态单元后，进度文件替换发生WinError 5，进程退出；实际71个完成缓存保留。失败协议、源码、进度与原因保存在initial_status_replace_failure。增加有限重试后续跑，工程版本变更记在protocol.json，未改变数据范围或策略参数。

此次读取交易所002280关注函链接返回Internal Error，保留检索线索，不标记原文读取通过。分析出现pandas空列拼接FutureWarning，当前不是失败；日志保留，未因此改变已下载数据。

## 后续验收尚待完成

全量下载、每年固定首尾样本、全部内容冲突和主要亏损股的原公告/版本匹配，以及2016—2020信号截面的公告年龄和可追溯覆盖。完成这些后才能判断数据是否支持可信历史策略。数据不可追溯时应报告不能通过，不填补未知后回测。

已检查标签实验665项及原ML实验295项旧输出，哈希均保持不变；核心源码保持冻结r1版本。没有新训练、回测或券商连接。
'''
    (out/'report.md').write_text(report,encoding='utf-8')
    audit.write_json(out/'report_snapshot_sha256.json',{'at':audit.now(),
        'source_sha256':{p.name:audit.sha(p) for p in (out/'source_snapshot').glob('*')},
        'files_sha256':{p.name:audit.sha(p) for p in out.iterdir() if p.is_file() and p.suffix in ['.csv','.md']}})
    print(str(out/'report.md'))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--final-snapshot',action='store_true');args=parser.parse_args()
    main(args.final_snapshot)
