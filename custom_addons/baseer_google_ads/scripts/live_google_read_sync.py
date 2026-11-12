"""Odoo shell startup file for one bounded, production read-only verification.

This is invoked only by ``import-google-live-connections.py`` after the secure
connection import.  It deliberately contains no token, OAuth configuration or
write action.  Google Business reply writing remains locked.
"""
import requests

from odoo import SUPERUSER_ID, api


def _verify_ads_identity(connection):
    rows = connection._search_stream("SELECT customer.id FROM customer LIMIT 1")
    identifiers = {str((row.get("customer") or {}).get("id") or "") for row in rows}
    if identifiers != {connection.customer_id}:
        raise RuntimeError("google_ads_customer_identity_rejected")


def _verify_gbp_identity(connection, location):
    """Prove the OAuth account can see exactly the approved location before sync."""
    token = connection._read_token()
    url = "https://mybusinessbusinessinformation.googleapis.com/v1/%s/locations" % connection.external_account_id
    page_token = None
    found = False
    for _page in range(20):
        params = {"readMask": "name", "pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        response = requests.get(url, headers={"Authorization": "Bearer %s" % token}, params=params, timeout=20)
        if response.status_code != 200:
            raise RuntimeError("google_business_account_identity_rejected")
        payload = response.json()
        found = found or any(item.get("name") == location.google_location_name for item in payload.get("locations") or [])
        page_token = payload.get("nextPageToken")
        if found or not page_token:
            break
    if not found:
        raise RuntimeError("google_business_location_identity_rejected")

secure_env = api.Environment(env.cr, SUPERUSER_ID, dict(env.context))
for model, external_id, is_ads in (
    ("baseer.gads.connection", "b0106731-9fc6-457d-9cc1-20b9d1d7356f", True),
    ("baseer.gads.connection", "43859b29-a24f-4030-8e4e-24ce52c7cb7e", True),
    ("baseer.gbp.connection", "9c90a65b-a8ee-42c1-8c18-41defe9ef755", False),
    ("baseer.gbp.connection", "61b7f19f-ba8a-424b-bef6-1cbfa4861316", False),
):
    key = "legacy_connection_id" if is_ads else "external_connection_id"
    connection = secure_env[model].search([(key, "=", external_id)], limit=1)
    if not connection or connection.state != "active":
        raise RuntimeError("imported_connection_not_active")
    if is_ads:
        _verify_ads_identity(connection)
        connection._sync_recent_campaign_facts()
        connection._sync_detail_datasets()
    else:
        location = secure_env["baseer.gbp.location"].search([("connection_id", "=", connection.id)], limit=1)
        if not location:
            raise RuntimeError("imported_location_missing")
        _verify_gbp_identity(connection, location)
        location.action_sync_read_only()

env.cr.commit()
print("live_google_read_sync_succeeded")
raise SystemExit(0)
