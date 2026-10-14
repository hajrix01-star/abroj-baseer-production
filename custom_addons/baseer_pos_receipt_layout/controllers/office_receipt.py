import json

from markupsafe import Markup

from odoo import http
from odoo.http import request
from odoo.tools import json_default


class OfficeReceiptController(http.Controller):
    @http.route('/baseer/pos/office-receipt/<int:order_id>', type='http', auth='user', methods=['GET'])
    def office_receipt(self, order_id, **kwargs):
        cookie_companies = request.httprequest.cookies.get('cids', '')
        if cookie_companies:
            try:
                selected = [int(value) for value in cookie_companies.split('-')]
            except ValueError:
                return request.not_found()
            if not selected or not set(selected).issubset(request.env.user.company_ids.ids):
                return request.not_found()
            request.update_context(allowed_company_ids=selected)
        order = request.env['pos.order'].browse(order_id)
        order._baseer_check_office_receipt_access()
        info = request.env['ir.http'].session_info()
        # Keep the user's allowed companies; never elevate access to the order's company.
        bootstrap = {
            '__session_info__': info,
            'csrf_token': request.csrf_token(),
            'debug': request.session.debug,
            'baseer_office_order_id': order.id,
        }
        safe_json = json.dumps(bootstrap, default=json_default).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
        response = request.render('baseer_pos_receipt_layout.office_receipt_page', {
            'bootstrap_json': Markup(safe_json),
            'order': order,
        })
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
