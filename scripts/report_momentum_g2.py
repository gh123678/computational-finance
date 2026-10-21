"""Predeclared product and economic gates; never select a replacement rule."""
import math

import pandas as pd

from momentum_g2_runtime import OUT, META, BASELINE, read_json, read_table, persist, write_table, verify_manifest, verify_frozen, check_g3_budget


def truth(value):
    return value is True or str(value).lower() == 'true'


def performance(nav, orders):
    frame = nav.copy()
    if frame.empty or not {'date', 'equity'}.issubset(frame):
        return None
    frame['date'] = pd.to_datetime(frame.date)
    frame = frame.sort_values('date')
    if frame.date.duplicated().any() or frame.date.iloc[0] != pd.Timestamp(BASELINE):
        raise ValueError('Performance requires one real initial baseline')
    equity = frame.set_index('date').equity.astype(float)
    if not all(math.isfinite(x) and x > 0 for x in equity):
        raise ValueError('Nonpositive/invalid equity')
    evaluation = frame.loc[frame.date.gt(pd.Timestamp(BASELINE))]
    count = len(evaluation)
    annual, prior = {}, equity.iloc[0]
    for year in (2018, 2019, 2020):
        values = equity.loc[equity.index.year == year]
        if values.empty:
            annual[str(year)] = None
        else:
            annual[str(year)] = float(values.iloc[-1] / prior - 1)
            prior = values.iloc[-1]
    fees = float(pd.to_numeric(orders.get('fee', pd.Series(dtype=float))).sum())
    turnover = (float(pd.to_numeric(evaluation.one_way_turnover).sum()) * 252 / count
                if count and 'one_way_turnover' in evaluation else None)
    return dict(total_return=float(equity.iloc[-1] / equity.iloc[0] - 1),
        max_drawdown=float((1 - equity / equity.cummax()).max()), annual_returns=annual,
        evaluation_sessions=count, first_date=str(frame.date.iloc[0].date()),
        last_date=str(frame.date.iloc[-1].date()), final_equity=float(equity.iloc[-1]),
        fees=fees, annualized_one_way_turnover=turnover,
        slippage_cost=float(pd.to_numeric(evaluation.get('slippage_cost', pd.Series(dtype=float))).sum()),
        max_stale_value=float(pd.to_numeric(evaluation.get('stale_value', pd.Series([0.]))).max()),
        positive_years=sum(v is not None and v > 0 for v in annual.values()))


def execution_gate(deployment, episodes):
    if len(deployment) != 1 or 'unconditional_completion' not in deployment:
        return dict(passed=False, reason='missing_or_duplicate_initial_deployment')
    completion = float(deployment.iloc[0].unconditional_completion)
    initial = math.isfinite(completion) and completion >= .95
    if episodes.empty:
        return dict(passed=False, initial_passed=initial, initial_completion=completion,
                    exits_covered=False, reason='no_real_exit_episode')
    required = {'complete_five_session_window', 'first_intent_completion', 'securities_risk_closed'}
    if not required.issubset(episodes):
        return dict(passed=False, initial_passed=initial, initial_completion=completion,
                    reason='missing_exit_evidence')
    exits = (episodes.complete_five_session_window.map(truth) &
             pd.to_numeric(episodes.first_intent_completion).ge(.95) &
             episodes.securities_risk_closed.map(truth))
    return dict(passed=bool(initial and exits.all()), initial_passed=initial,
                initial_completion=completion, exits_covered=True, exit_episodes=len(episodes),
                exits_passed=int(exits.sum()), exits_not_passed=int((~exits).sum()),
                reason='' if initial and exits.all() else 'fixed_deployment_or_exit_gate_not_met')


