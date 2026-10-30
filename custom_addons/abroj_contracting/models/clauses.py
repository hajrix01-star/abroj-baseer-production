from odoo import api, fields, models, Command
from odoo.exceptions import ValidationError

HELP = 'عدّل نص البند لهذا العقد؛ لا تؤثر التعديلات على العقود الأخرى.'


class Template(models.Model):
    _name = 'abroj.contract.clause.template'
    _description = 'قالب بنود العقد'
    _order = 'sequence, id'
    _rec_name = 'title_ar'

    sequence = fields.Integer(default=10, help='ترتيب ظهور البند في العقد.')
    title_ar = fields.Char(required=True, help='عنوان البند باللغة العربية.')
    title_en = fields.Char(required=True, help='عنوان البند باللغة الإنجليزية.')
    body_ar = fields.Text(required=True, help='النص الافتراضي للبند بالعربية.')
    body_en = fields.Text(required=True, help='النص الافتراضي للبند بالإنجليزية.')
    contract_type = fields.Selection([('client', 'عميل'), ('subcontract', 'باطن'), ('both', 'كلاهما')], required=True, default='both', help='العقود التي ينسخ إليها هذا البند.')
    active = fields.Boolean(default=True, help='ألغ التفعيل لإخفاء القالب دون حذفه.')
    is_default = fields.Boolean(default=True, help='ينسخ تلقائياً عند إنشاء عقد جديد.')
    legacy_id = fields.Many2one('abroj.contracting.clause', copy=False, help='مرجع القالب السابق لحفظ البيانات عند الترقية.')

    def init(self):
        # Keep legacy rows and XML IDs intact; migrate authored edits exactly once.
        self.env.cr.execute("""INSERT INTO abroj_contract_clause_template
            (sequence,title_ar,title_en,body_ar,body_en,contract_type,active,is_default,legacy_id)
            SELECT sequence, COALESCE(NULLIF(trim(split_part(name,'/',2)), ''), name), trim(split_part(name,'/',1)),
                text_ar,text_en,CASE WHEN kind='client' THEN 'client' ELSE 'subcontract' END,
                active,true,id FROM abroj_contracting_clause c
            WHERE NOT COALESCE(c.template_migrated, false)
              AND NOT EXISTS (SELECT 1 FROM abroj_contract_clause_template t WHERE t.legacy_id=c.id)""")

        self.env.cr.execute("""UPDATE ir_model_data d SET
            model='abroj.contract.clause.template', res_id=t.id
            FROM abroj_contract_clause_template t
            WHERE d.model='abroj.contracting.clause' AND d.res_id=t.legacy_id""")
        self.env.cr.execute("""UPDATE abroj_contracting_clause c SET template_migrated=true
            WHERE EXISTS (SELECT 1 FROM abroj_contract_clause_template t WHERE t.legacy_id=c.id)""")

    @api.model
    def migrate_defaults(self):
        self.check_access('create')
        self.init()

    def line_values(self):
        return {key: self[key] for key in ('sequence', 'title_ar', 'title_en', 'body_ar', 'body_en')}


class Line(models.Model):
    _name = 'abroj.contract.clause.line'
    _description = 'بند خاص بالعقد'
    _order = 'sequence, id'
    sequence = fields.Integer(default=10, help='اسحب لتغيير ترتيب البند.')
    title_ar = fields.Char(required=True, help=HELP)
    title_en = fields.Char(required=True, help=HELP)
    body_ar = fields.Text(required=True, help=HELP)
    body_en = fields.Text(required=True, help=HELP)
    project_id = fields.Many2one('project.project', ondelete='cascade', index=True, help='عقد العميل صاحب البند.')
    subcontractor_id = fields.Many2one('abroj.contracting.subcontractor', ondelete='cascade', index=True, help='عقد الباطن صاحب البند.')

    company_id = fields.Many2one('res.company', compute='_compute_company', store=True, help='شركة العقد لعزل صلاحيات الوصول.')

    @api.depends('project_id.company_id', 'subcontractor_id.company_id')
    def _compute_company(self):
        for line in self:
            line.company_id = line.project_id.company_id or line.subcontractor_id.company_id

    @api.constrains('project_id', 'subcontractor_id')
    def _check_owner(self):
        for line in self:
            if bool(line.project_id) == bool(line.subcontractor_id):
                raise ValidationError('يجب ربط البند بعقد واحد فقط.')

    def report_text(self, field, language):
        return self['title_' + language]

    text_ar = fields.Text(related='body_ar', string='نص التقرير العربي', help=HELP)
    text_en = fields.Text(related='body_en', string='نص التقرير الإنجليزي', help=HELP)


class Defaults(models.AbstractModel):
    _name = 'abroj.contract.clause.defaults'
    _description = 'نسخ البنود الافتراضية'

    def _default_clause_commands(self):
        kind = 'client' if self._name == 'project.project' else 'subcontract'
        return [Command.create(t.line_values()) for t in self.env['abroj.contract.clause.template'].search([
            ('is_default', '=', True), ('contract_type', 'in', [kind, 'both'])])]

    @api.model_create_multi
    def create(self, vals_list):
        values = []
        for vals in vals_list:
            vals = dict(vals)
            if 'clause_line_ids' not in vals:
                vals['clause_line_ids'] = self._default_clause_commands()
            values.append(vals)
        return super().create(values)

    def action_reload_default_clauses(self):
        for record in self:
            record.clause_line_ids = [Command.clear()] + record._default_clause_commands()
        return True


class Project(models.Model):
    _name = 'project.project'
    _inherit = ['project.project', 'abroj.contract.clause.defaults']
    clause_line_ids = fields.One2many('abroj.contract.clause.line', 'project_id', string='بنود عقد العميل', copy=True, help=HELP)


class Subcontract(models.Model):
    _name = 'abroj.contracting.subcontractor'
    _inherit = ['abroj.contracting.subcontractor', 'abroj.contract.clause.defaults']
    clause_line_ids = fields.One2many('abroj.contract.clause.line', 'subcontractor_id', string='بنود عقد الباطن', copy=True, help=HELP)


class Voucher(models.Model):
    _inherit = 'abroj.contracting.voucher'

    def amount_in_words(self, language):
        self.ensure_one()
        if language == 'ar':
            # num2words handles Arabic currency grammar and fractions without an
            # installed UI language or untranslated currency labels.
            from num2words import num2words
            words = num2words(self.currency_id.round(self.amount), lang='ar',
                              to='currency', currency=self.currency_id.name)
            return 'فقط %s لا غير' % words
        words = self.currency_id.with_context(lang='en_US').amount_to_text(self.amount)
        if self.currency_id.name == 'SAR':
            # Odoo's singular currency label is not the approved voucher wording.
            words = words.replace(' Saudi Riyals', '').replace(' Saudi Riyal', '').replace(' Riyals', '').replace(' Riyal', '')
            return '%s Saudi Riyals only' % words.capitalize()
        return '%s only' % words
