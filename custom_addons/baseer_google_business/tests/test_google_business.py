from unittest.mock import patch
from datetime import timedelta

import requests
from psycopg2 import IntegrityError
from odoo import fields

from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError, ValidationError

from ..models.google_business import _google_datetime, _original_google_review_text


class TestGoogleBusinessPolicy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.connection = cls.env["baseer.gbp.connection"].create({
            "name": "Test secure connection",
            "company_id": cls.company.id,
            "external_connection_id": "test-connection-policy",
            "external_account_id": "accounts/test-policy",
        })
        cls.location = cls.env["baseer.gbp.location"].create({
            "name": "Test location",
            "company_id": cls.company.id,
            "connection_id": cls.connection.id,
            "external_location_id": "accounts/test/locations/policy",
        })

    def _review(self, stars):
        return self.env["baseer.gbp.review"].create({
            "location_id": self.location.id,
            "external_review_id": "review-%s" % stars,
            "star_rating": stars,
        })

    def test_google_translation_trailer_is_not_kept_in_review_text(self):
        source = "تعليق العميل الأصلي\n\n(Translated by Google)\nThe translated review"
        self.assertEqual(_original_google_review_text(source), "تعليق العميل الأصلي")
        reverse_source = "(Translated by Google)\nThe translated review\n\n(Original)\nالتعليق الأصلي"
        self.assertEqual(_original_google_review_text(reverse_source), "التعليق الأصلي")
        self.assertEqual(_original_google_review_text("Original English review"), "Original English review")

    def test_one_to_three_stars_are_always_manual(self):
        policy = self.env["baseer.gbp.reply.policy"].create({
            "location_id": self.location.id,
            "four_five_action": "auto",
            "auto_reply_enabled": False,
        })
        for stars in (1, 2, 3):
            review = self._review(stars)
            review.action_classify()
            self.assertEqual(review.reply_state, "manual")
        policy.unlink()

    def test_automatic_policy_requires_consent_audit(self):
        with self.assertRaises(ValidationError):
            self.env["baseer.gbp.reply.policy"].create({
                "location_id": self.location.id,
                "four_five_action": "auto",
                "auto_reply_enabled": True,
            })

    def test_one_policy_per_location(self):
        self.env["baseer.gbp.reply.policy"].create({"location_id": self.location.id})
        with self.cr.savepoint(), self.assertRaises(IntegrityError):
            self.env["baseer.gbp.reply.policy"].create({"location_id": self.location.id})

    def test_existing_google_reply_is_never_queued(self):
        review = self._review(5)
        review.write({"has_google_reply": True})
        review.action_classify()
        self.assertEqual(review.reply_state, "published")

    def test_google_timestamp_is_converted_to_utc_datetime(self):
        parsed = _google_datetime("2026-09-18T19:30:11.000278Z")
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.tzinfo, None)

    def test_dashboard_contract_is_bounded_and_backend_aggregated(self):
        today = fields.Date.context_today(self.location)
        self._review(5).write({"has_google_reply": True})
        self.env["baseer.gbp.metric"].create([
            {"location_id": self.location.id, "metric_key": "impressions", "metric_date": today, "value": 120},
            {"location_id": self.location.id, "metric_key": "website_clicks", "metric_date": today, "value": 7},
            {"location_id": self.location.id, "metric_key": "calls", "metric_date": today, "value": 3},
        ])
        dashboard = self.env["baseer.gbp.location"].with_user(
            self.env.ref("base.user_admin")
        ).get_dashboard_data(self.location.id)
        self.assertEqual(dashboard["summary"]["reviews"], "1")
        self.assertEqual(dashboard["summary"]["replied_reviews"], "1")
        self.assertEqual(dashboard["summary"]["reply_rate"], "100.0")
        self.assertEqual(dashboard["summary"]["impressions"], "120")
        self.assertEqual(dashboard["summary"]["profile_actions"], "10")
        self.assertEqual(len(dashboard["series"]), 30)
        self.assertEqual(len(dashboard["monthly_series"]), 12)
        self.assertTrue(dashboard["has_source_data"])

    def test_dashboard_marks_unsynchronised_location_empty_without_masking_real_zeroes(self):
        empty_location = self.env["baseer.gbp.location"].create({
            "name": "No source data", "company_id": self.company.id,
            "connection_id": self.connection.id,
            "external_location_id": "accounts/test/locations/no-source",
        })
        dashboard = self.env["baseer.gbp.location"].with_user(
            self.env.ref("base.user_admin")
        ).get_dashboard_data(empty_location.id)
        self.assertFalse(dashboard["has_source_data"])

    def test_direct_rpc_style_writes_cannot_bypass_reply_workflow(self):
        manager = self.env.ref("base.user_admin")
        review = self._review(5)
        policy = self.env["baseer.gbp.reply.policy"].create({"location_id": self.location.id})
        with self.assertRaises(AccessError):
            review.with_user(manager).write({"reply_state": "published"})
        with self.assertRaises(AccessError):
            policy.with_user(manager).write({"auto_reply_enabled": True})
        with self.assertRaises(AccessError):
            self.env["baseer.gbp.reply.outbox"].with_user(manager).create({
                "review_id": review.id, "body": "Direct RPC", "revision": 1,
                "idempotency_key": "direct-rpc-%s" % review.id,
            })

    def test_writer_requires_explicit_production_environment_lock(self):
        with self.assertRaises(AccessError):
            self.connection.write({"writer_enabled": True})

    def test_owner_cannot_forge_secure_import_context(self):
        owner = self.env.ref("base.user_admin")
        with self.assertRaises(AccessError):
            self.connection.with_user(owner).with_context(
                gbp_internal_secret_write=True
            ).write({"token_ciphertext": "forged"})

    def test_timeout_keeps_reply_in_unknown_state_without_raising(self):
        manager = self.env.ref("base.user_admin")
        review = self._review(5)
        self.location.write({"last_source_sync_at": fields.Datetime.now()})
        outbox = self.env["baseer.gbp.reply.outbox"].with_context(gbp_internal_workflow=True).create({
            "review_id": review.id, "body": "Approved reply", "revision": 1,
            "state": "approved", "idempotency_key": "timeout-%s" % review.id,
        })
        with patch.object(type(self.connection), "_writer_is_allowed", return_value=True), \
                patch.object(type(self.connection), "_read_token", return_value="test-token"), \
                patch("odoo.addons.baseer_google_business.models.google_business.requests.put", side_effect=requests.RequestException):
            result = outbox.with_user(manager).action_send()
        self.assertEqual(outbox.state, "unknown")
        self.assertEqual(result["tag"], "display_notification")

    def test_retention_job_redacts_text_but_keeps_review_metadata(self):
        review = self._review(4)
        review.with_context(gbp_internal_review_write=True).write({
            "comment": "Personal review text", "remote_reply_text": "A reply",
            "retention_deadline": fields.Datetime.now() - timedelta(days=1),
        })
        self.env["baseer.gbp.review"].cron_redact_expired_reviews()
        self.assertFalse(review.comment)
        self.assertFalse(review.remote_reply_text)
        self.assertTrue(review.external_review_id)
