"""Source-only latest purchase-cost replay for the 18084 Noorix rehearsal.

The source contract is deliberately narrow: it authorizes only the latest,
positive received-purchase cost for 277 already-mapped, company-owned
products.  It is *not* a stock receipt, valuation, vendor bill, or price
history import.  This file is rehearsal-only and is deliberately absent from
the production candidate.
"""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from odoo.exceptions import UserError

from . import replay_writer, runtime_guard
from .models.evidence import WRITER_CONTEXT


CENT = Decimal("0.01")
POLICY = "latest_nonzero_received_purchase_cost_per_canonical_company_product"
ALMO_SOURCE_COMPANY = "cmnaivif80001wavxxfgriptm"
ARZ_SOURCE_COMPANY = "cmnf604ka009ay8lm556wgd9c"
EXPECTED_COMPANY_COSTS = {
    ALMO_SOURCE_COMPANY: 84,
    ARZ_SOURCE_COMPANY: 193,
}
EXPECTED_COST_ROWS = sum(EXPECTED_COMPANY_COSTS.values())


def _one(records, label):
    if len(records) != 1:
        raise UserError("Noorix cost replay requires exactly one %s; found %s" % (label, len(records)))
    return records


def _writer_model(env, model):
    return env[model].sudo().with_context(**{WRITER_CONTEXT: True})


def _company_env(env, model, company):
    """Return a strictly single-company model environment."""
    return env[model].sudo().with_company(company).with_context(
        allowed_company_ids=[company.id], active_test=False,
    )


def _money(value, label):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise UserError("Noorix cost %s is not a decimal" % label) from error
    if not amount.is_finite() or amount <= 0:
        raise UserError("Noorix cost %s must be positive and finite" % label)
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _source_identity(row, terminal_key):
    values = [row.get("source_system"), row.get("source_tenant_id"), row.get("source_company_id")]
    if terminal_key:
        values.append(row.get(terminal_key))
    if any(not isinstance(value, str) or not value for value in values):
        raise UserError("Noorix cost source identity is incomplete")
    return ":".join(values)


def _cost_identity(row):
    return _source_identity(row, "source_price_history_id")


def _product_identity(row):
    return _source_identity(row, "source_product_id")


def _get_or_start_run(env, run_key):
    """Use a distinct run key while retaining the existing evidence schema.

    ``baseer.noorix.rehearsal.run.scope`` is an intentionally closed legacy
    selection.  ``product_company`` is the only semantically valid available
    selection for a product property update.  The independent run key and
    ``product_cost`` source-map scope keep this cost wave separate from the
    product-master wave.
    """
    Run = _writer_model(env, "baseer.noorix.rehearsal.run")
    run = Run.search([("run_key", "=", run_key)])
    if run:
        run = _one(run, "cost replay run")
        if (
            run.scope != "product_company"
            or run.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
            or run.manifest_sha256 != runtime_guard.SOURCE_MANIFEST_SHA256
        ):
            raise UserError("Noorix cost replay run identity differs for %s" % run_key)
        if run.state not in {"committed", "reconciled"}:
            raise UserError("Noorix cost replay run %s is not safely resumable" % run_key)
        return run, False
    return Run.create({
        "run_key": run_key,
        "scope": "product_company",
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "manifest_sha256": runtime_guard.SOURCE_MANIFEST_SHA256,
        "state": "planned",
    }), True


def _commit_run(run, result):
    run.with_context(**{WRITER_CONTEXT: True}).write({
        "state": "committed",
        "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True),
    })


def _ensure_map(env, *, source_identity, source_row_sha256, canonical_key, target, run):
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    existing = Map.search([("scope", "=", "product_cost"), ("source_identity", "=", source_identity)])
    if existing:
        existing = _one(existing, "cost source mapping")
        if (
            existing.source_row_sha256 != source_row_sha256
            or existing.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
            or existing.canonical_key != canonical_key
            or existing.target_model != target._name
            or existing.target_res_id != target.id
            or existing.run_id != run
        ):
            raise UserError("Noorix cost source mapping differs for %s" % source_identity)
        return existing
    return Map.create({
        "scope": "product_cost",
        "source_identity": source_identity,
        "source_row_sha256": source_row_sha256,
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "canonical_key": canonical_key,
        "target_model": target._name,
        "target_res_id": target.id,
        "run_id": run.id,
    })


