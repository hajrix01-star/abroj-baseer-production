from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestPosCacheWorker(HttpCase):
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
