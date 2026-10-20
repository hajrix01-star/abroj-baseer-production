from odoo import api, models
from odoo.exceptions import AccessError, ValidationError
from .. import contracts, storage_policy


class BWorkStorage(models.AbstractModel):
    _name = 'baseer.bwork.storage'
    _description = 'BWork authorized read-only attachment inventory'

    @api.model
    def _inventory(self, company_id, limit=1000):
        contracts.require_released()
        scoped = self.env['baseer.bwork.service']._company_scope(company_id)
        scoped.env['baseer.bwork.service']._require_room_manager()
        if type(limit) is not int or not 1 <= limit <= 5000:
            raise ValidationError(self.env._('Choose a bound from 1 through 5000.'))
        attachments = scoped.env['ir.attachment'].search([('company_id', '=', company_id), ('type', '=', 'binary')], order='id', limit=limit + 1)
        records = []
        for attachment in attachments[:limit]:
            try:
                attachment.check_access('read')
                if attachment.res_model and attachment.res_id:
                    if attachment.res_model not in scoped.env:
                        continue
                    source = scoped.env[attachment.res_model].browse(attachment.res_id).exists()
                    if not source:
                        continue
                    source.check_access('read')
            except AccessError:
                continue
            purpose = None
            if attachment.res_model == 'discuss.channel' and attachment.res_id:
                binding = scoped.env['baseer.bwork.binding'].search([('channel_id', '=', attachment.res_id), ('company_id', '=', company_id)], limit=1)
                purpose = binding.purpose if binding else None
            records.append({'attachment_id': attachment.id, 'company_id': company_id,
                            'res_model': attachment.res_model, 'res_id': attachment.res_id,
                            'mimetype': attachment.mimetype, 'size': attachment.file_size,
                            'checksum': attachment.checksum, 'purpose': purpose,
                            'held': bool(attachment.baseer_invoice_source_held) if 'baseer_invoice_source_held' in attachment._fields else False})
        return storage_policy.inventory(records, company_id, complete=len(attachments) <= limit)
