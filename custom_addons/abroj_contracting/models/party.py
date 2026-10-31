from odoo import api, fields, models
from odoo.exceptions import ValidationError

PARTY_TYPES = [('client', 'عميل'), ('subcontractor', 'مقاول باطن'), ('supplier', 'مورد')]


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
    # Reuses contact tags only; parties never link to res.partner records.
    category_ids = fields.Many2many('res.partner.category', 'abroj_contracting_party_category_rel', 'party_id', 'category_id', string='الوسوم')

    _TYPE_TAGS = {'client': 'abroj_contracting.party_tag_clients', 'subcontractor': 'abroj_contracting.party_tag_subcontractors',
                  'supplier': 'abroj_contracting.party_tag_suppliers'}

    def _default_type_tags(self, party_type):
        tag = self.env.ref(self._TYPE_TAGS.get(party_type, ''), raise_if_not_found=False) if party_type else None
        return tag or self.env['res.partner.category']

    @api.constrains('category_ids')
    def _check_tags(self):
        for party in self:
            if not party.category_ids:
                raise ValidationError('اختر وسماً واحداً على الأقل للطرف.')

    @api.onchange('party_type')
    def _onchange_party_type_tags(self):
        type_tags = self.env['res.partner.category']
        for xid in self._TYPE_TAGS.values():
            type_tags |= self.env.ref(xid, raise_if_not_found=False) or self.env['res.partner.category']
        keep = [t._origin.id or t.id for t in self.category_ids if (t._origin.id or t.id) not in type_tags.ids]
        self.category_ids = [(6, 0, keep + self._default_type_tags(self.party_type).ids)]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('category_ids') or vals['category_ids'] in ([(6, 0, [])], [[6, 0, []]]):
                ptype = vals.get('party_type') or self.env.context.get('default_party_type') or 'subcontractor'
                vals['category_ids'] = [(6, 0, self._default_type_tags(ptype).ids)]
        return super().create(vals_list)

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
