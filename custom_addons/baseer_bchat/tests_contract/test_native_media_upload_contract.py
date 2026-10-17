"""Source-level security tripwires for the native BChat media capability."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = (ROOT / 'controllers' / 'media_api.py').read_text(encoding='utf-8')
GRANT = (ROOT / 'models' / 'mobile_upload_grant.py').read_text(encoding='utf-8')
SERVICE = (ROOT / 'models' / 'media_service.py').read_text(encoding='utf-8')


class NativeMediaUploadContractTests(unittest.TestCase):
    def test_native_routes_are_capability_only_and_cookie_free(self):
        self.assertIn("auth='none'", CONTROLLER)
        self.assertIn('csrf=False, save_session=False', CONTROLLER)
        self.assertIn("incoming.headers.get('Cookie')", CONTROLLER)
        self.assertIn("prefix = 'BChatUpload '", CONTROLLER)
        self.assertIn("incoming.content_type.split(';', 1)[0].strip().lower() != snapshot['mime']", CONTROLLER)
        self.assertIn("incoming.content_length != snapshot['size']", CONTROLLER)
        self.assertNotIn('multipart/form-data', CONTROLLER.split('def native_upload_content', 1)[1].split(
            "@http.route('/bchat/api/v2/rooms/<int:room_id>/uploads'", 1)[0])

    def test_grant_claim_is_short_and_result_can_be_recovered_without_reupload(self):
        self.assertIn("FOR UPDATE", GRANT)
        self.assertIn("with self.env.registry.cursor() as cursor", GRANT)
        self.assertIn("'state': 'uploading'", GRANT)
        self.assertIn("'state': 'resolved'", GRANT)
        self.assertIn('timedelta(minutes=15)', GRANT)
        self.assertIn("baseer_bchat_mobile_upload_grant_active_uniq", GRANT)
        self.assertIn("hmac.compare_digest", GRANT)
        self.assertIn("_status_capability", GRANT)

    def test_redemption_reuses_service_rechecks_instead_of_trusting_claims(self):
        self.assertIn('def _v2_mobile_upload_from_capability', SERVICE)
        self.assertIn('return self._v2_upload(room_id, metadata, raw)', SERVICE)
        self.assertIn('def _v2_issue_mobile_upload_grant', SERVICE)
        self.assertIn("secrets.token_urlsafe(32)", SERVICE)


if __name__ == '__main__':
    unittest.main()
