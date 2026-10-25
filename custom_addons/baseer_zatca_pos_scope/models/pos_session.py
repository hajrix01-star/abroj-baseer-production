from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def baseer_zatca_phase2_status(self):
        self.ensure_one()
        session = self.sudo()
        if not session.config_id.baseer_zatca_phase2_enabled:
            return {'enabled': False, 'sent': 0, 'pending': 0, 'error': 0}

        documents = self.env['account.edi.document'].sudo().search([
            ('edi_format_id.code', '=', 'sa_zatca'),
            ('move_id', 'in', session.order_ids.account_move.ids),
        ])
        return {
            'enabled': True,
            'sent': sum(document.state == 'sent' for document in documents),
            'pending': sum(document.state in ('to_send', 'to_cancel') for document in documents),
            'error': sum(document.state == 'error' for document in documents),
        }