def _cost_payload(manifest):
    candidates = [
        contract.get("payload", {})
        for contract in manifest["contracts"]
        if isinstance(contract.get("payload", {}).get("costs"), list)
    ]
    if len(candidates) != 1:
        raise UserError("Pinned source manifest must contain exactly one cost contract")
    payload = candidates[0]
    if payload.get("approved_policy") != POLICY:
        raise UserError("Pinned Noorix cost policy differs from the approved policy")
    if payload.get("source_archive_sha256") != runtime_guard.SOURCE_ARCHIVE_SHA256:
        raise UserError("Pinned Noorix cost source archive differs")
    costs = payload["costs"]
    if len(costs) != EXPECTED_COST_ROWS:
        raise UserError("Pinned Noorix cost row count differs")

    company_counts = Counter()
    product_identities = set()
    price_history_ids = set()
    canonical_keys = set()
    for row in costs:
        required = {
            "canonical_key", "decision", "effective_at", "source_archive_sha256", "source_company_id",
            "source_cost", "source_price_history_id", "source_product_id", "source_row_sha256",
            "source_system", "source_tenant_id",
        }
        if set(row) != required:
            raise UserError("Pinned Noorix cost source fields differ")
        if row["decision"] != "set_latest_received_cost":
            raise UserError("Noorix cost decision is not an approved latest received cost")
        if row["source_archive_sha256"] != runtime_guard.SOURCE_ARCHIVE_SHA256:
            raise UserError("Noorix cost row source archive differs")
        if row["source_company_id"] not in EXPECTED_COMPANY_COSTS:
            raise UserError("Noorix cost source company is outside the approved allow-list")
        if not isinstance(row["effective_at"], str) or not row["effective_at"]:
            raise UserError("Noorix cost effective date is absent")
        if not isinstance(row["source_row_sha256"], str) or len(row["source_row_sha256"]) != 64:
            raise UserError("Noorix cost source row digest differs")
        amount = _money(row["source_cost"], "source_cost")
        if amount != Decimal(str(row["source_cost"])):
            raise UserError("Noorix cost must be expressed to two decimal places or less")
        product_identity = _product_identity(row)
        if product_identity in product_identities:
            raise UserError("Noorix latest cost repeats a source product")
        product_identities.add(product_identity)
        history_identity = _cost_identity(row)
        if history_identity in price_history_ids:
            raise UserError("Noorix latest cost repeats a price-history identity")
        price_history_ids.add(history_identity)
        expected_key = "product:%s:%s:%s" % (
            row["source_tenant_id"], row["source_company_id"], row["source_product_id"],
        )
        if row["canonical_key"] != expected_key or row["canonical_key"] in canonical_keys:
            raise UserError("Noorix cost canonical product identity differs")
        canonical_keys.add(row["canonical_key"])
        company_counts[row["source_company_id"]] += 1
    if dict(company_counts) != EXPECTED_COMPANY_COSTS:
        raise UserError("Pinned Noorix cost company distribution differs")

    report = payload.get("report", {})
    if (
        report.get("company_1_cost_updates") != EXPECTED_COMPANY_COSTS[ARZ_SOURCE_COMPANY]
        or report.get("company_2_cost_updates") != EXPECTED_COMPANY_COSTS[ALMO_SOURCE_COMPANY]
        or report.get("excluded_zero_costs") != 1
        or report.get("source_latest_received_purchase_costs") != 279
    ):
        raise UserError("Pinned Noorix cost report differs")
    return sorted(costs, key=lambda row: (row["source_company_id"], row["canonical_key"]))


def _mapped_product(env, row, company):
    """Resolve the product solely from immutable product source evidence."""
    source_identity = _product_identity(row)
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    product_map = _one(Map.search([
        ("scope", "=", "product"), ("source_identity", "=", source_identity),
    ]), "product source mapping")
    if (
        product_map.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
        or product_map.canonical_key != row["canonical_key"]
        or product_map.target_model != "product.template"
    ):
        raise UserError("Noorix mapped product provenance differs for %s" % source_identity)
    product = _company_env(env, "product.template", company).browse(product_map.target_res_id).exists()
    if not product or product.company_id != company:
        raise UserError("Noorix mapped cost product is not owned by its target company")
    # The product-master wave intentionally created non-stockable consumables.
    # This must stay true before a standard-price property can be updated.
    if product.type != "consu" or product.is_storable or not product.purchase_ok or product.sale_ok:
        raise UserError("Noorix mapped cost product no longer satisfies the no-stock invariant")
    return product


def _read_standard_price(product):
    return _money(product.standard_price, "target standard price")


def _verify_map(env, run, row, product):
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    mapping = _one(Map.search([
        ("scope", "=", "product_cost"), ("source_identity", "=", _cost_identity(row)),
    ]), "cost provenance mapping")
    if (
        mapping.run_id != run
        or mapping.source_row_sha256 != row["source_row_sha256"]
        or mapping.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
        or mapping.canonical_key != row["canonical_key"]
        or mapping.target_model != "product.template"
        or mapping.target_res_id != product.id
    ):
        raise UserError("Noorix cost provenance mapping differs for %s" % _cost_identity(row))


