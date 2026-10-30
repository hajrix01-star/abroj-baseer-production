import base64
from markupsafe import Markup
from odoo.tools import file_open
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class Clause(models.Model):
    _name = 'abroj.contracting.clause'
    _description = 'Bilingual contract clause / بند العقد'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([('client', 'Client / العميل'), ('subcontractor', 'Subcontractor / مقاول الباطن')], required=True)
    text_ar = fields.Text(required=True)
    text_en = fields.Text(required=True)
    active = fields.Boolean(default=True)


class Company(models.Model):
    _inherit = 'res.company'
    contracting_name_ar = fields.Char('الاسم العربي للعقود')
    contracting_name_en = fields.Char('English contract name')

    def contract_font_css(self):
        with file_open('abroj_contracting/static/src/fonts/DejaVuSans.ttf', 'rb') as font:
            data = base64.b64encode(font.read()).decode()
        return "@font-face {font-family:AbrojArabic;src:url(data:font/truetype;base64,%s) format('truetype');} .header,.article,.footer {font-family:AbrojArabic,DejaVu Sans !important;}" % data


class Project(models.Model):
    _inherit = 'project.project'
    contract_vat_percent = fields.Float('VAT % / الضريبة', default=15)
    contract_retention_percent = fields.Float('Retention % / الضمان')
    contract_payment_schedule = fields.Text('Payment milestones / مراحل الدفع')

    def contract_clauses(self):
        return self.env['abroj.contracting.clause'].search([('kind', '=', 'client')])

    def action_print_contract(self):
        return self.env.ref('abroj_contracting.report_agreement').report_action(self)


class Subcontractor(models.Model):
    _inherit = 'abroj.contracting.subcontractor'
    start_date = fields.Date('Start / البدء')
    end_date = fields.Date('End / الانتهاء')
    penalties = fields.Text('Penalties / الغرامات')

    def contract_clauses(self):
        return self.env['abroj.contracting.clause'].search([('kind', '=', 'subcontractor')])

    def action_print_contract(self):
        return self.env.ref('abroj_contracting.report_subcontract').report_action(self)


