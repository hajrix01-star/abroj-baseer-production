"""Assign operational ticket numbers independently from native and fiscal references."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


_ORDER_FIELDS = ('baseer_ticket_number', 'baseer_ticket_session_id', 'baseer_ticket_label')
_SESSION_FIELDS = ('baseer_ticket_enabled', 'baseer_ticket_last_number')


class PosSession(models.Model):
    _inherit = 'pos.session'

    # No true field default: installing on an open session must keep its legacy tickets.
    baseer_ticket_enabled = fields.Boolean(readonly=True, copy=False)
    baseer_ticket_last_number = fields.Integer(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([
            dict(vals, baseer_ticket_enabled=True, baseer_ticket_last_number=0)
            for vals in vals_list
        ])

    def write(self, vals):
        if any(name in vals for name in _SESSION_FIELDS):
            raise AccessError(_('Session ticket counters are assigned by the server.'))
        return super().write(vals)

    @api.model
    def _load_pos_data_fields(self, config):
        names = super()._load_pos_data_fields(config)
        return list(dict.fromkeys([*names, 'baseer_ticket_enabled'])) if names else names


class PosOrder(models.Model):
    _inherit = 'pos.order'

    baseer_ticket_number = fields.Integer(readonly=True, copy=False)
    baseer_ticket_session_id = fields.Many2one('pos.session', readonly=True, copy=False, ondelete='restrict')
    baseer_ticket_label = fields.Char(compute='_compute_baseer_ticket_label')
    _baseer_session_ticket_unique = models.UniqueIndex(
        '(baseer_ticket_session_id, baseer_ticket_number) WHERE baseer_ticket_number > 0',
        'A ticket number must be unique within its session.',
    )

    @api.depends('baseer_ticket_number', 'baseer_ticket_session_id')
    def _compute_baseer_ticket_label(self):
        for order in self:
            order.baseer_ticket_label = (
                f'{order.baseer_ticket_session_id.id}-{order.baseer_ticket_number}'
                if order.baseer_ticket_number else False
            )

    @api.model
    def _load_pos_data_fields(self, config):
        names = super()._load_pos_data_fields(config)
        # An empty native list means all readable fields.
        return list(dict.fromkeys([*names, *_ORDER_FIELDS])) if names else names

    @api.model
    def _process_order(self, order, existing_order):
        # Reconnected clients can echo stale display fields. Never accept them as input.
        for name in _ORDER_FIELDS:
            order.pop(name, None)
        return super()._process_order(order, existing_order)

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            values = {key: value for key, value in vals.items() if key not in _ORDER_FIELDS}
            if 'session_id' not in values:
                values['session_id'] = self.default_get(['session_id']).get('session_id')
            session = self.env['pos.session'].browse(values['session_id'])
            # Preserve whether this order started in the new numbering scheme. In
            # particular, moving an old saved draft must not renumber it.
            values.update(baseer_ticket_number=0,
                          baseer_ticket_session_id=session.id if session.baseer_ticket_enabled else False)
            prepared.append(values)
        return super().create(prepared)

    def write(self, vals):
        if any(name in vals for name in _ORDER_FIELDS):
            raise AccessError(_('Order ticket numbers are assigned by the server.'))
        return super().write(vals)

    def _baseer_assign_session_ticket(self):
        # Called only after one or more real lines have been attached to these orders.
        pending = self.filtered(lambda order: order.baseer_ticket_session_id and not order.baseer_ticket_number)
        for order in pending.sorted(lambda rec: (rec.session_id.id, rec.id)):
            session = order.session_id
            if not session.baseer_ticket_enabled or session.state == 'closed':
                continue
            if order.company_id != session.company_id or (not self.env.su and session.company_id not in self.env.companies):
                raise AccessError(_('The ticket does not belong to an allowed session company.'))
            order.flush_recordset(['baseer_ticket_number', 'baseer_ticket_session_id'])
            self.env.cr.execute("""
                SELECT id FROM pos_order WHERE id = %s AND COALESCE(baseer_ticket_number, 0) = 0
                FOR NO KEY UPDATE
            """, [order.id])
            if not self.env.cr.fetchone():
                continue
            session.flush_recordset(['baseer_ticket_last_number'])
            # PostgreSQL serializes cashiers on this session only. Odoo retries a
            # serialization conflict with a fresh transaction; rollback restores the counter.
            self.env.cr.execute("""
                UPDATE pos_session SET baseer_ticket_last_number = baseer_ticket_last_number + 1
                WHERE id = %s RETURNING baseer_ticket_last_number
            """, [session.id])
            number, = self.env.cr.fetchone()
            self.env.cr.execute("""
                UPDATE pos_order SET baseer_ticket_number = %s, baseer_ticket_session_id = %s
                WHERE id = %s
            """, [number, session.id, order.id])
            session.invalidate_recordset(['baseer_ticket_last_number'])
            order.invalidate_recordset(list(_ORDER_FIELDS))
            order.modified(['baseer_ticket_number', 'baseer_ticket_session_id'])


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.order_id._baseer_assign_session_ticket()
        return lines

    def write(self, vals):
        result = super().write(vals)
        if vals.get('order_id'):
            self.order_id._baseer_assign_session_ticket()
        return result
