"""Read-only Google Ads reporting models.

The module deliberately owns Google Ads facts but exposes only bounded report
DTOs to the browser.  OAuth secrets are never accepted from RPC, forms, CSV,
or configuration parameters.
"""

import base64
import hashlib
import json
import os
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


GOOGLE_OAUTH_ORIGIN = "https://oauth2.googleapis.com"
GOOGLE_ADS_ORIGIN = "https://googleads.googleapis.com/v25"
GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
REQUEST_TIMEOUT_SECONDS = 20
VALUE_SCALE = Decimal("1000000")
MAX_REPORT_DAYS = 731


class GadsBigInteger(fields.Integer):
    """A PostgreSQL bigint for raw Google counters and micro-currency units."""

    _column_type = ("int8", "int8")


# Every query is read-only and deliberately bounded.  A failed optional Google
# resource must never erase a previously stored dataset or make the account's
# campaign history unavailable.
FULL_DATASET_QUERIES = {
    "campaigns": """
        SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
               campaign.bidding_strategy_type, campaign.start_date_time, campaign.end_date_time,
               campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.status IN ('ENABLED', 'PAUSED', 'REMOVED')
        ORDER BY campaign.name
        LIMIT 500
    """,
    "ads": """
        SELECT campaign.id, campaign.name, ad_group.id, ad_group.name,
               ad_group_ad.ad.id, ad_group_ad.ad.name, ad_group_ad.ad.type,
               ad_group_ad.status, ad_group_ad.primary_status,
               ad_group_ad.policy_summary.approval_status, ad_group_ad.policy_summary.review_status,
               ad_group_ad.ad_strength
        FROM ad_group_ad
        ORDER BY campaign.name, ad_group.name, ad_group_ad.ad.id
        LIMIT 1000
    """,
    "keywords": """
        SELECT campaign.id, campaign.name, ad_group.id, ad_group.name,
               ad_group_criterion.criterion_id, ad_group_criterion.keyword.text,
               ad_group_criterion.keyword.match_type, ad_group_criterion.status,
               ad_group_criterion.quality_info.quality_score,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE segments.date DURING LAST_30_DAYS AND ad_group_criterion.status != 'REMOVED'
        ORDER BY metrics.clicks DESC
        LIMIT 1000
    """,
    "search_terms": """
        SELECT campaign.id, campaign.name, ad_group.id, ad_group.name,
               search_term_view.search_term, search_term_view.status,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM search_term_view
        WHERE segments.date DURING LAST_30_DAYS
        ORDER BY metrics.cost_micros DESC
        LIMIT 1000
    """,
    "conversion_actions": """
        SELECT conversion_action.id, conversion_action.name, conversion_action.status,
               conversion_action.type, conversion_action.category,
               conversion_action.primary_for_goal, conversion_action.counting_type
        FROM conversion_action
        ORDER BY conversion_action.name
        LIMIT 500
    """,
    "conversion_performance": """
        SELECT campaign.id, campaign.name, segments.conversion_action,
               segments.conversion_action_name, segments.conversion_action_category,
               metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
        LIMIT 1000
    """,
    "opportunities": """
        SELECT campaign.id, campaign.name, metrics.search_impression_share,
               metrics.search_budget_lost_impression_share,
               metrics.search_rank_lost_impression_share
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS AND campaign.status IN ('ENABLED', 'PAUSED')
        LIMIT 500
    """,
    "devices": """
        SELECT campaign.id, campaign.name, segments.device, metrics.impressions, metrics.clicks,
               metrics.cost_micros, metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
        LIMIT 1000
    """,
    "day_hours": """
        SELECT campaign.id, campaign.name, segments.day_of_week, segments.hour,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
        LIMIT 1000
    """,
    "networks": """
        SELECT campaign.id, campaign.name, segments.ad_network_type, metrics.impressions,
               metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
        LIMIT 1000
    """,
    "locations": """
        SELECT campaign.id, campaign.name, geographic_view.country_criterion_id,
               geographic_view.location_type, metrics.impressions, metrics.clicks,
               metrics.cost_micros, metrics.conversions, metrics.conversions_value
        FROM geographic_view
        WHERE segments.date DURING LAST_30_DAYS
        ORDER BY metrics.clicks DESC
        LIMIT 500
    """,
    "smart_search_terms": """
        SELECT campaign.id, campaign.name, smart_campaign_search_term_view.search_term
        FROM smart_campaign_search_term_view
        LIMIT 1000
    """,
    "pmax_search_terms": """
        SELECT campaign.id, campaign.name, campaign_search_term_view.search_term,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM campaign_search_term_view
        WHERE segments.date DURING LAST_30_DAYS
          AND campaign.advertising_channel_type = 'PERFORMANCE_MAX'
        ORDER BY metrics.clicks DESC
        LIMIT 1000
    """,
    "campaign_negatives": """
        SELECT campaign.id, campaign.name, campaign_criterion.criterion_id,
               campaign_criterion.keyword.text, campaign_criterion.keyword.match_type,
               campaign_criterion.status, campaign_criterion.negative
        FROM campaign_criterion
        WHERE campaign_criterion.type = 'KEYWORD' AND campaign_criterion.negative = TRUE
        LIMIT 1000
    """,
    "ad_group_negatives": """
        SELECT campaign.id, campaign.name, ad_group.id, ad_group.name,
               ad_group_criterion.criterion_id, ad_group_criterion.keyword.text,
               ad_group_criterion.keyword.match_type, ad_group_criterion.status,
               ad_group_criterion.negative
        FROM ad_group_criterion
        WHERE ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = TRUE
        LIMIT 1000
    """,
    "optimization_score": """
        SELECT customer.optimization_score
        FROM customer
        LIMIT 1
    """,
    "pmax_asset_groups": """
        SELECT campaign.id, campaign.name, asset_group.id, asset_group.name,
               asset_group.status, asset_group.primary_status, asset_group.ad_strength,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM asset_group
        WHERE segments.date DURING LAST_30_DAYS
        ORDER BY metrics.clicks DESC
        LIMIT 500
    """,
    "recommendations": """
        SELECT recommendation.resource_name, recommendation.type, recommendation.campaign
        FROM recommendation
        LIMIT 500
    """,
    "recent_changes": """
        SELECT change_event.campaign, change_event.change_date_time,
               change_event.change_resource_type, change_event.resource_change_operation,
               change_event.resource_name, change_event.user_email, change_event.client_type
        FROM change_event
        WHERE change_event.change_date_time >= '{change_from}'
          AND change_event.change_date_time <= '{change_to}'
        ORDER BY change_event.change_date_time DESC
        LIMIT 1000
    """,
}

