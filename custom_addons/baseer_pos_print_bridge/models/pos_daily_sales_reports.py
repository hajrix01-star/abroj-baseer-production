from odoo import _, models
from odoo.exceptions import AccessError, UserError, ValidationError


class PosDailySalesReportsWizard(models.TransientModel):
    _inherit = 'pos.daily.sales.reports.wizard'

    def action_baseer_open_whatsapp_session_report(self):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_('Only a Point of Sale manager can send a session report by WhatsApp.'))

        session = self.pos_session_id
        if not session:
            raise UserError(_('Choose one closed POS session first.'))
        session.check_access_rights('read')
        session.check_access_rule('read')
        if session.company_id not in self.env.companies:
            raise AccessError(_('You do not have access to this session company.'))
        if session.state != 'closed':
            raise ValidationError(_('The WhatsApp session report is available only after the session is closed.'))

        return session.action_baseer_open_whatsapp_closing_report()

