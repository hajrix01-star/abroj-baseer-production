from odoo import api, fields, models
from odoo.exceptions import ValidationError

PARTY_TYPES = [('client', 'عميل'), ('subcontractor', 'مقاول باطن')]


class ContractParty(models.Model):
    """Contract parties kept apart from res.partner contacts on purpose."""
    _name = 'abroj.contracting.party'
    _description = 'أطراف العقود'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char('الاسم', required=True)
    party_type = fields.Selection(PARTY_TYPES, string='النوع', required=True, default='subcontractor')
    phone = fields.Char('الجوال')
    vat = fields.Char('الرقم الضريبي')
    notes = fields.Text('ملاحظات')
    company_id = fields.Many2one('res.company', string='الشركة', required=True, default=lambda self: self.env.company)
    active = fields.Boolean('نشط', default=True)

    _name_type_company_uniq = models.Constraint('unique(name, party_type, company_id)', 'هذا الطرف موجود مسبقاً بنفس النوع.')

    @api.model
    def name_create(self, name):
        # Quick-create from a Many2one: reuse an existing party with the same name.
        name = (name or '').strip()
        if not name:
            raise ValidationError('اسم الطرف مطلوب.')
        party_type = self.env.context.get('default_party_type') or 'subcontractor'
        company_id = self.env.context.get('default_company_id') or self.env.company.id
        existing = self.search([('name', '=', name), ('party_type', '=', party_type), ('company_id', '=', company_id)], limit=1)
        if existing:
            return existing.id, existing.display_name
        return super().name_create(name)
