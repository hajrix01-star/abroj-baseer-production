"""Explicit company and date scoped presentation mappings, never journal edits."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from psycopg2 import IntegrityError


class NoorixChannelMapping(models.Model):
    _name = 'baseer.pl.noorix.channel.mapping'
    _description = 'Noorix payment channel display mapping'
    _order = 'company_id, date_from, source_channel, id'

    company_id = fields.Many2one('res.company', string='الشركة', required=True, default=lambda self: self.env.company, index=True)
    source_channel = fields.Selection([
        ('cash', 'نقدي'), ('bank', 'بنك'), ('hunger', 'هنقرستيشن'),
        ('keeta', 'كيتا'), ('jahez', 'جاهز'),
    ], string='قناة نوركس', required=True, index=True)
    payment_method_id = fields.Integer(string='رقم طريقة الدفع في نقطة البيع', required=True)
    date_from = fields.Date(string='من تاريخ', required=True, index=True)
    date_to = fields.Date(string='إلى تاريخ', required=True, index=True)
    approval_reference = fields.Char(required=True, string='مرجع الموافقة والدليل')
    revoked = fields.Boolean(string='إلغاء الربط', default=False)
    revocation_reason = fields.Char(string='سبب الإلغاء')
    revoked_by_id = fields.Many2one('res.users', string='ألغاه', readonly=True)
    revoked_at = fields.Datetime(string='تاريخ الإلغاء', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if any(any(vals.get(key) for key in ('revoked', 'revocation_reason', 'revoked_by_id', 'revoked_at')) for vals in vals_list):
            raise AccessError(_('Create the approval before revoking it.'))
        try:
            with self.env.cr.savepoint():
                mappings = super().create(vals_list)
                for mapping in mappings:
                    self.env.cr.execute('''INSERT INTO baseer_pl_noorix_mapping_day
                        (mapping_id, company_id, source_channel, payment_method_id, day)
                        SELECT %s, %s, %s, %s, generate_series(%s::date,%s::date,'1 day')::date''',
                        [mapping.id, mapping.company_id.id, mapping.source_channel,
                         mapping.payment_method_id, mapping.date_from, mapping.date_to])
        except IntegrityError:
            raise ValidationError(_('An overlapping channel or payment method mapping already exists.')) from None
        return mappings

    def write(self, vals):
        if (set(vals) != {'revoked', 'revocation_reason'} or vals.get('revoked') is not True
                or not (vals.get('revocation_reason') or '').strip() or any(self.mapped('revoked'))):
            raise AccessError(_('Approvals are immutable. Revoke with a reason and create a replacement.'))
        result = super().write({**vals, 'revoked_by_id': self.env.user.id, 'revoked_at': fields.Datetime.now()})
        self.env.cr.execute('DELETE FROM baseer_pl_noorix_mapping_day WHERE mapping_id=ANY(%s)', [self.ids])
        return result

    @api.constrains('company_id', 'source_channel', 'payment_method_id', 'date_from', 'date_to', 'approval_reference')
    def _check_mapping(self):
        for company in self.mapped('company_id').sorted('id'):
            self.env.cr.execute('SELECT id FROM res_company WHERE id=%s FOR UPDATE', [company.id])
        for mapping in self:
            if (mapping.payment_method_id <= 0 or mapping.date_from > mapping.date_to
                    or (mapping.date_to - mapping.date_from).days > 365
                    or not (mapping.approval_reference or '').strip()):
                raise ValidationError(_('Enter a payment method, a period of at most 366 days and an approval reference.'))
            if 'pos.payment.method' not in self.env:
                raise ValidationError(_('POS payment methods are not available.'))
            Method = self.env['pos.payment.method'].with_context(active_test=False)
            method = Method.search([('id', '=', mapping.payment_method_id),
                                    ('company_id', '=', mapping.company_id.id)], limit=1)
            if not method:
                raise ValidationError(_('Select a payment method available in this company.'))
            method.check_access('read')
            self.flush_model(['company_id', 'source_channel', 'payment_method_id', 'date_from', 'date_to', 'revoked'])
            self.env.cr.execute('''SELECT 1 FROM baseer_pl_noorix_channel_mapping
                WHERE company_id=%s AND id<>%s AND NOT revoked AND date_from<=%s AND date_to>=%s
                AND (source_channel=%s OR payment_method_id=%s) LIMIT 1''',
                [mapping.company_id.id, mapping.id, mapping.date_to, mapping.date_from,
                 mapping.source_channel, mapping.payment_method_id])
            if self.env.cr.fetchone():
                raise ValidationError(_('An overlapping channel or payment method mapping already exists.'))


class NoorixChannelMappingDay(models.Model):
    _name = 'baseer.pl.noorix.mapping.day'
    _description = 'Private non-overlapping Noorix mapping dates'
    _log_access = False

    mapping_id = fields.Many2one('baseer.pl.noorix.channel.mapping', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    source_channel = fields.Char(required=True)
    payment_method_id = fields.Integer(required=True)
    day = fields.Date(required=True)
    _channel_day_unique = models.Constraint('UNIQUE(company_id, source_channel, day)',
                                            'The source channel already has an approved mapping on this day.')
    _method_day_unique = models.Constraint('UNIQUE(company_id, payment_method_id, day)',
                                           'The payment method already has an approved mapping on this day.')