class Voucher(models.Model):
    _inherit = 'abroj.contracting.voucher'
    vendor_contract_reference = fields.Char('Vendor contract / مرجع عقد المورد')
    vendor_contract_value = fields.Monetary('Vendor contract value / قيمة عقد المورد')
    balance_contract_value = fields.Monetary(compute='_compute_contract_balance', string='Contract value / قيمة العقد')
    balance_materials = fields.Monetary(compute='_compute_contract_balance', string='Materials / المواد')
    balance_before = fields.Monetary(compute='_compute_contract_balance', string='Previous / السابق')
    balance_remaining = fields.Monetary(compute='_compute_contract_balance', string='Remaining / المتبقي')
    balance_html = fields.Html(compute='_compute_contract_balance', string='Contract balance / رصيد العقد', sanitize=False)

    def previous_vouchers(self):
        self.ensure_one()
        domain = [('state', '=', 'issued'), ('company_id', '=', self.company_id.id),
                  ('project_id', '=', self.project_id.id), ('partner_id', '=', self.partner_id.id),
                  ('subcontractor_id', '=', self.subcontractor_id.id or False),
                  ('vendor_contract_reference', '=', self.vendor_contract_reference or False)]
        domain += [('id', '!=', self.id or 0)]
        previous = self.search(domain, order='issued_at, id')
        if self.state == 'issued':
            # Compare Python datetimes: ORM datetime domains serialize only seconds,
            # losing the precision needed for multiple issues within one second.
            previous = previous.filtered(lambda v: (v.issued_at, v.id) < (self.issued_at, self.id))
        return previous

    issued_at = fields.Datetime(readonly=True, copy=False)

    def init(self):
        self.env.cr.execute("UPDATE abroj_contracting_voucher SET issued_at = create_date WHERE state = 'issued' AND issued_at IS NULL")

    @api.depends('amount', 'kind', 'partner_id', 'project_id', 'subcontractor_id', 'vendor_contract_reference', 'vendor_contract_value', 'state', 'issued_at',
                 'project_id.voucher_ids.state', 'project_id.voucher_ids.amount', 'project_id.contract_value', 'subcontractor_id.materials_total', 'subcontractor_id.agreed_amount')
    def _compute_contract_balance(self):
        for v in self:
            previous = v.previous_vouchers() if v.project_id and v.partner_id else self.browse()
            sub = v.subcontractor_id
            value = sub.agreed_amount if sub else (v.vendor_contract_value if v.kind == 'payment' else v.project_id.contract_value)
            materials = sub.materials_total if sub else 0
            before = sum((p.amount if p.kind == 'payment' else -p.amount) if sub else p.amount for p in previous)
            current = -v.amount if sub and v.kind == 'receipt' else v.amount
            if v.state == 'cancelled':
                current = 0
            v.balance_contract_value = value
            v.balance_materials = materials
            v.balance_before = before
            v.balance_remaining = value - materials - before - current
            rows = [('Contract / العقد', value), ('Materials / المواد', materials), ('Previous / السابق', before), ('This voucher / هذا السند', v.amount), ('Remaining / المتبقي', v.balance_remaining)]
            history = Markup('<table class="table table-sm"><tr><th>Date / التاريخ</th><th>Number / الرقم</th><th>Amount / المبلغ</th></tr>%s</table>') % Markup('').join(
                Markup('<tr><td>%s</td><td>%s</td><td>%.2f</td></tr>') % (p.date, p.name, p.amount) for p in previous)
            v.balance_html = history + Markup('<table class="table table-sm">%s</table>') % Markup('').join(Markup('<tr><th>%s</th><td>%.2f</td></tr>') % (label, amount) for label, amount in rows)

    @api.onchange('project_id', 'kind', 'subcontractor_id')
    def _onchange_contract_party(self):
        if self.subcontractor_id:
            self.partner_id = self.subcontractor_id.partner_id
        elif self.kind == 'receipt':
            self.partner_id = self.project_id.partner_id

    @api.constrains('kind', 'partner_id', 'project_id', 'subcontractor_id')
    def _check_client_party(self):
        for v in self:
            # Receipts on subcontractor contracts are refunds, supported by existing accounting.
            if v.kind == 'receipt' and not v.subcontractor_id and v.partner_id != v.project_id.partner_id:
                raise ValidationError('سند القبض يجب أن يرتبط بعميل عقد المشروع.')

    @api.model_create_multi
    def create(self, vals_list):
        if any('issued_at' in vals for vals in vals_list):
            raise ValidationError('وقت الإصدار للقراءة فقط.')
        return super().create(vals_list)

    def write(self, vals):
        if 'issued_at' in vals:
            raise ValidationError('وقت الإصدار للقراءة فقط.')
        return super().write(vals)

    def action_issue(self):
        for v in self:
            if v.kind == 'payment' and not v.subcontractor_id and (not v.vendor_contract_reference or v.vendor_contract_value <= 0):
                raise ValidationError('حدد عقد مقاول الباطن أو مرجع عقد المورد وقيمته الموجبة.')
        result = super().action_issue()
        # Bypass the financial document lock only for this internal issuance timestamp.
        self.env.cr.execute('UPDATE abroj_contracting_voucher SET issued_at = timezone(\'UTC\', clock_timestamp()) WHERE id IN %s', [tuple(self.ids)])
        self.invalidate_recordset(['issued_at'])
        return result


class ContractReport(models.Model):
    _inherit = 'ir.actions.report'

    def _get_layout(self):
        if self.report_name in ('abroj_contracting.agreement', 'abroj_contracting.subcontract', 'abroj_contracting.voucher'):
            return self.env.ref('abroj_contracting.pdf_document_layout')
        return super()._get_layout()
