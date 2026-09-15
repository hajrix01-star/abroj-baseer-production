from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import math
import re
import unicodedata
from urllib.parse import quote
from uuid import UUID

from psycopg2 import IntegrityError
from odoo import api, fields, models, _, Command
from odoo.exceptions import AccessError, ConcurrencyError, UserError, ValidationError


REQUEST_CREATE_INTERNAL = '_baseer_procurement_request_create_internal'
OPTION_SYSTEM_WRITE = '_baseer_procurement_option_system_write'
FAVORITE_SYSTEM_WRITE = '_baseer_procurement_favorite_system_write'
IDENTITY_SYSTEM_WRITE = '_baseer_procurement_identity_system_write'
MONEY_QUANTUM = Decimal('0.01')
MAX_CATALOG_LINES = 200
MAX_CATALOG_HIGHLIGHTS = 12
NOORIX_MESSAGE_PREFIX_RE = re.compile(r'^\s*\[NOORIX(?:-[A-Z0-9]+)*\]\s*', re.IGNORECASE)


def _is_finite_number(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _decimal_input(value, label, *, positive=False):
    """Parse a UI decimal without binary-float calculation or hidden rounding."""
    try:
        number = Decimal(str(value if value not in (None, '') else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError('%s must be a valid number.' % label)
    if not number.is_finite():
        raise ValidationError('%s must be a finite number.' % label)
    rounded = number.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if number != rounded:
        raise ValidationError('%s cannot have more than two decimal places.' % label)
    if number < 0 or (positive and number <= 0):
        raise ValidationError('%s must be positive.' % label)
    return rounded


def _decimal_total(quantity, price):
    return (Decimal(str(quantity or 0)) * Decimal(str(price or 0))).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _decimal_text(value):
    return format(Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP), ',.2f')


def _whatsapp_product_label(product):
    """Keep migrated source IDs out of the customer-facing WhatsApp text."""
    display_name = product.display_name or ''
    cleaned_name = NOORIX_MESSAGE_PREFIX_RE.sub('', display_name).strip()
    return cleaned_name or display_name


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_purchase_representative = fields.Boolean(
        string='Purchase representative',
        company_dependent=True,
        help='Enable this contact as a purchasing representative in the active company.',
    )


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _baseer_check_procurement_option_usage_before_delete(self):
        options = self.env['baseer.procurement.purchase.option'].sudo().search([
            ('product_id', 'in', self.ids),
        ])
        if not options:
            return
        is_used = self.env['baseer.procurement.request.line'].sudo().search_count([
            ('option_id', 'in', options.ids),
        ], limit=1) or self.env['baseer.procurement.price.history'].sudo().search_count([
            ('option_id', 'in', options.ids),
        ], limit=1)
        if is_used:
            raise UserError(_(
                'This product is used in a procurement request or purchase-price history. '
                'Archive it instead of deleting it.'
            ))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_procurement_option_usage(self):
        self._baseer_check_procurement_option_usage_before_delete()


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.ondelete(at_uninstall=False)
    def _unlink_except_procurement_option_usage(self):
        variants = self.with_context(active_test=False).product_variant_ids
        variants._baseer_check_procurement_option_usage_before_delete()


class ProcurementOption(models.Model):
    _name = 'baseer.procurement.purchase.option'
    _description = 'Raw material purchase option'
    _order = 'sequence, product_id, id'
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company,
                                 index=True, ondelete='restrict')
    product_id = fields.Many2one('product.product', required=True, ondelete='cascade', check_company=True,
                                 domain="[('active', '=', True), ('purchase_ok', '=', True), ('type', '=', 'consu'), ('company_id', '=', company_id)]")
    category_id = fields.Many2one(related='product_id.categ_id', store=True, readonly=True, index=True)
    uom_id = fields.Many2one('uom.uom', required=True, ondelete='restrict', string='Purchase unit')
    packaging_note = fields.Char(string='Size / packaging', default='')
    catalog_default_key = fields.Char(readonly=True, copy=False, index=True)
    legacy_source_id = fields.Char(readonly=True, copy=False, index=True)
    last_price = fields.Monetary(currency_field='currency_id', readonly=True, copy=False)
    last_price_at = fields.Datetime(readonly=True, copy=False)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)

    _baseer_procurement_option_unique = models.Constraint(
        'unique(company_id, product_id, uom_id, packaging_note)',
        'A purchase option already exists for this material, unit and packaging.',
    )
    _baseer_procurement_legacy_option_unique = models.Constraint(
        'unique(company_id, legacy_source_id)',
        'A legacy purchase option was already imported for this company.',
    )
    _baseer_procurement_catalog_default_unique = models.Constraint(
        'unique(company_id, catalog_default_key)',
        'A default catalogue option already exists for this material.',
    )

    @api.constrains('product_id', 'uom_id', 'company_id')
    def _check_option(self):
        for option in self:
            product = option.product_id
            if product.company_id != option.company_id:
                raise ValidationError(_('The material must belong to the selected company.'))
            if not product.active or not product.purchase_ok or product.type != 'consu':
                raise ValidationError(_('The material must be an active purchasable goods product.'))
            if not option.product_id.uom_id._has_common_reference(option.uom_id):
                raise ValidationError(_('The purchase unit must be convertible to the material inventory unit.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('packaging_note', '')
            if not (self.env.su and self.env.context.get(OPTION_SYSTEM_WRITE)) and {
                'catalog_default_key', 'legacy_source_id', 'last_price', 'last_price_at',
            }.intersection(vals):
                raise AccessError(_('Technical source keys and last purchase prices are maintained by the procurement workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if not vals:
            return True
        system_write = bool(self.env.su and self.env.context.get(OPTION_SYSTEM_WRITE))
        protected = {'catalog_default_key', 'legacy_source_id', 'last_price', 'last_price_at'}
        if not system_write and protected.intersection(vals):
            raise AccessError(_('Technical source keys and last purchase prices are maintained by the procurement workflow.'))
        identity = {'company_id', 'product_id', 'uom_id', 'packaging_note'}
        if identity.intersection(vals):
            referenced = self.env['baseer.procurement.request.line'].sudo().search_count([
                ('option_id', 'in', self.ids),
            ], limit=1) or self.env['baseer.procurement.price.history'].sudo().search_count([
                ('option_id', 'in', self.ids),
            ], limit=1)
            if referenced:
                raise UserError(_(
                    'A purchase option already used by a request is historically frozen. '
                    'Archive it and create a new option instead.'
                ))
        return super().write(vals)


class ProcurementPriceHistory(models.Model):
    _name = 'baseer.procurement.price.history'
    _description = 'Raw material actual price history'
    _order = 'purchase_date desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='restrict')
    option_id = fields.Many2one('baseer.procurement.purchase.option', required=True, index=True,
                                ondelete='restrict', check_company=True)
    product_id = fields.Many2one(
        'product.product', required=True, readonly=True, index=True,
        ondelete='restrict', check_company=True, string='Product snapshot',
    )
    request_id = fields.Many2one('baseer.procurement.request', required=True, index=True,
                                 ondelete='restrict', check_company=True)
    warehouse_id = fields.Many2one(related='request_id.warehouse_id', store=True, readonly=True, index=True)
    purchaser_id = fields.Many2one(related='request_id.purchaser_id', store=True, readonly=True, index=True)
    representative_partner_id = fields.Many2one(
        related='request_id.representative_partner_id', store=True, readonly=True, index=True,
    )
    line_id = fields.Many2one('baseer.procurement.request.line', required=True, index=True,
                               ondelete='restrict', check_company=True)
    purchase_date = fields.Datetime(required=True, index=True)
    unit_price = fields.Monetary(required=True, currency_field='currency_id')
    quantity = fields.Float(required=True, digits='Product Unit of Measure')
    purchase_uom_id = fields.Many2one(
        'uom.uom', string='Purchase unit snapshot', readonly=True, ondelete='restrict',
    )
    inventory_uom_id = fields.Many2one(
        'uom.uom', string='Inventory unit snapshot', readonly=True, ondelete='restrict',
    )
    inventory_unit_cost = fields.Monetary(
        string='Inventory unit cost', currency_field='currency_id', readonly=True,
    )
    previous_standard_price = fields.Monetary(
        string='Previous standard cost', currency_field='currency_id', readonly=True,
    )
    new_standard_price = fields.Monetary(
        string='New standard cost', currency_field='currency_id', readonly=True,
    )
    stock_receipt_created = fields.Boolean(string='Stock receipt created', readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)

    def init(self):
        super().init()
        self.env.cr.execute(
            'CREATE INDEX IF NOT EXISTS baseer_procurement_price_history_company_product_date_idx '
            'ON baseer_procurement_price_history (company_id, product_id, purchase_date DESC)'
        )

    @api.model_create_multi
    def create(self, vals_list):
        Option = self.env['baseer.procurement.purchase.option']
        for vals in vals_list:
            option = Option.browse(vals.get('option_id')).exists()
            if not option:
                raise ValidationError(_('A valid purchase option is required for price history.'))
            product_id = vals.setdefault('product_id', option.product_id.id)
            if product_id != option.product_id.id:
                raise ValidationError(_('The price-history product snapshot must match the purchase option.'))
        return super().create(vals_list)

    def write(self, vals):
        if vals:
            raise UserError(_('Actual price history is immutable. Create a correcting receipt instead.'))
        return True

    def unlink(self):
        raise UserError(_('Actual price history is immutable. Create a correcting receipt instead.'))


class ProcurementProductFavorite(models.Model):
    _name = 'baseer.procurement.product.favorite'
    _description = 'Procurement cashier product favorite'
    _order = 'write_date desc, id desc'
    _check_company_auto = True

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', required=True, index=True, ondelete='cascade', check_company=True,
    )
    is_favorite = fields.Boolean(required=True, default=True, index=True)

    _baseer_procurement_favorite_unique = models.Constraint(
        'unique(user_id, company_id, product_id)',
        'This product is already a favorite for this cashier and company.',
    )

    @api.constrains('company_id', 'product_id')
    def _check_favorite_company(self):
        for favorite in self:
            if favorite.product_id.company_id != favorite.company_id:
                raise ValidationError(_('A favorite product must belong to the selected company.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(FAVORITE_SYSTEM_WRITE)):
            raise AccessError(_('Procurement favorites are maintained from the cashier catalogue.'))
        return super().create(vals_list)

    def write(self, vals):
        if vals and not (self.env.su and self.env.context.get(FAVORITE_SYSTEM_WRITE)):
            raise AccessError(_('Procurement favorites are maintained from the cashier catalogue.'))
        return super().write(vals)

    def unlink(self):
        if not (self.env.su and self.env.context.get(FAVORITE_SYSTEM_WRITE)):
            raise AccessError(_('Procurement favorites are maintained from the cashier catalogue.'))
        return super().unlink()


class ProcurementProductIdentity(models.Model):
    """Unique canonical-name authority for concurrency-safe quick creation."""

    _name = 'baseer.procurement.product.identity'
    _description = 'Procurement quick-product canonical identity'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='cascade')
    normalized_name = fields.Char(required=True, index=True)
    product_id = fields.Many2one(
        'product.product', required=True, index=True, ondelete='cascade', check_company=True,
    )

    _baseer_procurement_product_identity_unique = models.Constraint(
        'unique(company_id, normalized_name)',
        'This normalized product name is already reserved for the company.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(IDENTITY_SYSTEM_WRITE)):
            raise AccessError(_('Quick-product identities are maintained automatically.'))
        return super().create(vals_list)

    def write(self, vals):
        if vals and not (self.env.su and self.env.context.get(IDENTITY_SYSTEM_WRITE)):
            raise AccessError(_('Quick-product identities are maintained automatically.'))
        return super().write(vals)

    def unlink(self):
        if not (self.env.su and self.env.context.get(IDENTITY_SYSTEM_WRITE)):
            raise AccessError(_('Quick-product identities are maintained automatically.'))
        return super().unlink()


class ProcurementRequest(models.Model):
    _name = 'baseer.procurement.request'
    _description = 'Procurement request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True, default=lambda self: _('New'), copy=False, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company,
                                 index=True, ondelete='restrict', tracking=True)
    warehouse_id = fields.Many2one('stock.warehouse', required=True, check_company=True, ondelete='restrict',
                                   domain="[('company_id', '=', company_id)]", tracking=True)
    # Kept for existing employee-based requests.  New requests use the Contact
    # field below, so a purchasing representative does not need an employee or
    # supplier record merely to hold purchasing custody.
    purchaser_id = fields.Many2one(
        'hr.employee.public', string='Legacy purchasing employee', check_company=True,
        ondelete='restrict', tracking=True,
    )
    representative_partner_id = fields.Many2one(
        'res.partner', string='Purchase representative', check_company=True,
        ondelete='restrict', tracking=True, index=True,
        domain="[('is_purchase_representative', '=', True), ('is_company', '=', False), ('parent_id', '=', False), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help='A standalone contact enabled as a purchase representative in this company.',
    )
    requester_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user,
                                   ondelete='restrict', tracking=True)
    request_date = fields.Datetime(required=True, default=fields.Datetime.now, tracking=True)
    whatsapp_number = fields.Char()
    whatsapp_text = fields.Text(compute='_compute_whatsapp_text')
    whatsapp_opened_at = fields.Datetime(readonly=True, copy=False)
    whatsapp_sent_at = fields.Datetime(readonly=True, copy=False, tracking=True)
    manager_received_at = fields.Datetime(readonly=True, copy=False, tracking=True)
    actual_confirmed_at = fields.Datetime(readonly=True, copy=False, tracking=True)
    actual_confirmed_by_id = fields.Many2one('res.users', readonly=True, copy=False, ondelete='restrict')
    cancellation_reason = fields.Text(copy=False, readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('sent', 'Sent for purchase'), ('received', 'Manager receipt confirmed'),
        ('purchased', 'Quantity receipt completed'), ('cancel', 'Cancelled'),
    ], default='draft', required=True, readonly=True, tracking=True, index=True)
    line_ids = fields.One2many('baseer.procurement.request.line', 'request_id', copy=True)
    picking_id = fields.Many2one('stock.picking', readonly=True, copy=False, check_company=True, ondelete='restrict')
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    requested_total = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    actual_total = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    client_token = fields.Char(readonly=True, copy=False, index=True)
    client_payload_hash = fields.Char(readonly=True, copy=False)

    _baseer_procurement_request_client_token_unique = models.Constraint(
        'unique(company_id, requester_id, client_token)',
        'This procurement cart has already been submitted.',
    )

    @api.constrains('company_id', 'representative_partner_id')
    def _check_representative_partner(self):
        for request in self.filtered('representative_partner_id'):
            partner = request.representative_partner_id
            if partner.company_id and partner.company_id != request.company_id:
                raise ValidationError(_('The purchase representative must belong to the request company or be shared.'))
            if partner.is_company or partner.parent_id:
                raise ValidationError(_('Choose a standalone person as the purchase representative.'))
            if not partner.with_company(request.company_id).is_purchase_representative:
                raise ValidationError(_('The selected contact is not enabled as a purchase representative in this company.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            internal = bool(self.env.context.get(REQUEST_CREATE_INTERNAL) and self.env.su)
            protected = {
                'state', 'picking_id', 'whatsapp_opened_at', 'whatsapp_sent_at', 'manager_received_at',
                'actual_confirmed_at', 'actual_confirmed_by_id', 'client_token', 'client_payload_hash',
            }
            if not internal and protected & set(vals):
                raise AccessError(_('Request state, receipt links, and audit timestamps are controlled by the server.'))
            if not internal:
                if vals.get('company_id') and int(vals['company_id']) != self.env.company.id:
                    raise AccessError(_('Procurement requests must be created in the active company.'))
                if vals.get('requester_id') and int(vals['requester_id']) != self.env.user.id:
                    raise AccessError(_('A requester can only create their own procurement request.'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('baseer.procurement.request') or _('New')
        return super().create(vals_list)

    @api.depends('line_ids.requested_qty', 'line_ids.requested_price', 'line_ids.actual_qty', 'line_ids.actual_price')
    def _compute_totals(self):
        for request in self:
            requested = sum((_decimal_total(line.requested_qty, line.requested_price) for line in request.line_ids), Decimal('0.00'))
            actual = sum((_decimal_total(line.actual_qty, line.actual_price) for line in request.line_ids), Decimal('0.00'))
            request.requested_total = float(requested.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))
            request.actual_total = float(actual.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))

    @api.depends(
        'request_date', 'currency_id',
        'line_ids.option_id', 'line_ids.requested_qty', 'line_ids.requested_price',
    )
    def _compute_whatsapp_text(self):
        for request in self:
            request_date = fields.Datetime.context_timestamp(
                request, request.request_date
            ).date()
            currency_symbol = request.currency_id.symbol or request.currency_id.name
            lines = [
                'طلب مشتريات',
                'التاريخ: %s' % fields.Date.to_string(request_date),
                '',
            ]
            for line in request.line_ids:
                line_total = _decimal_total(line.requested_qty, line.requested_price)
                lines.append(
                    '• %s (%s): %s × %s = %s %s' % (
                        _whatsapp_product_label(line.option_id.product_id),
                        line.option_id.name,
                        _decimal_text(line.requested_qty),
                        _decimal_text(line.requested_price),
                        _decimal_text(line_total),
                        currency_symbol,
                    )
                )
            lines.extend([
                '',
                'الإجمالي التقديري: %s %s' % (
                    _decimal_text(request.requested_total), currency_symbol,
                ),
            ])
            request.whatsapp_text = '\n'.join(lines)

    def _require_state(self, *states):
        for request in self:
            if request.state not in states:
                raise UserError(_('This action is not available in the current request state.'))

    def _require_active_company_for_cashier(self):
        """Keep every cashier mutation inside the currently active company.

        Record rules deliberately let a multi-company user read the companies
        enabled for the session.  That must not permit the operational cashier
        role to mutate a request from another selected company through a form
        method or direct ORM call.  Managers without the cashier capability
        retain their existing multi-company workflow.
        """
        if self.env.su or not self.env.user.has_group(
            'baseer_procurement_requests.group_procurement_cashier'
        ):
            return
        if any(request.company_id != self.env.company for request in self):
            raise AccessError(_('The procurement request is unavailable in the active company.'))

    def action_mark_whatsapp_opened(self):
        self._require_active_company_for_cashier()
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_user'):
            raise AccessError(_('You are not allowed to send procurement requests.'))
        if self.state == 'cancel':
            raise UserError(_('A cancelled procurement request cannot be shared on WhatsApp.'))
        super(ProcurementRequest, self).write({'whatsapp_opened_at': fields.Datetime.now()})
        return True

    def action_open_whatsapp(self):
        """Open a human-confirmed WhatsApp share; the user chooses the recipient."""
        self.ensure_one()
        self.action_mark_whatsapp_opened()
        return {
            'type': 'ir.actions.act_url',
            'url': 'https://wa.me/?text=%s' % quote(self.whatsapp_text or ''),
            'target': 'new',
        }

    def action_mark_sent(self):
        self._require_active_company_for_cashier()
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_user'):
            raise AccessError(_('You are not allowed to send procurement requests.'))
        self._require_state('draft')
        if not self.line_ids:
            raise UserError(_('Add at least one raw material before sending the request.'))
        if not self.representative_partner_id and not self.purchaser_id:
            raise UserError(_('Choose the purchase representative before sending the request.'))
        super(ProcurementRequest, self).write({'state': 'sent', 'whatsapp_sent_at': fields.Datetime.now()})
        return True

    def action_confirm_manager_receipt(self):
        self._require_active_company_for_cashier()
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_manager'):
            raise AccessError(_('Only a procurement manager can confirm the operational receipt.'))
        self._require_state('sent')
        if not any(line.manager_received_qty > 0 for line in self.line_ids):
            raise UserError(_('Enter at least one physically received quantity.'))
        super(ProcurementRequest, self).write({'state': 'received', 'manager_received_at': fields.Datetime.now()})
        return True

    def action_open_manager_receipt_catalog(self):
        """Open the shared cashier surface for the manager's physical receipt."""
        self.ensure_one()
        self._require_active_company_for_cashier()
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_manager'):
            raise AccessError(_('Only a procurement manager can confirm the operational receipt.'))
        self._require_state('sent')
        return {
            'type': 'ir.actions.client', 'tag': 'baseer_procurement_requests.actual_catalog',
            'name': _('Manager receipt'), 'params': {'request_id': self.id, 'mode': 'manager_receipt'},
        }

    def action_cancel(self):
        self._require_active_company_for_cashier()
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_user'):
            raise AccessError(_('You are not allowed to cancel procurement requests.'))
        self._require_state('draft', 'sent')
        if not self.cancellation_reason or not self.cancellation_reason.strip():
            raise ValidationError(_('Enter a cancellation reason before cancelling the procurement request.'))
        super(ProcurementRequest, self).write({'state': 'cancel'})
        return True

    @api.model
    def _catalog_product_domain(self, search_term=False, category_id=False):
        """The active company's goods products are the catalogue authority."""
        term = (search_term or '').strip()
        if len(term) > 128:
            raise ValidationError(_('Search text cannot exceed 128 characters.'))
        domain = [
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
            ('purchase_ok', '=', True),
            ('type', '=', 'consu'),
        ]
        if category_id:
            try:
                domain.append(('categ_id', '=', int(category_id)))
            except (TypeError, ValueError):
                raise ValidationError(_('The selected material category is invalid.'))
        if term:
            option_product_ids = self.env['baseer.procurement.purchase.option'].search([
                ('company_id', '=', self.env.company.id),
                ('active', '=', True),
                ('product_id.company_id', '=', self.env.company.id),
                ('product_id.active', '=', True),
                ('product_id.purchase_ok', '=', True),
                ('product_id.type', '=', 'consu'),
                '|', '|',
                ('name', 'ilike', term),
                ('packaging_note', 'ilike', term),
                ('uom_id.name', 'ilike', term),
            ]).product_id.ids
            domain += [
                '|', '|', '|', '|', '|',
                ('name', 'ilike', term),
                ('default_code', 'ilike', term),
                ('barcode', 'ilike', term),
                ('uom_id.name', 'ilike', term),
                ('categ_id.name', 'ilike', term),
                ('id', 'in', option_product_ids),
            ]
        return domain

    @api.model
    def _assert_catalog_products(self, products):
        unavailable = products.filtered(
            lambda product: product.company_id != self.env.company
            or not product.active
            or not product.purchase_ok
            or product.type != 'consu'
        )
        if unavailable:
            raise AccessError(_('The cart contains an unavailable material.'))

    @api.model
    def _assert_catalog_options(self, options):
        if any(option.company_id != self.env.company or not option.active for option in options):
            raise AccessError(_('The cart contains an unavailable material.'))
        self._assert_catalog_products(options.product_id)
        if any(not option.uom_id._has_common_reference(option.product_id.uom_id) for option in options):
            raise AccessError(_('The cart contains an incompatible material unit.'))

    @api.model
    def _lock_catalog_products(self, products):
        """Serialize option/cost writes in a stable order to avoid lock inversion."""
        product_ids = sorted(set(products.ids))
        if product_ids:
            self.env.cr.execute(
                'SELECT id FROM product_product WHERE id IN %s ORDER BY id FOR UPDATE',
                [tuple(product_ids)],
            )

    @api.model
    def _default_options_for_products(self, products):
        """Return/create one default inventory-UoM option per eligible product.

        Product row locks are acquired in ascending order.  New defaults use an
        empty (not NULL) packaging key so the existing SQL uniqueness constraint
        remains a final backstop; legacy options are reused without rewriting or
        deleting them.
        """
        products = products.sorted('id')
        if not products:
            return self.env['baseer.procurement.purchase.option']
        self._assert_catalog_products(products)
        self._lock_catalog_products(products)
        option_model = self.env['baseer.procurement.purchase.option'].sudo().with_company(self.env.company)
        candidates = option_model.with_context(active_test=False).search([
            ('company_id', '=', self.env.company.id),
            ('product_id', 'in', products.ids),
            ('packaging_note', 'in', [False, '']),
        ], order='active desc, sequence, id')
        marked_defaults = option_model.with_context(active_test=False).search([
            ('company_id', '=', self.env.company.id),
            ('catalog_default_key', 'in', [str(product_id) for product_id in products.ids]),
        ])
        defaults = option_model.browse()
        for product in products:
            default_key = str(product.id)
            option = marked_defaults.filtered(
                lambda candidate: candidate.catalog_default_key == default_key
                and candidate.product_id == product
                and candidate.uom_id == product.uom_id
            )[:1]
            if not option:
                stale_default = marked_defaults.filtered(
                    lambda candidate: candidate.catalog_default_key == default_key
                )
                if stale_default:
                    stale_default.with_context(**{OPTION_SYSTEM_WRITE: True}).write({'catalog_default_key': False})
            option = option or candidates.filtered(
                lambda candidate: candidate.product_id == product and candidate.uom_id == product.uom_id
            ).sorted(lambda candidate: (candidate.packaging_note != '', not candidate.active, candidate.sequence, candidate.id))[:1]
            if option:
                values = {}
                if not option.active:
                    values['active'] = True
                if option.catalog_default_key != default_key:
                    values['catalog_default_key'] = default_key
                if values:
                    option.with_context(**{OPTION_SYSTEM_WRITE: True}).write(values)
            else:
                opening_cost = Decimal(str(
                    product.sudo().with_company(self.env.company).standard_price or 0
                ))
                option = option_model.with_context(**{OPTION_SYSTEM_WRITE: True}).create({
                    'name': product.uom_id.display_name,
                    'company_id': self.env.company.id,
                    'product_id': product.id,
                    'uom_id': product.uom_id.id,
                    'packaging_note': '',
                    'catalog_default_key': default_key,
                    'last_price': float(opening_cost),
                    'last_price_at': False,
                })
            defaults |= option
        return defaults

    def _assert_purchase_setup(self, lines):
        products = lines.option_id.product_id
        self._assert_catalog_products(products)
        product_ids = [line.option_id.product_id.id for line in lines]
        if len(product_ids) != len(set(product_ids)):
            raise UserError(_('A material cannot appear twice in the same request.'))
        for line in lines:
            product = line.option_id.product_id
            if line.option_id.company_id != self.company_id or not line.option_id.active:
                raise UserError(_('The material %s is no longer available.') % product.display_name)
            category = product.categ_id.with_company(self.company_id)
            cost_method_field = category._fields.get('property_cost_method')
            if cost_method_field and category.property_cost_method != 'standard':
                raise UserError(_('The material %s must use standard costing.') % product.display_name)
            valuation_field = category._fields.get('property_valuation')
            if product.is_storable and valuation_field and category.property_valuation == 'real_time':
                raise UserError(_('Quantity-only receipts require periodic/manual valuation. Material %s is real-time valued.') % product.display_name)
            if not line.option_id.uom_id._has_common_reference(product.uom_id):
                raise UserError(_('The selected purchase unit is incompatible with %s.') % product.display_name)
        if lines.filtered(lambda line: line.option_id.product_id.is_storable) and (
            not self.warehouse_id.in_type_id
            or not self.warehouse_id.in_type_id.default_location_src_id
            or not self.warehouse_id.in_type_id.default_location_dest_id
        ):
            raise UserError(_('Configure the warehouse incoming operation and locations before confirming a quantity receipt.'))

    @api.model
    def _inventory_unit_cost(self, option, purchase_price):
        """Convert through Odoo's UoM authority, then apply the approved currency precision."""
        purchase_price = _decimal_input(purchase_price, _('Actual unit price'), positive=True)
        converted = Decimal(str(option.uom_id._compute_price(
            float(purchase_price), option.product_id.uom_id,
        )))
        if not converted.is_finite() or converted <= 0:
            raise UserError(_('The unit conversion for %s is invalid.') % option.product_id.display_name)
        return converted.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)

    def action_confirm_actual_purchase(self):
        self.ensure_one()
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
            raise AccessError(_('Only a procurement cashier can confirm the quantity receipt.'))
        self._require_active_company_for_cashier()
        if self.state == 'purchased':
            return self.action_open_picking()
        self._require_state('received')
        self.env.cr.execute('SELECT id FROM baseer_procurement_request WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        if self.state == 'purchased':
            return self.action_open_picking()
        if not any(line.actual_qty > 0 and line.actual_price > 0 for line in self.line_ids):
            raise UserError(_('Enter a positive actual quantity and price for at least one received material.'))
        invalid = self.line_ids.filtered(lambda line: not _is_finite_number(line.actual_qty) or not _is_finite_number(line.actual_price) or line.actual_qty < 0 or line.actual_price < 0 or (line.actual_qty > 0 and not line.actual_price))
        if invalid:
            raise UserError(_('Actual quantities cannot be negative and every purchased material needs a positive price.'))
        purchased_lines = self.line_ids.filtered(lambda row: row.actual_qty > 0)
        self._assert_purchase_setup(purchased_lines)
        self._lock_catalog_products(purchased_lines.option_id.product_id)
        picking_type = self.warehouse_id.in_type_id
        moves = []
        for line in purchased_lines:
            if line.actual_qty > line.manager_received_qty:
                raise UserError(_('Actual quantity for %s cannot exceed the manager receipt.') % line.option_id.product_id.display_name)
            if not line.option_id.product_id.is_storable:
                continue
            product = line.option_id.product_id
            qty = line.option_id.uom_id._compute_quantity(line.actual_qty, product.uom_id)
            moves.append(Command.create({
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': picking_type.default_location_dest_id.id,
            }))
        picking = self.env['stock.picking']
        if moves:
            picking = self.env['stock.picking'].sudo().with_company(self.company_id).create({
                'picking_type_id': picking_type.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': picking_type.default_location_dest_id.id,
                'origin': self.name,
                'move_ids': moves,
            })
            picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.button_validate()
            if picking.state != 'done':
                raise UserError(_('The native stock receipt did not complete.'))
            # Quantity-only stock receipts must remain free of hidden entries.
            accounted = picking.move_ids.filtered(
                lambda move: 'account_move_id' in move._fields and move.account_move_id
            )
            if accounted:
                raise UserError(_('This receipt created an accounting move and was rejected by the quantity-only guard.'))
        now = fields.Datetime.now()
        histories = []
        for line in purchased_lines.sorted(lambda row: (row.option_id.product_id.id, row.id)):
            product = line.option_id.product_id
            company_product = product.sudo().with_company(self.company_id)
            previous_cost = Decimal(str(company_product.standard_price or 0))
            inventory_cost = self._inventory_unit_cost(line.option_id, line.actual_price)
            company_product.write({'standard_price': float(inventory_cost)})
            histories.append({
                'company_id': self.company_id.id, 'option_id': line.option_id.id,
                'product_id': product.id, 'request_id': self.id,
                'line_id': line.id, 'purchase_date': now, 'unit_price': line.actual_price, 'quantity': line.actual_qty,
                'purchase_uom_id': line.option_id.uom_id.id,
                'inventory_uom_id': product.uom_id.id,
                'inventory_unit_cost': float(inventory_cost),
                'previous_standard_price': float(previous_cost),
                'new_standard_price': float(inventory_cost),
                'stock_receipt_created': bool(product.is_storable and picking),
            })
            line.option_id.sudo().with_company(self.company_id).with_context(
                **{OPTION_SYSTEM_WRITE: True}
            ).write({'last_price': line.actual_price, 'last_price_at': now})
        super(ProcurementRequest, self).write({
            'state': 'purchased', 'picking_id': picking.id or False, 'actual_confirmed_at': now,
            'actual_confirmed_by_id': self.env.user.id,
        })
        self.env['baseer.procurement.price.history'].sudo().with_company(self.company_id).create(histories)
        return self.action_open_picking()

    def action_open_actual_catalog(self):
        self.ensure_one()
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
            raise AccessError(_('Only a procurement cashier can enter actual purchase details.'))
        self._require_active_company_for_cashier()
        self._require_state('sent', 'received')
        return {
            'type': 'ir.actions.client', 'tag': 'baseer_procurement_requests.actual_catalog',
            'name': self.display_name,
            'params': {'request_id': self.id, 'mode': 'cashier_receipt' if self.state == 'sent' else 'cashier'},
        }

    @api.model
    def _catalog_domain(self, search_term=False, category_id=False):
        term = (search_term or '').strip()
        if len(term) > 128:
            raise ValidationError(_('Search text cannot exceed 128 characters.'))
        domain = [
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
            ('product_id.company_id', '=', self.env.company.id),
            ('product_id.active', '=', True),
            ('product_id.purchase_ok', '=', True),
            ('product_id.type', '=', 'consu'),
        ]
        if category_id:
            try:
                domain.append(('category_id', '=', int(category_id)))
            except (TypeError, ValueError):
                raise ValidationError(_('The selected material category is invalid.'))
        if term:
            domain += [
                '|', '|', '|',
                ('name', 'ilike', term),
                ('packaging_note', 'ilike', term),
                ('product_id.name', 'ilike', term),
                ('uom_id.name', 'ilike', term),
            ]
        return domain

    @api.model
    def _check_catalog_access(self):
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_user'):
            raise AccessError(_('You are not allowed to browse the procurement catalogue.'))

    @api.model
    def _check_catalog_curator_access(self):
        self._check_catalog_access()
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
            raise AccessError(_('Only a procurement cashier can maintain catalogue shortcuts.'))

    @api.model
    def _canonical_product_name(self, value):
        normalized = unicodedata.normalize('NFKC', str(value or ''))
        return ' '.join(normalized.split()).casefold()

    @api.model
    def _catalog_advisory_lock(self, namespace, *parts):
        payload = '|'.join([namespace, *(str(part) for part in parts)])
        lock_key = int.from_bytes(hashlib.sha256(payload.encode('utf-8')).digest()[:8], 'big', signed=True)
        self.env.cr.execute('SELECT pg_try_advisory_xact_lock(%s)', [lock_key])
        if not self.env.cr.fetchone()[0]:
            # Let Odoo retry the whole RPC in a new transaction once the
            # concurrent winner has committed.  Keeping the lock, reads and
            # writes on this cursor preserves normal RPC rollback semantics.
            raise ConcurrencyError('Concurrent catalogue update; retry the transaction.')

    @api.model
    def _catalog_lock_company_id(self):
        """Resolve the active company without opening an MVCC snapshot first."""
        allowed_company_ids = self.env.context.get('allowed_company_ids') or []
        if allowed_company_ids:
            try:
                return int(allowed_company_ids[0])
            except (TypeError, ValueError):
                raise AccessError(_('The active company context is invalid.'))
        return self.env.company.id

    @api.model
    def _catalog_favorite_ids(self, product_ids):
        if not product_ids or not self.env.user.has_group(
            'baseer_procurement_requests.group_procurement_cashier'
        ):
            return set()
        favorites = self.env['baseer.procurement.product.favorite'].sudo().search([
            ('user_id', '=', self.env.user.id),
            ('company_id', '=', self.env.company.id),
            ('product_id', 'in', product_ids),
            ('is_favorite', '=', True),
        ])
        return set(favorites.product_id.ids)

    @api.model
    def _catalog_usage_stats(self, product_ids):
        product_ids = sorted(set(product_ids))
        if not product_ids:
            return {}
        self.env.cr.execute(
            '''
                SELECT product_id, COUNT(*)::integer, MAX(purchase_date)
                  FROM baseer_procurement_price_history
                 WHERE company_id = %s AND product_id IN %s
                 GROUP BY product_id
            ''',
            [self.env.company.id, tuple(product_ids)],
        )
        return {
            product_id: {'count': count, 'latest': latest}
            for product_id, count, latest in self.env.cr.fetchall()
        }

    @api.model
    def _serialize_catalog_products(self, products, favorite_ids=None, usage_stats=None):
        products = products.exists()
        if not products:
            return []
        self._default_options_for_products(products)
        product_ids = products.ids
        favorite_ids = self._catalog_favorite_ids(product_ids) if favorite_ids is None else set(favorite_ids)
        usage_stats = usage_stats or {}
        options = self.env['baseer.procurement.purchase.option'].search(
            self._catalog_domain() + [('product_id', 'in', product_ids)],
            order='product_id, sequence, id',
        )
        option_by_product = defaultdict(list)
        for option in options:
            option_by_product[option.product_id.id].append(option)
        currency = self.env.company.currency_id
        items = []
        for product in products:
            usage_count = usage_stats.get(product.id, {}).get('count', 0)
            for option in option_by_product[product.id]:
                items.append({
                    'id': option.id,
                    'product_id': product.id,
                    'product_name': product.name,
                    'option_name': option.name,
                    'uom_id': option.uom_id.id,
                    'uom_name': option.uom_id.display_name,
                    'packaging_note': option.packaging_note or '',
                    'category_id': option.category_id.id,
                    'category_name': option.category_id.display_name,
                    'last_price': _decimal_text(option.last_price).replace(',', ''),
                    'last_price_text': _decimal_text(option.last_price),
                    'currency_symbol': currency.symbol or currency.name,
                    'currency_position': currency.position or 'after',
                    'image_url': '/web/image/product.product/%s/image_128' % product.id if product.image_128 else '',
                    'is_favorite': product.id in favorite_ids,
                    'usage_count': usage_count,
                })
        return items

    @api.model
    def set_catalog_favorite(self, product_id, desired_state):
        if type(desired_state) is not bool:
            raise ValidationError(_('The requested favorite state is invalid.'))
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            raise ValidationError(_('The selected material is invalid.'))
        lock_company_id = self._catalog_lock_company_id()
        self._catalog_advisory_lock(
            'procurement-favorite', self.env.uid, lock_company_id, product_id,
        )
        self._check_catalog_curator_access()
        if self.env.company.id != lock_company_id:
            raise AccessError(_('The active company context is invalid.'))
        product = self.env['product.product'].browse(product_id).exists()
        self._assert_catalog_products(product)
        def apply_state(target_env):
            Favorite = target_env['baseer.procurement.product.favorite'].sudo().with_context(
                **{FAVORITE_SYSTEM_WRITE: True}
            )
            favorites = Favorite.search([
                ('user_id', '=', self.env.uid),
                ('company_id', '=', lock_company_id),
                ('product_id', '=', product_id),
            ])
            if favorites:
                favorites.write({'is_favorite': desired_state})
                Favorite.flush_model(['is_favorite'])
            else:
                try:
                    with target_env.cr.savepoint():
                        Favorite.create({
                            'user_id': self.env.uid,
                            'company_id': lock_company_id,
                            'product_id': product_id,
                            'is_favorite': desired_state,
                        })
                        Favorite.flush_model([
                            'user_id', 'company_id', 'product_id', 'is_favorite',
                        ])
                except IntegrityError as error:
                    if getattr(error, 'pgcode', None) != '23505':
                        raise
                    raise ConcurrencyError(
                        'Concurrent catalogue favorite update; retry the transaction.'
                    ) from None

        apply_state(self.env)
        return {'product_id': product.id, 'is_favorite': desired_state}

    @api.model
    def create_quick_catalog_product(self, name, purchase_price, category_id=False):
        display_name = unicodedata.normalize('NFKC', str(name or ''))
        display_name = ' '.join(display_name.split())
        canonical_name = self._canonical_product_name(display_name)
        if not canonical_name:
            raise ValidationError(_('Enter a product name.'))
        if len(display_name) > 120:
            raise ValidationError(_('Product name cannot exceed 120 characters.'))
        price = _decimal_input(purchase_price, _('Purchase price'), positive=True)
        lock_company_id = self._catalog_lock_company_id()
        self._catalog_advisory_lock('procurement-quick-product', lock_company_id, canonical_name)
        self._check_catalog_curator_access()
        if self.env.company.id != lock_company_id:
            raise AccessError(_('The active company context is invalid.'))

        if category_id:
            try:
                category = self.env['product.category'].browse(int(category_id)).exists()
            except (TypeError, ValueError):
                category = self.env['product.category']
        else:
            category = self.env.ref('product.product_category_goods', raise_if_not_found=False)
        if not category:
            raise ValidationError(_('The selected product category is unavailable.'))
        category.check_access('read')
        company_category = category.with_company(self.env.company)
        cost_method_field = category._fields.get('property_cost_method')
        if cost_method_field and company_category.property_cost_method != 'standard':
            raise ValidationError(_('The selected product category must use standard costing.'))

        Product = self.env['product.product'].sudo().with_company(self.env.company).with_context(active_test=False)
        Identity = self.env['baseer.procurement.product.identity'].sudo().with_context(
            **{IDENTITY_SYSTEM_WRITE: True}
        )
        reuse_error = _(
            'A product with this name already exists but cannot be reused from the procurement catalogue.'
        )

        def matching_products(product_model, request_model):
            return product_model.search([('company_id', '=', lock_company_id)]).filtered(
                lambda candidate: request_model._canonical_product_name(candidate.name) == canonical_name
            )

        def existing_result(matches, request_model):
            eligible = matches.filtered(
                lambda candidate: candidate.active and candidate.purchase_ok and candidate.type == 'consu'
            )
            if len(matches) == 1 and eligible:
                return {
                    'created': False,
                    'product_id': eligible.id,
                    'items': request_model._serialize_catalog_products(eligible),
                }
            raise ValidationError(reuse_error)

        identity = Identity.search([
            ('company_id', '=', lock_company_id), ('normalized_name', '=', canonical_name),
        ], limit=1)
        if identity:
            product = identity.product_id.with_context(active_test=False)
            if self._canonical_product_name(product.name) != canonical_name:
                raise ValidationError(reuse_error)
            return existing_result(product, self)

        try:
            with self.env.cr.savepoint():
                matches = matching_products(Product, self)
                if matches:
                    result = existing_result(matches, self)
                    product = matches
                else:
                    unit = self.env.ref('uom.product_uom_unit')
                    product = Product.create({
                        'name': display_name,
                        'company_id': self.env.company.id,
                        'categ_id': category.id,
                        'uom_id': unit.id,
                        'standard_price': float(price),
                        'purchase_ok': True,
                        'sale_ok': False,
                        'type': 'consu',
                        'is_storable': False,
                    })
                    self._default_options_for_products(product)
                    result = {
                        'created': True,
                        'product_id': product.id,
                        'items': self._serialize_catalog_products(product),
                    }
                Identity.create({
                    'company_id': lock_company_id,
                    'normalized_name': canonical_name,
                    'product_id': product.id,
                })
                Identity.flush_model(['company_id', 'normalized_name', 'product_id'])
                return result
        except IntegrityError as error:
            if getattr(error, 'pgcode', None) != '23505':
                raise
            raise ConcurrencyError(
                'Concurrent quick-product creation; retry the transaction.'
            ) from None

    @api.model
    def catalog_highlights(self, limit=MAX_CATALOG_HIGHLIGHTS):
        self._check_catalog_curator_access()
        try:
            limit = min(max(int(limit or MAX_CATALOG_HIGHLIGHTS), 1), MAX_CATALOG_HIGHLIGHTS)
        except (TypeError, ValueError):
            raise ValidationError(_('Catalogue highlight limit is invalid.'))
        products = self.env['product.product'].search(self._catalog_product_domain())
        eligible_ids = set(products.ids)
        if not eligible_ids:
            return {'items': []}

        favorites = self.env['baseer.procurement.product.favorite'].sudo().search([
            ('user_id', '=', self.env.user.id),
            ('company_id', '=', self.env.company.id),
            ('product_id', 'in', list(eligible_ids)),
            ('is_favorite', '=', True),
        ])
        favorites = favorites.sorted(lambda favorite: (
            -(favorite.write_date.timestamp() if favorite.write_date else 0),
            self._canonical_product_name(favorite.product_id.name),
            favorite.product_id.id,
        ))
        selected_ids = [favorite.product_id.id for favorite in favorites[:limit]]
        usage_stats = self._catalog_usage_stats(list(eligible_ids))
        usage_ids = sorted(
            (product_id for product_id in usage_stats if product_id not in selected_ids),
            key=lambda product_id: (
                -usage_stats[product_id]['count'],
                -(usage_stats[product_id]['latest'].timestamp() if usage_stats[product_id]['latest'] else 0),
                product_id,
            ),
        )
        selected_ids.extend(usage_ids[:max(limit - len(selected_ids), 0)])
        selected = self.env['product.product'].browse(selected_ids)
        return {
            'items': self._serialize_catalog_products(
                selected, favorite_ids=set(favorites.product_id.ids), usage_stats=usage_stats,
            ),
        }

    @api.model
    def cashier_recent_requests(self, offset=0, limit=50, search_term=False, state=False):
        """Return a searchable, paged, company-scoped cashier request feed.

        ``limit + 1`` deliberately replaces ``search_count`` so every page is a
        single bounded read.  The optional arguments extend the original RPC
        without breaking callers that still pass only ``offset`` and ``limit``.
        """
        self._check_catalog_access()
        try:
            offset = max(int(offset or 0), 0)
            limit = min(max(int(limit or 50), 1), 50)
        except (TypeError, ValueError):
            raise ValidationError(_('Request pagination is invalid.'))
        allowed_states = {'draft', 'sent', 'received', 'purchased', 'cancel'}
        if state in (None, False, '', 'all'):
            state = False
        elif state not in allowed_states:
            raise ValidationError(_('The selected request status is invalid.'))
        term = (search_term or '').strip()
        if len(term) > 128:
            raise ValidationError(_('Search text cannot exceed 128 characters.'))
        domain = [('company_id', '=', self.env.company.id)]
        if state:
            domain.append(('state', '=', state))
        if term:
            domain += [
                '|', '|', '|', '|', '|', '|', '|',
                ('name', 'ilike', term),
                ('warehouse_id.name', 'ilike', term),
                ('representative_partner_id.name', 'ilike', term),
                ('purchaser_id.name', 'ilike', term),
                ('line_ids.option_id.product_id.name', 'ilike', term),
                ('line_ids.option_id.name', 'ilike', term),
                ('line_ids.option_id.packaging_note', 'ilike', term),
                ('line_ids.option_id.uom_id.name', 'ilike', term),
            ]
        records = self.search(
            domain,
            order='request_date desc, id desc', limit=limit + 1, offset=offset,
        )
        has_more = len(records) > limit
        records = records[:limit]
        labels = {
            'draft': _('Draft'),
            'sent': _('Sent to purchaser'),
            'received': _('Waiting for cashier confirmation'),
            'purchased': _('Completed'),
            'cancel': _('Cancelled'),
        }
        currency = self.env.company.currency_id
        return {
            'items': [{
                'id': record.id,
                'name': record.name,
                'state': record.state,
                'state_label': labels.get(record.state, record.state),
                'request_date': fields.Datetime.to_string(record.request_date),
                'line_count': len(record.line_ids),
                'representative_name': (
                    record.representative_partner_id.display_name
                    or record.purchaser_id.name
                    or ''
                ),
                'total_text': _decimal_text(
                    record.actual_total if record.state == 'purchased' else record.requested_total
                ),
                'currency_symbol': currency.symbol or currency.name,
                'currency_position': currency.position or 'after',
            } for record in records],
            'next_offset': offset + len(records),
            'has_more': has_more,
            'currency_symbol': currency.symbol or currency.name,
            'currency_position': currency.position or 'after',
        }

    @api.model
    def open_cashier_request(self, request_id):
        """Open the original request only; this method never clones a cart."""
        self._check_catalog_access()
        request = self.browse(int(request_id)).exists()
        if not request or request.company_id != self.env.company:
            raise AccessError(_('The procurement request is unavailable in the active company.'))
        if request.state in ('sent', 'received'):
            if not self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
                raise AccessError(_('Only a procurement cashier can confirm a received request.'))
            return {
                'type': 'ir.actions.client',
                'tag': 'baseer_procurement_requests.catalog',
                'name': request.display_name,
                'params': {'request_id': request.id, 'mode': 'cashier_receipt'},
            }
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'baseer.procurement.request',
            'res_id': request.id,
            'views': [[False, 'form']],
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def cashier_request_cart(self, request_id):
        """Load an original sent request into the cashier cart without copying it."""
        self._check_catalog_access()
        request = self.browse(int(request_id)).exists()
        if not request or request.company_id != self.env.company:
            raise AccessError(_('The procurement request is unavailable in the active company.'))
        if request.state not in ('sent', 'received'):
            raise UserError(_('Only a sent request can be confirmed in the cashier cart.'))
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
            raise AccessError(_('Only a procurement cashier can confirm a received request.'))
        currency = self.env.company.currency_id
        return {
            'id': request.id, 'name': request.name, 'state': request.state,
            'warehouse_id': request.warehouse_id.id,
            'representative_partner_id': request.representative_partner_id.id or False,
            'representative_name': (
                request.representative_partner_id.display_name
                or request.purchaser_id.name
                or ''
            ),
            'items': [{
                'line_id': line.id, 'option_id': line.option_id.id,
                'product_id': line.option_id.product_id.id,
                'name': line.option_id.product_id.name,
                'unit': line.option_id.name,
                'packaging': line.option_id.packaging_note or '',
                'image_url': '/web/image/product.product/%s/image_128' % line.option_id.product_id.id if line.option_id.product_id.image_128 else '',
                'quantity': _decimal_text(line.requested_qty).replace(',', ''),
                'last_price': _decimal_text(line.option_id.last_price).replace(',', ''),
                'currency_symbol': currency.symbol or currency.name,
            } for line in request.line_ids],
        }

    @api.model
    def _money_response(self, rows, total):
        currency = self.env.company.currency_id
        return {
            'lines': rows,
            'total': _decimal_text(total).replace(',', ''),
            'total_text': _decimal_text(total),
            'currency_symbol': currency.symbol or currency.name,
            'currency_position': currency.position or 'after',
        }

    @api.model
    def catalog_page(self, search_term=False, category_id=False, offset=0, limit=48):
        """Return company products, augmented by their reusable purchase options."""
        self._check_catalog_access()
        try:
            offset = max(int(offset or 0), 0)
            limit = min(max(int(limit or 48), 1), 48)
        except (TypeError, ValueError):
            raise ValidationError(_('Catalogue pagination is invalid.'))
        product_model = self.env['product.product']
        products = product_model.search(
            self._catalog_product_domain(search_term, category_id),
            order='name, id', offset=offset, limit=limit + 1,
        )
        has_more = len(products) > limit
        products = products[:limit]
        product_ids = products.ids
        return {
            'items': self._serialize_catalog_products(products),
            'offset': offset,
            'next_offset': offset + len(product_ids),
            'has_more': has_more,
            'currency_symbol': self.env.company.currency_id.symbol or self.env.company.currency_id.name,
            'currency_position': self.env.company.currency_id.position or 'after',
            'can_curate_catalog': self.env.user.has_group(
                'baseer_procurement_requests.group_procurement_cashier'
            ),
        }

    @api.model
    def catalog_categories(self):
        self._check_catalog_access()
        category_counts = self.env['product.product']._read_group(
            self._catalog_product_domain(), groupby=['categ_id'], aggregates=['__count'],
        )
        return [
            {'id': category.id, 'name': category.display_name, 'count': count}
            for category, count in sorted(
                category_counts, key=lambda row: (row[0].display_name or '', row[0].id),
            )
        ]

    @api.model
    def catalog_representatives(self):
        """Return only purchase representatives enabled for the active company.

        The company-dependent flag keeps a shared contact from leaking into
        another company's cashier selector.  The RPC exposes only identifiers
        and display names required by the catalogue.
        """
        self._check_catalog_access()
        partners = self.env['res.partner'].with_company(self.env.company).search([
            ('active', '=', True),
            ('is_purchase_representative', '=', True),
            ('is_company', '=', False),
            ('parent_id', '=', False),
            '|', ('company_id', '=', False), ('company_id', '=', self.env.company.id),
        ], order='name, id', limit=500)
        return [{'id': partner.id, 'name': partner.display_name} for partner in partners]

    @api.model
    def quote_catalog_cart(self, lines):
        """Return the authoritative decimal estimate without writing a request."""
        self._check_catalog_access()
        if not isinstance(lines, list) or not lines or len(lines) > MAX_CATALOG_LINES:
            raise ValidationError(_('The cart must contain between 1 and %s materials.') % MAX_CATALOG_LINES)
        option_ids = []
        for row in lines:
            try:
                option_ids.append(int(row.get('option_id')))
            except (AttributeError, TypeError, ValueError):
                raise ValidationError(_('The cart contains an invalid material.'))
        if len(option_ids) != len(set(option_ids)):
            raise ValidationError(_('A material cannot appear twice in the same cart.'))
        options = self.env['baseer.procurement.purchase.option'].browse(option_ids).exists()
        option_by_id = {option.id: option for option in options}
        if len(option_by_id) != len(option_ids):
            raise AccessError(_('The cart contains an unavailable material.'))
        self._assert_catalog_options(options)
        product_ids = [option_by_id[option_id].product_id.id for option_id in option_ids]
        if len(product_ids) != len(set(product_ids)):
            raise ValidationError(_('A material cannot appear twice in the same cart.'))
        response_lines = []
        total = Decimal('0.00')
        for row, option_id in zip(lines, option_ids):
            quantity = _decimal_input(row.get('quantity'), _('Quantity'), positive=True)
            option = option_by_id[option_id]
            unit_price = _decimal_input(option.last_price, _('Unit price'))
            line_total = (quantity * unit_price).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
            total += line_total
            response_lines.append({
                'option_id': option.id,
                'quantity': _decimal_text(quantity).replace(',', ''),
                'quantity_text': _decimal_text(quantity),
                'unit_price': _decimal_text(unit_price).replace(',', ''),
                'unit_price_text': _decimal_text(unit_price),
                'line_total': _decimal_text(line_total).replace(',', ''),
                'line_total_text': _decimal_text(line_total),
            })
        return self._money_response(response_lines, total)

    @api.model
    def quote_actual_cart(self, request_id, lines):
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
            raise AccessError(_('Only a procurement cashier can enter actual purchase details.'))
        request = self.browse(int(request_id)).exists()
        if not request or request.company_id != self.env.company:
            raise AccessError(_('The procurement request is unavailable in the active company.'))
        request._require_state('sent', 'received')
        self._assert_catalog_options(request.line_ids.option_id)
        request_product_ids = [line.option_id.product_id.id for line in request.line_ids]
        if len(request_product_ids) != len(set(request_product_ids)):
            raise ValidationError(_('A material cannot appear twice in the same request.'))
        if not isinstance(lines, list) or len(lines) != len(request.line_ids):
            raise ValidationError(_('The actual-purchase cart must contain every request line.'))
        try:
            incoming = {int(row.get('line_id')): row for row in lines if row.get('line_id')}
        except (AttributeError, TypeError, ValueError):
            raise ValidationError(_('The actual-purchase cart contains an invalid line.'))
        if len(incoming) != len(lines) or set(incoming) != set(request.line_ids.ids):
            raise ValidationError(_('The actual-purchase cart does not match the request lines.'))
        response_lines = []
        total = Decimal('0.00')
        for line in request.line_ids:
            row = incoming[line.id]
            try:
                quantity = _decimal_input(row.get('actual_qty'), _('Actual quantity'))
                price = _decimal_input(row.get('actual_price'), _('Actual unit price'))
            except ValidationError:
                raise ValidationError(_('Actual quantity or price is invalid for %s.') % line.option_id.product_id.display_name)
            maximum = line.requested_qty if request.state == 'sent' else line.manager_received_qty
            if quantity > _decimal_input(maximum, _('Received quantity')):
                raise ValidationError(_('Actual quantity is invalid for %s.') % line.option_id.product_id.display_name)
            if quantity and not price:
                raise ValidationError(_('Every purchased material needs a positive price.'))
            line_total = (quantity * price).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
            total += line_total
            response_lines.append({
                'line_id': line.id,
                'quantity': _decimal_text(quantity).replace(',', ''),
                'quantity_text': _decimal_text(quantity),
                'unit_price': _decimal_text(price).replace(',', ''),
                'unit_price_text': _decimal_text(price),
                'line_total': _decimal_text(line_total).replace(',', ''),
                'line_total_text': _decimal_text(line_total),
            })
        return self._money_response(response_lines, total)

    @api.model
    def confirm_manager_receipt_from_catalog(self, request_id, lines):
        """Narrow manager boundary for the shared cashier receipt screen."""
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_manager'):
            raise AccessError(_('Only a procurement manager can confirm the operational receipt.'))
        request = self.browse(int(request_id)).exists()
        if not request or request.company_id != self.env.company:
            raise AccessError(_('The procurement request is unavailable in the active company.'))
        self.env.cr.execute('SELECT id FROM baseer_procurement_request WHERE id = %s FOR UPDATE', [request.id])
        request.invalidate_recordset()
        request._require_state('sent')
        if not isinstance(lines, list) or len(lines) != len(request.line_ids):
            raise ValidationError(_('The receipt cart must contain every request line.'))
        try:
            incoming = {int(row.get('line_id')): row for row in lines if row.get('line_id')}
        except (AttributeError, TypeError, ValueError):
            raise ValidationError(_('The receipt cart contains an invalid line.'))
        if set(incoming) != set(request.line_ids.ids):
            raise ValidationError(_('The receipt cart does not match the request lines.'))
        for line in request.line_ids:
            try:
                quantity = _decimal_input(incoming[line.id].get('manager_received_qty'), _('Manager received quantity'))
            except ValidationError:
                raise ValidationError(_('Manager received quantity is invalid for %s.') % line.option_id.product_id.display_name)
            if quantity > _decimal_input(line.requested_qty, _('Requested quantity')):
                raise ValidationError(_('Manager received quantity is invalid for %s.') % line.option_id.product_id.display_name)
            line.write({'manager_received_qty': float(quantity)})
        request.action_confirm_manager_receipt()
        return {'type': 'ir.actions.act_window', 'res_model': 'baseer.procurement.request',
                'res_id': request.id, 'views': [[False, 'form']], 'view_mode': 'form', 'target': 'current'}

    @api.model
    def catalog_options(self, search_term=False, limit=80):
        """Small server-searched catalogue for the purchasing-cashier screen."""
        self._check_catalog_access()
        limit = min(max(int(limit or 80), 1), 100)
        products = self.env['product.product'].search(
            self._catalog_product_domain(search_term), order='name, id', limit=limit,
        )
        self._default_options_for_products(products)
        return self.env['baseer.procurement.purchase.option'].search_read(
            self._catalog_domain() + [('product_id', 'in', products.ids)],
            ['name', 'product_id', 'uom_id', 'packaging_note', 'last_price'],
            limit=limit, order='sequence, product_id, id',
        )

    @api.model
    def confirm_actual_from_catalog(self, request_id, lines):
        """Narrow cashier boundary for the POS-like actual-quantity screen."""
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
            raise AccessError(_('Only a procurement cashier can enter actual purchase details.'))
        request = self.browse(int(request_id)).exists()
        if not request:
            raise UserError(_('The procurement request no longer exists.'))
        # ``browse`` honours allowed companies, not necessarily the company
        # currently selected in the UI.  A cashier may legitimately have two
        # companies in ``allowed_company_ids``; that must not let an RPC from
        # company A lock or confirm a request belonging to company B.
        # Keep this check before ``FOR UPDATE`` so a rejected cross-company
        # request cannot contend with or delay its owning company.
        if request.company_id != self.env.company:
            raise AccessError(_('The procurement request is unavailable in the active company.'))
        self.env.cr.execute('SELECT id FROM baseer_procurement_request WHERE id = %s FOR UPDATE', [request.id])
        request.invalidate_recordset()
        request._require_state('sent', 'received')
        cashier_receipt = request.state == 'sent'
        if not isinstance(lines, list) or len(lines) != len(request.line_ids):
            raise ValidationError(_('The actual-purchase cart must contain every request line.'))
        incoming = {int(row.get('line_id')): row for row in lines if row.get('line_id')}
        if set(incoming) != set(request.line_ids.ids):
            raise ValidationError(_('The actual-purchase cart does not match the request lines.'))
        for line in request.line_ids:
            row = incoming[line.id]
            try:
                quantity = _decimal_input(row.get('actual_qty'), _('Actual quantity'))
                price = _decimal_input(row.get('actual_price'), _('Actual unit price'))
            except ValidationError:
                raise ValidationError(_('Actual quantity or price is invalid for %s.') % line.option_id.product_id.display_name)
            maximum = line.requested_qty if cashier_receipt else line.manager_received_qty
            if quantity > _decimal_input(maximum, _('Received quantity')):
                raise ValidationError(_('Actual quantity or price is invalid for %s.') % line.option_id.product_id.display_name)
            if cashier_receipt:
                line.sudo().with_context(cashier_receipt_internal=True).write({
                    'manager_received_qty': float(quantity),
                })
        if cashier_receipt:
            super(ProcurementRequest, request.sudo()).write({
                'state': 'received', 'manager_received_at': fields.Datetime.now(),
            })
            request.invalidate_recordset()
        for line in request.line_ids:
            row = incoming[line.id]
            quantity = _decimal_input(row.get('actual_qty'), _('Actual quantity'))
            price = _decimal_input(row.get('actual_price'), _('Actual unit price'))
            line.write({'actual_qty': float(quantity), 'actual_price': float(price)})
        return request.action_confirm_actual_purchase()

    def action_open_picking(self):
        self.ensure_one()
        self._require_active_company_for_cashier()
        if not self.picking_id:
            return {
                'type': 'ir.actions.act_window',
                'name': self.display_name,
                'res_model': 'baseer.procurement.request',
                'view_mode': 'form',
                'res_id': self.id,
                'target': 'current',
            }
        return {'type': 'ir.actions.act_window', 'name': _('Receipt'), 'res_model': 'stock.picking',
                'view_mode': 'form', 'res_id': self.picking_id.id, 'target': 'current'}

    def write(self, vals):
        self._require_active_company_for_cashier()
        if 'company_id' in vals and self.env.user.has_group(
            'baseer_procurement_requests.group_procurement_cashier'
        ):
            try:
                requested_company_id = int(vals['company_id'])
            except (TypeError, ValueError):
                requested_company_id = False
            if requested_company_id != self.env.company.id:
                raise AccessError(_('The procurement request must remain in the active company.'))
        protected = {'state', 'picking_id', 'whatsapp_opened_at', 'whatsapp_sent_at', 'manager_received_at',
                     'actual_confirmed_at', 'actual_confirmed_by_id', 'client_token', 'client_payload_hash'}
        if protected & set(vals):
            raise AccessError(_('Request state, receipt links, and audit timestamps are controlled by the server.'))
        if 'cancellation_reason' in vals:
            if not self.env.user.has_group('baseer_procurement_requests.group_procurement_user'):
                raise AccessError(_('You are not allowed to record a cancellation reason.'))
            if any(request.state not in ('draft', 'sent') for request in self):
                raise UserError(_('A cancellation reason can only be entered before the manager receipt.'))
        if any(request.state != 'draft' for request in self) and {
            'company_id', 'warehouse_id', 'purchaser_id', 'representative_partner_id',
            'request_date', 'whatsapp_number', 'requester_id',
        } & set(vals):
            raise UserError(_('Request header details can only be changed while the request is a draft.'))
        return super().write(vals)

    def unlink(self):
        self._require_active_company_for_cashier()
        if any(request.state != 'draft' for request in self):
            raise UserError(_('Sent, received, or purchased procurement requests cannot be deleted. Use the authorized correction process.'))
        return super().unlink()

    @api.model
    def create_from_catalog(self, lines, warehouse_id, purchaser_id=False, whatsapp_number=False,
                            client_token=False, representative_partner_id=False):
        """Narrow RPC boundary used by the standalone POS-style catalogue."""
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_user'):
            raise AccessError(_('You are not allowed to create procurement requests.'))
        if not isinstance(lines, list) or not lines or len(lines) > MAX_CATALOG_LINES:
            raise ValidationError(_('Add at least one material to the cart.'))
        if not representative_partner_id and not purchaser_id:
            raise ValidationError(_('Choose the purchasing representative before saving the request.'))
        token = False
        if client_token:
            try:
                token = str(UUID(str(client_token)))
            except (TypeError, ValueError, AttributeError):
                raise ValidationError(_('The cart submission token is invalid.'))
            lock_key = '%s:%s:%s' % (self.env.company.id, self.env.user.id, token)
            self.env.cr.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))', (lock_key,))
            if not self.env.cr.fetchone()[0]:
                # Let Odoo retry the whole RPC with a fresh transaction after
                # the concurrent winner has committed its request.
                raise ConcurrencyError('Concurrent procurement cart submission; retry the transaction.')
        try:
            option_ids = [int(row.get('option_id')) for row in lines if row.get('option_id')]
        except (AttributeError, TypeError, ValueError):
            raise ValidationError(_('The cart contains an invalid material.'))
        if len(option_ids) != len(lines) or len(option_ids) != len(set(option_ids)):
            raise ValidationError(_('A material cannot appear twice in the same cart.'))
        options = self.env['baseer.procurement.purchase.option'].browse(option_ids).exists()
        if len(options) != len(set(option_ids)):
            raise AccessError(_('The cart contains an unavailable material.'))
        self._assert_catalog_options(options)
        option_by_id = {option.id: option for option in options}
        product_ids = [option_by_id[option_id].product_id.id for option_id in option_ids]
        if len(product_ids) != len(set(product_ids)):
            raise ValidationError(_('A material cannot appear twice in the same cart.'))
        values = []
        canonical_lines = []
        for row in lines:
            option = option_by_id[int(row['option_id'])]
            try:
                quantity = _decimal_input(row.get('quantity'), _('Quantity'), positive=True)
            except ValidationError:
                raise ValidationError(_('Every cart row needs a positive quantity with at most two decimal places.'))
            values.append(Command.create({'option_id': option.id, 'requested_qty': float(quantity),
                                          'requested_price': option.last_price}))
            canonical_lines.append({'option_id': option.id, 'quantity': _decimal_text(quantity).replace(',', '')})
        warehouse = self.env['stock.warehouse'].browse(int(warehouse_id)).exists()
        purchaser = self.env['hr.employee.public'].browse(int(purchaser_id)).exists() if purchaser_id else self.env['hr.employee.public']
        representative = (
            self.env['res.partner'].with_company(self.env.company).browse(int(representative_partner_id)).exists()
            if representative_partner_id else self.env['res.partner']
        )
        if not warehouse or warehouse.company_id != self.env.company:
            raise AccessError(_('Choose a warehouse in the active company.'))
        if purchaser_id and (not purchaser or purchaser.company_id != self.env.company):
            raise AccessError(_('Choose a purchasing representative in the active company.'))
        if representative_partner_id and (
            not representative
            or (representative.company_id and representative.company_id != self.env.company)
            or representative.is_company
            or representative.parent_id
            or not representative.with_company(self.env.company).is_purchase_representative
        ):
            raise AccessError(_('Choose an enabled purchase-representative contact in the active company.'))
        payload = {
            'warehouse_id': warehouse.id,
            'purchaser_id': purchaser.id or False,
            'representative_partner_id': representative.id or False,
            'whatsapp_number': whatsapp_number or '',
            'lines': sorted(canonical_lines, key=lambda row: row['option_id']),
        }
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        request_model = self.sudo().with_company(self.env.company).with_context(**{REQUEST_CREATE_INTERNAL: True})
        if token:
            existing = request_model.search([
                ('company_id', '=', self.env.company.id), ('requester_id', '=', self.env.user.id),
                ('client_token', '=', token),
            ], limit=1)
            if existing:
                if existing.client_payload_hash != payload_hash:
                    raise ValidationError(_('This cart token was already used with different request details.'))
                return existing.id
        create_values = {
            'company_id': self.env.company.id, 'warehouse_id': warehouse.id,
            'purchaser_id': purchaser.id or False,
            'representative_partner_id': representative.id or False,
            'requester_id': self.env.user.id, 'whatsapp_number': whatsapp_number or False, 'line_ids': values,
            'client_token': token, 'client_payload_hash': payload_hash if token else False,
        }
        try:
            with self.env.cr.savepoint():
                request = request_model.create(create_values)
                # Force the token constraint inside this savepoint so a
                # concurrent duplicate can be converted into an Odoo retry.
                request_model.flush_model(['client_token', 'client_payload_hash'])
                return request.id
        except IntegrityError as error:
            if not token or getattr(error, 'pgcode', None) != '23505':
                raise
            # Odoo uses repeatable-read transactions.  After a concurrent
            # unique-key conflict the winner is not visible in this snapshot,
            # so ask Odoo's service retry loop for a fresh transaction.  The
            # retry reaches the lookup above and returns the winner safely.
            raise ConcurrencyError('Concurrent procurement cart submission; retry the transaction.') from None


class ProcurementRequestLine(models.Model):
    _name = 'baseer.procurement.request.line'
    _description = 'Procurement request line'
    _order = 'id'
    _check_company_auto = True

    request_id = fields.Many2one('baseer.procurement.request', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='request_id.company_id', store=True, index=True)
    warehouse_id = fields.Many2one(related='request_id.warehouse_id', store=True, index=True, readonly=True)
    purchaser_id = fields.Many2one(related='request_id.purchaser_id', store=True, index=True, readonly=True)
    representative_partner_id = fields.Many2one(
        related='request_id.representative_partner_id', store=True, index=True, readonly=True,
    )
    option_id = fields.Many2one('baseer.procurement.purchase.option', required=True, ondelete='restrict', check_company=True)
    currency_id = fields.Many2one(related='request_id.currency_id')
    requested_qty = fields.Float(required=True, digits='Product Unit of Measure', default=1)
    requested_price = fields.Monetary(currency_field='currency_id', default=0)
    manager_received_qty = fields.Float(digits='Product Unit of Measure', default=0)
    actual_qty = fields.Float(digits='Product Unit of Measure', default=0)
    actual_price = fields.Monetary(currency_field='currency_id', default=0)
    manager_shortage_qty = fields.Float(
        string='Quantity not received', compute='_compute_quantity_variances', store=True,
        digits='Product Unit of Measure', readonly=True,
    )
    cashier_shortage_qty = fields.Float(
        string='Quantity not confirmed', compute='_compute_quantity_variances', store=True,
        digits='Product Unit of Measure', readonly=True,
    )

    @api.constrains('requested_qty', 'manager_received_qty', 'actual_qty', 'requested_price', 'actual_price')
    def _check_nonnegative(self):
        for line in self:
            values = (line.requested_qty, line.manager_received_qty, line.actual_qty, line.requested_price, line.actual_price)
            if not all(_is_finite_number(value) for value in values):
                raise ValidationError(_('Quantities and prices must be finite numbers.'))
            if line.requested_qty <= 0 or min(line.manager_received_qty, line.actual_qty, line.requested_price, line.actual_price) < 0:
                raise ValidationError(_('Quantities must be positive and prices cannot be negative.'))
            if line.manager_received_qty > line.requested_qty:
                raise ValidationError(_('Manager-received quantity cannot exceed the requested quantity.'))
            if line.actual_qty and not line.actual_price:
                raise ValidationError(_('Every purchased material needs a positive actual price.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self.env.context.get(REQUEST_CREATE_INTERNAL) and self.env.su:
                continue
            request = self.env['baseer.procurement.request'].browse(vals.get('request_id')).exists()
            if not request or request.state != 'draft':
                raise AccessError(_('Request lines can only be created on a draft procurement request.'))
            request._require_active_company_for_cashier()
            protected = ('manager_received_qty', 'actual_qty', 'actual_price')
            if any(vals.get(field) not in (False, 0, 0.0, None) for field in protected):
                raise AccessError(_('Received quantities and actual prices are controlled by the receipt workflow.'))
        return super().create(vals_list)

    @api.depends('requested_qty', 'manager_received_qty', 'actual_qty')
    def _compute_quantity_variances(self):
        for line in self:
            line.manager_shortage_qty = max(line.requested_qty - line.manager_received_qty, 0)
            line.cashier_shortage_qty = max(line.manager_received_qty - line.actual_qty, 0)

    def write(self, vals):
        self.mapped('request_id')._require_active_company_for_cashier()
        protected = {'requested_qty', 'requested_price', 'manager_received_qty', 'actual_qty', 'actual_price', 'option_id'}
        if protected & set(vals):
            locked = self.filtered(lambda line: line.request_id.state in ('purchased', 'cancel'))
            if locked:
                raise UserError(_('Purchased or cancelled request lines cannot be changed. Use a correcting stock operation.'))
            if {'requested_qty', 'requested_price', 'option_id'} & set(vals):
                if any(line.request_id.state != 'draft' for line in self):
                    raise UserError(_('Requested materials can only be changed while the request is a draft.'))
            if 'manager_received_qty' in vals:
                cashier_internal = self.env.su and self.env.context.get('cashier_receipt_internal')
                if not cashier_internal and not self.env.user.has_group('baseer_procurement_requests.group_procurement_manager'):
                    raise AccessError(_('Only a procurement manager can enter received quantities.'))
                if any(line.request_id.state != 'sent' for line in self):
                    raise UserError(_('Received quantities can only be entered after sending the request.'))
            if {'actual_qty', 'actual_price'} & set(vals):
                if not self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
                    raise AccessError(_('Only a procurement cashier can enter actual purchase details.'))
                if any(line.request_id.state != 'received' for line in self):
                    raise UserError(_('Actual purchase details can only be entered after manager receipt.'))
        return super().write(vals)

    def unlink(self):
        self.mapped('request_id')._require_active_company_for_cashier()
        if any(line.request_id.state != 'draft' for line in self):
            raise UserError(_('Lines on sent, received, or purchased procurement requests cannot be deleted.'))
        return super().unlink()
