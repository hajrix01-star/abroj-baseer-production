"""Authenticated, CSRF-protected downloads; no public links or attachments."""

import json

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import content_disposition, request


class BaseerReportDownload(http.Controller):
    @http.route('/baseer/reports/export', type='http', auth='user', methods=['POST'],
                csrf=True, readonly=True)
    def download(self, report_key=None, file_format=None, filters=None, **kwargs):
        try:
            if type(filters) is not str or len(filters) > 16384:
                raise ValueError('Invalid filters')
            options = json.loads(filters)
            if type(options) is not dict or type(options.get('company_id')) is not int:
                raise ValueError('Invalid company')
            # HTTP downloads do not receive the RPC allowed_company_ids context.
            # The active-company cookie is an untrusted selector, not authority.
            cookie = request.httprequest.cookies.get('cids')
            if cookie:
                parts = cookie.split('-')
                if len(parts) > 100 or any(not part.isascii() or not part.isdecimal() for part in parts):
                    raise ValueError('Invalid active companies')
                company_ids = [int(part) for part in parts]
            else:
                company_ids = [request.env.company.id]
            allowed = request.env.user.company_ids.ids
            if not company_ids or any(company_id not in allowed for company_id in company_ids):
                raise AccessError('Company unavailable')
            if options['company_id'] != company_ids[0]:
                raise AccessError('Active company changed')
            request.update_context(allowed_company_ids=company_ids)
            data, mimetype, name = request.env['baseer.report.export']._export(
                report_key, options, file_format,
            )
        except (AccessError, UserError, ValueError, TypeError, KeyError):
            # Deliberately no source amounts, tracebacks or private identifiers.
            return request.make_response('Report export unavailable. Refresh the report and check its filters and access.',
                status=400, headers=[('Content-Type', 'text/plain; charset=utf-8'),
                    ('Cache-Control', 'private, no-store'), ('X-Content-Type-Options', 'nosniff')])
        return request.make_response(data, headers=[
            ('Content-Type', mimetype), ('Content-Disposition', content_disposition(name)),
            ('Cache-Control', 'private, no-store'), ('X-Content-Type-Options', 'nosniff'),
        ])
