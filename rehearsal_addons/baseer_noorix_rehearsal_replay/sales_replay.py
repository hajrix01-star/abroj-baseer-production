"""Source-only sales-summary replay for the isolated Noorix 18084 rehearsal.

This module deliberately has no UI entry point.  It writes only to the
rehearsal database after proving the pinned source manifest and records
append-only evidence for every source daily summary.  It creates native
``baseer.pos.summary`` records and lets their native approval action create
the accounting/POS records; it never creates stock movements or substitutes
QA record identifiers.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from odoo import Command, fields
from odoo.exceptions import UserError

from odoo.addons.baseer_pos_summary.models.common import money, native_quote

from . import replay_writer, runtime_guard
from .models.evidence import WRITER_CONTEXT


CENT = Decimal("0.01")
CHANNELS = ("cash", "bank", "hungerstation", "keeta", "jahez")


def _decimal(value, label):
    try:
        result = Decimal(str(value))
    except Exception as error:  # Source validation boundary.
        raise UserError("Noorix sales source %s is not a decimal" % label) from error
    if not result.is_finite() or result < 0:
        raise UserError("Noorix sales source %s must be a non-negative finite amount" % label)
    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _writer_model(env, model):
    return env[model].sudo().with_context(**{WRITER_CONTEXT: True})


def _one(records, label):
    if len(records) != 1:
        raise UserError("Noorix sales replay requires exactly one %s; found %s" % (label, len(records)))
    return records


def _source_identity(row):
    return ":".join(str(row.get(key, "")) for key in (
        "source_system", "source_tenant_id", "source_company_id", "source_summary_id",
    ))


def _summary_identity(summary):
    return "%s:%s" % (summary["source_company_id"], summary["canonical_key"])


def _get_or_start_run(env, run_key):
    Run = _writer_model(env, "baseer.noorix.rehearsal.run")
    run = Run.search([("run_key", "=", run_key)])
    if run:
        run = _one(run, "sales replay run")
        if (
            run.scope != "sales_month"
            or run.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
            or run.manifest_sha256 != runtime_guard.SOURCE_MANIFEST_SHA256
        ):
            raise UserError("Noorix sales replay run identity differs for %s" % run_key)
        if run.state not in {"committed", "reconciled"}:
            raise UserError("Noorix sales replay run %s is not safely resumable" % run_key)
        return run, False
    return Run.create({
        "run_key": run_key,
        "scope": "sales_month",
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "manifest_sha256": runtime_guard.SOURCE_MANIFEST_SHA256,
        "state": "planned",
    }), True


def _commit_run(run, result):
    run.with_context(**{WRITER_CONTEXT: True}).write({
        "state": "committed",
        "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True),
    })


def _ensure_map(env, *, scope, source_identity, source_row_sha256, canonical_key, target, run):
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    existing = Map.search([("scope", "=", scope), ("source_identity", "=", source_identity)])
    if existing:
        existing = _one(existing, "sales source mapping")
        if (
            existing.source_row_sha256 != source_row_sha256
            or existing.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
            or existing.canonical_key != canonical_key
            or existing.target_model != target._name
            or existing.target_res_id != target.id
        ):
            raise UserError("Noorix sales source mapping differs for %s" % source_identity)
        return existing
    return Map.create({
        "scope": scope,
        "source_identity": source_identity,
        "source_row_sha256": source_row_sha256,
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "canonical_key": canonical_key,
        "target_model": target._name,
        "target_res_id": target.id,
        "run_id": run.id,
    })


def _sales_payload(manifest):
    payloads = [contract.get("payload", {}) for contract in manifest["contracts"]]
    candidates = [payload for payload in payloads if isinstance(payload.get("summaries"), list)]
    if len(candidates) != 1:
        raise UserError("Pinned source manifest must contain exactly one Noorix sales-summary contract")
    payload = candidates[0]
    if payload.get("approved_policy") != "gross_includes_15_percent_vat_and_arz_20260526_sources_merge_into_one_all_day_summary":
        raise UserError("Pinned Noorix sales policy differs from the owner-approved VAT/ARZ-merge policy")
    if payload.get("source_archive_sha256") != runtime_guard.SOURCE_ARCHIVE_SHA256:
        raise UserError("Pinned Noorix sales source archive differs")
    return payload


def _company_summaries(payload, source_company_id):
    summaries = [row for row in payload["summaries"] if row.get("source_company_id") == source_company_id]
    if not summaries:
        raise UserError("No approved Noorix sales summaries for source company %s" % source_company_id)
    canonical = set()
    sources = set()
    for summary in summaries:
        required = ("canonical_key", "business_date", "period_scope", "day_schedule", "external_reference", "customer_count", "amount_gross", "allocations", "source_rows", "wave_key")
        if any(key not in summary for key in required):
            raise UserError("Noorix sales summary has incomplete source fields")
        if summary["canonical_key"] in canonical:
            raise UserError("Noorix sales canonical summary repeats: %s" % summary["canonical_key"])
        canonical.add(summary["canonical_key"])
        if summary["period_scope"] not in {"all", "morning", "evening"}:
            raise UserError("Noorix sales summary has an unsupported period scope")
        if summary["day_schedule"] not in {"all", "split"}:
            raise UserError("Noorix sales summary has an unsupported day schedule")
        if (summary["day_schedule"] == "all") != (summary["period_scope"] == "all"):
            raise UserError("Noorix sales day schedule and period scope differ")
        if not isinstance(summary["customer_count"], int) or isinstance(summary["customer_count"], bool) or summary["customer_count"] < 0:
            raise UserError("Noorix sales customer count is invalid")
        gross = _decimal(summary["amount_gross"], "summary gross")
        allocated = sum((_decimal(row.get("amount"), "allocation amount") for row in summary["allocations"]), Decimal("0.00"))
        if gross != allocated:
            raise UserError("Noorix sales allocations do not equal the declared gross for %s" % summary["canonical_key"])
        channels = [row.get("channel_key") for row in summary["allocations"]]
        if len(channels) != len(set(channels)) or any(channel not in CHANNELS for channel in channels):
            raise UserError("Noorix sales allocation channels are invalid for %s" % summary["canonical_key"])
        source_gross = Decimal("0.00")
        source_customers = 0
        for row in summary["source_rows"]:
            if row.get("source_archive_sha256") != runtime_guard.SOURCE_ARCHIVE_SHA256 or row.get("source_company_id") != source_company_id:
                raise UserError("Noorix sales source row has an invalid source boundary")
            if row.get("canonical_key") != summary["canonical_key"] or not row.get("source_row_sha256"):
                raise UserError("Noorix sales source row does not prove its target summary")
            identity = _source_identity(row)
            if not row.get("source_summary_id") or identity in sources:
                raise UserError("Noorix sales source summary identity repeats or is absent")
            sources.add(identity)
            source_gross += _decimal(row.get("source_gross"), "source gross")
            source_customers += row.get("source_customers", -1)
        if gross != source_gross or summary["customer_count"] != source_customers:
            raise UserError("Noorix sales source rows do not reconcile to %s" % summary["canonical_key"])
    return sorted(summaries, key=lambda row: (row["business_date"], row["period_scope"], row["canonical_key"]))


def _company_context(env, company):
    return env["res.company"].sudo().with_company(company).with_context(allowed_company_ids=[company.id]).env


def _config_and_methods(env, company):
    scoped = _company_context(env, company)
    configs = scoped["pos.config"].search([
        ("company_id", "=", company.id), ("baseer_summary_only", "=", True), ("active", "=", True),
    ])
    config = _one(configs, "active dedicated sales-summary POS configuration")
    config._validate_baseer_setup()
    if config.company_id != company or config.baseer_summary_product_id.type != "service":
        raise UserError("Noorix sales configuration cannot post a service-only sales summary")
    quote = native_quote(money(Decimal("115.00")), config.baseer_summary_tax_id, config.baseer_summary_product_id, company)
    if money(quote["gross"]) != Decimal("115.00") or money(quote["net"]) != Decimal("100.00") or money(quote["tax"]) != Decimal("15.00"):
        raise UserError("Noorix sales configuration does not price VAT 15 percent inclusively")
    methods = {}
    Data = scoped["ir.model.data"]
    for channel in CHANNELS:
        data = Data.search([
            ("module", "=", "baseer_pos_summary"),
            ("name", "=", "payment_seed_method_%s_company_%s" % (channel, company.id)),
        ])
        data = _one(data, "semantic %s payment-method identity" % channel)
        if data.model != "pos.payment.method":
            raise UserError("Noorix sales payment identity has an invalid target model")
        method = scoped["pos.payment.method"].browse(data.res_id).exists()
        if not method or method.company_id != company or not method.active or method not in config.payment_method_ids:
            raise UserError("Noorix sales payment method is not active in the target configuration")
        expected_kind = "cash" if channel == "cash" else "bank" if channel == "bank" else "platform"
        if method.baseer_category_id.kind != expected_kind:
            raise UserError("Noorix sales payment method category differs for %s" % channel)
        method._validate_baseer_method(config)
        methods[channel] = method
    return config, methods


def _expected(summary, config):
    gross = _decimal(summary["amount_gross"], "summary gross")
    quote = native_quote(money(gross), config.baseer_summary_tax_id, config.baseer_summary_product_id, config.company_id)
    if money(quote["gross"]) != gross:
        raise UserError("Native sales quote gross differs from the Noorix source")
    return gross, money(quote["net"]), money(quote["tax"])


def _assert_open_journals(summary, config, methods):
    journals = config.journal_id | config.invoice_journal_id | methods["cash"].journal_id | methods["bank"].journal_id
    for allocation in summary["allocations"]:
        journals |= methods[allocation["channel_key"]].journal_id
    day = fields.Date.to_date(summary["business_date"])
    for journal in journals:
        if config.company_id._get_violated_lock_dates(day, True, journal):
            raise UserError("Noorix sales date %s is locked for journal %s" % (summary["business_date"], journal.code))


def _record_maps(env, run, summary, target):
    summary_hash = _hash(summary)
    _ensure_map(
        env, scope="sales_summary", source_identity=_summary_identity(summary),
        source_row_sha256=summary_hash, canonical_key=summary["canonical_key"], target=target, run=run,
    )
    for row in summary["source_rows"]:
        _ensure_map(
            env, scope="sales_source", source_identity=_source_identity(row),
            source_row_sha256=row["source_row_sha256"], canonical_key=summary["canonical_key"], target=target, run=run,
        )


def _verify_maps(env, run, summary, target):
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    expected = [("sales_summary", _summary_identity(summary), _hash(summary))] + [
        ("sales_source", _source_identity(row), row["source_row_sha256"])
        for row in summary["source_rows"]
    ]
    for scope, identity, row_hash in expected:
        mapping = _one(Map.search([("scope", "=", scope), ("source_identity", "=", identity)]), "sales provenance mapping")
        if (
            mapping.run_id != run or mapping.source_row_sha256 != row_hash
            or mapping.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
            or mapping.canonical_key != summary["canonical_key"]
            or mapping.target_model != target._name or mapping.target_res_id != target.id
        ):
            raise UserError("Noorix sales provenance mapping differs for %s" % identity)


def _mapped_summary(env, run, summary, company):
    mapping = _writer_model(env, "baseer.noorix.rehearsal.source.map").search([
        ("scope", "=", "sales_summary"), ("source_identity", "=", _summary_identity(summary)),
    ])
    mapping = _one(mapping, "mapped sales summary")
    if mapping.run_id != run or mapping.target_model != "baseer.pos.summary":
        raise UserError("Noorix mapped sales summary provenance differs")
    target = _company_context(env, company)["baseer.pos.summary"].browse(mapping.target_res_id).exists()
    if not target:
        raise UserError("Noorix mapped sales summary no longer exists")
    return target


def _verify_summary(env, run, summary, company, config, methods):
    target = _mapped_summary(env, run, summary, company)
    gross, net, tax = _expected(summary, config)
    if (
        target.company_id != company or target.config_id != config or str(target.business_date) != summary["business_date"]
        or target.period_scope != summary["period_scope"] or target.day_schedule != summary["day_schedule"]
        or target.external_reference != summary["external_reference"] or target.customer_count != summary["customer_count"]
        or target.notes != summary.get("notes") or target.state != "approved"
        or money(target.amount_gross) != gross or money(target.amount_net) != net or money(target.amount_tax) != tax
    ):
        raise UserError("Noorix sales target summary invariant differs for %s" % summary["canonical_key"])
    allocations = {line.payment_method_id.id: money(line.amount) for line in target.allocation_ids}
    expected_allocations = {methods[row["channel_key"]].id: _decimal(row["amount"], "allocation amount") for row in summary["allocations"]}
    if allocations != expected_allocations:
        raise UserError("Noorix sales allocation invariant differs for %s" % summary["canonical_key"])
    if not target.order_id or target.order_id.picking_ids or target.config_id.baseer_summary_product_id.type != "service":
        raise UserError("Noorix sales target must remain a service-only, no-stock posting")
    _verify_maps(env, run, summary, target)
    return target


def _result(summaries, config):
    gross = Decimal("0.00")
    net = Decimal("0.00")
    tax = Decimal("0.00")
    customers = 0
    sources = 0
    for summary in summaries:
        row_gross, row_net, row_tax = _expected(summary, config)
        gross += row_gross
        net += row_net
        tax += row_tax
        customers += summary["customer_count"]
        sources += len(summary["source_rows"])
    return {
        "summaries": len(summaries), "source_summaries": sources, "source_gross": str(gross),
        "source_net": str(net), "source_tax": str(tax), "customers": customers,
        "vat_policy": "15_percent_included", "stock_moves_created": 0,
    }


def plan_sales_company(env, source_company_id, path=None):
    """Read-only preflight for all approved sales summaries of one source company."""
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    summaries = _company_summaries(_sales_payload(manifest), source_company_id)
    company = replay_writer._company_by_source(env, source_company_id)
    if not company or not company.active:
        raise UserError("Noorix sales company mapping is missing or inactive")
    config, methods = _config_and_methods(env, company)
    for summary in summaries:
        _expected(summary, config)
        _assert_open_journals(summary, config, methods)
        if any(row["channel_key"] not in methods for row in summary["allocations"]):
            raise UserError("Noorix sales source refers to an unavailable payment method")
    result = _result(summaries, config)
    result.update({
        "database": env.cr.dbname, "source_company_id": source_company_id,
        "target_company_id": company.id, "target_config_id": config.id,
        "wave_key": summaries[0]["wave_key"], "orm_writes": 0,
    })
    return result


def apply_sales_company(env, source_company_id, path=None):
    """Atomically replay one source company's approved Noorix sales summaries."""
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    summaries = _company_summaries(_sales_payload(manifest), source_company_id)
    company = replay_writer._company_by_source(env, source_company_id)
    if not company or not company.active:
        raise UserError("Noorix sales company mapping is missing or inactive")
    config, methods = _config_and_methods(env, company)
    run_key = "sales:%s:all" % source_company_id
    replay_writer._lock(env, run_key)
    with env.cr.savepoint():
        run, fresh = _get_or_start_run(env, run_key)
        if not fresh:
            for summary in summaries:
                _verify_summary(env, run, summary, company, config, methods)
            return json.loads(run.result_json)
        Summary = _company_context(env, company)["baseer.pos.summary"]
        for summary in summaries:
            _expected(summary, config)
            _assert_open_journals(summary, config, methods)
            target = Summary.create({
                "company_id": company.id, "config_id": config.id,
                "business_date": summary["business_date"], "period_scope": summary["period_scope"],
                "day_schedule": summary["day_schedule"], "external_reference": summary["external_reference"],
                "customer_count": summary["customer_count"], "notes": summary.get("notes") or False,
                "allocation_ids": [Command.create({
                    "payment_method_id": methods[row["channel_key"]].id,
                    "amount": float(_decimal(row["amount"], "allocation amount")),
                }) for row in summary["allocations"]],
            })
            target.action_approve()
            _record_maps(env, run, summary, target)
        result = _result(summaries, config)
        result.update({"source_company_id": source_company_id, "target_company_id": company.id})
        _commit_run(run, result)
    return result
