"""Fixed dashboard-only download route and typed export provider."""
import json
import re

from odoo import _, api, http, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import content_disposition, request

from odoo.addons.baseer_reports_menu.report_document import validate_document


_REVISION = re.compile(r'^[a-f0-9]{64}$', re.ASCII)
_EXPORT_REVISIONS = '_financial_dashboard_export_revisions'


def validate_revisions(revisions):
    if type(revisions) is not list or not 1 <= len(revisions) <= 4:
        raise ValidationError(_('Refresh the dashboard before exporting.'))
    result = []
    for item in revisions:
        if (type(item) is not dict or set(item) != {'key', 'revision'}
                or type(item['key']) is not str or not 1 <= len(item['key']) <= 64
                or type(item['revision']) is not str or not _REVISION.fullmatch(item['revision'])):
            raise ValidationError(_('Refresh the dashboard before exporting.'))
        result.append((item['key'], item['revision']))
    if len({key for key, _revision in result}) != len(result):
        raise ValidationError(_('Refresh the dashboard before exporting.'))
    return result


def assert_snapshot_revisions(snapshot, revisions):
    expected = validate_revisions(revisions)
    periods = snapshot.get('periods') if type(snapshot) is dict else None
    if (type(snapshot) is not dict or snapshot.get('complete') is not True
            or not isinstance(periods, list) or any(type(period) is not dict for period in periods)
            or [(period.get('key'), period.get('revision')) for period in periods] != expected):
        raise AccessError(_('The dashboard changed. Refresh it before exporting.'))


class FinancialDashboardExportRevision(models.AbstractModel):
    _inherit = 'baseer.financial.dashboard.operations'

    @api.model
    def get_owner_snapshot(self, filters):
        snapshot = super().get_owner_snapshot(filters)
        expected = self.env.context.get(_EXPORT_REVISIONS)
        if expected is not None:
            assert_snapshot_revisions(snapshot, expected)
        return snapshot


class FinancialDashboardExport(models.AbstractModel):
    _name = 'baseer.financial.dashboard.export'
    _inherit = 'baseer.report.export'
    _description = 'Financial Dashboard Private Export'

    @api.model
    def _document(self, report_key, filters):
        # Never accept a caller-supplied provider or fall back to the billing
        # report registry: the dashboard must export its own verified snapshot.
        if report_key != 'financial_dashboard_operations':
            raise ValidationError(_('This report does not support unified export yet.'))
        if type(filters) is not dict or type(filters.get('company_id')) is not int:
            raise ValidationError(_('Select valid report filters.'))
        if filters['company_id'] != self.env.company.id:
            raise AccessError(_('Export the report for the active company only.'))
        revisions = self.env.context.get(_EXPORT_REVISIONS)
        validate_revisions(revisions)
        document = self.env['baseer.financial.dashboard.operations'].with_context(
            **{_EXPORT_REVISIONS: revisions}
        )._get_export_document(filters)
        validate_document(document)
        return document


class FinancialDashboardDownload(http.Controller):
    @http.route('/baseer/financial-dashboard/export', type='http', auth='user',
                methods=['POST'], csrf=True, readonly=True)
    def download(self, file_format=None, filters=None, revisions=None, **kwargs):
        try:
            if type(filters) is not str or len(filters) > 16384:
                raise ValueError('Invalid filters')
            options = json.loads(filters)
            if type(options) is not dict or type(options.get('company_id')) is not int:
                raise ValueError('Invalid company')
            if type(revisions) is not str or len(revisions) > 2048:
                raise ValueError('Invalid revisions')
            expected = json.loads(revisions)
            validate_revisions(expected)
            # Match the existing authenticated exporter: cookie is a selector,
            # never authority, and must name only companies the user can read.
            cookie = request.httprequest.cookies.get('cids')
            if cookie:
                parts = cookie.split('-')
                if len(parts) > 100 or any(not part.isascii() or not part.isdecimal() for part in parts):
                    raise ValueError('Invalid active companies')
                company_ids = [int(part) for part in parts]
            else:
                company_ids = [request.env.company.id]
            if not company_ids or any(company_id not in request.env.user.company_ids.ids
                                      for company_id in company_ids):
                raise AccessError('Company unavailable')
            if options['company_id'] != company_ids[0]:
                raise AccessError('Active company changed')
            request.update_context(allowed_company_ids=company_ids,
                                   **{_EXPORT_REVISIONS: expected})
            data, mimetype, name = request.env['baseer.financial.dashboard.export']._export(
                'financial_dashboard_operations', options, file_format,
            )
        except (AccessError, UserError, ValueError, TypeError, KeyError):
            return request.make_response(
                'Report export unavailable. Refresh the report and check its filters and access.',
                status=400, headers=[('Content-Type', 'text/plain; charset=utf-8'),
                                     ('Cache-Control', 'private, no-store'),
                                     ('X-Content-Type-Options', 'nosniff')],
            )
        return request.make_response(data, headers=[
            ('Content-Type', mimetype), ('Content-Disposition', content_disposition(name)),
            ('Cache-Control', 'private, no-store'), ('X-Content-Type-Options', 'nosniff'),
        ])
