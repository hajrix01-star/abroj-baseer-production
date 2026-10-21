from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..contracts import DEFAULT_HISTORY_POLICY
from ..company_display import short_name


DISPLAY_FIELDS = frozenset({'bwork_short_name_ar', 'bwork_short_name_en', 'bwork_hidden'})


class ResCompany(models.Model):
    _inherit = 'res.company'

    bwork_short_name_ar = fields.Char(string='Short name in Arabic', size=64,
                                     copy=False, groups='base.group_system')
    bwork_short_name_en = fields.Char(string='Short name in English', size=64,
                                     copy=False, groups='base.group_system')
    bwork_hidden = fields.Boolean(string='Hide company from BWork', default=False,
                                 copy=False, groups='base.group_system',
                                 help='Hide this company in BWork only. Odoo permissions and existing data stay unchanged.')

    @api.model_create_multi
    def create(self, vals_list):
        if (any(DISPLAY_FIELDS & set(vals) for vals in vals_list)
                or any('default_' + field in self.env.context for field in DISPLAY_FIELDS)):
            raise AccessError(self.env._('Create the company first, then configure its display in BWork settings.'))
        return super().create(vals_list)

    def write(self, vals):
        if DISPLAY_FIELDS & set(vals):
            user = self.env['baseer.bwork.service']._require_room_manager()
            if (not user.has_group('base.group_system') or not self
                    or not set(self.ids) <= set(user.company_ids.ids) & set(self.env.companies.ids)):
                raise AccessError(self.env._('Select only currently authorized companies.'))
            vals = dict(vals)
            for field in ('bwork_short_name_ar', 'bwork_short_name_en'):
                if field in vals:
                    try:
                        vals[field] = short_name(vals[field])
                    except ValueError:
                        raise ValidationError(self.env._('Use a short company name of at most 64 characters without control characters.')) from None
            if 'bwork_hidden' in vals and type(vals['bwork_hidden']) is not bool:
                raise ValidationError(self.env._('Choose whether to hide the company from BWork.'))
        return super().write(vals)

    bwork_history_policy = fields.Selection(
        [('since_join', 'Messages from joining onward'),
         ('all_history', 'All history, only after explicit policy approval')],
        string='BWork History Policy',
        required=True, default=DEFAULT_HISTORY_POLICY,
        groups='base.group_system',
        help='Policy intent only. Neither option activates BWork. Global native '
             'Discuss, attachment, quote and notification enforcement is pending.',
    )
