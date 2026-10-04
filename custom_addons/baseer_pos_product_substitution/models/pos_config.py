from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_substitution_enabled = fields.Boolean(
        string='Use controlled product substitutions',
        help=(
            'When enabled, products marked for controlled substitution cannot be '
            'deleted directly in this Point of Sale.'
        ),
        default=False,
    )

    @api.model
    def _load_pos_data_fields(self, config):
        # Extend the canonical native + print bridge contract.  In particular,
        # never replace it with a Baseer-only field list: currency_id and
        # use_pricelist are required to bootstrap the POS store.
        inherited = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(inherited + [
            'baseer_substitution_enabled',
        ])) if inherited else inherited

    @api.model
    def _load_pos_data_read(self, records, config):
        values = super()._load_pos_data_read(records, config)
        by_id = {record.id: record for record in records}
        for value in values:
            record = by_id.get(value.get('id'))
            if record:
                value['baseer_substitution_enabled'] = record.baseer_substitution_enabled
                # POS 19 may hydrate a sale line from a variant cache before
                # its template delegates are ready.  Send the small, immutable
                # policy map with the register configuration as the source of
                # truth: only protected POS products and their permitted
                # replacement IDs are exposed to the cashier.
                protected_templates = self.env['product.template'].search([
                    ('available_in_pos', '=', True),
                    ('baseer_substitution_enabled', '=', True),
                    '|', ('company_id', '=', False), ('company_id', '=', record.company_id.id),
                ])
                value['baseer_substitution_policies'] = [
                    {
                        'source_product_id': template.product_variant_id.id,
                        'replacement_product_ids': template.baseer_substitution_product_ids.ids,
                    }
                    for template in protected_templates
                    if template.product_variant_id and template.baseer_substitution_product_ids
                ]
                session = record.current_session_id
                locked_lines = []
                if session and session.state in ('opened', 'closing_control'):
                    events = self.env['baseer.pos.substitution'].sudo().search([
                        ('session_id', '=', session.id),
                        ('order_id.state', '=', 'draft'),
                    ])
                    for event in events:
                        for snapshot in event.replacement_snapshot or []:
                            if snapshot.get('line_uuid'):
                                locked_lines.append({
                                    'line_uuid': snapshot['line_uuid'],
                                    'minimum_quantity': snapshot.get('quantity', 0),
                                })
                value['baseer_substitution_locked_lines'] = locked_lines
        return values
