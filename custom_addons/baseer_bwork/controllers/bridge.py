"""Tiny same-origin landing page for an authenticated BWork WebView."""

from odoo.addons.baseer_bwork.compatibility import routes, wire_payload, validate_headers, response_header, upload_token

from odoo import http
from odoo.http import request


_BRIDGE_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<title>BWork</title></head><body></body></html>'
)


class BWorkBridge(http.Controller):
    @http.route(routes('/bwork/app/bridge'), type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def bridge(self, **kwargs):
        return request.make_response(_BRIDGE_HTML, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-store'),
            ('Pragma', 'no-cache'),
            ('Vary', 'Cookie'),
            ('X-Content-Type-Options', 'nosniff'),
        ])
