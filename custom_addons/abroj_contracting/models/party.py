import re
import unicodedata

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_AR_MARKS = re.compile('[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]')
_AR_MAP = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ة': 'ه', 'ى': 'ي', 'ؤ': 'و', 'ئ': 'ي'})


def normalize_ar(text):
    """Search key: no diacritics/tatweel, unified alef forms, ة→ه, ى→ي, case-folded."""
    text = unicodedata.normalize('NFKD', str(text or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = _AR_MARKS.sub('', text).translate(_AR_MAP).casefold()
    return ' '.join(text.split())


PARTY_TYPES = [('citizen', 'مواطن'), ('client', 'عميل'), ('subcontractor', 'مقاول باطن'), ('supplier', 'مورد')]


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
    company_id = fields.Many2one('res.company', string='الشركة', required=True, default=lambda self: self.env['res.company']._abroj_company())
    active = fields.Boolean('نشط', default=True)
    # Legacy contact tags: kept for existing data only; party_type is the sole classification.
    category_ids = fields.Many2many('res.partner.category', 'abroj_contracting_party_category_rel', 'party_id', 'category_id', string='الوسوم',
                                    domain=[('abroj_party_tag', '=', True)])

    _rec_names_search = ['name', 'phone']

    @api.depends('name', 'party_type')
    @api.depends_context('abroj_party_show_type')
    def _compute_display_name(self):
        labels = dict(self._fields['party_type']._description_selection(self.env))
        show = self.env.context.get('abroj_party_show_type')
        for party in self:
            party.display_name = f"{party.name or ''} · {labels.get(party.party_type, '')}" if show and party.party_type else (party.name or '')

    @api.model
    def _abroj_search_ids(self, term, domain=None, limit=None):
        """Ids of parties whose name matches term (Arabic-normalized) or whose phone contains it."""
        words = normalize_ar(term).split()
        digits = re.sub(r'\D', '', term or '')
        ids = []
        for party in self.search_fetch(list(domain or []), ['name', 'phone']):
            name = normalize_ar(party.name)
            if (words and all(w in name for w in words)) or (len(digits) >= 3 and digits in re.sub(r'\D', '', party.phone or '')):
                ids.append(party.id)
                if limit and len(ids) >= limit:
                    break
        return ids

    @api.model
    def _search_display_name(self, operator, value):
        # Many2one autocomplete: Arabic-normalized name match, plus phone.
        if operator == 'ilike' and isinstance(value, str) and value.strip():
            return ['|', '|', ('name', 'ilike', value), ('phone', 'ilike', value), ('id', 'in', self._abroj_search_ids(value, [], limit=1000))]
        return super()._search_display_name(operator, value)

    _name_type_company_uniq = models.Constraint('unique(name, party_type, company_id)', 'هذا الطرف موجود مسبقاً بنفس النوع.')

    @api.model
    @api.model_create_multi
    def create(self, vals_list):
        self.env['res.company']._abroj_force_company(vals_list)
        return super().create(vals_list)

    def name_create(self, name):
        # Quick-create from a Many2one: reuse an existing party with the same name.
        name = (name or '').strip()
        if not name:
            raise ValidationError('اسم الطرف مطلوب.')
        party_type = self.env.context.get('default_party_type') or 'subcontractor'
        company_id = self.env['res.company']._abroj_company().id
        existing = self.search([('name', '=', name), ('party_type', '=', party_type), ('company_id', '=', company_id)], limit=1)
        if existing:
            return existing.id, existing.display_name
        return super().name_create(name)


PARTY_TAG_XMLIDS = ('abroj_contracting.party_tag_subcontractors', 'abroj_contracting.party_tag_clients',
                    'abroj_contracting.party_tag_suppliers', 'abroj_contracting.party_tag_contracting')


class PartnerCategory(models.Model):
    """Flags the contact tags relevant to contract parties (not stored)."""
    _inherit = 'res.partner.category'

    abroj_party_tag = fields.Boolean('وسم أطراف العقود', compute='_compute_abroj_party_tag', search='_search_abroj_party_tag')

    @api.model
    def _abroj_party_tag_ids(self):
        """The 4 seeded party tags plus any tag already used on a contract party."""
        ids = set()
        for xid in PARTY_TAG_XMLIDS:
            tag = self.env.ref(xid, raise_if_not_found=False)
            if tag:
                ids.add(tag.id)
        self.env['abroj.contracting.party'].flush_model(['category_ids'])
        self.env.cr.execute('SELECT DISTINCT category_id FROM abroj_contracting_party_category_rel')
        ids.update(row[0] for row in self.env.cr.fetchall())
        return list(ids)

    def _compute_abroj_party_tag(self):
        allowed = set(self._abroj_party_tag_ids())
        for tag in self:
            tag.abroj_party_tag = tag.id in allowed

    def _search_abroj_party_tag(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        positive = (operator == '=') == value
        return [('id', 'in' if positive else 'not in', self._abroj_party_tag_ids())]
