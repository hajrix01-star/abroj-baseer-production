"""Run through ``odoo shell`` and feed one JSON line on stdin.

The caller must set ``TARGET_COMPANY_ID`` in the shell globals.  The safety
boundary is deliberately narrow: the script rejects every database other than
the procurement QA database and imports only operational catalogue metadata.
"""
import json
from datetime import datetime
from collections import deque

from odoo import fields
from odoo.exceptions import UserError


EXPECTED_DB = 'baseer_procurement_qa_20260911'
if env.cr.dbname != EXPECTED_DB:
    raise UserError('Legacy catalogue import is restricted to the dedicated procurement QA database.')
if 'TARGET_COMPANY_ID' not in globals():
    raise UserError('Set TARGET_COMPANY_ID explicitly before importing.')

payload = globals().get('LEGACY_PAYLOAD')
if not isinstance(payload, dict):
    raise UserError('Provide a parsed LEGACY_PAYLOAD dictionary to the import shell.')
company = env['res.company'].browse(int(TARGET_COMPANY_ID)).exists()
if not company:
    raise UserError('The explicit QA target company does not exist.')
if payload.get('source_company_id') != '7e64301f-c87e-4d98-9881-35328ace117b':
    raise UserError('Unexpected legacy source company.')

uom_by_code = {
    'piece': env.ref('uom.product_uom_unit'),
    'kg': env.ref('uom.product_uom_kgm'),
    'g': env.ref('uom.product_uom_gram'),
    'l': env.ref('uom.product_uom_litre'),
}
# Include disabled purchase sizes: a historical option may be inactive in the
# legacy catalogue, yet it still needs a stable source key on re-import.
Option = env['baseer.procurement.purchase.option'].sudo().with_context(
    active_test=False,
    _baseer_procurement_option_system_write=True,
)
Product = env['product.product'].sudo()
Uom = env['uom.uom'].sudo()
Category = env['product.category'].sudo()
category = Category.search([('name', '=', 'مواد خام — بصير القديم (QA)')], limit=1)
if not category:
    category = Category.create({'name': 'مواد خام — بصير القديم (QA)'})


def legacy_datetime(value):
    if not value:
        return False
    return fields.Datetime.to_string(datetime.fromisoformat(value.replace('Z', '+00:00')))


def path_factor(edges, source, target):
    """Return source-quantity -> target-quantity factor, or None."""
    graph = {}
    for edge in edges:
        factor = float(edge['factor'])
        if not factor:
            continue
        graph.setdefault(edge['from_unit_id'], []).append((edge['to_unit_id'], factor))
        graph.setdefault(edge['to_unit_id'], []).append((edge['from_unit_id'], 1 / factor))
    queue = deque([(source, 1.0)])
    seen = {source}
    while queue:
        unit, factor = queue.popleft()
        if unit == target:
            return factor
        for destination, multiplier in graph.get(unit, []):
            if destination not in seen:
                seen.add(destination)
                queue.append((destination, factor * multiplier))
    return None


def imported_uom(item, unit, base_unit, factor):
    # Known base units retain Odoo's native global UoM. A size whose factor
    # differs per raw material is deliberately a product-specific derived UoM.
    # Legacy data contains a few duplicate unit identities with the same code
    # (for example box/box). Treat matching codes as the declared base unit;
    # never invent a conversion between two unrelated package definitions.
    if unit['source_id'] == base_unit['source_id'] or unit['code'] == base_unit['code']:
        return base_unit['_target_uom']
    if unit['code'] in uom_by_code and uom_by_code[unit['code']]._has_common_reference(base_unit['_target_uom']):
        return uom_by_code[unit['code']]
    if not factor or factor <= 0:
        return None
    legacy_key = f"[PRC:{item['source_id']}:{unit['source_id']}]"
    result = Uom.search([('name', '=', legacy_key)], limit=1)
    if not result:
        result = Uom.create({
            'name': legacy_key, 'relative_uom_id': base_unit['_target_uom'].id,
            'relative_factor': factor,
        })
    return result


