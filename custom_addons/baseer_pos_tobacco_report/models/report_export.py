"""Typed export projection of the bounded POS tobacco-fee register."""

from odoo import _, api, models
from odoo.exceptions import ValidationError

from odoo.addons.baseer_reports_menu.report_values import (
    export_document, require_active_filters, source_money,
)


class TobaccoReportExport(models.TransientModel):
    _inherit = 'baseer.pos.tobacco.report.wizard'

    @api.model
    def _get_export_document(self, filters):
        allowed = {'period', 'month', 'year', 'date_from', 'date_to', 'show_products', 'page'}
        require_active_filters(self.env, filters, allowed)
        options = {key: filters[key] for key in allowed if key in filters}
        if set(options) != allowed:
            raise ValidationError(_('Invalid report options.'))
        company, values = self._hub_wizard_values({**options, 'company_id': self.env.company.id})
        wizard = self.with_company(company).new(values)
        report = self.env['report.baseer_pos_tobacco_report.report_pos_tobacco_fees'].with_company(
            company,
        )._build_report(wizard)
        columns = [
            {'key': 'date', 'label': report['labels']['date'], 'type': 'text', 'width': 19},
            {'key': 'order', 'label': report['labels']['order'], 'type': 'text', 'width': 19},
        ]
        if report['show_products']:
            columns.append({'key': 'products', 'label': report['labels']['product'],
                            'type': 'text', 'width': 36})
        columns.extend([
            {'key': 'type', 'label': report['labels']['type'], 'type': 'text', 'width': 14},
            {'key': 'debit', 'label': report['labels']['debit'], 'type': 'money', 'width': 17},
            {'key': 'credit', 'label': report['labels']['credit'], 'type': 'money', 'width': 17},
            {'key': 'running', 'label': report['labels']['running'], 'type': 'money', 'width': 18},
        ])
        if report['exceptions']:
            columns.extend([
                {'key': 'computed', 'label': report['labels']['computed_total'], 'type': 'money', 'width': 19},
                {'key': 'saved', 'label': report['labels']['saved_total'], 'type': 'money', 'width': 19},
            ])
        rows = []
        for item in report['rows']:
            cells = {key: item[key] for key in ('date', 'order', 'type')}
            if report['show_products']:
                cells['products'] = item['products']
            for key in ('debit', 'credit', 'running'):
                cells[key] = source_money(item[key])
            rows.append({'cells': cells, 'kind': 'detail'})
        rows.append({'cells': {'type': report['labels']['total'],
                               'debit': source_money(report['debit_total']),
                               'credit': source_money(report['credit_total']),
                               'running': source_money(report['closing'])}, 'kind': 'total'})
        for item in report['exceptions']:
            rows.append({'cells': {'date': item['date'], 'order': item['order'],
                                   'type': report['labels']['mismatch'],
                                   'computed': source_money(item['computed_total']),
                                   'saved': source_money(item['saved_total'])}, 'kind': 'section'})
        return export_document(self.env, report['labels']['title'], columns, rows,
                               metadata=[(report['labels']['from'].rstrip(':： '), report['from_text']),
                                         (report['labels']['to'].rstrip(':： '), report['to_text'])],
                               notes=[report['labels']['mismatch']] if report['exceptions'] else [])
