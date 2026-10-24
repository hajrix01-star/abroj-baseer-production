"""Fixed read-only dispatch; each provider revalidates its exact source scope."""

import json
from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError

PROVIDERS = {
    'activity': 'baseer.account.activity',
    'general_ledger': 'baseer.general.ledger.report',
    'trial_balance': 'baseer.trial.balance.report',
    'balance_sheet': 'baseer.balance.sheet.report',
    'profit_loss': 'baseer.profit.loss.report',
    'aged_receivable': 'baseer.aged.receivable.report',
    'aged_payable': 'baseer.aged.payable.report',
    'vat': 'baseer.tax.report.wizard',
    'tobacco': 'baseer.pos.tobacco.report.wizard',
}


class BaseerReportDrill(models.AbstractModel):
    _name = 'baseer.report.drill'
    _description = 'Baseer guarded report details'

    def _provider(self, report_key, filters, selector):
        if type(report_key) is not str or report_key not in PROVIDERS:
            raise ValidationError(_('Select a supported report.'))
        if type(filters) is not dict or type(selector) is not dict:
            raise ValidationError(_('Select valid report details.'))
        try:
            size = len(json.dumps([filters, selector]).encode('utf-8'))
        except (TypeError, ValueError, RecursionError) as error:
            raise ValidationError(_('Select valid report details.')) from error
        if size > 16384:
            raise ValidationError(_('Select valid report details.'))
        if type(filters.get('company_id')) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Select the active company report.'))
        self.env.company.check_access('read')
        if PROVIDERS[report_key] not in self.env:
            raise ValidationError(_('This report is not installed.'))
        return self.env[PROVIDERS[report_key]]

    @api.model
    def get_drilldown(self, report_key, filters, selector, page=1):
        if type(page) is not int or not 1 <= page <= 100:
            raise ValidationError(_('Select a valid detail page.'))
        provider = self._provider(report_key, filters, selector)
        method = getattr(provider, '_get_drilldown', None)
        if not callable(method):
            raise ValidationError(_('This report detail is not available.'))
        return method(filters, selector, page)

    @api.model
    def open_source(self, report_key, filters, selector):
        provider = self._provider(report_key, filters, selector)
        method = getattr(provider, '_open_drill_source', None)
        if not callable(method):
            raise ValidationError(_('This report source is not available.'))
        return method(filters, selector)
