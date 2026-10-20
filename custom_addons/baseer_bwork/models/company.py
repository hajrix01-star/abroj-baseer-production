from odoo import fields, models

from ..contracts import DEFAULT_HISTORY_POLICY


class ResCompany(models.Model):
    _inherit = 'res.company'

    bwork_history_policy = fields.Selection(
        [('since_join', 'Messages from joining onward'),
         ('all_history', 'All history, only after explicit policy approval')],
        string='BWork History Policy',
        required=True, default=DEFAULT_HISTORY_POLICY,
        groups='base.group_system',
        help='Policy intent only. Neither option activates BWork. Global native '
             'Discuss, attachment, quote and notification enforcement is pending.',
    )