def economic_gates(metrics):
    main10, main30, control = (metrics[k] for k in ('momentum_10bp', 'momentum_30bp', 'control_10bp'))
    if any(x is None for x in (main10, main30, control)):
        raise ValueError('Cannot judge economic gates without complete comparable accounts')
    return dict(main10_positive=main10['total_return'] > 0,
                main30_positive=main30['total_return'] > 0,
                main10_above_fixed_control10=main10['total_return'] > control['total_return'],
                main10_drawdown_le25=main10['max_drawdown'] <= .25,
                main10_at_least_two_positive_years=main10['positive_years'] >= 2)


def execution_breakdown(intents, events, path):
    """Reference-value completion, keeping each original request/side separate."""
    if intents.empty:
        return pd.DataFrame()
    lookup = {}
    for row in events.loc[events.path.eq(path)].to_dict('records') if not events.empty else []:
        date = pd.Timestamp(row['signal_date'])
        lookup[(date, row['code'])] = row['kind']
        if row['kind'] == 'active_replace':
            lookup[(date, row['other_code'])] = 'active_replace'
    rows = intents.copy()
    rows['category'] = [lookup.get((pd.Timestamp(r.formation_date), r.ts_code),
                                   'full_exit' if truth(r.full_exit) else r.role)
                        for r in rows.itertuples()]
    rows['requested_reference_cny'] = rows.requested_formation_shares * rows.formation_close
    rows['filled_reference_cny'] = rows[['filled_formation_equivalent', 'requested_formation_shares']].min(axis=1) * rows.formation_close
    answer = []
    for (category, side), group in rows.groupby(['category', 'side']):
        requested, filled = group.requested_reference_cny.sum(), group.filled_reference_cny.sum()
        answer.append(dict(category=category, side=side, intents=len(group),
            requested_reference_cny=requested, filled_reference_cny=filled,
            completion=filled / requested if requested else None,
            refused=int((group.requested_formation_shares.gt(0) & group.filled_formation_equivalent.eq(0) & group.status.eq('expired')).sum()),
            not_attempted=int(group.status.eq('formed').sum()),
            partial=int((group.filled_formation_equivalent.gt(0) & group.filled_formation_equivalent.lt(group.requested_formation_shares)).sum()),
            expired=int(group.status.eq('expired').sum())))
    return pd.DataFrame(answer)


def industry_exposure(holdings, history):
    """Daily interval mapping; ambiguity remains explicit, never forward-filled."""
    columns = ['date', 'industry', 'value', 'weight', 'ambiguous_or_missing']
    if holdings.empty:
        return pd.DataFrame(columns=columns)
    history = history.copy()
    for col in ('in_date', 'out_date'):
        history[col] = pd.to_datetime(history[col], errors='coerce')
    groups = {code: group for code, group in history.groupby('ts_code')}
    rows = []
    for row in holdings.itertuples():
        date = pd.Timestamp(row.date)
        group = groups.get(row.ts_code)
        sectors = [] if group is None else group.loc[group.in_date.le(date) &
            (group.out_date.isna() | group.out_date.gt(date)), 'l1_code'].dropna().unique().tolist()
        known = len(sectors) == 1 and str(sectors[0]).strip() != ''
        rows.append(dict(date=date, industry=sectors[0] if known else 'UNKNOWN_OR_AMBIGUOUS',
                         value=row.value, weight=row.weight, ambiguous_or_missing=not known))
    return pd.DataFrame(rows).groupby(['date', 'industry', 'ambiguous_or_missing'], as_index=False)[['value', 'weight']].sum()[columns]


