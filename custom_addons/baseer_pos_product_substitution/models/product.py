from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    baseer_substitution_enabled = fields.Boolean(
        string='Eligible for controlled substitution',
        help='Cashiers must substitute this POS item instead of deleting it directly.',
    )
    baseer_substitution_product_ids = fields.Many2many(
        'product.product',
        'baseer_substitution_product_rel',
        'source_tmpl_id',
        'replacement_product_id',
        string='Allowed substitution products',
        help='Only these products may replace this protected product in Point of Sale.',
    )
    baseer_substitution_product_ids_json = fields.Json(
        compute='_compute_baseer_substitution_product_ids_json',
        string='POS substitution product IDs', store=True,
        help='Read-only POS policy payload. The cashier never receives edit rights.',
    )

    @api.constrains('baseer_substitution_enabled', 'baseer_substitution_product_ids')
    def _check_baseer_substitution_products(self):
        for template in self:
            replacements = template.baseer_substitution_product_ids
            if template.baseer_substitution_enabled and not replacements:
                raise ValidationError(_('Choose at least one allowed substitution product.'))
            if any(product.product_tmpl_id == template for product in replacements):
                raise ValidationError(_('A product cannot be its own substitution product.'))
            if any(not product.active or not product.available_in_pos for product in replacements):
                raise ValidationError(_('Allowed substitution products must be active and available in Point of Sale.'))

    @api.depends('baseer_substitution_product_ids')
    def _compute_baseer_substitution_product_ids_json(self):
        for template in self:
            template.baseer_substitution_product_ids_json = template.baseer_substitution_product_ids.ids

    @api.model
    def _load_pos_data_fields(self, config):
        # Odoo 19's POS catalog is built around product.template and resolves
        # variants through it in the browser.  Loading the policy here makes
        # the protected-delete decision durable across full POS cache reloads.
        inherited = super()._load_pos_data_fields(config)
        return inherited + [
            'baseer_substitution_enabled',
            'baseer_substitution_product_ids_json',
        ] if inherited else inherited


class ProductProduct(models.Model):
    _inherit = 'product.product'

    baseer_substitution_enabled = fields.Boolean(
        related='product_tmpl_id.baseer_substitution_enabled', readonly=True, store=True,
    )
    baseer_substitution_product_ids = fields.Many2many(
        related='product_tmpl_id.baseer_substitution_product_ids', readonly=True,
    )
    baseer_substitution_product_ids_json = fields.Json(
        related='product_tmpl_id.baseer_substitution_product_ids_json', readonly=True, store=True,
    )

    @api.model
    def _load_pos_data_fields(self, config):
        inherited = super()._load_pos_data_fields(config)
        return inherited + [
            'baseer_substitution_enabled',
            'baseer_substitution_product_ids_json',
        ] if inherited else inherited
