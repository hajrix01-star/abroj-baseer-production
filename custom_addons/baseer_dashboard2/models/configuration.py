from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class DashboardCategory(models.Model):
    _name = 'baseer.dashboard2.category'
    _description = 'Dashboard category'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Selection([(x, x) for x in ('revenue', 'other_income', 'food_cost', 'salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'zakat_tax')], required=True)
    sequence = fields.Integer(default=10)
    account_code_prefixes = fields.Char()
    account_type_fallback = fields.Char()
    color_token = fields.Char()
    active = fields.Boolean(default=True)


class DashboardChannel(models.Model):
    _name = 'baseer.dashboard2.channel'
    _description = 'Dashboard channel'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    key = fields.Selection([(x, x) for x in ('cash', 'card', 'keeta', 'hunger', 'jahez', 'other_app', 'other')], required=True)
    kind = fields.Selection([('hall', 'Hall'), ('app', 'App')], required=True)
    sequence = fields.Integer(default=10)
    color_token = fields.Char()
    line_keywords = fields.Char()
    pos_method_keywords = fields.Char()
    commission_rate = fields.Float(default=0)
    active = fields.Boolean(default=True)


class DashboardTarget(models.Model):
    _name = 'baseer.dashboard2.target'
    _description = 'Dashboard target'

    company_id = fields.Many2one('res.company', ondelete='cascade')
    key = fields.Selection([(x, x) for x in ('food_pct', 'salaries_pct', 'prime_pct', 'net_margin_pct')], required=True)
    operator = fields.Selection([('le', '≤'), ('ge', '≥')], required=True)
    value = fields.Float(required=True)


class DashboardEvent(models.Model):
    _name = 'baseer.dashboard2.event'
    _description = 'Dashboard event'
    _order = 'date_from, id'

    name = fields.Char(required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    company_ids = fields.Many2many('res.company')
    kind = fields.Selection([('holiday', 'إجازة/عيد'), ('season', 'موسم'), ('salary', 'نزول الرواتب'), ('promo', 'عرض/حملة'), ('other', 'أخرى')], required=True, default='other')
    note = fields.Text()
    color_token = fields.Char()
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('date_from') and not vals.get('date_to'):
                vals['date_to'] = vals['date_from']
        return super().create(vals_list)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_from and record.date_to and record.date_to < record.date_from:
                raise ValidationError(_('The end date must not precede the start date.'))


class DashboardSettings(models.Model):
    _name = 'baseer.dashboard2.settings'
    _description = 'Dashboard company settings'
    _company_unique = models.Constraint('unique(company_id)', 'Only one settings record is allowed per company.')

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='cascade')
    outflow_journal_ids = fields.Many2many('account.journal', 'bd2_settings_outflow_journal_rel', 'settings_id', 'journal_id', check_company=True)
    custody_journal_ids = fields.Many2many('account.journal', 'bd2_settings_custody_journal_rel', 'settings_id', 'journal_id', check_company=True)
    show_vat_paid_line = fields.Boolean(default=True)
    pos_cutover_note = fields.Text()