def _model_count(env, model, company_ids):
    """Return a verifiable count, or ``None`` only when the model is absent."""
    if model not in env.registry.models:
        return None
    target = env[model].sudo().with_context(active_test=False)
    if "company_id" not in target._fields:
        raise UserError("Noorix effect guard cannot scope %s to a company" % model)
    return target.search_count([("company_id", "in", company_ids)])


def _effect_snapshot(env, company_ids):
    return {
        "account_move": _model_count(env, "account.move", company_ids),
        "stock_valuation_layer": _model_count(env, "stock.valuation.layer", company_ids),
        "stock_move": _model_count(env, "stock.move", company_ids),
    }


def _assert_no_financial_or_stock_effects(before, after):
    for model in ("account_move", "stock_valuation_layer", "stock_move"):
        if before[model] is None and after[model] is None:
            continue
        if before[model] is None or after[model] is None or after[model] != before[model]:
            raise UserError("Noorix cost write unexpectedly changed %s" % model)


def _result(costs, companies, effects, *, orm_writes):
    totals = Counter(row["source_company_id"] for row in costs)
    source_cost_total = sum((_money(row["source_cost"], "source_cost") for row in costs), Decimal("0.00"))
    unavailable = [model for model, count in effects.items() if count is None]
    return {
        "cost_rows": len(costs),
        "source_cost_total": str(source_cost_total),
        "source_company_counts": dict(sorted(totals.items())),
        "target_company_ids": {
            source_company_id: companies[source_company_id].id
            for source_company_id in sorted(companies)
        },
        "evidence_map_scope": "product_cost",
        "run_scope": "product_company",
        "orm_product_standard_price_writes": orm_writes,
        "account_moves_created": 0,
        # ``None`` means the isolated profile deliberately has no such model;
        # it is never reported as a misleading zero-row count.
        "stock_valuation_layers_created": None if effects["stock_valuation_layer"] is None else 0,
        "stock_moves_created": None if effects["stock_move"] is None else 0,
        "unavailable_effect_models": unavailable,
        "effect_counts_before_after": {"before": effects, "after": effects},
    }


def _preflight(env, path=None):
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    costs = _cost_payload(manifest)
    companies = {}
    products = {}
    for row in costs:
        source_company_id = row["source_company_id"]
        company = companies.get(source_company_id)
        if not company:
            company = replay_writer._company_by_source(env, source_company_id)
            if not company or not company.active:
                raise UserError("Noorix cost company mapping is missing or inactive")
            companies[source_company_id] = company
        products[_cost_identity(row)] = _mapped_product(env, row, company)
    effects = _effect_snapshot(env, [company.id for company in companies.values()])
    return costs, companies, products, effects


def plan_product_costs(env, path=None):
    """Read-only proof that all 277 cost rows rebind safely before apply."""
    costs, companies, _products, effects = _preflight(env, path)
    result = _result(costs, companies, effects, orm_writes=0)
    result.update({
        "database": env.cr.dbname,
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "manifest_sha256": runtime_guard.SOURCE_MANIFEST_SHA256,
        "mode": "plan",
    })
    return result


def apply_product_costs(env, path=None):
    """Atomically write only current product standard costs and cost evidence.

    The caller must explicitly commit the successful shell transaction.  A
    change to any accounting or stock-model count raises an exception inside
    the savepoint, rolling back every product property and evidence write.
    """
    costs, companies, products, before = _preflight(env, path)
    replay_writer._lock(env, "product-cost:all")
    with env.cr.savepoint():
        run, fresh = _get_or_start_run(env, "product-cost:all")
        if not fresh:
            for row in costs:
                product = products[_cost_identity(row)]
                if _read_standard_price(product) != _money(row["source_cost"], "source_cost"):
                    raise UserError("Noorix committed product cost differs for %s" % row["canonical_key"])
                _verify_map(env, run, row, product)
            after = _effect_snapshot(env, [company.id for company in companies.values()])
            _assert_no_financial_or_stock_effects(before, after)
            return json.loads(run.result_json)

        for row in costs:
            product = products[_cost_identity(row)]
            amount = _money(row["source_cost"], "source_cost")
            product.with_company(product.company_id).with_context(
                allowed_company_ids=[product.company_id.id], active_test=False,
            ).write({"standard_price": float(amount)})
            if _read_standard_price(product) != amount:
                raise UserError("Noorix product cost write differs for %s" % row["canonical_key"])
            _ensure_map(
                env,
                source_identity=_cost_identity(row),
                source_row_sha256=row["source_row_sha256"],
                canonical_key=row["canonical_key"],
                target=product,
                run=run,
            )

        after = _effect_snapshot(env, [company.id for company in companies.values()])
        _assert_no_financial_or_stock_effects(before, after)
        result = _result(costs, companies, before, orm_writes=len(costs))
        result["effect_counts_before_after"] = {"before": before, "after": after}
        _commit_run(run, result)
    return result
