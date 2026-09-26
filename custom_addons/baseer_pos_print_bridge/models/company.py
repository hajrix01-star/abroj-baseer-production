from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    baseer_primary_print_agent_id = fields.Many2one(
        'baseer.print.agent', string='Primary Windows print computer',
        ondelete='restrict', copy=False,
        help='The one Windows computer that prints this company’s POS jobs.',
    )

    def _baseer_effective_print_agent(self):
        """Return the explicit primary Agent, or the only safe legacy choice."""
        self.ensure_one()
        agent = self.baseer_primary_print_agent_id
        if agent and agent.active and agent.state in ('online', 'offline') and agent._allows_company(self):
            return agent
        candidates = self.env['baseer.print.agent'].search([
            ('active', '=', True),
            ('state', 'in', ('online', 'offline')),
            ('allowed_company_ids', 'in', self.ids),
        ], limit=2)
        return candidates if len(candidates) == 1 else self.env['baseer.print.agent']

    @api.constrains('baseer_primary_print_agent_id')
    def _check_baseer_primary_print_agent(self):
        for company in self:
            agent = company.baseer_primary_print_agent_id
            if not agent:
                continue
            if not agent.active or agent.state not in ('online', 'offline') or not agent._allows_company(company):
                raise ValidationError(_(
                    'The primary Windows print computer must be active and authorized for this company.'
                ))
