from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from unittest.mock import patch

from ..models.google_ads import _dataset_identity, _dataset_row_values


@tagged("post_install", "-at_install")
class TestGoogleAdsReadOnlyContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = cls.env["res.users"].create({
            "name": "Ads reader", "login": "ads-reader-contract",
            "group_ids": [Command.set([cls.env.ref("baseer_google_ads.group_gads_reader").id])],
        })
        cls.manager = cls.env["res.users"].create({
            "name": "Ads manager", "login": "ads-manager-contract",
            "group_ids": [Command.set([cls.env.ref("baseer_google_ads.group_gads_manager").id])],
        })
        cls.connection = cls.env["baseer.gads.connection"].sudo().create({
            "name": "QA Ads", "company_id": cls.env.company.id,
            "legacy_connection_id": "legacy-ads-contract-1", "customer_id": "1234567890",
        })

    def _create_fact(self, metric_date, campaign_id, campaign_name, campaign_status, **metrics):
        values = {
            "connection_id": self.connection.id,
            "customer_id": self.connection.customer_id,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "campaign_status": campaign_status,
            "metric_date": metric_date,
            "impressions": 0,
            "clicks": 0,
            "cost_micros": 0,
            "conversions_scaled": 0,
            "conversion_value_scaled": 0,
        }
        values.update(metrics)
        return self.env["baseer.gads.daily.fact"].sudo().create(values)

    def _create_dataset_row(self, dataset, external_id, title, **values):
        row_values = {
            "dataset_id": dataset.id,
            "external_id": external_id,
            "title": title,
            "fetched_at": fields.Datetime.now(),
        }
        row_values.update(values)
        return self.env["baseer.gads.dataset.row"].sudo().create(row_values)

    def test_dashboard_keeps_decimals_and_source_visibility_truthful(self):
        metric_date = fields.Date.context_today(self.env["baseer.gads.daily.fact"])
        self._create_fact(metric_date, "7", "Arabic campaign", "ENABLED",
            impressions=7, clicks=3, cost_micros=1000001,
            conversions_scaled=1500000, conversion_value_scaled=1234567,
        )
        self.env["baseer.gads.daily.coverage"].sudo().create({
            "connection_id": self.connection.id, "metric_date": metric_date, "state": "available",
        })
        campaign_dataset = self.env["baseer.gads.dataset"].sudo().create({
            "connection_id": self.connection.id, "dataset_key": "campaigns", "state": "available",
        })
        self._create_dataset_row(
            campaign_dataset, "campaign-without-period-activity", "New enabled campaign",
            campaign_id="8", campaign_name="New enabled campaign", status="ENABLED",
        )
        report = self.env["baseer.gads.dashboard"].with_user(self.reader).get_dashboard_data(
            self.connection.id, metric_date, metric_date
        )
        self.assertEqual(report["summary"]["cost"], "1.00")
        self.assertEqual(report["summary"]["google_conversions"], "1.50")
        self.assertEqual(report["summary"]["google_conversion_value"], "1.23")
        self.assertEqual(report["period"]["covered_days"], 1)
        campaigns = {campaign["id"]: campaign for campaign in report["filters"]["campaigns"]}
        self.assertIn("8", campaigns)
        self.assertEqual(campaigns["8"]["impressions"], "0")
        self.assertEqual(campaigns["8"]["cost"], "0.00")

    def test_dashboard_rejects_invalid_connection_input_safely(self):
        dashboard = self.env["baseer.gads.dashboard"].with_user(self.reader)
        with self.assertRaises(ValidationError):
            dashboard.get_dashboard_data(connection_id="not-a-connection")
        with self.assertRaises(AccessError):
            dashboard.get_dashboard_data(connection_id=self.connection.id + 1000000)

    def test_campaign_status_and_campaign_filters_change_the_summary(self):
        metric_date = fields.Date.context_today(self.env["baseer.gads.daily.fact"])
        self._create_fact(
            metric_date, "enabled-campaign", "Enabled campaign", "ENABLED",
            impressions=100, clicks=10, cost_micros=1000000, conversions_scaled=1000000,
        )
        self._create_fact(
            metric_date, "paused-campaign", "Paused campaign", "PAUSED",
            impressions=20, clicks=4, cost_micros=2000000, conversions_scaled=2500000,
        )
        dashboard = self.env["baseer.gads.dashboard"].with_user(self.reader)

        paused_report = dashboard.get_dashboard_data(
            self.connection.id, metric_date, metric_date, campaign_status="PAUSED"
        )
        self.assertEqual(paused_report["summary"]["impressions"], "20")
        self.assertEqual(paused_report["summary"]["cost"], "2.00")
        self.assertEqual(paused_report["summary"]["google_conversions"], "2.50")

        selected_campaign_report = dashboard.get_dashboard_data(
            self.connection.id, metric_date, metric_date, campaign_id="enabled-campaign"
        )
        self.assertEqual(selected_campaign_report["summary"]["impressions"], "100")
        self.assertEqual(selected_campaign_report["summary"]["cost"], "1.00")
        self.assertEqual(selected_campaign_report["summary"]["google_conversions"], "1.00")

    def test_timeline_metric_and_equal_previous_period_are_server_scoped(self):
        current_date = fields.Date.context_today(self.env["baseer.gads.daily.fact"])
        previous_date = current_date - timedelta(days=1)
        self._create_fact(
            current_date, "timeline-campaign", "Timeline campaign", "ENABLED",
            impressions=200, clicks=20, cost_micros=4000000, conversions_scaled=2000000,
        )
        self._create_fact(
            previous_date, "timeline-campaign", "Timeline campaign", "ENABLED",
            impressions=100, clicks=10, cost_micros=1000000, conversions_scaled=1000000,
        )

        report = self.env["baseer.gads.dashboard"].with_user(self.reader).get_dashboard_data(
            self.connection.id, current_date, current_date,
            campaign_id="timeline-campaign", timeline_metric="cpa", compare_previous=True,
        )

        self.assertEqual(report["timeline"]["metric"], "cpa")
        self.assertTrue(report["timeline"]["comparison_enabled"])
        self.assertEqual(report["timeline"]["comparison_period"]["to"], fields.Date.to_string(previous_date))
        self.assertEqual(report["series"][0]["cpa"], "2.00")
        self.assertEqual(report["comparison_series"][0]["cpa"], "1.00")

    def test_timeline_preserves_missing_day_position_and_previous_coverage(self):
        end_date = fields.Date.context_today(self.env["baseer.gads.daily.fact"]) - timedelta(days=10)
        start_date = end_date - timedelta(days=2)
        previous_start = start_date - timedelta(days=3)
        campaign_id = "gap-safe-timeline"
        for metric_date, impressions in ((start_date, 10), (end_date, 30)):
            self._create_fact(
                metric_date, campaign_id, "Gap safe timeline", "ENABLED",
                impressions=impressions, clicks=impressions // 10,
            )
            self.env["baseer.gads.daily.coverage"].sudo().create({
                "connection_id": self.connection.id, "metric_date": metric_date, "state": "available",
            })
        for offset in range(3):
            metric_date = previous_start + timedelta(days=offset)
            self._create_fact(
                metric_date, campaign_id, "Gap safe timeline", "ENABLED",
                impressions=100 + offset, clicks=10,
            )
            self.env["baseer.gads.daily.coverage"].sudo().create({
                "connection_id": self.connection.id, "metric_date": metric_date, "state": "available",
            })

        report = self.env["baseer.gads.dashboard"].with_user(self.reader).get_dashboard_data(
            self.connection.id, start_date, end_date, campaign_id=campaign_id,
            timeline_metric="impressions", compare_previous=True,
        )

        self.assertEqual([point["position"] for point in report["series"]], [0, 1, 2])
        self.assertEqual([point["position"] for point in report["comparison_series"]], [0, 1, 2])
        self.assertFalse(report["series"][1]["has_data"])
        self.assertFalse(report["series"][1]["impressions"])
        self.assertEqual(report["series"][2]["impressions"], "30")
        self.assertEqual(report["timeline"]["comparison_period"]["covered_days"], 3)
        self.assertEqual(report["timeline"]["comparison_period"]["total_days"], 3)

    def test_ad_status_filters_only_ad_detail_rows_not_the_summary(self):
        metric_date = fields.Date.context_today(self.env["baseer.gads.daily.fact"])
        self._create_fact(
            metric_date, "ad-campaign", "Campaign with ads", "ENABLED",
            impressions=17, clicks=3, cost_micros=1000001, conversions_scaled=1500000,
        )
        ads_dataset = self.env["baseer.gads.dataset"].sudo().create({
            "connection_id": self.connection.id, "dataset_key": "ads", "state": "available",
        })
        self._create_dataset_row(
            ads_dataset, "enabled-ad", "Enabled ad", campaign_id="ad-campaign",
            campaign_name="Campaign with ads", status="ENABLED", impressions=10,
        )
        self._create_dataset_row(
            ads_dataset, "disapproved-ad", "Disapproved ad", campaign_id="ad-campaign",
            campaign_name="Campaign with ads", status="DISAPPROVED", impressions=7,
        )
        dashboard = self.env["baseer.gads.dashboard"].with_user(self.reader)
        unfiltered_report = dashboard.get_dashboard_data(self.connection.id, metric_date, metric_date)
        filtered_report = dashboard.get_dashboard_data(
            self.connection.id, metric_date, metric_date, ad_status="DISAPPROVED"
        )

        self.assertEqual(filtered_report["summary"], unfiltered_report["summary"])
        self.assertEqual(filtered_report["datasets"]["ads"]["row_count"], 1)
        self.assertEqual(
            [row["status"] for row in filtered_report["datasets"]["ads"]["rows"]], ["DISAPPROVED"]
        )

    def test_conversion_performance_identity_includes_its_campaign(self):
        first_campaign = {
            "campaign": {"id": "campaign-a", "name": "Campaign A"},
            "segments": {"conversionAction": "actions/42", "conversionActionName": "Lead"},
        }
        second_campaign = {
            "campaign": {"id": "campaign-b", "name": "Campaign B"},
            "segments": {"conversionAction": "actions/42", "conversionActionName": "Lead"},
        }

        self.assertNotEqual(
            _dataset_identity("conversion_performance", first_campaign),
            _dataset_identity("conversion_performance", second_campaign),
        )

    def test_successful_empty_detail_refresh_retires_stale_rows_as_no_data(self):
        dataset = self.env["baseer.gads.dataset"].sudo().create({
            "connection_id": self.connection.id,
            "dataset_key": "conversion_performance",
            "state": "available",
            "row_count": 1,
            "last_sync_at": fields.Datetime.now(),
        })
        self._create_dataset_row(
            dataset, "stale-conversion-row", "Old conversion", campaign_id="old-campaign",
            campaign_name="Old campaign", conversions_scaled=1000000,
        )

        with patch.object(type(self.connection), "_search_stream", return_value=[]):
            self.connection._sync_detail_datasets()

        dataset.invalidate_recordset()
        report = self.env["baseer.gads.dashboard"].with_user(self.reader).get_dashboard_data(
            self.connection.id
        )
        self.assertEqual(dataset.state, "no_data")
        self.assertEqual(dataset.row_count, 0)
        self.assertEqual(report["datasets"]["conversion_performance"]["row_count"], 0)
        self.assertEqual(report["datasets"]["conversion_performance"]["rows"], [])

    def test_credentials_cannot_be_written_outside_importer(self):
        with self.assertRaises(AccessError):
            self.connection.with_user(self.reader).write({"token_ciphertext": "not-a-secret"})
        with self.assertRaises(AccessError):
            self.connection.with_user(self.manager).with_context(
                gads_internal_secret_write=True
            ).write({"token_ciphertext": "not-a-secret"})

    def test_customer_id_validation(self):
        with self.assertRaises(ValidationError):
            self.env["baseer.gads.connection"].sudo().create({
                "name": "Invalid", "company_id": self.env.company.id,
                "legacy_connection_id": "legacy-ads-contract-2", "customer_id": "not-an-id",
            })

    def test_detail_row_is_deterministic_and_stays_in_its_company(self):
        raw = {
            "campaign": {"id": "7", "name": "Campaign A", "status": "ENABLED"},
            "adGroup": {"id": "21", "name": "Group A"},
            "adGroupCriterion": {"criterionId": "31", "keyword": {"text": "coffee"}, "status": "ENABLED"},
            "metrics": {"impressions": "10", "clicks": "2", "costMicros": "1234567", "conversions": "1.5", "conversionsValue": "2"},
        }
        values = _dataset_row_values("keywords", raw)
        self.assertEqual(values["external_id"], _dataset_identity("keywords", raw))
        self.assertEqual(values["conversions_scaled"], 1500000)
        dataset = self.env["baseer.gads.dataset"].sudo().create({
            "connection_id": self.connection.id, "dataset_key": "keywords", "state": "available",
        })
        self.env["baseer.gads.dataset.row"].sudo().create({
            "dataset_id": dataset.id, "fetched_at": fields.Datetime.now(), **values,
        })
        report = self.env["baseer.gads.dashboard"].with_user(self.reader).get_dashboard_data(
            self.connection.id
        )
        self.assertEqual(report["datasets"]["keywords"]["row_count"], 1)
        self.assertEqual(report["datasets"]["keywords"]["source_row_count"], 0)
        self.assertEqual(len(report["datasets"]["keywords"]["rows"]), 1)
