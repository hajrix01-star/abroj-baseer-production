import base64
import hashlib
import hmac
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from odoo import _, models
from odoo.exceptions import AccessError, UserError, ValidationError


# Only receipt-related edges are followed. In particular, company partners,
# customer children, other sessions/orders and the product catalogue are not.
RECEIPT_EDGES = {
    'pos.order': ('lines', 'payment_ids', 'partner_id', 'user_id', 'employee_id', 'table_id', 'preset_id', 'fiscal_position_id', 'account_move'),
    'pos.order.line': ('product_id', 'tax_ids', 'pack_lot_ids', 'custom_attribute_value_ids', 'attribute_value_ids', 'combo_item_id'),
    'pos.payment': ('payment_method_id',),
    'pos.config': ('currency_id', 'rounding_method', 'picking_type_id'),
    'res.company': ('country_id', 'state_id', 'currency_id'),
    'res.partner': ('country_id', 'state_id'),
    'res.users': ('partner_id',),
    'res.country.state': ('country_id',),
    'product.product': ('product_tmpl_id', 'product_template_attribute_value_ids'),
    'product.template': ('uom_id', 'taxes_id', 'categ_id', 'pos_categ_ids'),
    'account.tax': ('children_tax_ids', 'tax_group_id'),
    'product.template.attribute.value': ('attribute_id', 'product_attribute_value_id'),
    'product.attribute.custom.value': ('custom_product_template_attribute_value_id',),
    'product.combo.item': ('product_id', 'combo_id'),
    'pos.category': ('parent_id',),
    'stock.picking.type': (),
}
MAX_RECEIPT_RECORDS = 2000
MAX_RECEIPT_DEPTH = 12


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _baseer_check_office_receipt_access(self):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can view customer receipts.'))
        self.check_access('read')
        if not self.exists():
            raise UserError(_('The Point of Sale order no longer exists.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('The receipt belongs to a company that is not selected.'))
        if self.state not in ('paid', 'done', 'invoiced'):
            raise UserError(_('Complete payment before printing the customer receipt.'))
        if self.company_id.country_id.code == 'SA' and self.env['ir.module.module'].sudo().search_count([
            ('name', '=', 'l10n_sa_edi_pos'), ('state', '=', 'installed'),
        ]):
            move = self.account_move
            if (not move or move.company_id != self.company_id or move.state != 'posted'
                    or not move.l10n_sa_qr_code_str or move.edi_state != 'sent'):
                raise UserError(_('The Saudi electronic invoice is not complete; the receipt cannot be printed yet.'))

    def action_baseer_office_receipt(self):
        self._baseer_check_office_receipt_access()
        return {
            'type': 'ir.actions.act_url',
            'url': '/baseer/pos/office-receipt/%s' % self.id,
            'target': 'new',
        }

    def _baseer_original_receipt_image(self):
        # The manager-owned queue remains private. Authorization of the source
        # order/company is checked before this narrow, single-order lookup.
        job = self.env['baseer.print.job'].sudo().search([
            ('source_order_id', '=', self.id),
            ('company_id', '=', self.company_id.id),
            ('ticket_type', '=', 'receipt'),
            ('reprint_of_id', '=', False),
            ('receipt_image', '!=', False),
        ], order='id asc', limit=1)
        if not job or job.payload.get('schema') != 4:
            return False
        try:
            encoded = job.receipt_image
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise UserError(_('The original receipt image could not be verified.'))
        if len(raw) > 3 * 1024 * 1024 or not raw.startswith(b'\xff\xd8'):
            raise UserError(_('The original receipt image could not be verified.'))
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), job.receipt_image_sha256 or ''):
            raise UserError(_('The original receipt image could not be verified.'))
        return encoded.decode('ascii') if isinstance(encoded, bytes) else encoded

    def baseer_office_receipt_data(self):
        self._baseer_check_office_receipt_access()
        image = self._baseer_original_receipt_image()
        if image:
            return {'image': image, 'name': self.pos_reference or self.name}

        order = self.with_company(self.company_id).with_context(active_test=False, pos_limited_loading=False)
        session, config = order.session_id, order.config_id
        session.check_access('read')
        config.check_access('read')
        params = session.load_data_params()
        # Metadata is native, while record reads are bounded to this order's graph.
        data = {model: [] for model in params}
        pending = {
            'pos.order': {order.id}, 'pos.session': {session.id},
            'pos.config': {config.id}, 'res.company': {order.company_id.id},
            'decimal.precision': set(order.env['decimal.precision'].search([
                ('name', 'in', ['Product Unit', 'Product Price', 'Discount'])
            ]).ids),
        }
        seen = {model: set() for model in params}
        for _depth in range(MAX_RECEIPT_DEPTH):
            next_pending = {}
            for model, ids in pending.items():
                if model not in params:
                    continue
                ids = ids - seen[model]
                if not ids:
                    continue
                if sum(map(len, seen.values())) + len(ids) > MAX_RECEIPT_RECORDS:
                    raise UserError(_('This receipt is too large to preview safely.'))
                records = order.env[model].browse(sorted(ids)).exists()
                records.check_access('read')
                seen[model].update(ids)
                values = order.env[model]._load_pos_data_read(records, config)
                data[model].extend(values)
                for name in RECEIPT_EDGES.get(model, ()):
                    field = records._fields.get(name)
                    if not field or field.comodel_name not in params:
                        continue
                    related = records.mapped(name)
                    next_pending.setdefault(field.comodel_name, set()).update(related.ids)
            if not next_pending:
                break
            pending = next_pending
        else:
            raise UserError(_('The receipt contains too many nested details to preview safely.'))
        return {
            'name': self.pos_reference or self.name,
            'params': params,
            'data': data,
        }

    def baseer_validate_office_receipt(self, displayed):
        """Fail closed if current tax/master data changes historical amounts."""
        self._baseer_check_office_receipt_access()
        if not isinstance(displayed, dict) or not isinstance(displayed.get('lines'), list):
            raise ValidationError(_('Invalid receipt details.'))
        if len(displayed['lines']) != len(self.lines):
            raise ValidationError(_('The receipt does not contain all original order lines.'))

        quantum = Decimal(str(self.currency_id.rounding))

        def matches(value, stored):
            try:
                number = Decimal(str(value))
                expected = Decimal(str(stored))
                if not number.is_finite() or len(str(value)) > 64:
                    return False
                return ((number / quantum).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                        == (expected / quantum).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            except (InvalidOperation, ValueError, TypeError):
                return False

        pairs = [('total', self.amount_total), ('tax', self.amount_tax), ('paid', self.amount_paid), ('change', self.amount_return)]
        lines = {line.id: line for line in self.lines}
        visited = set()
        for value in displayed['lines']:
            if not isinstance(value, dict) or not isinstance(value.get('id'), int):
                raise ValidationError(_('Invalid receipt details.'))
            line = lines.get(value['id'])
            if not line or line.id in visited:
                raise ValidationError(_('Invalid receipt details.'))
            visited.add(line.id)
            if not matches(value.get('excl'), line.price_subtotal) or not matches(value.get('incl'), line.price_subtotal_incl):
                raise UserError(_('The current receipt amounts differ from the saved order. The original receipt is required.'))
        if any(not matches(displayed.get(key), amount) for key, amount in pairs):
            raise UserError(_('The current receipt amounts differ from the saved order. The original receipt is required.'))
        return True
