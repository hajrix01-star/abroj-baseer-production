"""Keep the Baseer subdomain focused on the native Odoo sign-in journey."""

from odoo import http
from odoo.http import request
from odoo.addons.website.controllers.main import Website


class BaseerWebsite(Website):
    """Redirect only the public Baseer hostname; do not alter Abroj's homepage."""

    @http.route()
    def index(self, **kwargs):
        hostname = (request.httprequest.host or "").split(":", 1)[0].lower()
        if hostname == "baseer.abroj.sa":
            return request.redirect("/web/login", code=302)
        return super().index(**kwargs)
