from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.osv import expression


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_zatca_allow_anonymous_b2c = fields.Boolean(
        string='Allow anonymous B2C ZATCA sales',
        default=False,
        help='For Saudi POS only. A configured internal consumer is assigned only when the cashier has not selected a customer.',
    )
    baseer_zatca_anonymous_partner_id = fields.Many2one(
        'res.partner',
        string='Internal anonymous consumer',
        check_company=True,
        help='Internal person record used only for an unnamed consumer sale. It must not represent a real customer.',
    )

    @api.model
    def _load_pos_data_fields(self, config):
        """Expose the opt-in policy and its internal partner to the POS client.

        The Saudi localization performs its mandatory-invoice validation in the
        browser before the order reaches ``_process_order``.  Therefore the
        client must receive both fields so it can assign the internal consumer
        first; the server-side assignment remains the authoritative fallback.
        """
        inherited = super()._load_pos_data_fields(config)
        if not inherited:
            # An empty list is the native "load all permitted fields" marker.
            # Preserve it instead of accidentally narrowing POS bootstrap data.
            return inherited
        return list(dict.fromkeys(inherited + [
            'baseer_zatca_allow_anonymous_b2c',
            'baseer_zatca_anonymous_partner_id',
        ]))

    @api.constrains('baseer_zatca_allow_anonymous_b2c', 'baseer_zatca_anonymous_partner_id', 'company_id')
    def _check_baseer_zatca_anonymous_b2c(self):
        for config in self:
            if not config.baseer_zatca_allow_anonymous_b2c:
                continue
            partner = config.baseer_zatca_anonymous_partner_id
            if config.company_id.country_id.code != 'SA':
                raise ValidationError(_('Anonymous B2C ZATCA sales are available only for a Saudi company.'))
            if not partner:
                raise ValidationError(_('Choose the internal anonymous consumer before enabling anonymous B2C ZATCA sales.'))
            if partner.company_type != 'person' or partner.vat:
                raise ValidationError(_('The internal anonymous consumer must be an individual without a VAT number.'))
            if partner.company_id and partner.company_id != config.company_id:
                raise ValidationError(_('The internal anonymous consumer must belong to this company or be shared.'))

    def _baseer_zatca_anonymous_partner_for_order(self, order):
        """Return the configured internal consumer only for a final Saudi B2C POS sale."""
        self.ensure_one()
        partner = self.baseer_zatca_anonymous_partner_id
        if not (
            self.baseer_zatca_allow_anonymous_b2c
            and self.company_id.country_id.code == 'SA'
            and partner
            and partner.company_type == 'person'
            and not partner.vat
            and (not partner.company_id or partner.company_id == self.company_id)
            and not order.get('partner_id')
            and order.get('to_invoice')
            and not order.get('shipping_date')
            and order.get('state') in ('paid', 'done', 'invoiced')
        ):
            return self.env['res.partner']
        return partner


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = super()._load_pos_data_domain(data, config)
        partner = config.baseer_zatca_anonymous_partner_id
        if config.baseer_zatca_allow_anonymous_b2c and partner:
            return expression.OR([domain, [('id', '=', partner.id)]])
        return domain
