"""One authorized fixed six-account experiment; refuses a second start."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CASE = Path('D:/QuantResearchEvidence/single_etf_monthly_trend_2018_2025_r1')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def csvsave(path, data, fields=None):
    with Path(path).open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def check_frozen(freeze):
    import platform
    import numpy
    import matplotlib
    versions = {'python':platform.python_version(), 'numpy':numpy.__version__,
                'matplotlib':matplotlib.__version__}
    if versions != freeze['runtime_versions']:
        raise RuntimeError('Frozen runtime dependency versions changed')
    for path, expected in freeze['sources'].items():
        if sha(path) != expected:
            raise RuntimeError('Frozen source or test changed: '+path)
    for name, expected in read(CASE/'inputs/input_sha256.json').items():
        if sha(CASE/'inputs'/name) != expected:
            raise RuntimeError('Frozen input changed: '+name)
    if sha(CASE/'inputs/input_sha256.json') != freeze['input_manifest_sha256']:
        raise RuntimeError('Input manifest changed')
    if sha(CASE/'admission/admission_sha256.json') != freeze['admission_manifest_sha256']:
        raise RuntimeError('Admission manifest changed')
    for relative, expected in read(CASE/'admission/admission_sha256.json').items():
        if sha(CASE/'admission'/relative) != expected:
            raise RuntimeError('Admission evidence changed: '+relative)
    if sha(CASE/'implementation_protocol.json') != freeze['implementation_protocol_sha256']:
        raise RuntimeError('Implementation protocol changed')


def prepare_check(produced, independent):
    if produced['schedule'] != independent['schedule']:
        raise RuntimeError('Independent schedule mismatch')
    for kind in ('daily', 'monthly'):
        if len(produced[kind]) != len(independent[kind]):
            raise RuntimeError('Independent signal length mismatch')
        for a,b in zip(produced[kind], independent[kind]):
            for key in a:
                if a[key] != b[key]:
                    raise RuntimeError(f'Independent {kind} signal mismatch {a["date"]}:{key}')
    return {'status': 'PASS', 'daily_points': len(produced['daily']),
            'monthly_points': len(produced['monthly']), 'execution_dates': len(produced['schedule']),
            'exact_float64_values_and_states_match': True}


def report_text(metrics, gates, verification, elapsed):
    trend = metrics['trend_10bp']
    hold = metrics['hold_10bp']
    passed = all(gates.values())
    lines = ['# 单ETF月度趋势固定六组结果', '',
             '2026-10-20；主人“确认”批准的510330.SH单资产方案。100万元，2017预热，2018—2025评价；无参数搜索、无券商连接。', '',
             '**结论：'+('通过本版历史开发关卡。' if passed else '未通过本版历史开发关卡，本候选结束，不追加调参变体。')+'** 独立信号及逐日账务核验通过，研究关卡与账务核验分别报告。', '',
             '|路径/成本|累计净收益|252年化|最大回撤|夏普|盈利年数|期末权益|',
             '|---|---:|---:|---:|---:|---:|---:|']
    for key, m in metrics.items():
        s = m['sharpe_rf0_ddof1_252']
        s_text = f'{s:.4f}' if s is not None else '不可计算'
        lines.append(f'|{key}|{m["total_return"]:.2%}|{m["annualized_return_252"]:.2%}|{m["max_drawdown"]:.2%}|{s_text}|' + f'{m["positive_years"]}/8|{Decimal(m["final_equity_cny"]):,.2f}|')
    lines += ['', '夏普：零无风险收益、日收益样本标准差ddof=1、sqrt(252)。年化使用1942个评价交易日；年收益从上一年末真实权益连续计算。', '',
              '|主10bp事前门槛|结果|', '|---|---|']
    labels = {'trend10_total_positive': '10bp累计收益>0', 'trend30_total_positive': '30bp累计收益>0',
              'trend10_drawdown_le_25pct': '10bp最大回撤≤25%', 'trend10_at_least_five_positive_years': '10bp至少五个盈利年份',
              'trend10_sharpe_gt_hold10': '10bp夏普严格高于买入持有10bp'}
    for k, v in gates.items():
        lines.append(f'|{labels[k]}|'+('通过' if v else '失败')+'|')
    gap = trend['total_return']-hold['total_return']
    lines += ['', f'主10bp相对同成本持有的累计收益差：{gap*100:+.2f}个百分点。'+('累计收益落后持有，不能称累计超额通过。' if gap < 0 else '该历史差异不等于未来超额保证。'), '',
              '|年份|趋势0bp|趋势10bp|趋势30bp|持有0bp|持有10bp|持有30bp|', '|---|---:|---:|---:|---:|---:|---:|']
    keys = list(metrics)
    for y in map(str, range(2018,2026)):
        lines.append('|'+y+'|'+'|'.join(f'{metrics[k]["annual_returns"][y]:.2%}' for k in keys)+'|')
    lines += ['', '|路径/成本|日均证券暴露|持仓交易日|佣金元|滑点成本元|年化买卖合计换手|成交/尝试|拒单|部分成交|', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for k,m in metrics.items():
        lines.append(f'|{k}|{m["mean_close_market_exposure"]:.2%}|{m["invested_close_days"]}|{Decimal(m["commission_cny"]):,.2f}|{Decimal(m["slippage_cny"]):,.2f}|{m["annualized_buy_plus_sell_turnover"]:.4f}|{m["filled_attempts"]}/{m["order_attempts"]}|{m["rejected_attempts"]}|{m["partial_attempts"]}|')
    lines += ['', '换手按每日买卖实际成交额合计/当日收盘权益，再以252/交易日数年化；未除以2。滑点已体现在成交价内，表中仅披露，不再从现金重复扣。0bp费用与滑点关闭；10/30bp佣金为max(5元,成交额×0.0003)按分half-up，全包研究假设。未按股票征印花/过户费；未对基金净值重复扣管理费。', '',
              '信号的现金总收益指数仅用于月度判断。真实账户登记日收盘锁权益、除息日才计应收、付款日按模型日初转现金；红利不自动再投资。只在状态变化时设固定份额意图，部分成交每日重试，反转取消。无月度反复等权、无期末强平。', '',
              '独立核验从原价、八项官方现金行动、日历和订单分别重建信号及现金/持仓/可卖/应收/成本，不调用生产模拟器生成期望。六账户共42处跨年边界，逐日数量及货币余额核对；详细结果在independent_verification.json。', '',
              '数据准入是有明确假设的历史开发准入。八份官方现金原件及16页已核，16条重复投影映射成8次真实事件。涨跌停采用历史普通10%规则与回校原前收推导；供应商etf_limit旧段1723字段精度冲突，已拒绝作为精确边界输入。前收先按0.001显示精度回校是表示约定，并非额外认证的逐字舍入条款；2018无原边界接口覆盖，不能声称恢复了每日交易所原价界。', '',
              '局限：当前官方原件不是首次历史版本链认证；普通指定交易、非专用席位及付款日日初到账为模型条件；没有完整逐日交易所例外/盘中停牌状态源，普通有效开盘可交易是研究假设。2020规则使用修订通知与前后版本连续性，未取得该版完整原文。本例无观察到的未知份额行动，但不声称认证了全世界所有潜在事件。全部为已知历史开发结果，不能重新贴未见样本外标签；无实盘资格。', '',
              '保留的真实失败：早期证据JSONL换行解析曾修复一次，已保留首败；可选pre_close全空的诊断比较曾失败，后续只比较实际返回字段，未填补原缓存。工程修复预算已消费，实际六组阶段没有重跑或改冻结输入。', '',
              f'本轮六账户及独立核验耗时（截至报告生成前，含等待）：{elapsed:.1f}秒；独立核验账户数{verification["cases"]}，跨年边界{verification["cross_year_boundaries"]}。报告写入及末次冻结核对另计入runtime/completed.json，最后封存及总阶段时间见目录外delivery_receipt。准入保守累计上界3771.74秒，未超过2小时。', '',
              '研究目录：`D:/QuantResearchEvidence/single_etf_monthly_trend_2018_2025_r1`。inputs、admission、freeze、preparation、accounts、independent_verification.json、metrics.json、gates.json及output_sha256.json分别保存输入、证据、源码/测试指纹、形成信息、六账本、核验、结果及完整封存。']
    return '\n'.join(lines)+'\n'


def make_plot():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from datetime import datetime as dt
    fig, axes = plt.subplots(2,1,figsize=(10,6),sharex=True,
                             gridspec_kw={'height_ratios':[2,1]})
    for key, label in [('trend_10bp','Monthly trend, 10bp'),('hold_10bp','Buy and hold, 10bp')]:
        nav = rows(CASE/'accounts'/key/'nav.csv')
        dates = [dt.strptime(r['date'],'%Y%m%d') for r in nav]
        values = np.array([float(r['equity']) for r in nav])
        axes[0].plot(dates,values/values[0],label=label)
        axes[1].plot(dates,(values/np.maximum.accumulate(values)-1)*100)
    axes[0].set_ylabel('Actual equity / initial equity')
    axes[1].set_ylabel('Drawdown (%)')
    axes[0].set_title('510330.SH | Historical development | 2018-2025')
    axes[0].legend()
    for ax in axes:
        ax.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(CASE/'equity_drawdown.png',dpi=160)
    plt.close(fig)


def main():
    freeze = read(CASE/'freeze/freeze.json')
    check_frozen(freeze)
    if read(CASE/'admission/admission_decision.json')['status'] != 'ADMITTED_CONDITIONAL_HISTORICAL_DEVELOPMENT_ONLY':
        raise RuntimeError('Admission has not passed')
    if freeze['test_status'] != 'PASS':
        raise RuntimeError('Tests not passed')
    # Atomic creation denies every second process, even after a failed first run.
    lock_path = CASE/'runtime/accounts.lock'
    with lock_path.open('x+b') as lock:
        lock.write(b'1'); lock.flush(); lock.seek(0)
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        started = datetime.now(timezone.utc)
        save(CASE/'runtime/run_started.json', {'started_utc': started.isoformat(), 'pid': os.getpid(), 'case_count':6, 'freeze_sha256': sha(CASE/'freeze/freeze.json'), 'second_start_forbidden':True})
        try:
            from quant_research.etf_trend_signal import prepare_signals, performance
            from quant_research.etf_single_account import simulate
            from quant_research.etf_independent_audit import independently_prepare, audit_case
            bars = rows(CASE/'inputs/bars.csv')
            actions = rows(CASE/'inputs/actions.csv')
            limits = rows(CASE/'inputs/limits.csv')
            prepared = prepare_signals(bars,actions)
            rebuilt = independently_prepare(bars,actions)
            prep_check = prepare_check(prepared,rebuilt)
            if prep_check['daily_points'] != 2186 or prep_check['monthly_points'] != 108:
                raise RuntimeError('Fixed preparation coverage mismatch')
            p = CASE/'preparation'; p.mkdir(exist_ok=False)
            save(p/'independent_preparation_check.json', prep_check)
            save(p/'signals.json',prepared)
            csvsave(p/'daily.csv',prepared['daily'])
            csvsave(p/'monthly.csv',prepared['monthly'])
            schedule = prepared['schedule']
            eval_first = next(b['trade_date'] for b in bars if b['trade_date'] >= '20180101')
            if eval_first not in schedule:
                raise RuntimeError('Missing initial month state')
            metrics, audits = {}, {}
            ac = CASE/'accounts'; ac.mkdir(exist_ok=False)
            for path in ('trend','hold'):
                for bps in (0,10,30):
                    check_frozen(freeze)
                    key = f'{path}_{bps}bp'
                    dest = ac/key; dest.mkdir(exist_ok=False)
                    path_schedule = schedule if path=='trend' else {eval_first:1}
                    save(dest/'started.json',{'at_utc':now(),'path':path,'slippage_bps':bps})
                    result = simulate(bars,actions,limits,path_schedule,bps)
                    save(dest/'result.json',result)
                    for name in ('nav','orders','events'):
                        if result[name]:
                            csvsave(dest/(name+'.csv'),result[name])
                        else:
                            save(dest/(name+'_empty.json'),[])
                    audit = audit_case(bars,actions,limits,path_schedule,bps,result)
                    save(dest/'independent_audit.json',audit)
                    if audit.get('status') != 'PASS':
                        raise RuntimeError('Independent audit failed: '+key)
                    if len(audit['year_boundaries']) != 7:
                        raise RuntimeError('Independent cross-year coverage mismatch: '+key)
                    if len(result['nav']) != 1943:
                        raise RuntimeError('Fixed account coverage mismatch')
                    audits[key] = audit
                    metrics[key] = performance(result['nav'],result['orders'])
                    save(dest/'metrics.json',metrics[key])
                    print(json.dumps({'case':key,'status':'account_and_independent_audit_passed'}),flush=True)
            t,h = metrics['trend_10bp'],metrics['hold_10bp']
            ts,hs = t['sharpe_rf0_ddof1_252'],h['sharpe_rf0_ddof1_252']
            gates = {'trend10_total_positive':t['total_return']>0,
                     'trend30_total_positive':metrics['trend_30bp']['total_return']>0,
                     'trend10_drawdown_le_25pct':t['max_drawdown']<=.25,
                     'trend10_at_least_five_positive_years':t['positive_years']>=5,
                     'trend10_sharpe_gt_hold10':ts is not None and hs is not None and ts>hs}
            verification = {'status':'PASS','signal_check':prep_check,'cases':6,'cross_year_boundaries':42,'audits':audits}
            elapsed = (datetime.now(timezone.utc)-started).total_seconds()
            if elapsed > 21600:
                raise RuntimeError('Six-account/report stage budget exceeded')
            save(CASE/'independent_verification.json',verification)
            save(CASE/'metrics.json',metrics)
            save(CASE/'gates.json',{'status':'PASS_CONDITIONAL_DEVELOPMENT' if all(gates.values()) else 'FAIL_RESEARCH_GATES','gates':gates,'no_candidate_retries':True,'broker_connected':False})
            make_plot()
            report = report_text(metrics,gates,verification,elapsed)
            with (CASE/'report.md').open('x',encoding='utf-8') as stream:
                stream.write(report)
            with (ROOT/'docs/2026-10-20-single-etf-monthly-trend-results.md').open('x',encoding='utf-8') as stream:
                stream.write(report)
            check_frozen(freeze)
            elapsed_through_report = (datetime.now(timezone.utc)-started).total_seconds()
            if elapsed_through_report > 21600:
                raise RuntimeError('Account/report stage budget exceeded at completion')
            save(CASE/'runtime/completed.json',{'started_utc':started.isoformat(),'at_utc':now(),'cases':6,'cross_year_boundaries':42,'accounts_ledger_passed':True,'research_gates_passed':all(gates.values()),'wall_seconds_through_report':elapsed_through_report,'final_seal_administration_in_external_delivery_receipt':True,'second_start_forbidden':True})
        except BaseException as exc:
            save(CASE/'runtime/first_failure.json', {'at_utc':now(),'type':type(exc).__name__,'message':str(exc),'engineering_repairs_remaining':0,'retry_forbidden':True})
            raise
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
    save(CASE/'output_sha256.json',{p.relative_to(CASE).as_posix():sha(p) for p in sorted(CASE.rglob('*')) if p.is_file()})
    print(json.dumps({'completed':True,'cases':6,'research_passed':all(gates.values()),'output_manifest_sha256':sha(CASE/'output_sha256.json')}))


if __name__ == '__main__':
    main()
