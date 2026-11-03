from datetime import datetime, timezone
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import AccessError, MissingError, ValidationError

LINKABLE_MODELS = ['res.partner', 'project.project', 'account.move', 'abroj.contracting.voucher']
COLORS = [(key, key.title()) for key in ('default', 'red', 'orange', 'yellow', 'green', 'teal', 'blue', 'darkblue', 'purple', 'pink', 'brown', 'gray')]


def _utc_naive(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class GrokNoteLabel(models.Model):
    _name = 'grok.note.label'
    _description = 'Grok Note Label'

    name = fields.Char(required=True)
    color = fields.Integer()


class GrokNoteItem(models.Model):
    _name = 'grok.note.item'
    _description = 'Grok Note Item'
    _order = 'sequence, id'

    note_id = fields.Many2one('grok.note', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    done = fields.Boolean()
    sequence = fields.Integer(default=10)


class GrokNote(models.Model):
    _name = 'grok.note'
    _description = 'Grok Note'
    _order = 'pinned desc, write_date desc, id desc'

    title = fields.Char()
    body = fields.Text()
    is_list = fields.Boolean()
    item_ids = fields.One2many('grok.note.item', 'note_id', order='sequence, id')
    item_count = fields.Integer(compute='_compute_item_counts')
    done_count = fields.Integer(compute='_compute_item_counts')
    color = fields.Selection(COLORS, default='default')
    pinned = fields.Boolean()
    active = fields.Boolean(default=True)
    label_ids = fields.Many2many('grok.note.label')
    res_model = fields.Char(index=True)
    res_id = fields.Many2oneReference(model_field='res_model')
    res_name = fields.Char(compute='_compute_res_name')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user)
    grok_uid = fields.Char(required=True, index=True, default=lambda self: str(uuid4()), copy=False)
    _grok_uid_unique = models.Constraint('unique(grok_uid)', 'Grok UID must be unique.')

    @api.depends('item_ids.done')
    def _compute_item_counts(self):
        for note in self:
            note.item_count = len(note.item_ids)
            note.done_count = len(note.item_ids.filtered('done'))

    @api.model
    def _get_linkable_models(self):
        return [name for name in LINKABLE_MODELS if name in self.env]

    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        for note in self:
            note.res_name = False
            if note.res_model in note._get_linkable_models() and note.res_id:
                try:
                    record = self.env[note.res_model].browse(note.res_id).exists()
                    if record:
                        note.res_name = record.display_name
                except (AccessError, MissingError):
                    pass

    @api.constrains('res_model')
    def _check_res_model(self):
        for note in self:
            if note.res_model and note.res_model not in note._get_linkable_models():
                raise ValidationError('This model cannot be linked to a Grok note.')

    def link_to(self, record):
        record.ensure_one()
        if record._name not in self._get_linkable_models():
            raise ValidationError('This model cannot be linked to a Grok note.')
        self.write({'res_model': record._name, 'res_id': record.id})
        return True

    @api.model
    def grok_upsert(self, vals_list):
        result = []
        for payload in vals_list:
            uid = payload.get('grok_uid')
            if not uid:
                raise ValidationError('grok_uid is required.')
            note = self.with_context(active_test=False).search([('grok_uid', '=', uid)], limit=1)
            updated_at = payload.get('updated_at')
            if note and (not updated_at or _utc_naive(updated_at) <= note.write_date):
                action = 'skipped'
            else:
                vals = {key: payload[key] for key in ('grok_uid', 'title', 'body', 'is_list', 'color', 'pinned', 'active', 'res_model', 'res_id') if key in payload}
                if 'archived' in payload and 'active' not in payload:
                    vals['active'] = not payload['archived']
                if 'labels' in payload:
                    labels = self.env['grok.note.label']
                    for name in payload['labels']:
                        label = labels.search([('name', '=', name)], limit=1)
                        labels |= label or labels.create({'name': name})
                    vals['label_ids'] = [(6, 0, labels.ids)]
                if 'items' in payload:
                    vals['item_ids'] = [(5, 0, 0)] + [(0, 0, {key: item[key] for key in ('name', 'done', 'sequence') if key in item}) for item in payload['items']]
                if note:
                    note.write(vals)
                    action = 'updated'
                else:
                    note = self.create(vals)
                    action = 'created'
            result.append({'grok_uid': uid, 'id': note.id, 'write_date': fields.Datetime.to_string(note.write_date), 'action': action})
        return result
