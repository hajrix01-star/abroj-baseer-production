import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

APP_BALANCE_START_DATE = '2026-11-01'

# Live reference identifiers; all are validated before use.
DOCUMENTED_DEFAULTS = {
    1: {'custody': (460, 3426), 'excluded': (459, 407, 408, 409, 405, 406, 458), 'pos_cutover_date': '2026-10-03'},
    2: {'custody': (461, 3427), 'excluded': (459, 405, 406, 458), 'pos_cutover_date': '2026-11-19'},
    3: {'custody': None, 'excluded': (405, 406, 458)},
}
POS_DEFAULTS = {'cash': (112, 121, 126, 127), 'card': (113, 122, 119), 'transfer': (114, 120), 'credit': (128,), 'hunger': (115, 123), 'keeta': (116, 124), 'jahez': (117, 125)}
ACCOUNT_DEFAULTS = {'105090': 'cash', '101090': 'card', '102110': 'hunger', '102111': 'keeta', '102112': 'jahez'}
from odoo.exceptions import ValidationError


class DashboardCategory(models.Model):
    _name = 'baseer.dashboard2.category'
    _description = 'Dashboard category'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Selection([(x, x) for x in ('revenue', 'other_income', 'food_cost', 'salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'non_operating', 'zakat_tax')], required=True)
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
    key = fields.Selection([(x, x) for x in ('cash', 'card', 'keeta', 'hunger', 'jahez', 'other_app', 'other', 'transfer', 'credit')], required=True)
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
    pos_cutover_date = fields.Date(help='Legacy reference date; posted entries determine sales unless a source override applies.')
    app_balance_start_date = fields.Date(help='Exclude app balance movements before this date; earlier balances are under review.')
    summary_pos_config_ids = fields.Many2many('pos.config', 'bd2_summary_pos_rel', 'settings_id', 'config_id', check_company=True)
    liquidity_account_ids = fields.Many2many('account.account', 'bd2_liquidity_account_rel', 'settings_id', 'account_id', check_company=True)
    food_purchase_account_ids = fields.Many2many('account.account', 'bd2_food_purchase_account_rel', 'settings_id', 'account_id', string='حسابات مشتريات الطعام', check_company=True)
    liquidity_ids = fields.One2many('baseer.dashboard2.liquidity', 'settings_id')

    excluded_journal_ids = fields.Many2many('account.journal', 'bd2_settings_excluded_journal_rel', 'settings_id', 'journal_id', check_company=True)
    min_order_amount = fields.Float(default=1.5)
    channel_map_ids = fields.One2many('baseer.dashboard2.channel.map', 'settings_id')
    source_override_ids = fields.One2many('baseer.dashboard2.source.override', 'settings_id')

    @api.model
    def _seed_food_purchase_accounts(self):
        for company in self.env['res.company'].sudo().search([]):
            settings = self.sudo().search([('company_id', '=', company.id)], limit=1)
            if not settings:
                settings = self.sudo().create({'company_id': company.id})
            if not settings.food_purchase_account_ids:
                accounts = self.env['account.account'].sudo().with_company(company).search([
                    ('company_ids', 'in', company.id), ('code', 'in', ['400001', '400002'])])
                if accounts:
                    settings.write({'food_purchase_account_ids': [(6, 0, accounts.ids)]})

    def action_seed_documented_defaults(self):
        self._seed_documented_defaults(force=True, company_ids=self.mapped('company_id').ids)
        return True

    @api.model
    def _seed_documented_defaults(self, force=False, company_ids=None):
        companies = self.env['res.company'].browse([i for i in DOCUMENTED_DEFAULTS if company_ids is None or i in company_ids]).exists()
        channels = {c.key: c for c in self.env['baseer.dashboard2.channel'].search([])}
        mapping = self.env['baseer.dashboard2.channel.map']
        for company in companies:
            env = self.with_company(company).with_context(allowed_company_ids=[company.id])
            settings = env.search([('company_id', '=', company.id)], limit=1)
            if not settings:
                settings = env.create({'company_id': company.id})
            defaults = DOCUMENTED_DEFAULTS[company.id]
            def journal(jid, account_id=None):
                rec = self.env['account.journal'].sudo().browse(jid).exists()
                if not rec or rec.company_id != company or (account_id and rec.default_account_id.id != account_id):
                    _logger.info('Dashboard defaults: skip journal %s for company %s (missing or mismatch)', jid, company.id)
                    return self.env['account.journal']
                return rec
            excluded = self.env['account.journal']
            for jid in defaults['excluded']:
                excluded |= journal(jid)
            custody = journal(*defaults['custody']) if defaults['custody'] else self.env['account.journal']
            # Empty fields may be filled; existing values are never overwritten by installation.
            vals = {}
            if not settings.app_balance_start_date:
                vals['app_balance_start_date'] = APP_BALANCE_START_DATE
            if not settings.pos_cutover_date and defaults.get('pos_cutover_date'):
                vals['pos_cutover_date'] = defaults['pos_cutover_date']
            if force or not settings.excluded_journal_ids:
                vals['excluded_journal_ids'] = [(6, 0, excluded.ids)]
            if force or not settings.custody_journal_ids:
                vals['custody_journal_ids'] = [(6, 0, custody.ids)]
            if force or not settings.outflow_journal_ids:
                excluded_effective = excluded if force or not settings.excluded_journal_ids else settings.excluded_journal_ids
                custody_effective = custody if force or not settings.custody_journal_ids else settings.custody_journal_ids
                journals = self.env['account.journal'].sudo().search([('company_id', '=', company.id), ('type', 'in', ('bank', 'cash'))])
                vals['outflow_journal_ids'] = [(6, 0, ((journals - excluded_effective) | custody_effective).ids)]
            settings.write(vals)
            def add(source, record, key):
                field = {'pos_method': 'pos_payment_method_id', 'account': 'account_id', 'journal': 'journal_id'}[source]
                existing = mapping.search([('company_id', '=', company.id), ('source', '=', source), (field, '=', record.id)], limit=1)
                if not existing and key in channels:
                    mapping.create({'settings_id': settings.id, 'company_id': company.id, 'source': source, field: record.id, 'channel_id': channels[key].id, 'kind': 'app' if channels[key].kind == 'app' else key if key in ('transfer', 'credit') else 'hall'})
            for key, ids in POS_DEFAULTS.items():
                for rid in ids:
                    rec = self.env['pos.payment.method'].sudo().browse(rid).exists()
                    if rec and rec.company_id == company:
                        add('pos_method', rec, key)
                    else:
                        _logger.info('Dashboard defaults: skip payment method %s for company %s (missing or mismatch)', rid, company.id)
            for code, key in ACCOUNT_DEFAULTS.items():
                accounts = self.env['account.account'].sudo().with_company(company).search([('company_ids', 'in', company.id), ('code', '=', code)])
                for account in accounts:
                    add('account', account, key)
            defaults_accounts = {1: [(3426, 'custody', '')], 2: [(3427, 'custody', ''), (3420, 'bank', 'حساب الأهلي — كيتا'), (3421, 'bank', 'حساب الأهلي — هنقرستيشن'), (3986, 'bank', 'حساب الأهلي — جاهز')], 3: []}
            for aid, kind, label in defaults_accounts.get(company.id, []):
                account = self.env['account.account'].sudo().browse(aid).exists()
                if not account or company not in account.company_ids:
                    _logger.info('Dashboard defaults: skip liquidity account %s for company %s (missing or mismatch)', aid, company.id)
                    continue
                if account not in settings.liquidity_account_ids:
                    settings.write({'liquidity_account_ids': [(4, account.id)]})
                if not settings.liquidity_ids.filtered(lambda row: row.account_id == account):
                    self.env['baseer.dashboard2.liquidity'].create({'settings_id': settings.id, 'account_id': account.id, 'kind': kind, 'label': label})
                if company.id == 2 and aid in (3420, 3421, 3986):
                    add('account', account, {3420: 'keeta', 3421: 'hunger', 3986: 'jahez'}[aid])
            for code in ('101090', '105090'):
                accounts = self.env['account.account'].sudo().with_company(company).search([('company_ids', 'in', company.id), ('code', '=', code)])
                settings.write({'liquidity_account_ids': [(4, account.id) for account in accounts]})
        return True


class DashboardChannelMap(models.Model):
    _name = 'baseer.dashboard2.channel.map'
    _description = 'Dashboard channel mapping'
    _check_company_auto = True

    settings_id = fields.Many2one('baseer.dashboard2.settings', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one('res.company', required=True, ondelete='cascade')
    source = fields.Selection([('pos_method', 'POS payment method'), ('account', 'Account'), ('journal', 'Journal')], required=True)
    pos_payment_method_id = fields.Many2one('pos.payment.method', check_company=True)
    account_id = fields.Many2one('account.account', check_company=True)
    journal_id = fields.Many2one('account.journal', check_company=True)
    channel_id = fields.Many2one('baseer.dashboard2.channel', required=True)
    kind = fields.Selection([('hall', 'Hall'), ('app', 'App'), ('transfer', 'Transfer'), ('credit', 'Credit')], required=True)
    active = fields.Boolean(default=True)

    @api.constrains('source', 'pos_payment_method_id', 'account_id', 'journal_id', 'company_id', 'settings_id')
    def _check_mapping(self):
        for rec in self:
            fields_by_source = {'pos_method': rec.pos_payment_method_id, 'account': rec.account_id, 'journal': rec.journal_id}
            if not fields_by_source.get(rec.source) or sum(bool(v) for v in fields_by_source.values()) != 1 or rec.settings_id.company_id != rec.company_id:
                raise ValidationError(_('Select the matching source and company.'))


class DashboardLiquidity(models.Model):
    _name = 'baseer.dashboard2.liquidity'
    _description = 'Dashboard liquidity account source'
    _check_company_auto = True

    settings_id = fields.Many2one('baseer.dashboard2.settings', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='settings_id.company_id', store=True)
    account_id = fields.Many2one('account.account', required=True, check_company=True)
    kind = fields.Selection([('bank', 'Bank'), ('cash', 'Cash'), ('custody', 'Custody'), ('app', 'App account')], required=True)
    label = fields.Char()


class DashboardSourceOverride(models.Model):
    _name = 'baseer.dashboard2.source.override'
    _description = 'Dashboard sales source override'
    _check_company_auto = True
    _order = 'date_from, id'

    settings_id = fields.Many2one('baseer.dashboard2.settings', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='settings_id.company_id', store=True, index=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    source = fields.Selection([('auto', 'Automatic merge'), ('summary', 'Summary'), ('pos', 'POS')], required=True, default='auto')
    note = fields.Text()

    @api.constrains('date_from', 'date_to', 'company_id')
    def _check_period(self):
        for record in self:
            if record.date_from and record.date_to and record.date_to < record.date_from:
                raise ValidationError(_('The end date must not precede the start date.'))
            if record.date_from and record.date_to and self.search_count([
                ('id', '!=', record.id), ('company_id', '=', record.company_id.id),
                ('date_from', '<=', record.date_to), ('date_to', '>=', record.date_from)]):
                raise ValidationError(_('Sales source override periods cannot overlap for the same company.'))
