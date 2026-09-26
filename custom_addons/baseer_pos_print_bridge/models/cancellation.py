import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


CANCELLATION_REASONS = [
    ('customer_cancelled', 'Customer cancelled'),
    ('wrong_order', 'Wrong order'),
    ('duplicate_order', 'Duplicate order'),
    ('unavailable_item', 'Item unavailable'),
    ('staff_error', 'Staff error'),
    ('other', 'Other'),
]


class BaseerPrintCancellation(models.Model):
    _name = 'baseer.print.cancellation'
    _description = 'Baseer Kitchen Cancellation'
    _order = 'create_date desc, id desc'
    _check_company_auto = False

    company_id = fields.Many2one('res.company', required=True, index=True, readonly=True)
    pos_config_id = fields.Many2one('pos.config', required=True, ondelete='restrict', index=True, readonly=True)
    session_id = fields.Many2one('pos.session', required=True, ondelete='restrict', index=True, readonly=True)
    order_id = fields.Many2one('pos.order', ondelete='set null', index=True, readonly=True)
    order_reference = fields.Char(required=True, readonly=True, index=True)
    requested_by = fields.Many2one('res.users', required=True, ondelete='restrict', readonly=True)
    reason_code = fields.Selection(CANCELLATION_REASONS, required=True, readonly=True, index=True)
    reason_note = fields.Char(readonly=True)
    snapshot = fields.Json(required=True, readonly=True)
    job_ids = fields.One2many('baseer.print.job', 'cancellation_id', readonly=True)

    _order_unique = models.Constraint('unique(order_id)', 'A kitchen cancellation already exists for this order.')

    @api.constrains('reason_code', 'reason_note')
    def _check_reason(self):
        for record in self:
            note = (record.reason_note or '').strip()
            if record.reason_code == 'other' and not note:
                raise ValidationError(_('A description is required when the cancellation reason is Other.'))
            if record.reason_code != 'other' and note:
                raise ValidationError(_('Only the Other cancellation reason may include a description.'))
            if len(note) > 240:
                raise ValidationError(_('The cancellation description is too long.'))

    @api.constrains('company_id', 'pos_config_id', 'session_id', 'order_id')
    def _check_links(self):
        for record in self:
            if (record.pos_config_id.company_id != record.company_id
                    or record.session_id.config_id != record.pos_config_id
                    or record.session_id.company_id != record.company_id
                    or (record.order_id and (record.order_id.company_id != record.company_id
                                              or record.order_id.config_id != record.pos_config_id
                                              or record.order_id.session_id != record.session_id))):
                raise ValidationError(_('Kitchen cancellation links do not belong to the same point of sale company.'))

    def write(self, vals):
        raise AccessError(_('Kitchen cancellation records are immutable.'))

    def unlink(self):
        raise AccessError(_('Kitchen cancellation records cannot be deleted.'))

    @api.model
    def _reason_label(self, reason_code):
        return dict(CANCELLATION_REASONS).get(reason_code, _('Other'))

    @api.model
    def _normalized_reason(self, reason_code, reason_note=False):
        if reason_code not in dict(CANCELLATION_REASONS):
            raise ValidationError(_('Choose a valid kitchen cancellation reason.'))
        if reason_note is False or reason_note is None:
            reason_note = ''
        if not isinstance(reason_note, str):
            raise ValidationError(_('The cancellation description is invalid.'))
        note = reason_note.strip()
        if reason_code == 'other' and not note:
            raise ValidationError(_('A description is required when the cancellation reason is Other.'))
        if reason_code != 'other' and note:
            raise ValidationError(_('Only the Other cancellation reason may include a description.'))
        if len(note) > 240:
            raise ValidationError(_('The cancellation description is too long.'))
        return reason_code, note

    @api.model
    def _snapshot(self, order, states, reason_code, reason_note):
        destinations = {}
        for state in states:
            key = '%s:%s' % (state.printer_id.id, state.copies)
            destination = destinations.setdefault(key, {
                'printer_id': state.printer_id.id,
                'printer_name': state.printer_id.display_name,
                'copies': state.copies,
                'lines': [],
            })
            destination['lines'].append({
                'line_uuid': state.line_uuid,
                'product_id': state.product_id.id,
                'name': state.details.get('name', state.product_id.display_name),
                'quantity': state.quantity,
            })
        return {
            'schema': 1,
            'order': {'id': order.id, 'reference': order.pos_reference or order.name or str(order.id)},
            'reason_code': reason_code,
            'reason_label': self._reason_label(reason_code),
            'reason_note': reason_note,
            'destinations': list(destinations.values()),
        }

    @api.model
    def _get_or_create_for_order(self, order, states, reason_code, reason_note):
        existing = self.sudo().search([('order_id', '=', order.id)], limit=1)
        if existing:
            return existing
        return self.sudo().create({
            'company_id': order.company_id.id,
            'pos_config_id': order.config_id.id,
            'session_id': order.session_id.id,
            'order_id': order.id,
            'order_reference': order.pos_reference or order.name or str(order.id),
            'requested_by': self.env.user.id,
            'reason_code': reason_code,
            'reason_note': reason_note or False,
            'snapshot': self._snapshot(order, states, reason_code, reason_note),
        })

    @api.model
    def _snapshot_text(self, cancellation):
        return json.dumps(cancellation.snapshot, ensure_ascii=False, sort_keys=True)
