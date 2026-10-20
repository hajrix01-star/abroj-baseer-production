"""Focused contracts for the native Android media capability boundary."""
import hashlib
from datetime import timedelta
from uuid import uuid4

from odoo import SUPERUSER_ID, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from ..contracts import ProtocolError
from ..models.mobile_upload_grant import _MOBILE_UPLOAD_GRANT_TOKEN
from .test_media_v2 import BWorkMediaCase


@tagged('post_install', '-at_install', 'baseer_bwork_media')
class BWorkMobileUploadGrantCase(BWorkMediaCase):
    def _metadata(self, raw, **overrides):
        return super()._metadata(raw, **overrides)

    def _issue(self, raw, **overrides):
        metadata = self._metadata(raw, **overrides)
        service = self.env['baseer.bwork.service'].with_user(self.manager)
        return metadata, service._v2_issue_mobile_upload_grant(self.room.id, metadata)

    def test_grant_is_single_use_scope_and_direct_model_access_is_denied(self):
        raw = self._image()
        metadata, issued = self._issue(raw)
        self.assertRegex(issued['grant_id'], r'^[0-9a-f-]{36}$')
        self.assertRegex(issued['secret'], r'^[A-Za-z0-9_-]{43,128}$')
        grant = self.env['baseer.bwork.mobile.upload.grant'].sudo().search([
            ('grant_id', '=', issued['grant_id']),
        ], limit=1)
        self.assertEqual((grant.user_id, grant.room_id, grant.membership_id),
                         (self.manager, self.room, self.manager_epoch))
        self.assertEqual((grant.upload_uuid, grant.sha256, grant.size_bytes),
                         (metadata['upload_uuid'], metadata['sha256'], len(raw)))
        self.assertNotEqual(grant.secret_hash, issued['secret'])
        with self.assertRaises(AccessError):
            self.env['baseer.bwork.mobile.upload.grant'].with_user(self.manager).create({})
        replacement = self.env['baseer.bwork.service'].with_user(self.manager)._v2_issue_mobile_upload_grant(
            self.room.id, metadata)
        grant.invalidate_recordset(['state'])
        self.assertEqual(grant.state, 'expired')
        self.assertNotEqual(replacement['grant_id'], issued['grant_id'])
        active = self.env['baseer.bwork.mobile.upload.grant'].sudo().search([
            ('grant_id', '=', replacement['grant_id']),
        ], limit=1)
        active._write_verified({'state': 'uploading', 'upload_started_at': fields.Datetime.now()},
                               _MOBILE_UPLOAD_GRANT_TOKEN)
        with self.assertRaises(ProtocolError) as busy:
            self.env['baseer.bwork.service'].with_user(self.manager)._v2_issue_mobile_upload_grant(
                self.room.id, metadata)
        self.assertEqual(busy.exception.code, 'upload_in_progress')

    def test_redeem_path_rechecks_membership_and_result_is_retained_after_upload_expiry(self):
        raw = self._image()
        metadata, issued = self._issue(raw)
        grants = self.env['baseer.bwork.mobile.upload.grant'].sudo()
        grant = grants.search([('grant_id', '=', issued['grant_id'])], limit=1)
        grant._write_verified({
            'state': 'uploading', 'upload_started_at': fields.Datetime.now(),
        }, _MOBILE_UPLOAD_GRANT_TOKEN)
        snapshot = grant._snapshot()
        snapshot['claimed'] = True
        self.manager_epoch.with_user(self.room_admin).with_company(self.company).action_revoke()
        service = self.env['baseer.bwork.service'].with_user(self.manager).with_context({
            'allowed_company_ids': [self.company.id],
        })
        with self.assertRaises(ProtocolError) as membership_changed:
            service._v2_mobile_upload_from_capability(snapshot, raw)
        self.assertEqual(membership_changed.exception.code, 'membership_changed')
        # The HTTP boundary denies this claim after a service rejection.  This direct
        # service test performs the equivalent cleanup before requesting a new grant.
        grant._write_verified({'state': 'denied', 'failure_code': 'access_revoked'},
                              _MOBILE_UPLOAD_GRANT_TOKEN)

        # A fresh grant can resolve normally.  Its durable receipt remains readable for the
        # result-retention window even though the short upload privilege has ended.
        self.manager_epoch = self._join(self.manager)
        metadata, issued = self._issue(raw, uuid=str(uuid4()))
        grant = grants.search([('grant_id', '=', issued['grant_id'])], limit=1)
        media_id = self.env['baseer.bwork.service'].with_user(self.manager)._v2_upload(
            self.room.id, metadata, raw)['media_id']
        grant._write_verified({
            'state': 'resolved', 'media_id': media_id,
            'result_expires_at': fields.Datetime.now() + timedelta(minutes=1),
        }, _MOBILE_UPLOAD_GRANT_TOKEN)
        status = grants._status_capability(issued['grant_id'], issued['secret'])
        self.assertEqual((status['state'], status['media_id']), ('resolved', media_id))
        grant._write_verified({
            'result_expires_at': fields.Datetime.now() - timedelta(seconds=1),
        }, _MOBILE_UPLOAD_GRANT_TOKEN)
        with self.assertRaises(ProtocolError) as expired:
            grants._status_capability(issued['grant_id'], issued['secret'])
        self.assertEqual(expired.exception.status, 410)

    def test_capability_snapshot_cannot_change_metadata(self):
        raw = self._image()
        metadata, issued = self._issue(raw)
        grant = self.env['baseer.bwork.mobile.upload.grant'].sudo().search([
            ('grant_id', '=', issued['grant_id']),
        ], limit=1)
        snapshot = grant._snapshot()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), snapshot['sha256'])
        self.assertEqual(metadata['mime'], snapshot['mime'])
        with self.assertRaises(AccessError):
            grant.write({'mime': 'application/pdf'})

    def test_issue_is_bounded_and_reconcile_is_scoped_to_current_membership_epoch(self):
        raw = self._image()
        metadata, issued = self._issue(raw)
        service = self.env['baseer.bwork.service'].with_user(self.manager)
        with self.assertRaises(ProtocolError) as second_active:
            service._v2_issue_mobile_upload_grant(self.room.id, {
                **metadata, 'upload_uuid': str(uuid4()),
            })
        self.assertEqual(second_active.exception.status, 429)

        # A lost grant response may be renewed for the same logical upload, but an in-flight
        # body cannot be superseded.  The service serializes both decisions by user.
        renewed = service._v2_issue_mobile_upload_grant(self.room.id, metadata)
        self.assertNotEqual(issued['grant_id'], renewed['grant_id'])
        media_id = service._v2_upload(self.room.id, metadata, raw)['media_id']
        reconciled = service._v2_reconcile_native_upload(self.room.id, metadata['upload_uuid'])
        self.assertEqual((reconciled['state'], reconciled['media_id']), ('staged', media_id))

        self.manager_epoch.with_user(self.room_admin).with_company(self.company).action_revoke()
        self.manager_epoch = self._join(self.manager)
        missing = service._v2_reconcile_native_upload(self.room.id, metadata['upload_uuid'])
        self.assertEqual((missing['state'], missing.get('media_id')), ('missing', None))

    def test_same_upload_grant_reissues_are_rate_limited(self):
        raw = self._image()
        metadata, _issued = self._issue(raw)
        service = self.env['baseer.bwork.service'].with_user(self.manager)
        # The first issue plus two controlled renewals accommodate a lost response while
        # preventing an authenticated loop from accumulating expired receipts indefinitely.
        service._v2_issue_mobile_upload_grant(self.room.id, metadata)
        service._v2_issue_mobile_upload_grant(self.room.id, metadata)
        with self.assertRaises(ProtocolError) as limited:
            service._v2_issue_mobile_upload_grant(self.room.id, metadata)
        self.assertEqual((limited.exception.code, limited.exception.status),
                         ('upload_rate_limited', 429))

    def test_reconcile_reports_only_the_current_memberships_active_native_upload(self):
        raw = self._image()
        metadata, issued = self._issue(raw)
        grants = self.env['baseer.bwork.mobile.upload.grant'].sudo()
        grant = grants.search([('grant_id', '=', issued['grant_id'])], limit=1)
        # The independent capability claim cursor is intentionally not part of a
        # TransactionCase savepoint.  This direct verified transition models the durable
        # post-claim state while keeping the regression test isolated.
        grant._write_verified({'state': 'uploading', 'upload_started_at': fields.Datetime.now()},
                               _MOBILE_UPLOAD_GRANT_TOKEN)
        state = self.env['baseer.bwork.service'].with_user(self.manager)._v2_reconcile_native_upload(
            self.room.id, metadata['upload_uuid'])
        self.assertEqual((state['state'], state.get('media_id')), ('uploading', None))

    def test_expired_tombstones_are_purged_only_by_the_verified_cron(self):
        raw = self._image()
        _, issued = self._issue(raw)
        grants = self.env['baseer.bwork.mobile.upload.grant'].sudo()
        grant = grants.search([('grant_id', '=', issued['grant_id'])], limit=1)
        grant._write_verified({'state': 'expired'}, _MOBILE_UPLOAD_GRANT_TOKEN)
        grant.flush_recordset(['state', 'write_date'])
        self.env.cr.execute('''
            UPDATE baseer_bwork_mobile_upload_grant
            SET write_date = %s WHERE id = %s
        ''', [fields.Datetime.now() - timedelta(hours=25), grant.id])
        result = grants.with_user(SUPERUSER_ID)._cron_expire_mobile_upload_grants()
        self.assertGreaterEqual(result['purged_count'], 1)
        self.assertFalse(grant.exists())

    def test_cron_expires_finished_grant_receipts_before_their_later_purge(self):
        raw = self._image()
        metadata, issued = self._issue(raw)
        service = self.env['baseer.bwork.service'].with_user(self.manager)
        grants = self.env['baseer.bwork.mobile.upload.grant'].sudo()
        resolved = grants.search([('grant_id', '=', issued['grant_id'])], limit=1)
        media_id = service._v2_upload(self.room.id, metadata, raw)['media_id']
        resolved._write_verified({
            'state': 'resolved', 'media_id': media_id,
            'result_expires_at': fields.Datetime.now() - timedelta(seconds=1),
        }, _MOBILE_UPLOAD_GRANT_TOKEN)

        denied_metadata, denied_issued = self._issue(raw, uuid=str(uuid4()))
        denied = grants.search([('grant_id', '=', denied_issued['grant_id'])], limit=1)
        denied._write_verified({
            'state': 'denied', 'failure_code': 'access_revoked',
            'result_expires_at': fields.Datetime.now() - timedelta(seconds=1),
        }, _MOBILE_UPLOAD_GRANT_TOKEN)

        result = grants.with_user(SUPERUSER_ID)._cron_expire_mobile_upload_grants()
        resolved.invalidate_recordset(['state'])
        denied.invalidate_recordset(['state'])
        self.assertEqual((resolved.state, denied.state), ('expired', 'expired'))
        self.assertGreaterEqual(result['expired_count'], 2)
