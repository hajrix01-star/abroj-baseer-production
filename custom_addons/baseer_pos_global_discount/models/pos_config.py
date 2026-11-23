import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_global_discount_enabled = fields.Boolean(string='Invoice discount', default=False)
    baseer_global_discount_max_percent = fields.Float(string='Maximum invoice discount (%)', default=100, digits=(16, 2))
    baseer_global_discount_max_amount = fields.Monetary(string='Maximum invoice discount amount', currency_field='currency_id')
    baseer_global_discount_product_id = fields.Many2one('product.product', string='Invoice discount product', check_company=True)
    baseer_global_discount_account_id = fields.Many2one(
        'account.account', string='Invoice discount income account', check_company=True,
        domain="[('account_type', 'in', ['income', 'income_other']), ('active', '=', True)]",
    )
    baseer_offline_discount_account_proofs = fields.Json(
        compute='_compute_offline_discount_account_proofs', compute_sudo=True,
        string='Offline discount account proofs',
    )

    def _gd_offline_account_proof(self, fiscal_position):
        """Bind the POS-loaded discount account and fiscal mapping to this shop.

        This is not an account policy: it detects a later change before an
        offline-paid sale is posted. Source product accounts remain native POS.
        """
        self.ensure_one()
        config = self.sudo().with_company(self.company_id)
        account = config.baseer_global_discount_account_id
        product = config.baseer_global_discount_product_id
        if not account or not product:
            return False
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret')
        if not secret:
            return False
        position = fiscal_position.sudo().with_company(config.company_id)
        effective = position.map_account(account) if position else account
        product_income = product.with_company(config.company_id).property_account_income_id
        value = {
            'version': 1, 'company_id': config.company_id.id, 'config_id': config.id,
            'product_id': product.id, 'configured_account_id': account.id,
            'product_income_account_id': product_income.id or 0,
            'fiscal_position_id': position.id or 0, 'effective_account_id': effective.id or 0,
            'configured_active': bool(account.active), 'configured_type': account.account_type,
            'effective_active': bool(effective.active), 'effective_type': effective.account_type,
            'configured_companies': sorted(account.company_ids.ids),
            'effective_companies': sorted(effective.company_ids.ids),
        }
        body = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def _compute_offline_discount_account_proofs(self):
        Position = self.env['account.fiscal.position'].sudo().with_context(active_test=False)
        for config in self:
            proofs = {}
            if config.baseer_global_discount_enabled:
                position_domain = Position._check_company_domain(config.company_id.id)
                positions = Position.search(position_domain)
                empty = Position.browse()
                proof = config._gd_offline_account_proof(empty)
                if proof:
                    proofs['0'] = proof
                    for position in positions:
                        proofs[str(position.id)] = config._gd_offline_account_proof(position)
            config.baseer_offline_discount_account_proofs = proofs

    def _gd_check_account_setup(self):
        self.ensure_one()
        config = self.with_company(self.company_id)
        account = config.baseer_global_discount_account_id
        product = config.baseer_global_discount_product_id
        if (not account or not account.active or account.account_type not in ('income', 'income_other')
                or self.company_id not in account.company_ids
                or not product or product.company_id != self.company_id
                or product.type != 'service' or product.standard_price != 0
                or product.property_account_income_id != account):
            raise ValidationError(_('Set an active income account in this company for the zero-cost invoice discount service.'))
        return account

    @api.constrains('baseer_global_discount_max_percent', 'baseer_global_discount_max_amount', 'baseer_global_discount_product_id')
    def _check_baseer_global_discount_settings(self):
        for config in self:
            if not 0 <= config.baseer_global_discount_max_percent <= 100 or config.baseer_global_discount_max_amount < 0:
                raise ValidationError(_('Discount limits must be non-negative and the percentage cannot exceed 100.'))
            product = config.baseer_global_discount_product_id
            if product and (product.type != 'service' or not product.sale_ok or not product.available_in_pos
                            or product.company_id != config.company_id):
                raise ValidationError(_('The invoice discount product must be a POS service in this company.'))

    @api.model
    def _gd_validate_settings_input(self, values):
        if any(key.startswith('baseer_global_discount_') for key in values):
            if not self.env.user.has_group('point_of_sale.group_pos_manager'):
                raise AccessError(_('Only a POS manager can configure invoice discounts.'))
            for key in ('baseer_global_discount_max_percent', 'baseer_global_discount_max_amount'):
                if key in values:
                    try:
                        value = Decimal(str(values[key]))
                    except (InvalidOperation, ValueError):
                        raise ValidationError(_('Enter a valid discount limit.')) from None
                    if not value.is_finite() or value.as_tuple().exponent < -2:
                        raise ValidationError(_('Discount limits accept at most two decimal places.'))

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            self._gd_validate_settings_input(values)
        return super().create(values_list)

    def write(self, values):
        self._gd_validate_settings_input(values)
        return super().write(values)

    def action_baseer_setup_global_discount(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('point_of_sale.group_pos_manager') or self.company_id not in self.env.companies:
            raise AccessError(_('Only a POS manager in this company can configure invoice discounts.'))
        if not self.baseer_global_discount_product_id:
            product = self.env['product.product'].with_company(self.company_id).create({
                'name': _('Invoice discount'), 'type': 'service', 'sale_ok': True,
                'purchase_ok': False, 'available_in_pos': True, 'list_price': 0,
                'company_id': self.company_id.id, 'taxes_id': [(5, 0, 0)],
            })
            self.baseer_global_discount_product_id = product
        product = self.baseer_global_discount_product_id.with_company(self.company_id)
        account = self.baseer_global_discount_account_id or product._get_product_accounts()['income']
        if not account:
            raise ValidationError(_('Choose the invoice discount income account before enabling discounts.'))
        self.baseer_global_discount_account_id = account
        # Pin the already selected native income account; never create a chart
        # account or rely on an implicit journal fallback at sale time.
        product.property_account_income_id = account
        self._gd_check_account_setup()
        values = {'baseer_global_discount_enabled': True, 'module_pos_discount': True}
        if not self.discount_product_id:
            native_product = self.env.ref('pos_discount.product_product_consumable', raise_if_not_found=False)
            values['discount_product_id'] = (
                native_product.id if native_product and (not native_product.company_id or native_product.company_id == self.company_id)
                else self.baseer_global_discount_product_id.id
            )
        self.write(values)
        return True

    def _get_special_products(self):
        return super()._get_special_products() | self.search([]).mapped('baseer_global_discount_product_id')

    @api.model
    def _load_pos_data_fields(self, config):
        inherited = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(inherited + [
            'baseer_global_discount_enabled', 'baseer_global_discount_max_percent',
            'baseer_global_discount_max_amount', 'baseer_global_discount_product_id',
            'baseer_offline_discount_account_proofs',
        ])) if inherited else inherited
