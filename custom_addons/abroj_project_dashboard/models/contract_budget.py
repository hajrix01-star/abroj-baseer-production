import logging
import unicodedata

from odoo import api, fields, models
from odoo.addons.abroj_contracting.models.contracting import FrozenDocument

_logger = logging.getLogger(__name__)


def _tokens(value):
    return set(''.join(c if c.isalpha() or unicodedata.category(c).startswith('M') else ' '
                       for c in (value or '').lower().replace('ـ', '')).split())


class Subcontractor(models.Model):
    _inherit = 'abroj.contracting.subcontractor'

    budget_line_id = fields.Many2one('abroj.project.budget.line', string='بند التكلفة',
                                     domain="[('project_id', '=', project_id)]")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records.filtered(lambda r: not r.budget_line_id and r.project_id):
            try:
                with self.env.cr.savepoint():
                    words = _tokens(' '.join(filter(None, [record.party_id.name, record.partner_id.name,
                                                          record.scope, record.name if 'name' in record._fields else ''])))
                    scores = [(len(words & _tokens(line.name)), line) for line in
                              self.env['abroj.project.budget.line'].search([('project_id', '=', record.project_id.id)])]
                    best = max((score for score, line in scores), default=0)
                    matches = [line for score, line in scores if score == best and score]
                    if len(matches) == 1:
                        record.budget_line_id = matches[0]
            except Exception:
                _logger.exception('Could not suggest subcontract budget line')
        return records


class ClauseLine(models.Model):
    _inherit = 'abroj.contract.clause.line'

    budget_line_id = fields.Many2one('abroj.project.budget.line', string='بند التكلفة',
                                     domain="[('project_id', '=', project_id)]")


class BudgetLine(models.Model):
    _inherit = 'abroj.project.budget.line'

    parent_id = fields.Many2one('abroj.project.budget.line', string='البند الرئيسي', ondelete='set null',
                                domain="[('project_id', '=', project_id)]")
    child_ids = fields.One2many('abroj.project.budget.line', 'parent_id', string='البنود الفرعية')
    group_name = fields.Char(string='مجموعة البند', compute='_compute_group_name', store=True)

    voucher_ids = fields.One2many('abroj.contracting.voucher', 'abroj_budget_line_id')
    advance_paid = fields.Monetary(string='مدفوع مقدماً', compute='_compute_spending')
    total_spent = fields.Monetary(string='إجمالي المصروف', compute='_compute_spending')
    remaining_budget = fields.Monetary(string='الميزانية المتبقية', compute='_compute_spending')
    over_budget = fields.Boolean(string='تجاوز الميزانية', compute='_compute_spending')

    @api.depends('budget', 'actual', 'voucher_ids.state', 'voucher_ids.kind',
                 'voucher_ids.payment_purpose', 'voucher_ids.amount',
                 'voucher_ids.payment_id.move_id.state',
                 'voucher_ids.payment_id.move_id.line_ids.amount_residual',
                 'voucher_ids.payment_id.move_id.line_ids.account_id.account_type')
    @api.depends_context('uid', 'company')
    def _compute_spending(self):
        for line in self:
            advances = 0.0
            readable = all(self.env[model].has_access('read') for model in
                           ('abroj.contracting.voucher', 'account.payment', 'account.move', 'account.move.line', 'account.account'))
            vouchers = line.voucher_ids if readable else self.env['abroj.contracting.voucher']
            for voucher in vouchers.filtered(lambda v: v.state == 'issued' and v.kind == 'payment'
                                                       and v.payment_purpose == 'advance'):
                payment = voucher.payment_id
                if not payment or payment.move_id.state != 'posted':
                    continue
                payable = payment.move_id.line_ids.filtered(lambda l: l.account_id.account_type == 'liability_payable')
                advances += sum(abs(item.amount_residual) for item in payable) if payable else voucher.amount
            line.advance_paid = advances
            line.total_spent = line.actual + advances
            line.remaining_budget = line.budget - line.total_spent
            line.over_budget = bool(line.budget and line.total_spent > line.budget)

    @api.depends('name', 'parent_id.name')
    def _compute_group_name(self):
        for line in self:
            line.group_name = line.parent_id.name or line.name


class Voucher(models.Model):
    _inherit = 'abroj.contracting.voucher'

    def _suggest_budget_line(self):
        self.ensure_one()
        # Accommodate a clause link if another installed module supplies one.
        clause_field = next((name for name, field in self._fields.items()
                             if field.type == 'many2one' and field.comodel_name == 'abroj.contract.clause.line'), None)
        clause = self[clause_field] if clause_field else False
        line = (clause and clause.budget_line_id) or self.subcontractor_id.budget_line_id
        if line and line.project_id == self.project_id:
            return line
        domain = [('id', '!=', self.id), ('project_id', '=', self.project_id.id),
                  ('abroj_budget_line_id', '!=', False)]
        if self.party_id:
            domain.append(('party_id', '=', self.party_id.id))
        elif self.partner_id:
            domain.append(('partner_id', '=', self.partner_id.id))
        else:
            return self.env['abroj.project.budget.line']
        return self.search(domain, order='date desc, id desc', limit=1).abroj_budget_line_id

    def _autofill_budget_line(self):
        for voucher in self.filtered(lambda v: v.state == 'draft' and v.project_id and not v.abroj_budget_line_id):
            try:
                with self.env.cr.savepoint():
                    line = voucher._suggest_budget_line()
                    if line:
                        super(FrozenDocument, voucher).write({'abroj_budget_line_id': line.id})
            except Exception:
                _logger.exception('Could not suggest voucher budget line')

    @api.model_create_multi
    def create(self, vals_list):
        vouchers = super().create(vals_list)
        vouchers._autofill_budget_line()
        return vouchers

    def write(self, vals):
        result = super().write(vals)
        if {'subcontractor_id', 'project_id'} & vals.keys():
            self._autofill_budget_line()
        return result
