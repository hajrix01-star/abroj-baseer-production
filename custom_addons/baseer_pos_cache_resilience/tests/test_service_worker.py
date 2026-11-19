from odoo.tests import HttpCase, tagged
from odoo.tools import file_open
from odoo.tools.js_transpiler import transpile_javascript


@tagged('post_install', '-at_install')
class TestPosCacheWorker(HttpCase):
    def test_receipt_recovery_asset_replaces_native_definition(self):
        assets = self.env['ir.asset']
        paths = [item[0].lstrip('/') for item in assets._get_asset_paths(
            'point_of_sale._assets_pos', assets._get_asset_params())]
        self.assertIn('baseer_pos_cache_resilience/static/src/reset_local_data.js', paths)
        self.assertIn('baseer_pos_cache_resilience/static/src/receipt_storage.js', paths)
        self.assertIn('baseer_pos_cache_resilience/static/src/receipt_number_reservation.js', paths)
        self.assertNotIn(
            'point_of_sale/static/src/app/components/loader/critical_pos_error/reset_local_data.js', paths)

    def test_receipt_recovery_named_alias_compiles(self):
        path = 'baseer_pos_cache_resilience/static/src/reset_local_data.js'
        with file_open(path) as source:
            compiled = transpile_javascript('/' + path, source.read())
        self.assertIn('@point_of_sale/app/components/loader/critical_pos_error/reset_local_data', compiled)
        self.assertIn('__exports.resetLocalData', compiled)
        self.assertIn('@baseer_pos_cache_resilience/receipt_storage', compiled)

    def test_worker_route_retains_native_authentication(self):
        self.authenticate(None, None)
        response = self.url_open('/pos/service-worker.js', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/web/login', response.headers.get('Location', ''))

    def test_authenticated_native_endpoint_serves_bounded_worker(self):
        self.authenticate('admin', 'admin')
        response = self.url_open('/pos/service-worker.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/javascript', response.headers['Content-Type'])
        self.assertEqual(response.headers['Service-Worker-Allowed'], '/pos')
        self.assertIn('baseer-pos-cache-manifest', response.text)
        self.assertIn('const MAX_BYTES = 128 * 1024 * 1024;', response.text)
