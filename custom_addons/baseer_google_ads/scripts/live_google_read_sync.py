"""Odoo shell startup file for one bounded, production read-only verification.

This is invoked only by ``import-google-live-connections.py`` after the secure
connection import.  It deliberately contains no token, OAuth configuration or
write action.  Google Business reply writing remains locked.
"""
from odoo import SUPERUSER_ID, api

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
        connection._sync_recent_campaign_facts()
        connection._sync_detail_datasets()
    else:
        location = secure_env["baseer.gbp.location"].search([("connection_id", "=", connection.id)], limit=1)
        if not location:
            raise RuntimeError("imported_location_missing")
        location.action_sync_read_only()

env.cr.commit()
print("live_google_read_sync_succeeded")
raise SystemExit(0)
