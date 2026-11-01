from odoo.addons.point_of_sale.controllers.main import PosController
from odoo.tools import file_open


class BaseerPosCacheController(PosController):
    def _get_pos_service_worker(self):
        # Keep Odoo's authenticated route, response type and /pos scope.
        with file_open('baseer_pos_cache_resilience/static/src/service_worker.js') as source:
            return source.read()
