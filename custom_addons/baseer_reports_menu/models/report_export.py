"""Private, fixed-provider transport for Baseer-owned report documents."""

from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError

from ..report_document import _font_styles, render_html, render_xlsx, validate_document


# Fixed converter-only page numbering. No document text or URLs are interpolated.
_PAGE_FOOTER = '''<!doctype html><html><head><meta charset="utf-8"/>
<style>__BASEER_FIXED_FONT_STYLES__body{font-family:'IBM Plex Sans Arabic',sans-serif;font-size:9pt;color:#53657a;text-align:center;}</style>
<script>function pages(){var p={};location.search.substring(1).split('&').forEach(function(x){var a=x.split('=');p[a[0]]=a[1];});['page','topage'].forEach(function(k){var v=p[k]||'';document.getElementById(k).textContent=/^[0-9]+$/.test(v)?v:'';});}</script>
</head><body onload="pages()"><span id="page"></span> / <span id="topage"></span></body></html>'''


class BaseerReportExport(models.AbstractModel):
    _name = 'baseer.report.export'
    _description = 'Baseer private report export engine'

    @api.model
    def _document(self, report_key, filters):
        # Fixed code registry: never accept a client-supplied model or method.
        providers = {
            'operations_gross': 'baseer.operations.report',
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
        if type(report_key) is not str or report_key not in providers:
            raise ValidationError(_('This report does not support unified export yet.'))
        if type(filters) is not dict or type(filters.get('company_id')) is not int:
            raise ValidationError(_('Select valid report filters.'))
        if filters['company_id'] != self.env.company.id:
            raise AccessError(_('Export the report for the active company only.'))
        model_name = providers[report_key]
        if model_name not in self.env:
            raise ValidationError(_('This report is not installed.'))
        collector = getattr(self.env[model_name], '_get_export_document', None)
        if not callable(collector):
            raise ValidationError(_('This report does not support unified export yet.'))
        document = collector(filters)
        validate_document(document)
        return document

    @api.model
    def _export(self, report_key, filters, file_format):
        if file_format not in ('xlsx', 'pdf'):
            raise ValidationError(_('Choose Excel or PDF.'))
        document = self._document(report_key, filters)
        try:
            if file_format == 'xlsx':
                data = render_xlsx(document)
                mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            else:
                body = render_html(document)
                # Only the installed low-level converter is reused. Baseer owns
                # document/schema/layout; no account.report or report_action.
                paper = self.env['report.paperformat'].new({
                    'name': 'Baseer unified A4', 'format': 'A4',
                    'orientation': 'Landscape' if len(document['columns']) > 4 else 'Portrait',
                    'margin_top': 12, 'margin_bottom': 16, 'margin_left': 12, 'margin_right': 12,
                    'header_line': False, 'header_spacing': 0, 'dpi': 96,
                    'disable_shrinking': True,
                })
                renderer = self.env['ir.actions.report'].new({'paperformat_id': paper})
                data = renderer._run_wkhtmltopdf(
                    [body], landscape=len(document['columns']) > 4,
                    footer=_PAGE_FOOTER.replace('__BASEER_FIXED_FONT_STYLES__', _font_styles()),
                    specific_paperformat_args={
                        'data-report-margin-top': 12,
                        'data-report-margin-bottom': 16,
                        'data-report-dpi': 96,
                    },
                )
                mimetype = 'application/pdf'
        except (ValueError, TypeError, OSError) as error:
            raise ValidationError(_('The report cannot be exported safely. Check its size and numeric precision.')) from error
        if len(data) > 10 * 1024 * 1024:
            raise ValidationError(_('The export is too large. Select a shorter period.'))
        return data, mimetype, f'{document["title"]}.{file_format}'