DATASET_DISPLAY_LIMITS = {
    "campaigns": 500, "ads": 1000, "keywords": 1000, "search_terms": 1000,
    "conversion_actions": 500, "conversion_performance": 1000, "opportunities": 500, "devices": 1000,
    "day_hours": 1000, "networks": 1000, "locations": 500, "smart_search_terms": 1000,
    "pmax_search_terms": 1000, "campaign_negatives": 1000, "ad_group_negatives": 1000,
    "optimization_score": 1, "pmax_asset_groups": 500, "recommendations": 500,
    "recent_changes": 1000,
}


def _master_key():
    raw = _environment_secret("BASEER_GADS_CREDENTIAL_MASTER_KEY")
    if not raw:
        raise UserError(_("Google Ads credentials are not configured on this server."))
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _environment_secret(name):
    """Read a secret directly or from a base64-only deployment environment.

    The latter keeps Docker's dotenv parser away from punctuation in OAuth
    credentials.  Neither representation is exposed through Odoo fields.
    """
    encoded = os.environ.get(name + "_B64")
    if encoded:
        try:
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise UserError(_("Google Ads server credential configuration is invalid.")) from exc
    return os.environ.get(name)


def _encrypt_secret(value):
    nonce = os.urandom(12)
    ciphertext = AESGCM(_master_key()).encrypt(nonce, value.encode("utf-8"), None)
    return base64.b64encode(nonce).decode(), base64.b64encode(ciphertext).decode()


def _decrypt_secret(nonce, ciphertext):
    try:
        return AESGCM(_master_key()).decrypt(
            base64.b64decode(nonce), base64.b64decode(ciphertext), None
        ).decode("utf-8")
    except Exception as exc:
        raise UserError(_("Stored Google Ads credentials cannot be decrypted.")) from exc


def _decimal_to_scaled(value):
    """Persist decimal values as fixed six-place integers, never Float."""
    return int((Decimal(str(value or 0)) * VALUE_SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def _scaled_to_decimal(value):
    return Decimal(int(value or 0)) / VALUE_SCALE


def _display_decimal(value, digits=2):
    quantum = Decimal("1") if not digits else Decimal("1." + ("0" * digits))
    return format(Decimal(value or 0).quantize(quantum, rounding=ROUND_HALF_UP), "f")


def _path(value, *keys):
    """Safely read a nested Google API value without inventing a default fact."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _as_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dataset_identity(dataset_key, row):
    campaign_id = str(_path(row, "campaign", "id") or "")
    ad_group_id = str(_path(row, "adGroup", "id") or "")
    values = {
        "campaigns": campaign_id,
        "ads": "%s:%s:%s" % (campaign_id, ad_group_id, _path(row, "adGroupAd", "ad", "id") or ""),
        "keywords": "%s:%s:%s" % (campaign_id, ad_group_id, _path(row, "adGroupCriterion", "criterionId") or ""),
        "search_terms": "%s:%s:%s" % (campaign_id, ad_group_id, _path(row, "searchTermView", "searchTerm") or ""),
        "conversion_actions": str(_path(row, "conversionAction", "id") or ""),
        # Google returns conversion performance at campaign × action grain.
        # Keeping only the action would overwrite another campaign's result.
        "conversion_performance": "%s:%s" % (campaign_id, _path(row, "segments", "conversionAction") or ""),
        "opportunities": campaign_id,
        "devices": "%s:%s" % (campaign_id, _path(row, "segments", "device") or ""),
        "day_hours": "%s:%s:%s" % (campaign_id, _path(row, "segments", "dayOfWeek") or "", _path(row, "segments", "hour") or ""),
        "networks": "%s:%s" % (campaign_id, _path(row, "segments", "adNetworkType") or ""),
        "locations": "%s:%s:%s" % (campaign_id, _path(row, "geographicView", "countryCriterionId") or "", _path(row, "geographicView", "locationType") or ""),
        "smart_search_terms": "%s:%s" % (campaign_id, _path(row, "smartCampaignSearchTermView", "searchTerm") or ""),
        "pmax_search_terms": "%s:%s" % (campaign_id, _path(row, "campaignSearchTermView", "searchTerm") or ""),
        "campaign_negatives": "%s:%s" % (campaign_id, _path(row, "campaignCriterion", "criterionId") or ""),
        "ad_group_negatives": "%s:%s:%s" % (campaign_id, ad_group_id, _path(row, "adGroupCriterion", "criterionId") or ""),
        "optimization_score": str(_path(row, "customer", "resourceName") or _path(row, "customer", "id") or "optimization"),
        "pmax_asset_groups": "%s:%s" % (campaign_id, _path(row, "assetGroup", "id") or ""),
        "recommendations": str(_path(row, "recommendation", "resourceName") or ""),
        "recent_changes": str(_path(row, "changeEvent", "resourceName") or ""),
    }
    value = values.get(dataset_key) or hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return hashlib.sha256((dataset_key + ":" + value).encode("utf-8")).hexdigest()


def _dataset_row_values(dataset_key, row):
    campaign_id = str(_path(row, "campaign", "id") or "")
    campaign_name = _path(row, "campaign", "name") or ""
    ad_group_name = _path(row, "adGroup", "name") or ""
    metrics = row.get("metrics") or {}
    title, subtitle, status = campaign_name or dataset_key, ad_group_name, ""
    if dataset_key == "ads":
        title = _path(row, "adGroupAd", "ad", "name") or _path(row, "adGroupAd", "ad", "id") or ""
        status = _path(row, "adGroupAd", "primaryStatus") or _path(row, "adGroupAd", "status") or ""
        subtitle = "%s · %s" % (campaign_name, ad_group_name)
    elif dataset_key == "keywords":
        title = _path(row, "adGroupCriterion", "keyword", "text") or ""
        status = _path(row, "adGroupCriterion", "status") or ""
        subtitle = "%s · %s" % (campaign_name, ad_group_name)
    elif dataset_key == "search_terms":
        title = _path(row, "searchTermView", "searchTerm") or ""
        status = _path(row, "searchTermView", "status") or ""
        subtitle = "%s · %s" % (campaign_name, ad_group_name)
    elif dataset_key == "conversion_actions":
        title = _path(row, "conversionAction", "name") or ""
        status = _path(row, "conversionAction", "status") or ""
        subtitle = _path(row, "conversionAction", "category") or ""
    elif dataset_key == "conversion_performance":
        title = _path(row, "segments", "conversionActionName") or _path(row, "segments", "conversionAction") or ""
        subtitle = "%s · %s" % (campaign_name, _path(row, "segments", "conversionActionCategory") or "")
    elif dataset_key in {"smart_search_terms", "pmax_search_terms"}:
        key = "smartCampaignSearchTermView" if dataset_key == "smart_search_terms" else "campaignSearchTermView"
        title = _path(row, key, "searchTerm") or ""
        subtitle = campaign_name
    elif dataset_key in {"campaign_negatives", "ad_group_negatives"}:
        key = "campaignCriterion" if dataset_key == "campaign_negatives" else "adGroupCriterion"
        title = _path(row, key, "keyword", "text") or ""
        status = _path(row, key, "status") or ""
        subtitle = campaign_name if dataset_key == "campaign_negatives" else "%s · %s" % (campaign_name, ad_group_name)
    elif dataset_key == "optimization_score":
        title = "Optimization score"
        subtitle = str(_path(row, "customer", "optimizationScore") or "")
    elif dataset_key == "pmax_asset_groups":
        title = _path(row, "assetGroup", "name") or _path(row, "assetGroup", "id") or ""
        status = _path(row, "assetGroup", "primaryStatus") or _path(row, "assetGroup", "status") or ""
        subtitle = campaign_name
    elif dataset_key == "recent_changes":
        title = _path(row, "changeEvent", "changeResourceType") or ""
        subtitle = "%s · %s" % (_path(row, "changeEvent", "resourceChangeOperation") or "", _path(row, "changeEvent", "changeDateTime") or "")
    elif dataset_key == "recommendations":
        title = _path(row, "recommendation", "type") or ""
        subtitle = _path(row, "recommendation", "campaign") or ""
    elif dataset_key in {"devices", "day_hours", "networks", "locations"}:
        segment = row.get("segments") or row.get("geographicView") or {}
        title = " · ".join(str(value) for value in segment.values() if value not in (None, ""))
        subtitle = campaign_name
    elif dataset_key == "opportunities":
        status = "METRICS"
    else:
        status = _path(row, "campaign", "status") or ""
    return {
        "external_id": _dataset_identity(dataset_key, row),
        "campaign_id": campaign_id, "campaign_name": campaign_name,
        "title": str(title or dataset_key), "subtitle": str(subtitle or ""), "status": str(status or ""),
        "impressions": _as_int(metrics.get("impressions")), "clicks": _as_int(metrics.get("clicks")),
        "cost_micros": _as_int(metrics.get("costMicros")),
        "conversions_scaled": _decimal_to_scaled(metrics.get("conversions")),
        "conversion_value_scaled": _decimal_to_scaled(metrics.get("conversionsValue")),
        "payload": row,
    }


class GadsConnection(models.Model):
    _name = "baseer.gads.connection"
    _description = "Google Ads read-only connection"
    _order = "company_id, name"

    _gads_legacy_connection_unique = models.Constraint(
        "unique(legacy_connection_id)", "The legacy Google Ads connection can only be imported once."
    )
    _gads_company_customer_unique = models.Constraint(
        "unique(company_id, customer_id)", "A company can only have one connection to this Google Ads customer."
    )

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, index=True,
                                 default=lambda self: self.env.company)
    legacy_connection_id = fields.Char(required=True, index=True, copy=False)
    customer_id = fields.Char(required=True, index=True, copy=False,
                              help="Google Ads client customer ID without hyphens.")
    login_customer_id = fields.Char(copy=False, help="Optional Google Ads manager ID without hyphens.")

    state = fields.Selection([
        ("pending", "Pending secure import"), ("active", "Active"),
        ("attention", "Needs re-authorization"), ("disabled", "Disabled"),
    ], required=True, default="pending", index=True)
    token_ciphertext = fields.Text(copy=False, groups="base.group_system", exportable=False)
    token_nonce = fields.Char(copy=False, groups="base.group_system", exportable=False)
    token_key_version = fields.Char(copy=False, groups="base.group_system", exportable=False)
    last_sync_at = fields.Datetime(copy=False, readonly=True)
    last_error_at = fields.Datetime(copy=False, readonly=True)
    last_error_code = fields.Char(copy=False, readonly=True)

    @api.constrains("customer_id", "login_customer_id")
    def _check_customer_ids(self):
        for record in self:
            for value in (record.customer_id, record.login_customer_id):
                if value and (not value.isdigit() or len(value) != 10):
                    raise ValidationError(_("Google Ads customer IDs must be ten digits without hyphens."))

    def _require_system(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only a system administrator can operate secure Google Ads credentials."))

    def _require_manager(self):
        if not self.env.user.has_group("baseer_google_ads.group_gads_manager"):
            raise AccessError(_("You do not have permission to synchronize Google Ads."))

    def write(self, values):
        protected = {"token_ciphertext", "token_nonce", "token_key_version"}
        if protected.intersection(values) and (
            self.env.uid != SUPERUSER_ID or not self.env.context.get("gads_internal_secret_write")
        ):
            # RPC callers can forge context values, but they cannot impersonate
            # Odoo's superuser.  The production bridge writes under that server
            # identity only; ordinary managers never get a secret-write path.
            raise AccessError(_("Google Ads credentials can only be changed by the secure server-side importer."))
        return super().write(values)

    def _secure_import_refresh_token(self, refresh_token, key_version="v1"):
        """Trusted, server-only endpoint for the future one-time bridge."""
        self._require_system()
        if not refresh_token:
            raise ValidationError(_("A refresh token is required for secure import."))
        for record in self:
            nonce, ciphertext = _encrypt_secret(refresh_token)
            record.with_context(gads_internal_secret_write=True).write({
                "token_nonce": nonce, "token_ciphertext": ciphertext,
                "token_key_version": key_version, "state": "active",
                "last_error_at": False, "last_error_code": False,
            })
            self.env["baseer.gads.audit"].sudo().create({
                "company_id": record.company_id.id, "connection_id": record.id,
                "event": "credential_imported", "detail": "Server-side secure import completed.",
            })
        return True

    def _refresh_access_token(self):
        self.ensure_one()
        if self.state != "active" or not self.token_ciphertext or not self.token_nonce:
            raise UserError(_("This Google Ads connection is not ready for read-only sync."))
        client_id = _environment_secret("BASEER_GADS_GOOGLE_CLIENT_ID")
        client_secret = _environment_secret("BASEER_GADS_GOOGLE_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise UserError(_("Google OAuth client credentials are not configured on this server."))
        try:
            response = requests.post(GOOGLE_OAUTH_ORIGIN + "/token", data={
                "grant_type": "refresh_token", "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": _decrypt_secret(self.token_nonce, self.token_ciphertext),
            }, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise UserError(_("Google OAuth is temporarily unavailable.")) from exc
        if response.status_code != 200:
            self.sudo().write({"state": "attention", "last_error_at": fields.Datetime.now(),
                               "last_error_code": "oauth_refresh_rejected"})
            raise UserError(_("Google authorization needs to be renewed by an administrator."))
        token = response.json().get("access_token")
        if not token:
            raise UserError(_("Google OAuth did not return an access token."))
        return token

    def _google_headers(self):
        self.ensure_one()
        developer_token = _environment_secret("BASEER_GADS_DEVELOPER_TOKEN")
        if not developer_token:
            raise UserError(_("Google Ads developer access is not configured on this server."))
        headers = {
            "Authorization": "Bearer " + self._refresh_access_token(),
            "Content-Type": "application/json",
            "developer-token": developer_token,
        }
        if self.login_customer_id:
            headers["login-customer-id"] = self.login_customer_id
        return headers

    def _search_stream(self, query):
        """Only read-only GAQL SearchStream is exposed by this module."""
        self.ensure_one()
        try:
            response = requests.post(
                "%s/customers/%s/googleAds:searchStream" % (GOOGLE_ADS_ORIGIN, self.customer_id),
                headers=self._google_headers(), json={"query": query}, timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise UserError(_("Google Ads is temporarily unavailable.")) from exc
        if response.status_code != 200:
            self.sudo().write({"last_error_at": fields.Datetime.now(), "last_error_code": "google_read_rejected"})
            raise UserError(_("Google Ads could not be read. Review the connection configuration."))
        rows = []
        for batch in response.json() or []:
            rows.extend(batch.get("results") or [])
        return rows

    def action_sync_read_only(self):
        self._require_manager()
        for record in self:
            if record.company_id not in self.env.companies:
                raise AccessError(_("This Google Ads connection belongs to another company."))
            record._sync_recent_campaign_facts()
            record._sync_detail_datasets()
        return True

    def _sync_recent_campaign_facts(self):
        """First vertical slice: bounded campaign/day fact ingestion, no Google writes."""
        self.ensure_one()
        self.env.cr.execute("SELECT id FROM baseer_gads_connection WHERE id = %s FOR UPDATE NOWAIT", [self.id])
        run = self.env["baseer.gads.sync.run"].sudo().create({
            "connection_id": self.id, "company_id": self.company_id.id, "kind": "recent", "state": "running",
        })
        try:
            rows = self._search_stream("""
                SELECT customer.id, campaign.id, campaign.name, campaign.status,
                       segments.date, metrics.impressions, metrics.clicks, metrics.cost_micros,
                       metrics.conversions, metrics.conversions_value
                FROM campaign
                WHERE segments.date DURING LAST_30_DAYS
            """)
            Fact = self.env["baseer.gads.daily.fact"].sudo()
            dates = set()
            for row in rows:
                campaign = row.get("campaign") or {}
                segments = row.get("segments") or {}
                metrics = row.get("metrics") or {}
                metric_date = segments.get("date")
                campaign_id = str(campaign.get("id") or "")
                if not metric_date or not campaign_id:
                    continue
                dates.add(metric_date)
                values = {
                    "connection_id": self.id, "company_id": self.company_id.id,
                    "customer_id": self.customer_id, "campaign_id": campaign_id,
                    "campaign_name": campaign.get("name") or campaign_id,
                    "campaign_status": campaign.get("status") or "UNKNOWN",
                    "metric_date": metric_date, "impressions": int(metrics.get("impressions") or 0),
                    "clicks": int(metrics.get("clicks") or 0), "cost_micros": int(metrics.get("costMicros") or 0),
                    "conversions_scaled": _decimal_to_scaled(metrics.get("conversions")),
                    "conversion_value_scaled": _decimal_to_scaled(metrics.get("conversionsValue")),
                }
                existing = Fact.search([("connection_id", "=", self.id), ("campaign_id", "=", campaign_id),
                                        ("metric_date", "=", metric_date)], limit=1)
                if existing:
                    existing.write(values)
                else:
                    Fact.create(values)
            Coverage = self.env["baseer.gads.daily.coverage"].sudo()
            for metric_date in dates:
                coverage = Coverage.search([("connection_id", "=", self.id), ("metric_date", "=", metric_date)], limit=1)
                if coverage:
                    coverage.write({"state": "available", "sync_run_id": run.id})
                else:
                    Coverage.create({"connection_id": self.id, "company_id": self.company_id.id,
                                     "metric_date": metric_date, "state": "available", "sync_run_id": run.id})
            self.sudo().write({"last_sync_at": fields.Datetime.now(), "last_error_at": False, "last_error_code": False})
            run.write({"state": "succeeded", "finished_at": fields.Datetime.now(), "row_count": len(rows)})
        except Exception:
            run.write({"state": "failed", "finished_at": fields.Datetime.now(), "error_code": "sync_failed"})
            raise

    def _sync_detail_datasets(self):
        """Refresh every detailed read model independently.

        A missing entitlement for one Google resource is a visible partial
        state for that tab, not a reason to hide valid data in the others.
        Rows are reconciled only after a complete successful response; an API
        error preserves the last known-good snapshot.
        """
        self.ensure_one()
        run = self.env["baseer.gads.sync.run"].sudo().create({
            "connection_id": self.id, "company_id": self.company_id.id,
            "kind": "detail", "state": "running",
        })
        Dataset = self.env["baseer.gads.dataset"].sudo()
        DatasetRow = self.env["baseer.gads.dataset.row"].sudo()
        total_rows, failed = 0, 0
        for dataset_key, query in FULL_DATASET_QUERIES.items():
            dataset = Dataset.search([
                ("connection_id", "=", self.id), ("dataset_key", "=", dataset_key),
            ], limit=1)
            if not dataset:
                dataset = Dataset.create({
                    "connection_id": self.id, "dataset_key": dataset_key,
                })
            try:
                # A failed update must leave both state and rows at the prior
                # successful snapshot.  The savepoint rolls back partial upserts.
                with self.env.cr.savepoint():
                    now = fields.Datetime.now()
                    query = query.format(
                        change_from=(now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
                        change_to=now.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    rows = self._search_stream(query)
                    fetched_at = fields.Datetime.now()
                    existing_rows = DatasetRow.search([("dataset_id", "=", dataset.id)])
                    existing_by_external_id = {row.external_id: row for row in existing_rows}
                    received_ids = set()
                    for raw in rows:
                        values = _dataset_row_values(dataset_key, raw)
                        received_ids.add(values["external_id"])
                        values.update({"dataset_id": dataset.id, "fetched_at": fetched_at})
                        existing = existing_by_external_id.get(values["external_id"])
                        if existing:
                            existing.write(values)
                        else:
                            DatasetRow.create(values)
                    # A successful empty response means this current snapshot
                    # is empty.  Stale records are never presented as fresh.
                    existing_rows.filtered(lambda row: row.external_id not in received_ids).unlink()
                    state = "no_data" if not rows else (
                        "limited" if dataset_key != "optimization_score" and len(rows) >= DATASET_DISPLAY_LIMITS[dataset_key]
                        else "available"
                    )
                    dataset.write({
                        "state": state, "row_count": len(rows), "last_sync_at": fetched_at,
                        "last_error_code": False,
                    })
                    total_rows += len(rows)
            except Exception as error:
                failed += 1
                error_text = str(error).lower()
                state = "not_supported" if "not supported" in error_text or "unsupported" in error_text else "query_failed"
                dataset.write({
                    "state": state, "last_sync_at": fields.Datetime.now(),
                    "last_error_code": "google_read_rejected",
                })
        run.write({
            "state": "succeeded" if not failed else "partial",
            "finished_at": fields.Datetime.now(), "row_count": total_rows,
            "error_code": "detail_query_failed" if failed else False,
        })


class GadsDailyFact(models.Model):
    _name = "baseer.gads.daily.fact"
    _description = "Google Ads daily campaign fact"
    _order = "metric_date desc, campaign_name, id"

    _gads_daily_fact_unique = models.Constraint(
        "unique(connection_id, campaign_id, metric_date)", "A daily campaign fact already exists."
    )

    connection_id = fields.Many2one("baseer.gads.connection", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="connection_id.company_id", store=True, index=True)
    customer_id = fields.Char(required=True, index=True, readonly=True)
    campaign_id = fields.Char(required=True, index=True, readonly=True)
    campaign_name = fields.Char(required=True, readonly=True)
    campaign_status = fields.Char(required=True, index=True, readonly=True)
    metric_date = fields.Date(required=True, index=True, readonly=True)
    impressions = GadsBigInteger(required=True, readonly=True)
    clicks = GadsBigInteger(required=True, readonly=True)
    cost_micros = GadsBigInteger(required=True, readonly=True)
    conversions_scaled = GadsBigInteger(required=True, readonly=True)
    conversion_value_scaled = GadsBigInteger(required=True, readonly=True)


class GadsDataset(models.Model):
    """Status and freshness ledger for each bounded Google Ads resource."""

    _name = "baseer.gads.dataset"
    _description = "Google Ads detailed dataset"
    _order = "connection_id, dataset_key"

    _gads_dataset_unique = models.Constraint(
        "unique(connection_id, dataset_key)", "A Google Ads dataset already exists for this connection."
    )

    connection_id = fields.Many2one("baseer.gads.connection", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="connection_id.company_id", store=True, index=True)
    dataset_key = fields.Selection([
        ("campaigns", "Campaigns"), ("ads", "Ads"), ("keywords", "Keywords"),
        ("search_terms", "Search terms"), ("conversion_actions", "Conversion actions"),
        ("conversion_performance", "Conversion performance"),
        ("opportunities", "Opportunities"), ("devices", "Devices"), ("day_hours", "Day and hour"),
        ("networks", "Networks"), ("locations", "Locations"), ("recommendations", "Recommendations"),
        ("smart_search_terms", "Smart campaign search terms"),
        ("pmax_search_terms", "Performance Max search terms"),
        ("campaign_negatives", "Campaign negative keywords"),
        ("ad_group_negatives", "Ad group negative keywords"),
        ("optimization_score", "Optimization score"), ("pmax_asset_groups", "Performance Max asset groups"),
        ("recent_changes", "Recent changes"),
    ], required=True, index=True, readonly=True)
    state = fields.Selection([
        ("pending", "Pending"), ("available", "Available"), ("no_data", "No data"),
        ("limited", "Limited by safe display limit"), ("not_supported", "Not supported"),
        ("query_failed", "Query failed"),
    ], required=True, default="pending", index=True, readonly=True)
    row_count = fields.Integer(readonly=True)
    last_sync_at = fields.Datetime(readonly=True)
    last_error_code = fields.Char(readonly=True)


class GadsDatasetRow(models.Model):
    """Normalized presentation row, with the original Google API payload retained."""

    _name = "baseer.gads.dataset.row"
    _description = "Google Ads detailed dataset row"
    _order = "fetched_at desc, impressions desc, clicks desc, id desc"

    _gads_dataset_row_unique = models.Constraint(
        "unique(dataset_id, external_id)", "A Google Ads dataset row already exists."
    )

    dataset_id = fields.Many2one("baseer.gads.dataset", required=True, ondelete="cascade", index=True)
    connection_id = fields.Many2one(related="dataset_id.connection_id", store=True, index=True)
    company_id = fields.Many2one(related="dataset_id.company_id", store=True, index=True)
    external_id = fields.Char(required=True, index=True, readonly=True)
    campaign_id = fields.Char(index=True, readonly=True)
    campaign_name = fields.Char(readonly=True)
    title = fields.Char(required=True, readonly=True)
    subtitle = fields.Char(readonly=True)
    status = fields.Char(index=True, readonly=True)
    impressions = GadsBigInteger(readonly=True)
    clicks = GadsBigInteger(readonly=True)
    cost_micros = GadsBigInteger(readonly=True)
    conversions_scaled = GadsBigInteger(readonly=True)
    conversion_value_scaled = GadsBigInteger(readonly=True)
    payload = fields.Json(readonly=True)
    fetched_at = fields.Datetime(required=True, readonly=True, index=True)


class GadsDailyCoverage(models.Model):
    _name = "baseer.gads.daily.coverage"
    _description = "Google Ads daily coverage"
    _order = "metric_date desc"

    _gads_coverage_unique = models.Constraint("unique(connection_id, metric_date)", "Daily coverage already exists.")
    connection_id = fields.Many2one("baseer.gads.connection", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="connection_id.company_id", store=True, index=True)
    metric_date = fields.Date(required=True, index=True)
    state = fields.Selection([("available", "Available"), ("no_data", "No data"),
                              ("not_supported", "Not supported"), ("query_failed", "Query failed")],
                             required=True, default="available", index=True)
    sync_run_id = fields.Many2one("baseer.gads.sync.run", ondelete="set null")


class GadsSyncRun(models.Model):
    _name = "baseer.gads.sync.run"
    _description = "Google Ads synchronization run"
    _order = "create_date desc, id desc"

    connection_id = fields.Many2one("baseer.gads.connection", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="connection_id.company_id", store=True, index=True)
    kind = fields.Selection([
        ("recent", "Recent refresh"), ("detail", "Detailed refresh"),
        ("backfill", "Historical backfill"),
    ], required=True)
    state = fields.Selection([("running", "Running"), ("succeeded", "Succeeded"),
                              ("partial", "Partial"), ("failed", "Failed")], required=True, default="running")
    started_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    finished_at = fields.Datetime(readonly=True)
    row_count = fields.Integer(readonly=True)
    error_code = fields.Char(readonly=True)


class GadsAudit(models.Model):
    _name = "baseer.gads.audit"
    _description = "Google Ads safety audit"
    _order = "create_date desc, id desc"

    company_id = fields.Many2one("res.company", required=True, index=True)
    connection_id = fields.Many2one("baseer.gads.connection", ondelete="set null", index=True)
    event = fields.Char(required=True, index=True)
    detail = fields.Char(copy=False)


class GadsDashboard(models.AbstractModel):
    _name = "baseer.gads.dashboard"
    _description = "Google Ads dashboard read contract"

    @api.model
    def get_dashboard_data(self, connection_id=False, date_from=False, date_to=False,
                           campaign_status="ALL", campaign_id=False, ad_status="ALL",
                           timeline_grain="day", timeline_metric="cost",
                           compare_previous=False):
        if not self.env.user.has_group("baseer_google_ads.group_gads_reader"):
            raise AccessError(_("You do not have access to Google Ads reporting."))
        today = fields.Date.context_today(self)
        start = fields.Date.to_date(date_from) if date_from else today - timedelta(days=29)
        end = fields.Date.to_date(date_to) if date_to else today
        if start > end or (end - start).days > MAX_REPORT_DAYS:
            raise ValidationError(_("Choose a report period from one to 731 days."))
        if timeline_grain not in {"day", "month", "year"}:
            raise ValidationError(_("Choose a supported timeline grouping."))
        timeline_metrics = {
            "cost", "impressions", "clicks", "ctr", "cpc",
            "google_conversions", "cpa",
        }
        if timeline_metric not in timeline_metrics:
            raise ValidationError(_("Choose a supported timeline metric."))
        available_connections = self.env["baseer.gads.connection"].search([("state", "!=", "disabled")])
        connections = available_connections
        if connection_id:
            try:
                requested_connection_id = int(connection_id)
            except (TypeError, ValueError):
                raise ValidationError(_("Choose an available Google Ads account."))
            connections = connections.filtered(lambda item: item.id == requested_connection_id)
        elif len(connections) > 1:
            # A report must never silently blend unrelated advertising accounts.
            connections = connections[:1]
        if not connections:
            raise AccessError(_("This Google Ads connection is not available to you."))
        base_domain = [("connection_id", "in", connections.ids), ("metric_date", ">=", start), ("metric_date", "<=", end)]
        base_facts = self.env["baseer.gads.daily.fact"].search(base_domain)
        campaign_totals = {}
        for fact in base_facts:
            campaign = campaign_totals.setdefault(fact.campaign_id, {
                "id": fact.campaign_id, "name": fact.campaign_name,
                "status": fact.campaign_status, "last_date": fact.metric_date,
                "impressions": 0, "clicks": 0, "cost_micros": 0,
                "conversions_scaled": 0, "conversion_value_scaled": 0,
            })
            if fact.metric_date >= campaign["last_date"]:
                campaign.update({"name": fact.campaign_name, "status": fact.campaign_status, "last_date": fact.metric_date})
            for key in ("impressions", "clicks", "cost_micros", "conversions_scaled", "conversion_value_scaled"):
                campaign[key] += getattr(fact, key)
        # The detailed campaign view is the most recent source for its current
        # status.  It may legitimately include a new campaign with no activity
        # in the selected period, which must still be visible to the owner.
        current_campaign_rows = self.env["baseer.gads.dataset.row"].search([
            ("connection_id", "in", connections.ids), ("dataset_id.dataset_key", "=", "campaigns"),
        ])
        for row in current_campaign_rows:
            if not row.campaign_id:
                continue
            campaign = campaign_totals.setdefault(row.campaign_id, {
                "id": row.campaign_id, "name": row.title or row.campaign_id,
                "status": row.status or "UNKNOWN", "last_date": False,
                "impressions": 0, "clicks": 0, "cost_micros": 0,
                "conversions_scaled": 0, "conversion_value_scaled": 0,
            })
            campaign.update({"name": row.title or campaign["name"], "status": row.status or campaign["status"]})
        all_campaigns = sorted(campaign_totals.values(), key=lambda item: (item["name"] or "").lower())
        available_campaign_statuses = {item["status"] for item in all_campaigns if item["status"]}
        if campaign_status and campaign_status not in {"ALL", *available_campaign_statuses}:
            raise ValidationError(_("Choose an available campaign status."))
        if campaign_id and str(campaign_id) not in {item["id"] for item in all_campaigns}:
            raise ValidationError(_("Choose a campaign from the selected Google Ads account."))
        ads_dataset = self.env["baseer.gads.dataset"].search([
            ("connection_id", "in", connections.ids), ("dataset_key", "=", "ads"),
        ], limit=1)
        available_ad_statuses = set()
        if ads_dataset:
            available_ad_statuses = set(self.env["baseer.gads.dataset.row"].search([
                ("dataset_id", "=", ads_dataset.id), ("status", "!=", False),
            ]).mapped("status"))
        if ad_status and ad_status not in {"ALL", *available_ad_statuses}:
            raise ValidationError(_("Choose an available ad status."))
        if campaign_status and campaign_status != "ALL":
            selected_campaigns = [item for item in all_campaigns if item["status"] == campaign_status]
        else:
            selected_campaigns = all_campaigns
        if campaign_id:
            selected_campaigns = [item for item in selected_campaigns if item["id"] == str(campaign_id)]
        selected_campaign_ids = {item["id"] for item in selected_campaigns}
        facts = base_facts.filtered(lambda item: item.campaign_id in selected_campaign_ids)
        totals = {key: 0 for key in ("impressions", "clicks", "cost_micros", "conversions_scaled", "conversion_value_scaled")}
        per_day = {}
        previous_totals = {key: 0 for key in totals}
        previous_per_day = {}

        def bucket_key(metric_date):
            if timeline_grain == "year":
                return str(metric_date.year)
            if timeline_grain == "month":
                return "%04d-%02d" % (metric_date.year, metric_date.month)
            return fields.Date.to_string(metric_date)

        def add_fact(target_totals, target_buckets, fact):
            point_key = bucket_key(fact.metric_date)
            bucket = target_buckets.setdefault(point_key, {key: 0 for key in target_totals})
            for key in target_totals:
                value = getattr(fact, key)
                target_totals[key] += value
                bucket[key] += value

        for fact in facts:
            add_fact(totals, per_day, fact)
        previous_period = False
        if compare_previous:
            period_days = (end - start).days + 1
            previous_end = start - timedelta(days=1)
            previous_start = previous_end - timedelta(days=period_days - 1)
            previous_period = {"from": fields.Date.to_string(previous_start), "to": fields.Date.to_string(previous_end)}
            previous_facts = self.env["baseer.gads.daily.fact"].search([
                ("connection_id", "in", connections.ids),
                ("metric_date", ">=", previous_start),
                ("metric_date", "<=", previous_end),
                ("campaign_id", "in", list(selected_campaign_ids)),
            ])
            for fact in previous_facts:
                add_fact(previous_totals, previous_per_day, fact)
        coverage = self.env["baseer.gads.daily.coverage"].search_count([
            ("connection_id", "in", connections.ids), ("metric_date", ">=", start), ("metric_date", "<=", end),
            ("state", "=", "available"),
        ])
        if previous_period:
            previous_period.update({
                "covered_days": self.env["baseer.gads.daily.coverage"].search_count([
                    ("connection_id", "in", connections.ids),
                    ("metric_date", ">=", previous_start), ("metric_date", "<=", previous_end),
                    ("state", "=", "available"),
                ]),
                "total_days": (previous_end - previous_start).days + 1,
            })
        def ratio(numerator, denominator):
            return Decimal(numerator) * Decimal("100") / Decimal(denominator) if denominator else Decimal(0)
        ctr = ratio(totals["clicks"], totals["impressions"])
        cpc = Decimal(totals["cost_micros"]) / Decimal(totals["clicks"] or 1) / Decimal(1000000)
        cost = Decimal(totals["cost_micros"]) / Decimal(1000000)
        conversion_value = _scaled_to_decimal(totals["conversion_value_scaled"])
        def series_contract(day, values, position):
            if values is None:
                return {
                    "date": day, "position": position, "has_data": False,
                    "impressions": False, "clicks": False, "cost": False,
                    "ctr": False, "cpc": False, "conversions": False,
                    "google_conversions": False, "cpa": False,
                }
            point_cost = Decimal(values["cost_micros"]) / Decimal(1000000)
            point_conversions = _scaled_to_decimal(values["conversions_scaled"])
            point_ctr = ratio(values["clicks"], values["impressions"])
            point_cpc = point_cost / Decimal(values["clicks"]) if values["clicks"] else None
            point_cpa = point_cost / point_conversions if point_conversions else None
            return {
                "date": day, "position": position, "has_data": True,
                "impressions": str(values["impressions"]),
                "clicks": str(values["clicks"]),
                "cost": _display_decimal(point_cost),
                "ctr": _display_decimal(point_ctr),
                "cpc": _display_decimal(point_cpc) if point_cpc is not None else False,
                "conversions": _display_decimal(point_conversions, 2),
                "google_conversions": _display_decimal(point_conversions, 2),
                "cpa": _display_decimal(point_cpa) if point_cpa is not None else False,
            }

        def timeline_buckets(first, last):
            buckets = []
            if timeline_grain == "day":
                cursor = first
                while cursor <= last:
                    buckets.append(fields.Date.to_string(cursor))
                    cursor += timedelta(days=1)
            elif timeline_grain == "month":
                cursor = first.replace(day=1)
                last_month = last.replace(day=1)
                while cursor <= last_month:
                    buckets.append("%04d-%02d" % (cursor.year, cursor.month))
                    cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
            else:
                for year in range(first.year, last.year + 1):
                    buckets.append(str(year))
            return buckets

        series = [
            series_contract(day, per_day.get(day), position)
            for position, day in enumerate(timeline_buckets(start, end))
        ]
        comparison_series = [
            series_contract(day, previous_per_day.get(day), position)
            for position, day in enumerate(timeline_buckets(previous_start, previous_end))
        ] if previous_period else []
        Dataset = self.env["baseer.gads.dataset"].search([
            ("connection_id", "in", connections.ids),
        ])
        datasets = {}
        for dataset in Dataset:
            row_domain = [("dataset_id", "=", dataset.id)]
            if campaign_id:
                row_domain.append(("campaign_id", "=", str(campaign_id)))
            elif campaign_status and campaign_status != "ALL":
                row_domain.append(("campaign_id", "in", list(selected_campaign_ids)))
            if dataset.dataset_key == "ads" and ad_status and ad_status != "ALL":
                row_domain.append(("status", "=", ad_status))
            rows = self.env["baseer.gads.dataset.row"].search(row_domain, limit=250)
            def row_contract(row):
                return {
                    "id": row.id, "title": row.title, "subtitle": row.subtitle or False,
                    "status": row.status or False, "campaign": row.campaign_name or False,
                    "campaign_id": row.campaign_id or False,
                    "impressions": str(row.impressions), "clicks": str(row.clicks),
                    "cost": _display_decimal(Decimal(row.cost_micros) / Decimal(1000000)),
                    "conversions": _display_decimal(_scaled_to_decimal(row.conversions_scaled)),
                    "conversion_value": _display_decimal(_scaled_to_decimal(row.conversion_value_scaled)),
                }
            datasets[dataset.dataset_key] = {
                "state": dataset.state, "row_count": self.env["baseer.gads.dataset.row"].search_count(row_domain),
                "source_row_count": dataset.row_count,
                "last_sync": fields.Datetime.to_string(dataset.last_sync_at) if dataset.last_sync_at else False,
                "rows": [row_contract(row) for row in rows],
            }
        for dataset_key in FULL_DATASET_QUERIES:
            datasets.setdefault(dataset_key, {
                "state": "pending", "row_count": 0, "source_row_count": 0,
                "last_sync": False, "rows": [],
            })
        insights = []
        if totals["cost_micros"] > 0 and totals["conversions_scaled"] == 0:
            insights.append({"level": "attention", "title": _("Spend without Google-reported conversions"), "detail": "spend_without_conversion"})
        for row in datasets["keywords"]["rows"]:
            if Decimal(row["cost"]) > 0 and row["conversions"] == "0.00":
                insights.append({"level": "watch", "title": row["title"], "detail": "keyword_spend_without_conversion"})
        for row in datasets["ads"]["rows"]:
            if row["status"] in ("DISAPPROVED", "NOT_ELIGIBLE"):
                insights.append({"level": "attention", "title": row["title"], "detail": "ad_policy_or_eligibility"})
        for row in datasets["recommendations"]["rows"]:
            insights.append({"level": "recommendation", "title": row["title"], "detail": "google_recommendation"})
        datasets["insights"] = {
            "state": "available" if insights else "no_data", "row_count": len(insights),
            "last_sync": max((item.get("last_sync") or "" for item in datasets.values()), default=False) or False,
            "rows": insights[:250],
        }
        active_campaigns = [item for item in all_campaigns if item["status"] == "ENABLED"]
        paused_campaigns = [item for item in all_campaigns if item["status"] == "PAUSED"]
        latest_active_campaign = max(
            (item for item in active_campaigns if item["last_date"]),
            key=lambda item: item["last_date"], default=False,
        )
        def campaign_contract(item):
            return {
                "id": item["id"], "name": item["name"], "status": item["status"],
                "last_activity": fields.Date.to_string(item["last_date"]) if item["last_date"] else False,
                "impressions": str(item["impressions"]), "clicks": str(item["clicks"]),
                "cost": _display_decimal(Decimal(item["cost_micros"]) / Decimal(1000000)),
                "conversions": _display_decimal(_scaled_to_decimal(item["conversions_scaled"])),
            }
        return {
            "connections": [{"id": item.id, "name": item.name, "state": item.state,
                             "last_sync": fields.Datetime.to_string(item.last_sync_at) if item.last_sync_at else False}
                            for item in available_connections],
            "selected_connection_id": connections.id,
            "period": {"from": fields.Date.to_string(start), "to": fields.Date.to_string(end),
                       "covered_days": coverage, "total_days": (end - start).days + 1},
            "summary": {"impressions": str(totals["impressions"]), "clicks": str(totals["clicks"]),
                        "cost": _display_decimal(cost), "ctr": _display_decimal(ctr), "cpc": _display_decimal(cpc),
                        "google_conversions": _display_decimal(_scaled_to_decimal(totals["conversions_scaled"])),
                        "google_conversion_value": _display_decimal(conversion_value)},
            "series": series, "comparison_series": comparison_series,
            "timeline": {
                "metric": timeline_metric,
                "grain": timeline_grain,
                "comparison_enabled": bool(compare_previous),
                "comparison_period": previous_period,
            },
            "datasets": datasets, "read_only": True,
            "filters": {
                "campaigns": [campaign_contract(item) for item in all_campaigns[:250]],
                "campaign_statuses": sorted(available_campaign_statuses),
                "ad_statuses": sorted(available_ad_statuses),
            },
            "operational": {
                "active_campaigns": len(active_campaigns), "paused_campaigns": len(paused_campaigns),
                "total_campaigns": len(all_campaigns), "alerts": len(insights),
                "keyword_watch": sum(1 for item in insights if item["detail"] == "keyword_spend_without_conversion"),
                "ad_issues": sum(1 for item in insights if item["detail"] == "ad_policy_or_eligibility"),
                "latest_active_campaign": campaign_contract(latest_active_campaign) if latest_active_campaign else False,
            },
            "selected_filters": {"campaign_status": campaign_status or "ALL", "campaign_id": str(campaign_id) if campaign_id else False,
                                 "ad_status": ad_status or "ALL", "timeline_grain": timeline_grain,
                                 "timeline_metric": timeline_metric,
                                 "compare_previous": bool(compare_previous)},
        }
