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
        self.assertIn("'upload_interrupted'", CONTROLLER)
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
        self.assertIn("pg_advisory_xact_lock", GRANT)
        self.assertIn("_ensure_claim_current", GRANT)
        self.assertIn("_purge_verified", GRANT)
        self.assertIn("_GRANT_ISSUE_WINDOW_SECONDS = 300", GRANT)
        self.assertIn("_MAX_GRANT_ISSUES_PER_UPLOAD_WINDOW = 3", GRANT)
        self.assertIn("'upload_rate_limited'", GRANT)

    def test_redemption_reuses_service_rechecks_instead_of_trusting_claims(self):
        self.assertIn('def _v2_mobile_upload_from_capability', SERVICE)
        self.assertIn('return self._v2_upload(room_id, metadata, raw)', SERVICE)
        self.assertIn('def _v2_issue_mobile_upload_grant', SERVICE)
        self.assertIn("secrets.token_urlsafe(32)", SERVICE)

    def test_reconciliation_is_authenticated_read_only_and_epoch_scoped(self):
        self.assertIn("uploads/<string:upload_uuid>/reconcile", CONTROLLER)
        self.assertIn("def reconcile_mobile_upload", CONTROLLER)
        self.assertIn("def _v2_reconcile_native_upload", SERVICE)
        self.assertIn("('membership_id', '=', member.id)", SERVICE)
        self.assertIn("('author_user_id', '=', self.env.uid)", SERVICE)
        self.assertIn("('state', 'in', ('staged', 'attached'))", SERVICE)

    def test_grant_lifecycle_is_bounded_and_recovers_a_lost_native_response(self):
        self.assertIn('_MAX_ACTIVE_GRANTS_PER_USER = 1', GRANT)
        self.assertIn('_UPLOAD_LEASE_SECONDS = 90', GRANT)
        self.assertIn("'upload_in_progress'", GRANT)
        self.assertIn("_TOMBSTONE_RETENTION_HOURS = 24", GRANT)

    def test_expiry_rechecks_a_locked_row_before_overwriting_a_receipt(self):
        status = GRANT.split('def _status_capability', 1)[1].split('def _ensure_claim_current', 1)[0]
        cron = GRANT.split('def _cron_expire_mobile_upload_grants', 1)[1]
        self.assertIn("WHERE grant_id = %s FOR UPDATE", status)
        self.assertIn("for stale_id in stale.ids", cron)
        self.assertIn("WHERE id = %s FOR UPDATE", cron)
        self.assertIn("grant.state == 'uploading'", cron)


if __name__ == '__main__':
    unittest.main()