created_products = updated_products = created_options = updated_options = 0
rejected = []
for item in payload.get('items', []):
    unit_by_id = {row['source_id']: row for row in item.get('units', [])}
    base_unit = unit_by_id.get(item.get('base_unit_id'))
    if not base_unit:
        rejected.append({'source_id': item['source_id'], 'reason': 'missing_base_unit'})
        continue
    base_uom = uom_by_code.get(base_unit['code'])
    if not base_uom:
        base_uom = Uom.search([('name', '=', f"[PRC:{item['source_id']}:{base_unit['source_id']}]")], limit=1)
        if not base_uom:
            base_uom = Uom.create({'name': f"[PRC:{item['source_id']}:{base_unit['source_id']}]", 'relative_factor': 1.0})
    base_unit = dict(base_unit, _target_uom=base_uom)
    product = Product.search([('default_code', '=', f"PRC-LEGACY-{item['source_id']}")], limit=1)
    values = {
        'name': item['name_ar'] or item['name_en'] or item['code'],
        'default_code': f"PRC-LEGACY-{item['source_id']}", 'categ_id': category.id,
        'uom_id': base_uom.id, 'is_storable': True,
    }
    if product:
        product.write(values)
        updated_products += 1
    else:
        product = Product.create(values)
        created_products += 1
    for option in item.get('options', []):
        unit = unit_by_id.get(option['unit_id'])
        if not unit:
            rejected.append({'source_id': item['source_id'], 'option_id': option['source_id'], 'reason': 'missing_option_unit'})
            continue
        factor = path_factor(item.get('conversions', []), unit['source_id'], base_unit['source_id'])
        if unit['source_id'] == base_unit['source_id'] or unit['code'] == base_unit['code']:
            factor = 1.0
        target_uom = imported_uom(item, unit, base_unit, factor)
        if not target_uom or not target_uom._has_common_reference(base_uom):
            rejected.append({'source_id': item['source_id'], 'option_id': option['source_id'], 'reason': 'no_safe_conversion'})
            continue
        name = unit['name_ar'] or unit['name_en'] or unit['code']
        existing = Option.search([('company_id', '=', company.id), ('legacy_source_id', '=', option['source_id'])], limit=1)
        if not existing:
            # Backfill the stable source key for the first import, without
            # relying on translated option names stored as JSONB in Odoo 19.
            existing = Option.search([
                ('company_id', '=', company.id), ('product_id', '=', product.id),
                ('uom_id', '=', target_uom.id), ('packaging_note', '=', name),
            ], limit=1)
        option_values = {
            'company_id': company.id, 'product_id': product.id, 'uom_id': target_uom.id,
            # Keep the source UUID in its own immutable field; the catalogue
            # needs the human-readable size in the POS-like interface.
            'name': name, 'packaging_note': name,
            'legacy_source_id': option['source_id'],
            'last_price': option.get('last_price') or 0,
            'last_price_at': legacy_datetime(option.get('last_price_at')),
            'active': bool(option.get('is_order_enabled')),
        }
        if existing:
            existing.write(option_values)
            updated_options += 1
        else:
            Option.create(option_values)
            created_options += 1

result = {
    'database': env.cr.dbname, 'company_id': company.id, 'source': payload.get('source'),
    'source_items': len(payload.get('items', [])), 'created_products': created_products,
    'updated_products': updated_products, 'created_options': created_options,
    'updated_options': updated_options, 'rejected_count': len(rejected), 'rejected': rejected,
}
# Odoo shell deliberately rolls the transaction back at process exit. The
# caller is a restricted QA-only operation, so commit once, after the entire
# payload has passed validation and every item has been processed.
env.cr.commit()
print('PRC_IMPORT_RESULT=' + json.dumps(result, ensure_ascii=False, sort_keys=True))
