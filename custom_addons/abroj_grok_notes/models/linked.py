from odoo import fields, models


class NoteLinkMixin(models.AbstractModel):
    _name = 'grok.note.link.mixin'
    _description = 'Grok Note Link'

    grok_note_count = fields.Integer(compute='_compute_grok_note_count')

    def _compute_grok_note_count(self):
        notes = self.env['grok.note']
        for record in self:
            record.grok_note_count = notes.search_count([('res_model', '=', record._name), ('res_id', '=', record.id)])

    def action_open_grok_notes(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('abroj_grok_notes.action_grok_notes')
        action.update(domain=[('res_model', '=', self._name), ('res_id', '=', self.id)],
                      context={'default_res_model': self._name, 'default_res_id': self.id})
        return action


class Partner(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'grok.note.link.mixin']


class Project(models.Model):
    _name = 'project.project'
    _inherit = ['project.project', 'grok.note.link.mixin']