def report():
    if (OUT / 'summary.json').exists():
        raise RuntimeError('Report already written; no overwrite')
    verify_frozen()
    budget_reason = None
    if (OUT / 'runtime/G3_phase_start.json').exists():
        try:
            check_g3_budget()
        except RuntimeError as exc:
            budget_reason = str(exc)
    verify_manifest(OUT / 'preparation_manifest.json')
    prep = read_json(OUT / 'preparation/summary.json')
    prep_audit = read_json(OUT / 'preparation_audit.json') if (OUT / 'preparation_audit.json').exists() else None
    if prep_audit:
        verify_manifest(OUT / 'preparation_audit_manifest.json')
    preparation_passed = prep['preparation_passed'] and bool(prep_audit and prep_audit.get('accounts_allowed'))
    account_file = OUT / 'accounts_status.json'
    stopping = read_json(OUT / 'runtime/research_stop.json') if (OUT / 'runtime/research_stop.json').exists() else None
    if preparation_passed and not account_file.exists() and not stopping and not budget_reason:
        raise RuntimeError('Authorized fixed accounts have not run; report cannot end successful preparation early')
    states = read_json(account_file) if account_file.exists() else []
    expected_keys = [f'{p}_{b}bp' for p in ('momentum', 'control') for b in (0, 10, 30)]
    if states and [s['account'] for s in states] != expected_keys:
        raise RuntimeError('Fixed six account identity/order changed')
    metrics, products, annual, sectors = {}, {}, [], {}
    diagnostics = OUT / 'diagnostics'
    events = read_table(OUT / 'preparation/selection_events.csv', missing_ok=not preparation_passed)
    history = pd.read_csv(META / 'industry_history.csv', dtype=str) if states else None
    if states:
        verify_manifest(OUT / 'accounts_manifest.json')
    for state in states:
        if state['status'] == 'not_started':
            continue
        key = state['account']
        folder = OUT / 'accounts' / key
        partial = state['status'] != 'complete'
        metrics[key] = performance(read_table(folder / 'nav.csv', missing_ok=partial),
                                   read_table(folder / 'orders.csv', missing_ok=partial))
        products[key] = execution_gate(read_table(folder / 'deployment.csv', missing_ok=partial),
                                       read_table(folder / 'exit_episodes.csv', missing_ok=partial))
        breakdown = execution_breakdown(read_table(folder / 'intents.csv', missing_ok=partial), events,
                                        key.rsplit('_', 1)[0])
        write_table(diagnostics / (key + '_execution.csv'), breakdown)
        exposure = industry_exposure(read_table(folder / 'holdings.csv', missing_ok=partial), history)
        write_table(diagnostics / (key + '_industry.csv'), exposure)
        sectors[key] = exposure
        if metrics[key]:
            annual.extend(dict(account=key, year=y, net_return=v, account_complete=not partial,
                               last_observed_date=metrics[key]['last_date'])
                          for y, v in metrics[key]['annual_returns'].items())
    audits = read_json(OUT / 'accounts_audit.json') if (OUT / 'accounts_audit.json').exists() else {}
    if audits:
        verify_manifest(OUT / 'accounts_audit_manifest.json')
    all_complete = len(states) == 6 and all(x['status'] == 'complete' for x in states)
    audited = all_complete and set(audits) == set(expected_keys) and all(x.get('passed', False) for x in audits.values())
    if all_complete:
        gap = sectors['momentum_10bp'].pivot(index='date', columns='industry', values='weight').fillna(0).subtract(
              sectors['control_10bp'].pivot(index='date', columns='industry', values='weight').fillna(0), fill_value=0)
        write_table(diagnostics / 'momentum_minus_control_10bp_industry.csv', gap.reset_index().melt(id_vars='date', value_name='weight_difference'))
    product_keys = ('momentum_10bp', 'momentum_30bp', 'control_10bp', 'control_30bp')
    product_passed = audited and all(products[k]['passed'] for k in product_keys)
    economics = economic_gates(metrics) if audited else None
    passed = bool(preparation_passed and audited and product_passed and all(economics.values()))
    if not prep['preparation_passed']:
        outcome, reason = 'DATA_PREPARATION_STOP', prep.get('reason')
    elif not preparation_passed:
        outcome, reason = 'INDEPENDENT_PREPARATION_NOT_PASSED', 'Raw reconstruction did not admit accounts'
    elif not all_complete:
        outcome, reason = 'PARTIAL_ACCOUNT_DATA_OR_ACCOUNTING_STOP', 'Fixed cohort incomplete; no full profitability verdict'
    elif not audited:
        outcome, reason = 'ACCOUNT_AUDIT_NOT_PASSED', 'Independent ledger reconstruction not passed'
    elif not product_passed:
        outcome, reason = 'PRODUCT_OR_EXECUTION_NOT_PASSED', 'Fixed denominators/exits not fully verified'
    elif not all(economics.values()):
        outcome, reason = 'RESEARCH_GATES_FAILED', 'One or more preregistered economic conditions failed'
    else:
        outcome, reason = 'CONDITIONAL_HISTORICAL_GATES_PASSED', 'Forward and real executable-price evidence still required'
    if (OUT / 'runtime/G3_phase_start.json').exists():
        try:
            check_g3_budget()
        except RuntimeError as exc:
            budget_reason = str(exc)
    if budget_reason:
        outcome, reason, passed = 'BUDGET_STOP', budget_reason, False
    elif stopping:
        outcome, reason, passed = 'RECORDED_RESEARCH_STOP', stopping, False
    summary = dict(status=outcome, reason=reason, passed=passed,
        preparation=prep, preparation_audit=prep_audit, accounts=states,
        all_six_accounts_complete=all_complete, all_six_independently_audited=audited,
        metrics=metrics, product_gates=products, economic_gates=economics,
        full_historical_PIT_certified=False, real_broker_fills_certified=False,
        forward_T0=None, broker=False, strategy_deployment_authorized=False,
        full_portfolio_exit_not_synthesized=True, additional_seventh_account=False)
    verify_frozen()
    persist(OUT / 'summary.json', summary)
    write_table(OUT / 'annual_returns.csv', pd.DataFrame(annual,
        columns=['account', 'year', 'net_return', 'account_complete', 'last_observed_date']))
    lines = ['# 中期股票动量G2固定实验结果', '', '**终态：' + outcome + '**。', '',
        '本次只检验批准的252间隔／跳21动量、固定哈希留仓对照及单次计划委托。没有调参、扩年份、换基准或连接券商。', '',
        '准备：' + prep['status'] + '；账户实际尝试' + str(sum(x['status'] != 'not_started' for x in states)) + '组。', '']
    if reason:
        lines.extend(['原因：' + str(reason), ''])
    if metrics:
        lines.extend(['|账户|终态|累计净收益|最大回撤|费用元|滑点价差元|年化单边换手|', '|---|---|---:|---:|---:|---:|---:|'])
        for state in states:
            key = state['account']; m = metrics.get(key)
            if m:
                turn = '' if m['annualized_one_way_turnover'] is None else f"{m['annualized_one_way_turnover']:.6f}"
                lines.append(f"|{key}|{state['status']}|{m['total_return']:.6%}|{m['max_drawdown']:.6%}|{m['fees']:.2f}|{m['slippage_cost']:.2f}|{turn}|")
        lines.append('')
    lines.extend(['完整判定及部署／退出分母见summary.json，逐年见annual_returns.csv，逐日账、意图、应收和首败见对应子目录。执行分项完成率、逐日行业暴露及主／对照行业偏离见diagnostics；部分账户年度数仅截至last_observed_date，不冒充完整年度。', '',
        '未完成六账户或独立核验时，不签发完整收益关卡通过；准备失败无新账户收益。产品失败和经济收益失败分别记录。', '',
        '资料是假设明确的历史开发：2016—2025已使用，历史ST／行业首次版本、实际托管与税制并未全面认证；毛权益信号按除息日理论再投、待上市股按同股标记，真实账户到账与可卖分开。', '',
        '每日停复牌按供应商字段解释：当日S空日内区间为全天，日内仅覆盖开盘时段才否定开盘；不把一个每日记录延伸到以后所有日期。字段依据：[Tushare每日停复牌](https://tushare.pro/document/2?doc_id=214)，当前文档不认证历史公告时点。', '',
        '日线开盘与研究滑点不是人工实盘成交证据。即使条件性历史门通过，也须合格版本冻结后新发生的前向记录及执行评审；本次不设虚构T0、不启用实盘。'])
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary
