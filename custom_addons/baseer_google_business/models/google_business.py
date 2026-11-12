"""Google Business Profile operational models.

This module deliberately keeps credentials out of Odoo configuration and the
normal user interface.  The one-time legacy credential import is an operator
runbook action, executed server-side with the production secret manager; it
does not accept tokens from a browser or a CSV file.
"""

import base64
import hashlib
import json
import os
import re
from datetime import date, timedelta, timezone
from datetime import datetime as python_datetime
from decimal import Decimal, ROUND_HALF_UP

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


GOOGLE_OAUTH_ORIGIN = "https://oauth2.googleapis.com"
GOOGLE_BUSINESS_ORIGIN = "https://mybusiness.googleapis.com"
GOOGLE_INFO_ORIGIN = "https://mybusinessbusinessinformation.googleapis.com"
GOOGLE_PERFORMANCE_ORIGIN = "https://businessprofileperformance.googleapis.com"
REQUEST_TIMEOUT_SECONDS = 20
SYNC_COOLDOWN_SECONDS = 60
POLICY_VERSION = "legacy-reply-policy-2026-09-20"
GOOGLE_TRANSLATION_TRAILER = re.compile(
    r"(?:\r?\n)+\s*\(Translated by Google\)\s*.*\Z",
    re.IGNORECASE | re.DOTALL,
)
GOOGLE_TRANSLATION_PREFIX = re.compile(
    r"^\s*\(Translated by Google\)\s*.*?(?:\r?\n)+\s*\(Original\)\s*(.*)\Z",
    re.IGNORECASE | re.DOTALL,
)


def _original_google_review_text(value):
    """Keep only the reviewer text, excluding Google's appended translation."""
    if not value:
        return False
    translated_first = GOOGLE_TRANSLATION_PREFIX.match(value)
    if translated_first:
        return translated_first.group(1).strip() or False
    return GOOGLE_TRANSLATION_TRAILER.sub("", value).rstrip() or False


def _environment_secret(name):
    """Read a secret from the Odoo-only mount, then compatible env fallbacks."""
    secret_dir = os.environ.get("BASEER_SECRET_DIR", "/run/baseer-google-secrets")
    for candidate in (name + "_B64", name):
        path = os.path.join(secret_dir, candidate)
        try:
            with open(path, "r", encoding="utf-8") as secret_file:
                stored = secret_file.read().strip()
        except FileNotFoundError:
            continue
        if candidate.endswith("_B64"):
            try:
                return base64.b64decode(stored, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise UserError(_("Google Business server credential configuration is invalid.")) from exc
        if stored:
            return stored
    encoded = os.environ.get(name + "_B64")
    if encoded:
        try:
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise UserError(_("Google Business server credential configuration is invalid.")) from exc
    return os.environ.get(name)


def _master_key():
    """Return a stable AES-256 key without exposing or persisting the secret."""
    raw = _environment_secret("BASEER_GBP_CREDENTIAL_MASTER_KEY")
    if not raw:
        raise UserError(_("Google Business credentials are not configured on this server."))
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _google_writes_are_environmentally_allowed():
    """A database flag can never turn QA into a Google writer by itself.

    Production must deliberately set both variables; every other environment,
    including a missing or malformed configuration, remains read-only.
    """
    environment = os.environ.get("BASEER_GBP_ENVIRONMENT", "").strip().lower()
    allow_writes = os.environ.get("BASEER_GBP_WRITES_ALLOWED", "").strip().lower()
    return environment == "production" and allow_writes in {"1", "true", "yes", "on"}


def _encrypt_secret(value):
    nonce = os.urandom(12)
    encrypted = AESGCM(_master_key()).encrypt(nonce, value.encode("utf-8"), None)
    return base64.b64encode(nonce).decode(), base64.b64encode(encrypted).decode()


def _decrypt_secret(nonce, encrypted):
    try:
        return AESGCM(_master_key()).decrypt(
            base64.b64decode(nonce), base64.b64decode(encrypted), None
        ).decode("utf-8")
    except Exception as exc:  # no secret or provider response is ever logged
        raise UserError(_("Stored Google Business credentials cannot be decrypted.")) from exc


def _google_datetime(value):
    """Convert RFC 3339 timestamps returned by Google to Odoo's UTC datetime."""
    if not value:
        return False
    try:
        parsed = python_datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError):
        return False


class GbpConnection(models.Model):
    _name = "baseer.gbp.connection"
    _description = "Google Business credential connection"
    _order = "company_id, name"

    _gbp_connection_external_unique = models.Constraint(
        "unique(external_connection_id)", "The legacy Google connection can only be imported once."
    )

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, index=True,
                                 default=lambda self: self.env.company)
    external_connection_id = fields.Char(required=True, index=True, copy=False)
    external_account_id = fields.Char(required=True, index=True, copy=False)
    state = fields.Selection([
        ("pending", "Pending secure import"),
        ("active", "Active"),
        ("attention", "Needs re-authorization"),
        ("disabled", "Disabled"),
    ], default="pending", required=True, index=True)
    writer_enabled = fields.Boolean(
        default=False, copy=False,
        help="Safety fence. A migrated connection starts read-only.")
    token_ciphertext = fields.Text(copy=False, groups="base.group_system", exportable=False)
    token_nonce = fields.Char(copy=False, groups="base.group_system", exportable=False)
    token_key_version = fields.Char(copy=False, groups="base.group_system", exportable=False)
    token_expires_at = fields.Datetime(copy=False, groups="base.group_system", exportable=False)
    last_read_sync_at = fields.Datetime(copy=False)
    last_error_at = fields.Datetime(copy=False)
    last_error_code = fields.Char(copy=False)

    def _require_system(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only a system administrator can operate connection credentials."))

    def _require_secure_importer(self):
        """Keep credential writes outside every browser/RPC identity.

        A Baseer owner is intentionally a system administrator for normal Odoo
        administration.  That must not make a forged RPC context equivalent to
        the one-time server-side importer.  The importer runs as Odoo's
        superuser in a controlled server process, so require that exact uid in
        addition to the private context marker below.
        """
        if self.env.uid != SUPERUSER_ID:
            raise AccessError(_("Google credentials can only be changed by the secure server-side importer."))

    def write(self, values):
        protected = {"token_ciphertext", "token_nonce", "token_key_version"}
        if protected.intersection(values):
            self._require_secure_importer()
            if not self.env.context.get("gbp_internal_secret_write"):
                raise AccessError(_("Google credentials can only be changed by the secure server-side importer."))
        writer_changed = "writer_enabled" in values
        if writer_changed:
            self._require_system()
            if values["writer_enabled"] and not _google_writes_are_environmentally_allowed():
                raise AccessError(_("Google reply publishing is locked by this environment."))
        result = super().write(values)
        if writer_changed and not self.env.context.get("gbp_internal_writer_audit"):
            for record in self:
                self.env["baseer.gbp.audit"].sudo().create({
                    "company_id": record.company_id.id,
                    "connection_id": record.id,
                    "event": "writer_%s" % ("enabled" if record.writer_enabled else "disabled"),
                    "detail": "Writer setting changed by a system administrator.",
                })
        return result

    def _secure_import_refresh_token(self, refresh_token, key_version="v1"):
        """Internal server-side importer only; never expose through an RPC view."""
        self._require_secure_importer()
        if not refresh_token:
            raise ValidationError(_("A refresh token is required for a secure import."))
        for record in self:
            nonce, ciphertext = _encrypt_secret(refresh_token)
            record.with_context(gbp_internal_secret_write=True).write({
                "token_nonce": nonce,
                "token_ciphertext": ciphertext,
                "token_key_version": key_version,
                "state": "active",
                "last_error_at": False,
                "last_error_code": False,
            })
            self.env["baseer.gbp.audit"].sudo().create({
                "company_id": record.company_id.id,
                "connection_id": record.id,
                "event": "credential_imported",
                "detail": "Server-side credential import completed.",
            })
        return True

    def _refresh_access_token(self):
        self.ensure_one()
        if self.state != "active" or not self.token_ciphertext or not self.token_nonce:
            raise UserError(_("This Google Business connection is not ready for read-only sync."))
        client_id = _environment_secret("BASEER_GBP_GOOGLE_CLIENT_ID")
        client_secret = _environment_secret("BASEER_GBP_GOOGLE_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise UserError(_("Google OAuth client credentials are not configured on this server."))
        refresh_token = _decrypt_secret(self.token_nonce, self.token_ciphertext)
        try:
            response = requests.post(
                GOOGLE_OAUTH_ORIGIN + "/token",
                data={"grant_type": "refresh_token", "client_id": client_id,
                      "client_secret": client_secret, "refresh_token": refresh_token},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise UserError(_("Google OAuth is temporarily unavailable.")) from exc
        if response.status_code != 200:
            # invalid refresh grants must stop, never silently fall back to another account
            self.sudo().write({"state": "attention", "last_error_at": fields.Datetime.now(),
                               "last_error_code": "oauth_refresh_rejected"})
            raise UserError(_("Google authorization needs to be renewed by an administrator."))
        body = response.json()
        access_token = body.get("access_token")
        if not access_token:
            raise UserError(_("Google OAuth did not return an access token."))
        expires = int(body.get("expires_in", 0))
        self.sudo().write({"token_expires_at": fields.Datetime.now() + timedelta(seconds=expires)})
        return access_token

    def _read_token(self):
        """Used by a trusted server workflow; no caller receives the token."""
        self.ensure_one()
        return self.sudo()._refresh_access_token()

    def _writer_is_allowed(self):
        self.ensure_one()
        return bool(self.writer_enabled and _google_writes_are_environmentally_allowed())


class GbpLocation(models.Model):
    _name = "baseer.gbp.location"
    _description = "Google Business location"
    _order = "company_id, name"

    _gbp_location_resource_unique = models.Constraint(
        "unique(external_location_id)", "A Google review location can only belong to one Baseer company."
    )

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, index=True,
                                 default=lambda self: self.env.company)
    connection_id = fields.Many2one("baseer.gbp.connection", required=True,
                                    ondelete="restrict", index=True)
    external_location_id = fields.Char(required=True, index=True,
                                       help="Exact Google reviews resource, never inferred.")
    google_location_name = fields.Char(index=True, help="Google Business Information resource.")
    google_place_id = fields.Char(index=True)
    state = fields.Selection([
        ("draft", "Draft"), ("connected", "Connected"), ("attention", "Needs attention")
    ], default="draft", required=True, index=True)
    active = fields.Boolean(default=True)
    average_rating = fields.Float(readonly=True)
    total_review_count = fields.Integer(readonly=True)
    profile_address = fields.Text(readonly=True, copy=False)
    profile_phone = fields.Char(readonly=True, copy=False)
    profile_website = fields.Char(readonly=True, copy=False)
    profile_hours = fields.Text(readonly=True, copy=False)
    last_source_sync_at = fields.Datetime(readonly=True)
    last_sync_started_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, values_list):
        protected = {"company_id", "connection_id", "external_location_id", "google_location_name", "google_place_id"}
        if any(protected.intersection(values) for values in values_list) and not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only a system administrator can map a Google Business location."))
        return super().create(values_list)

    def write(self, values):
        protected = {"company_id", "connection_id", "external_location_id", "google_location_name", "google_place_id"}
        if protected.intersection(values) and not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only a system administrator can change Google Business mapping."))
        return super().write(values)

    @api.constrains("company_id", "connection_id")
    def _check_connection_company(self):
        for record in self:
            if record.connection_id and record.connection_id.company_id != record.company_id:
                raise ValidationError(_("A location and its Google connection must belong to the same company."))

    def _require_reader(self):
        if not self.env.user.has_group("baseer_google_business.group_gbp_reader"):
            raise AccessError(_("You do not have access to Google Business data."))

    @api.model
    def get_dashboard_data(self, location_id=False):
        """Return a bounded, read-only dashboard contract for the current user.

        The browser receives prepared display values and a maximum of 30 daily
        points. It never receives OAuth configuration, credentials, or an
        unbounded review dataset.
        """
        self._require_reader()
        today = fields.Date.context_today(self)
        start = today - timedelta(days=29)
        locations = self.search([("active", "=", True)])
        selected = locations
        if location_id:
            selected = locations.filtered(lambda location: location.id == int(location_id))
            if not selected:
                raise AccessError(_("This Google Business location is not available to you."))

        def display_number(value, decimals=0):
            quantizer = Decimal("1") if not decimals else Decimal("1." + ("0" * decimals))
            return format(Decimal(str(value or 0)).quantize(quantizer, rounding=ROUND_HALF_UP), "f")

        def percentage(numerator, denominator):
            if not denominator:
                return "0.0"
            value = (Decimal(numerator) * Decimal("100")) / Decimal(denominator)
            return display_number(value, 1)

        review_domain = [("location_id", "in", selected.ids)]
        Review = self.env["baseer.gbp.review"]
        review_count = Review.search_count(review_domain)
        replied_count = Review.search_count(review_domain + [("has_google_reply", "=", True)])
        unanswered_count = Review.search_count(review_domain + [("has_google_reply", "=", False)])
        manual_count = Review.search_count(review_domain + [
            ("has_google_reply", "=", False), ("star_rating", "<=", 3),
        ])

        metric_values = {key: 0 for key in ("impressions", "website_clicks", "calls", "directions")}
        dates = [start + timedelta(days=offset) for offset in range(30)]
        daily_values = {
            metric_date: {key: 0 for key in metric_values}
            for metric_date in dates
        }
        month_index = today.year * 12 + today.month - 1
        month_starts = [
            date((month_index - offset) // 12, (month_index - offset) % 12 + 1, 1)
            for offset in range(11, -1, -1)
        ]
        monthly_values = {
            month_start: {key: 0 for key in metric_values}
            for month_start in month_starts
        }
        metrics = self.env["baseer.gbp.metric"].search([
            ("location_id", "in", selected.ids), ("metric_date", ">=", month_starts[0]),
            ("metric_date", "<=", today),
        ])
        for metric in metrics:
            month_start = metric.metric_date.replace(day=1)
            if month_start in monthly_values:
                monthly_values[month_start][metric.metric_key] += metric.value
            if metric.metric_date in daily_values:
                metric_values[metric.metric_key] += metric.value
                daily_values[metric.metric_date][metric.metric_key] += metric.value

        max_impressions = max([daily_values[item]["impressions"] for item in dates] or [0])
        series = []
        for index, metric_date in enumerate(dates):
            values = daily_values[metric_date]
            series.append({
                "date": fields.Date.to_string(metric_date),
                "label": fields.Date.to_string(metric_date) if index in (0, 7, 14, 21, 29) else "",
                "impressions": display_number(values["impressions"]),
                "website_clicks": display_number(values["website_clicks"]),
                "calls": display_number(values["calls"]),
                "directions": display_number(values["directions"]),
                "impression_height": display_number(
                    (Decimal(values["impressions"]) * Decimal("100") / Decimal(max_impressions))
                    if max_impressions else 0
                ),
            })

        max_monthly_impressions = max([monthly_values[item]["impressions"] for item in month_starts] or [0])
        monthly_series = []
        for month_start in month_starts:
            values = monthly_values[month_start]
            monthly_series.append({
                "date": fields.Date.to_string(month_start),
                "label": fields.Date.to_string(month_start)[:7],
                "impressions": display_number(values["impressions"]),
                "website_clicks": display_number(values["website_clicks"]),
                "calls": display_number(values["calls"]),
                "directions": display_number(values["directions"]),
                "impression_height": display_number(
                    (Decimal(values["impressions"]) * Decimal("100") / Decimal(max_monthly_impressions))
                    if max_monthly_impressions else 0
                ),
            })

        recent_impressions = sum(daily_values[item]["impressions"] for item in dates[-7:])
        previous_impressions = sum(daily_values[item]["impressions"] for item in dates[-14:-7])
        if previous_impressions:
            trend_change = percentage(recent_impressions - previous_impressions, previous_impressions)
            trend_direction = "up" if recent_impressions > previous_impressions else (
                "down" if recent_impressions < previous_impressions else "flat"
            )
        else:
            trend_change = "0.0"
            trend_direction = "no_baseline"

        weighted_rating = sum(
            Decimal(str(location.average_rating or 0)) * Decimal(location.total_review_count or 0)
            for location in selected
        )
        total_location_reviews = sum(selected.mapped("total_review_count"))
        overall_rating = weighted_rating / Decimal(total_location_reviews) if total_location_reviews else Decimal("0")
        actions_total = metric_values["website_clicks"] + metric_values["calls"] + metric_values["directions"]
        last_syncs = [item for item in selected.mapped("last_source_sync_at") if item]

        return {
            "locations": [{
                "id": location.id,
                "name": location.name,
                "company_name": location.company_id.name,
                "state": location.state,
            } for location in locations],
            "selected_location_id": selected.id if len(selected) == 1 else False,
            "is_all_locations": not location_id,
            "has_source_data": bool(last_syncs or review_count or metrics or total_location_reviews),
            "can_sync": self.env.user.has_group("baseer_google_business.group_gbp_manager"),
            "summary": {
                "rating": display_number(overall_rating, 2),
                "reviews": display_number(review_count),
                "replied_reviews": display_number(replied_count),
                "reply_rate": percentage(replied_count, review_count),
                "profile_actions": display_number(actions_total),
                "impressions": display_number(metric_values["impressions"]),
                "website_clicks": display_number(metric_values["website_clicks"]),
                "calls": display_number(metric_values["calls"]),
                "directions": display_number(metric_values["directions"]),
                "unanswered_reviews": display_number(unanswered_count),
                "manual_reviews": display_number(manual_count),
                "last_sync": fields.Datetime.to_string(max(last_syncs)) if last_syncs else False,
            },
            "trend": {
                "direction": trend_direction,
                "change": trend_change,
                "recent_impressions": display_number(recent_impressions),
                "previous_impressions": display_number(previous_impressions),
            },
            "series": series,
            "monthly_series": monthly_series,
        }

    @api.model
    def get_dashboard_action(self, location_id, section):
        """Return a scoped native action without exposing another company."""
        self._require_reader()
        location = self.search([("id", "=", int(location_id))], limit=1)
        if not location:
            raise AccessError(_("This Google Business location is not available to you."))
        action_xmlid = {
            "profile": "baseer_google_business.action_gbp_locations",
            "reviews": "baseer_google_business.action_gbp_reviews",
            "replies": "baseer_google_business.action_gbp_outbox",
        }.get(section)
        if not action_xmlid:
            raise ValidationError(_("Unknown Google Business dashboard destination."))
        action = self.env["ir.actions.actions"]._for_xml_id(action_xmlid)
        action["domain"] = [("location_id", "=", location.id)] if section != "profile" else [("id", "=", location.id)]
        action["context"] = dict(self.env.context, default_location_id=location.id)
        return action

    def action_sync_read_only(self):
        """Read only. It never publishes a Google reply or enables a writer."""
        if not self.env.user.has_group("baseer_google_business.group_gbp_manager"):
            raise AccessError(_("Only a Google Business manager can refresh Google data."))
        for location in self:
            if location.company_id not in self.env.companies:
                raise AccessError(_("This location belongs to another company."))
            self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", [location.id])
            if not self.env.cr.fetchone()[0]:
                raise UserError(_("Google Business refresh is already running for this location."))
            now = fields.Datetime.now()
            if location.last_sync_started_at and location.last_sync_started_at >= now - timedelta(seconds=SYNC_COOLDOWN_SECONDS):
                raise UserError(_("Google Business was refreshed recently. Please wait one minute before trying again."))
            location.sudo().write({"last_sync_started_at": now})
            location.sudo()._sync_reviews_read_only()
            location.sudo()._sync_profile_read_only()
            location.sudo()._sync_metrics_read_only()
            self.env["baseer.gbp.audit"].sudo().create({
                "company_id": location.company_id.id,
                "location_id": location.id,
                "connection_id": location.connection_id.id,
                "event": "read_only_sync_completed",
                "detail": "Read-only Google Business refresh completed.",
            })
        return True

    def _sync_reviews_read_only(self):
        self.ensure_one()
        token = self.connection_id._read_token()
        next_page_token = False
        for _page in range(100):
            params = {"pageSize": 50}
            if next_page_token:
                params["pageToken"] = next_page_token
            try:
                response = requests.get(
                    GOOGLE_BUSINESS_ORIGIN + "/v4/{}/reviews".format(self.external_location_id),
                    headers={"Authorization": "Bearer " + token}, params=params,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise UserError(_("Google reviews are temporarily unavailable.")) from exc
            if response.status_code != 200:
                self.sudo().write({"state": "attention"})
                raise UserError(_("Google reviews could not be read for this location."))
            page = response.json()
            for payload in page.get("reviews", []):
                review_id = payload.get("reviewId")
                if not review_id:
                    continue
                rating = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}.get(payload.get("starRating"))
                if not rating:
                    continue
                values = {
                    "star_rating": rating,
                    "comment": _original_google_review_text(payload.get("comment")),
                    "external_update_time": _google_datetime(payload.get("updateTime")),
                    "has_google_reply": bool(payload.get("reviewReply")),
                    "remote_reply_text": (payload.get("reviewReply") or {}).get("comment") or False,
                }
                review = self.env["baseer.gbp.review"].search([
                    ("location_id", "=", self.id), ("external_review_id", "=", review_id)
                ], limit=1)
                if review:
                    review.with_context(gbp_internal_review_write=True).write(values)
                else:
                    values.update({"location_id": self.id, "external_review_id": review_id})
                    review = self.env["baseer.gbp.review"].with_context(gbp_internal_sync=True).create(values)
                review.action_classify()
            next_page_token = page.get("nextPageToken")
            if not next_page_token:
                break
        if next_page_token:
            self.sudo().write({"state": "attention"})
            raise UserError(_("Google returned more reviews than the safe refresh limit. Data was not marked fresh."))
        now = fields.Datetime.now()
        all_reviews = self.env["baseer.gbp.review"].search([("location_id", "=", self.id)])
        total = len(all_reviews)
        average = (sum(all_reviews.mapped("star_rating")) / total) if total else 0
        self.write({"last_source_sync_at": now, "state": "connected", "total_review_count": total,
                    "average_rating": average})
        self.connection_id.write({"last_read_sync_at": now})
        return True

    def _sync_profile_read_only(self):
        """Fetch profile summary and engagement metrics without changing Google."""
        self.ensure_one()
        if not self.google_location_name:
            return True
        token = self.connection_id._read_token()
        try:
            response = requests.get(
                GOOGLE_INFO_ORIGIN + "/v1/{}".format(self.google_location_name),
                headers={"Authorization": "Bearer " + token},
                params={"readMask": "name,title,storefrontAddress,phoneNumbers,websiteUri,regularHours,metadata"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise UserError(_("Google profile information is temporarily unavailable.")) from exc
        if response.status_code != 200:
            # Keep review data intact; profile fields are refreshed only after a valid response.
            return False
        payload = response.json()
        address = payload.get("storefrontAddress") or {}
        phone_numbers = payload.get("phoneNumbers") or {}
        self.write({
            "profile_address": ", ".join(filter(None, address.get("addressLines", []))) or False,
            "profile_phone": (phone_numbers.get("primaryPhone") or False),
            "profile_website": payload.get("websiteUri") or False,
            "profile_hours": json.dumps(payload.get("regularHours") or {}, ensure_ascii=False),
        })
        return True

    def _sync_metrics_read_only(self):
        """Load the last 30 days of Google engagement, never sales figures."""
        self.ensure_one()
        if not self.google_location_name:
            return True
        today = fields.Date.context_today(self)
        start = today - timedelta(days=29)
        google_metrics = {
            "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": "impressions",
            "BUSINESS_IMPRESSIONS_MOBILE_MAPS": "impressions",
            "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": "impressions",
            "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": "impressions",
            "BUSINESS_DIRECTION_REQUESTS": "directions",
            "CALL_CLICKS": "calls",
            "WEBSITE_CLICKS": "website_clicks",
        }
        params = []
        for metric in google_metrics:
            params.append(("dailyMetrics", metric))
        for prefix, value in (("dailyRange.startDate", start), ("dailyRange.endDate", today)):
            params.extend([
                (prefix + ".year", str(value.year)),
                (prefix + ".month", str(value.month)),
                (prefix + ".day", str(value.day)),
            ])
        try:
            response = requests.get(
                GOOGLE_PERFORMANCE_ORIGIN + "/v1/{}:fetchMultiDailyMetricsTimeSeries".format(
                    self.google_location_name
                ),
                headers={"Authorization": "Bearer " + self.connection_id._read_token()},
                params=params, timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            return False
        if response.status_code != 200:
            return False
        aggregates = {}
        for wrapper in response.json().get("multiDailyMetricTimeSeries", []):
            for series in wrapper.get("dailyMetricTimeSeries", []):
                metric_key = google_metrics.get(series.get("dailyMetric"))
                if not metric_key:
                    continue
                for point in (series.get("timeSeries") or {}).get("datedValues", []):
                    parts = point.get("date") or {}
                    try:
                        metric_date = date(int(parts["year"]), int(parts["month"]), int(parts["day"]))
                        value = int(point.get("value") or 0)
                    except (KeyError, TypeError, ValueError):
                        continue
                    key = (metric_key, metric_date)
                    aggregates[key] = aggregates.get(key, 0) + value
        Metric = self.env["baseer.gbp.metric"]
        for (metric_key, metric_date), value in aggregates.items():
            metric = Metric.search([
                ("location_id", "=", self.id), ("metric_key", "=", metric_key),
                ("metric_date", "=", metric_date),
            ], limit=1)
            if metric:
                metric.write({"value": value})
            else:
                Metric.create({"location_id": self.id, "metric_key": metric_key,
                               "metric_date": metric_date, "value": value})
        return True


class GbpReplyPolicy(models.Model):
    _name = "baseer.gbp.reply.policy"
    _description = "Google review reply policy"

    _gbp_policy_location_unique = models.Constraint(
        "unique(location_id)", "Only one reply policy is allowed per location."
    )

    location_id = fields.Many2one("baseer.gbp.location", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="location_id.company_id", store=True, index=True)
    auto_reply_enabled = fields.Boolean(default=False)
    explicit_consent_at = fields.Datetime(copy=False, readonly=True)
    explicit_consent_by = fields.Many2one("res.users", copy=False, readonly=True)
    consent_version = fields.Char(copy=False, readonly=True)
    four_five_action = fields.Selection([("manual", "Manual"), ("auto", "Automatic")],
                                        default="manual", required=True)
    low_rating_action = fields.Selection([("manual", "Manual")], default="manual", required=True)
    max_batch_size = fields.Integer(default=20, required=True)
    freshness_hours = fields.Integer(default=12, required=True)

    _consent_controlled_fields = {
        "auto_reply_enabled", "explicit_consent_at", "explicit_consent_by", "consent_version",
    }

    def write(self, values):
        if (self._consent_controlled_fields.intersection(values)
                and not self.env.context.get("gbp_internal_policy_consent")
                and not self.env.is_superuser()):
            raise AccessError(_("Automatic-reply consent can only be recorded by the approved workflow."))
        return super().write(values)

    @api.constrains("auto_reply_enabled", "explicit_consent_at", "consent_version", "four_five_action",
                    "max_batch_size", "freshness_hours")
    def _check_policy(self):
        for record in self:
            if record.auto_reply_enabled and (
                not record.explicit_consent_at or not record.explicit_consent_by
                or not record.consent_version or record.four_five_action != "auto"
            ):
                raise ValidationError(_("Automatic replies require recorded explicit consent and the approved 4–5 star policy."))
            if record.max_batch_size < 1 or record.max_batch_size > 50:
                raise ValidationError(_("The reply batch size must be between 1 and 50."))
            if record.freshness_hours < 1 or record.freshness_hours > 24:
                raise ValidationError(_("The source freshness limit must be between 1 and 24 hours."))

    def action_record_consent(self):
        if not self.env.user.has_group("baseer_google_business.group_gbp_manager"):
            raise AccessError(_("Only a Google Business manager can approve automatic replies."))
        for record in self:
            if record.company_id not in self.env.companies:
                raise AccessError(_("This reply policy belongs to another company."))
            if record.four_five_action != "auto":
                raise ValidationError(_("Choose the approved 4–5 star automatic policy first."))
            if record.auto_reply_enabled or record.explicit_consent_at:
                raise UserError(_("Automatic-reply consent has already been recorded for this policy."))
            record.with_context(gbp_internal_policy_consent=True).write({
                "auto_reply_enabled": True, "explicit_consent_at": fields.Datetime.now(),
                "explicit_consent_by": self.env.user.id, "consent_version": POLICY_VERSION,
            })
            self.env["baseer.gbp.audit"].sudo().create({
                "company_id": record.company_id.id, "location_id": record.location_id.id,
                "event": "auto_reply_consent_recorded", "detail": POLICY_VERSION,
            })
        return True


class GbpReview(models.Model):
    _name = "baseer.gbp.review"
    _description = "Google review"
    _order = "external_update_time desc, id desc"

    _gbp_review_unique = models.Constraint(
        "unique(location_id, external_review_id)", "This Google review already exists."
    )

    location_id = fields.Many2one("baseer.gbp.location", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="location_id.company_id", store=True, index=True)
    external_review_id = fields.Char(required=True, index=True, copy=False)
    star_rating = fields.Integer(required=True)
    comment = fields.Text(copy=False)
    external_update_time = fields.Datetime(index=True, copy=False)
    has_google_reply = fields.Boolean(default=False, readonly=True)
    remote_reply_text = fields.Text(copy=False, readonly=True)
    reply_state = fields.Selection([
        ("unanswered", "Unanswered"), ("draft", "Draft"), ("manual", "Manual required"),
        ("queued", "Queued"), ("published", "Published"), ("needs_check", "Needs check")
    ], default="unanswered", required=True, index=True)
    retention_deadline = fields.Datetime(copy=False)

    _sync_controlled_fields = {
        "location_id", "external_review_id", "star_rating", "comment", "external_update_time",
        "has_google_reply", "remote_reply_text", "reply_state", "retention_deadline",
    }

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.context.get("gbp_internal_sync") and not self.env.is_superuser():
            raise AccessError(_("Google reviews can only be created by the secure sync service."))
        for values in values_list:
            values.setdefault("retention_deadline", fields.Datetime.now() + timedelta(days=365))
        return super().create(values_list)

    def write(self, values):
        if (self._sync_controlled_fields.intersection(values)
                and not self.env.context.get("gbp_internal_review_write")
                and not self.env.is_superuser()):
            raise AccessError(_("Google review source data and workflow state can only be changed by the secure service."))
        return super().write(values)

    @api.constrains("star_rating")
    def _check_stars(self):
        for record in self:
            if record.star_rating not in range(1, 6):
                raise ValidationError(_("Star rating must be between 1 and 5."))

    def action_classify(self):
        for record in self:
            policy = self.env["baseer.gbp.reply.policy"].search([( "location_id", "=", record.location_id.id)], limit=1)
            if record.has_google_reply:
                state = "published"
            elif record.star_rating <= 3:
                state = "manual"  # legacy policy: one through three stars are always manual
            elif policy.auto_reply_enabled and policy.four_five_action == "auto":
                state = "queued"
            else:
                state = "draft"
            record.with_context(gbp_internal_review_write=True).write({"reply_state": state})
        return True

    def action_prepare_reply(self):
        if not self.env.user.has_group("baseer_google_business.group_gbp_responder"):
            raise AccessError(_("You do not have permission to prepare replies."))
        result = self.env["baseer.gbp.reply.outbox"]
        for review in self:
            if review.company_id not in self.env.companies or review.has_google_reply:
                continue
            # AI gateway adapter is intentionally not called until central governance exists.
            template = _("Thank you for your feedback. We appreciate your support.") if review.star_rating >= 4 else _(
                "Thank you for your feedback. Our team will review it carefully.")
            result |= self.env["baseer.gbp.reply.outbox"].with_context(gbp_internal_workflow=True).create({
                "review_id": review.id, "revision": 1, "body": template,
                "state": "draft", "idempotency_key": "review:%s:revision:1" % review.id,
            })
            # Drafting is never publishing. A future approved worker may queue only an
            # already approved 4--5 star reply after freshness and consent checks.
            review.with_context(gbp_internal_review_write=True).write({"reply_state": "draft"})
        return result

    @api.model
    def cron_redact_expired_reviews(self):
        """Retention job: retain operational metadata but remove old review text."""
        expired = self.sudo().search([
            ("retention_deadline", "!=", False), ("retention_deadline", "<", fields.Datetime.now()),
            ("comment", "!=", False),
        ])
        expired.with_context(gbp_internal_review_write=True).write({"comment": False, "remote_reply_text": False})
        return True


class GbpReplyOutbox(models.Model):
    _name = "baseer.gbp.reply.outbox"
    _description = "Google reply outbox"
    _order = "create_date desc, id desc"

    _gbp_outbox_revision_unique = models.Constraint(
        "unique(review_id, revision)", "A reply revision already exists for this review."
    )
    _gbp_outbox_idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "This reply operation already exists."
    )

    review_id = fields.Many2one("baseer.gbp.review", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="review_id.company_id", store=True, index=True)
    revision = fields.Integer(default=1, required=True, copy=False)
    body = fields.Text(required=True)
    state = fields.Selection([
        ("draft", "Draft"), ("approved", "Approved"), ("queued", "Queued"),
        ("sending", "Sending"), ("published", "Published"), ("unknown", "Needs reconciliation"),
        ("failed", "Failed"), ("cancelled", "Cancelled")
    ], default="draft", required=True, index=True)
    idempotency_key = fields.Char(required=True, copy=False, index=True)
    attempt_count = fields.Integer(default=0, readonly=True)
    published_at = fields.Datetime(readonly=True)
    last_error_code = fields.Char(readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    approved_by = fields.Many2one("res.users", readonly=True, copy=False)

    _workflow_controlled_fields = {
        "review_id", "revision", "state", "idempotency_key", "attempt_count", "published_at",
        "last_error_code", "approved_at", "approved_by",
    }

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.context.get("gbp_internal_workflow") and not self.env.is_superuser():
            raise AccessError(_("Replies can only be created from the review workflow."))
        return super().create(values_list)

    def write(self, values):
        if (self._workflow_controlled_fields.intersection(values)
                and not self.env.context.get("gbp_internal_workflow")
                and not self.env.is_superuser()):
            raise AccessError(_("Reply workflow state can only be changed by the approved workflow."))
        if "body" in values and not self.env.context.get("gbp_internal_workflow"):
            if any(record.state != "draft" for record in self):
                raise AccessError(_("Only a draft reply can be edited."))
        return super().write(values)

    def action_approve(self):
        if not self.env.user.has_group("baseer_google_business.group_gbp_responder"):
            raise AccessError(_("You do not have permission to approve replies."))
        for record in self:
            if record.company_id not in self.env.companies:
                raise AccessError(_("This reply belongs to another company."))
            if record.review_id.star_rating <= 3:
                # low rating responses can be written, but must be deliberately approved.
                if not self.env.user.has_group("baseer_google_business.group_gbp_manager"):
                    raise AccessError(_("A manager must approve one to three star replies."))
            if record.state != "draft":
                raise UserError(_("Only draft replies can be approved."))
            record.with_context(gbp_internal_workflow=True).write({
                "state": "approved", "approved_at": fields.Datetime.now(), "approved_by": self.env.user.id,
            })
        return True

    def action_send(self):
        """Publish one approved reply with a writer fence and a row lock."""
        if not self.env.user.has_group("baseer_google_business.group_gbp_manager"):
            raise AccessError(_("Only a Google Business manager can send replies."))
        for record in self:
            if record.company_id not in self.env.companies:
                raise AccessError(_("This reply belongs to another company."))
            if record.state != "approved":
                raise UserError(_("Only approved replies can be sent."))
            review = record.review_id
            location = review.location_id
            connection = location.connection_id
            if not connection._writer_is_allowed():
                raise UserError(_("Google reply publishing is disabled for this connection."))
            policy = self.env["baseer.gbp.reply.policy"].search([("location_id", "=", location.id)], limit=1)
            freshness_limit = fields.Datetime.now() - timedelta(hours=(policy.freshness_hours if policy else 12))
            if not location.last_source_sync_at or location.last_source_sync_at < freshness_limit:
                raise UserError(_("Refresh Google reviews before publishing; the source data is stale."))
            self.env.cr.execute(
                "SELECT id FROM baseer_gbp_reply_outbox WHERE id = %s FOR UPDATE NOWAIT", [record.id]
            )
            record.invalidate_recordset()
            if record.state != "approved":
                raise UserError(_("This reply is already being processed."))
            record.with_context(gbp_internal_workflow=True).write({
                "state": "sending", "attempt_count": record.attempt_count + 1,
            })
            try:
                response = requests.put(
                    GOOGLE_BUSINESS_ORIGIN + "/v4/{}/reviews/{}/reply".format(
                        location.external_location_id, review.external_review_id
                    ),
                    headers={"Authorization": "Bearer " + connection._read_token()},
                    json={"comment": record.body}, timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException:
                # A timeout could have reached Google. Never retry it blindly.
                record.with_context(gbp_internal_workflow=True).write({
                    "state": "unknown", "last_error_code": "network_outcome_unknown",
                })
                self.env["baseer.gbp.audit"].sudo().create({
                    "company_id": record.company_id.id, "location_id": location.id,
                    "connection_id": connection.id, "event": "reply_outcome_unknown",
                    "detail": "Google did not confirm a reply; reconciliation is required.",
                })
                return self._workflow_notification(
                    _("Google did not confirm the reply. Reconcile it before any retry."), "warning"
                )
            if response.status_code not in (200, 201):
                record.with_context(gbp_internal_workflow=True).write({
                    "state": "failed", "last_error_code": "google_reply_rejected",
                })
                self.env["baseer.gbp.audit"].sudo().create({
                    "company_id": record.company_id.id, "location_id": location.id,
                    "connection_id": connection.id, "event": "reply_rejected",
                    "detail": "Google rejected a reply; it was not queued for retry.",
                })
                return self._workflow_notification(_("Google rejected this reply; it was not queued for retry."), "danger")
            record.with_context(gbp_internal_workflow=True).write({
                "state": "published", "published_at": fields.Datetime.now(), "last_error_code": False,
            })
            review.with_context(gbp_internal_review_write=True).write({
                "reply_state": "published", "has_google_reply": True, "remote_reply_text": record.body,
            })
            self.env["baseer.gbp.audit"].sudo().create({
                "company_id": record.company_id.id, "location_id": location.id,
                "connection_id": connection.id, "event": "reply_published", "detail": "Google confirmed a reply publication.",
            })
        return True

    @api.model
    def _workflow_notification(self, message, notification_type):
        """Keep terminal send states durable instead of rolling them back via UserError."""
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": notification_type, "sticky": True},
        }

    def action_reconcile_remote(self):
        """Resolve an unknown send by reading Google before any manual retry."""
        if not self.env.user.has_group("baseer_google_business.group_gbp_manager"):
            raise AccessError(_("Only a Google Business manager can reconcile replies."))
        for record in self:
            if record.company_id not in self.env.companies:
                raise AccessError(_("This reply belongs to another company."))
            if record.state != "unknown":
                raise UserError(_("Only an unknown reply can be reconciled."))
            review = record.review_id
            location = review.location_id
            try:
                response = requests.get(
                    GOOGLE_BUSINESS_ORIGIN + "/v4/{}/reviews/{}".format(
                        location.external_location_id, review.external_review_id
                    ),
                    headers={"Authorization": "Bearer " + location.connection_id._read_token()},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException:
                raise UserError(_("Google is temporarily unavailable; keep this reply in reconciliation."))
            if response.status_code != 200:
                raise UserError(_("Google could not confirm this review; keep it in reconciliation."))
            remote_text = (response.json().get("reviewReply") or {}).get("comment")
            if remote_text == record.body:
                record.with_context(gbp_internal_workflow=True).write({
                    "state": "published", "published_at": fields.Datetime.now(), "last_error_code": False,
                })
                review.with_context(gbp_internal_review_write=True).write({
                    "reply_state": "published", "has_google_reply": True, "remote_reply_text": remote_text,
                })
            else:
                record.with_context(gbp_internal_workflow=True).write({
                    "state": "failed", "last_error_code": "remote_reply_mismatch",
                })
                review.with_context(gbp_internal_review_write=True).write({"reply_state": "needs_check"})
            self.env["baseer.gbp.audit"].sudo().create({
                "company_id": record.company_id.id, "location_id": location.id,
                "connection_id": location.connection_id.id, "event": "reply_reconciled",
                "detail": "Google reply reconciliation completed.",
            })
        return True


class GbpMetric(models.Model):
    _name = "baseer.gbp.metric"
    _description = "Google Business metric"
    _order = "metric_date desc, id desc"

    _gbp_metric_unique = models.Constraint(
        "unique(location_id, metric_key, metric_date)", "This metric already exists for the date."
    )

    location_id = fields.Many2one("baseer.gbp.location", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="location_id.company_id", store=True, index=True)
    metric_key = fields.Selection([
        ("impressions", "Impressions"), ("website_clicks", "Website clicks"),
        ("calls", "Calls"), ("directions", "Directions")
    ], required=True, index=True)
    metric_date = fields.Date(required=True, index=True)
    value = fields.Integer(required=True)


class GbpAudit(models.Model):
    _name = "baseer.gbp.audit"
    _description = "Google Business safety audit"
    _order = "create_date desc, id desc"

    company_id = fields.Many2one("res.company", required=True, index=True)
    connection_id = fields.Many2one("baseer.gbp.connection", ondelete="set null")
    location_id = fields.Many2one("baseer.gbp.location", ondelete="set null")
    event = fields.Char(required=True, index=True)
    detail = fields.Char(copy=False)
