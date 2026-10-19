"""r5 source-version guard layered on the frozen r4 exposure boundaries."""
import json

import pandas as pd

from alphaforge_r4_guard import (
    ExposureGuard as R4ExposureGuard, AccountDataFailure, _serial,
    share_price_scope, obligation_scope, prune_prices,
)
from alphaforge_r5_events import distribution_view, rights_stage


class ExposureGuard(R4ExposureGuard):
    """Keep r4 quote/state checks; apply corrections even when quotes exist."""

    def require_rights_stage(self, issue, date, ledger, stage):
        view = rights_stage(issue, date, self.evidence, stage=stage)
        if not view.get('stage_usable', False):
            row = self.row(issue.code, date, 'rights_' + stage, ledger)
            row.update(event_sources=json.dumps(view.get('sources', []), default=str),
                       stage_reason=view.get('reason'),
                       terms_known_date=view.get('terms_known_date'),
                       result_known_date=view.get('result_known_date'),
                       listing_known_date=view.get('listing_known_date'))
            self.stop(row, 'rights_' + stage + '_source_not_usable_asof')
        return view

    def _special_interval(self, code, date, row, left=None):
        if left is None:
            left, _ = self.previous(code, date)
        for action in self.actions[code]:
            view = distribution_view(action, date, self.evidence)
            stages = (action.record, action.ex, action.stock_pay)
            crossed = [d for d in stages if pd.notna(d) and
                       (d == date or (pd.notna(left) and left < d <= date))]
            if crossed and not view.get('stage_usable', True):
                self.stop(row, 'distribution_source_not_usable_preopen')
            if not view.get('unsupported_special', False):
                continue
            if crossed:
                row.update(event_version=view.get('version'),
                           event_role=view.get('role'),
                           event_known_date=view.get('known_date'),
                           event_sources=json.dumps(view.get('sources', []), default=str),
                           unsupported_stages=json.dumps(sorted({str(d.date()) for d in crossed})))
                self.stop(row, 'unsupported_special_reorganization_exposure_or_plan')

    def _bridge(self, code, date, row, require_quote=False):
        self._special_interval(code, date, row)
        return super()._bridge(code, date, row, require_quote=require_quote)

    def _interval(self, code, left, date, gap, row, quote_present):
        ordinary, rights = [], []
        for action in self.actions[code]:
            view = distribution_view(action, date, self.evidence)
            if not view.get('apply_distribution', True):
                continue
            if any(pd.notna(d) and left < d <= date for d in
                   (action.record, action.ex, action.cash_pay, action.stock_pay)):
                ordinary.append(action)
        for issue in self.rights[code]:
            stage = rights_stage(issue, date, self.evidence, stage='listing')
            listed = stage.get('list_date')
            listed = pd.NaT if listed is None else pd.Timestamp(listed)
            if any(pd.notna(d) and left < d <= date for d in (issue.record, issue.ex, listed)):
                rights.append(issue)
        row['interval_actions'] = json.dumps([_serial(a) for a in ordinary] + [
            dict(code=r.code, record=str(r.record.date()), ex=str(r.ex.date()),
                 **{k: v for k, v in rights_stage(r, date, self.evidence, stage='listing').items()
                    if k not in ('code', 'record', 'ex')}) for r in rights], default=str)
        if gap:
            for action in ordinary:
                self._ordinary_allowed(action, date, row)
            for issue in rights:
                stage = rights_stage(issue, date, self.evidence, stage='listing')
                listed = stage.get('list_date')
                listed = pd.NaT if listed is None else pd.Timestamp(listed)
                quoted_ex = quote_present and issue.ex == date and issue.record <= left
                known_listing_release = (issue.price is not None and
                    stage.get('quota_ratio') is not None and pd.notna(listed) and
                    stage.get('stage_usable', False) and issue.ex <= left and
                    not any(left < d <= date for d in (issue.record, issue.ex)))
                if not (quoted_ex or known_listing_release):
                    self.stop(row, 'rights_obligation_across_unquoted_equity_date')
        return ordinary, rights

    def check_day(self, code, date, ledger, *, planned_signal=None, rights_entitlements=()):
        if (code in share_price_scope(ledger, (), rights_entitlements) or
                code in obligation_scope(ledger, rights_entitlements) or planned_signal is not None):
            role = ('planned' if planned_signal is not None else
                    'price' if code in share_price_scope(ledger, (), rights_entitlements)
                    else 'cash_obligation')
            self._special_interval(code, date, self.row(code, date, role, ledger))
        return super().check_day(code, date, ledger, planned_signal=planned_signal,
                                 rights_entitlements=rights_entitlements)
