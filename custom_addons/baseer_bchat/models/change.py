"""Commit-ordered, content-free BChat change hints for one authorized user.

The cursor row is updated in the same transaction as the source operation.
PostgreSQL cannot commit a later sequence for that user before an earlier
sequence while both writers hold that row lock.  A global BIGSERIAL does not
provide that property.
"""

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..contracts import ProtocolError


_CHANGE_TOKEN = object()


class BChatChangeCursor(models.Model):
    _name = 'baseer.bchat.change.cursor'
    _description = 'BChat private per-user change cursor'
    _order = 'user_id'

    user_id = fields.Many2one('res.users', required=True, readonly=True,
                              ondelete='restrict', index=True)
    sequence = fields.Integer(required=True, readonly=True, default=0)

    _user_unique = models.Constraint('UNIQUE(user_id)', 'One BChat cursor per user.')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BChat cursor creation is unavailable.'))

    def write(self, vals):
        raise AccessError(self.env._('BChat cursors are maintained by the service.'))

    def unlink(self):
        raise AccessError(self.env._('BChat cursors cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('BChat cursors cannot be copied.'))


class BChatChange(models.Model):
    _name = 'baseer.bchat.change'
    _description = 'BChat private per-user content-free change hint'
    _order = 'sequence'

    user_id = fields.Many2one('res.users', required=True, readonly=True,
                              ondelete='restrict', index=True)
    sequence = fields.Integer(required=True, readonly=True)
    kind = fields.Selection([
        ('message', 'Message changed'),
        ('receipt', 'Message receipt changed'),
        ('room', 'Room changed'),
        ('revoked', 'Room access revoked'),
        ('task', 'Task changed'),
        ('task_revoked', 'Standalone task access revoked'),
        ('order', 'Order changed'),
    ], required=True, readonly=True)
    room_id = fields.Many2one('baseer.bchat.room', readonly=True, ondelete='restrict')
    membership_id = fields.Many2one('baseer.bchat.membership', readonly=True, ondelete='restrict')
    message_id = fields.Many2one('baseer.bchat.message', readonly=True, ondelete='restrict')
    task_id = fields.Many2one('baseer.bchat.task', readonly=True, ondelete='restrict')
    order_id = fields.Integer(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True, ondelete='restrict')

    _user_sequence_unique = models.Constraint(
        'UNIQUE(user_id, sequence)', 'A BChat change cursor must be unique per user.',
    )

    def init(self):
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bchat_change_user_seq_idx
            ON baseer_bchat_change (user_id, sequence)
        ''')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BChat change creation is unavailable.'))

    @api.model
    def _append_verified(self, user_ids, kind, *, token, room_id=None,
                         message_id=None, task_id=None, order_id=None,
                         company_id=None, memberships=None):
        """Append one hint per recipient under stable lock order.

        Call only after source ACL checks and while the source transaction is
        open.  No text, filename, price or other content belongs here.
        """
        if token is not _CHANGE_TOKEN or kind not in dict(self._fields['kind'].selection):
            raise AccessError(self.env._('A verified BChat change is required.'))
        recipients = sorted({user_id for user_id in user_ids if type(user_id) is int and user_id > 0})
        memberships = memberships or {}
        if not recipients:
            return []
        cursor_model = self.env['baseer.bchat.change.cursor']
        cursor_model.flush_model(['user_id', 'sequence'])
        for user_id in recipients:
            self.env.cr.execute('''
                INSERT INTO baseer_bchat_change_cursor (user_id, sequence, create_uid,
                                                        create_date, write_uid, write_date)
                VALUES (%s, 0, %s, NOW(), %s, NOW())
                ON CONFLICT (user_id) DO NOTHING
            ''', [user_id, self.env.uid, self.env.uid])
        self.env.cr.execute('''
            SELECT user_id FROM baseer_bchat_change_cursor
            WHERE user_id = ANY(%s) ORDER BY user_id FOR UPDATE
        ''', [recipients])
        if [row[0] for row in self.env.cr.fetchall()] != recipients:
            raise AccessError(self.env._('A BChat change cursor is unavailable.'))
        self.env.cr.execute('''
            UPDATE baseer_bchat_change_cursor
            SET sequence = sequence + 1, write_uid = %s, write_date = NOW()
            WHERE user_id = ANY(%s) RETURNING user_id, sequence
        ''', [self.env.uid, recipients])
        sequence_by_user = dict(self.env.cr.fetchall())
        if set(sequence_by_user) != set(recipients):
            raise AccessError(self.env._('A BChat change cursor is unavailable.'))
        rows = super(BChatChange, self.sudo()).create([{
                'user_id': user_id, 'sequence': sequence_by_user[user_id], 'kind': kind,
                'room_id': room_id, 'message_id': message_id,
                'membership_id': memberships.get(user_id),
                'task_id': task_id, 'order_id': order_id,
                'company_id': company_id,
            } for user_id in recipients])
        created = [(row.user_id.id, row.sequence, row.id) for row in rows]
        cursor_model.invalidate_model(['sequence'])
        # A wake-up is an optimization; durable rows above are the truth.
        # The Bus implementation queues delivery after the transaction commits.
        try:
            with self.env.cr.savepoint():
                users = self.env['res.users'].sudo().browse(recipients)
                targets = {user.id: user.partner_id for user in users}
                for user_id, sequence, _row_id in created:
                    if targets.get(user_id):
                        self.env['bus.bus']._sendone(targets[user_id], 'bchat.change',
                                                     {'sequence': sequence})
        except Exception:
            pass
        return created

    def write(self, vals):
        raise AccessError(self.env._('BChat change hints are immutable.'))

    def unlink(self):
        raise AccessError(self.env._('BChat change hints cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('BChat change hints cannot be copied.'))


class BChatChangeService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _change_publish(self, user_ids, kind, **kwargs):
        return self.env['baseer.bchat.change'].sudo()._append_verified(
            user_ids, kind, token=_CHANGE_TOKEN, **kwargs,
        )

    @api.model
    def _v2_changes(self, after=0, limit=100):
        user = self._require_user()
        if type(after) is not int or after < 0 or after > 2147483647:
            raise ProtocolError('invalid_payload', 'after must be a nonnegative cursor.')
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ProtocolError('invalid_payload', 'limit must be between 1 and 100.')
        cursor = self.env['baseer.bchat.change.cursor'].sudo().search([
            ('user_id', '=', user.id),
        ], limit=1)
        watermark = cursor.sequence if cursor else 0
        oldest = self.env['baseer.bchat.change'].sudo().search([
            ('user_id', '=', user.id),
        ], order='sequence', limit=1)
        if after > watermark or (oldest and after < oldest.sequence - 1):
            return {'api_version': 2, 'changes': [], 'next_after': 0,
                    'watermark': watermark, 'reset_required': True,
                    'snapshot_required': True}
        changes = self.env['baseer.bchat.change'].sudo().search([
            ('user_id', '=', user.id), ('sequence', '>', after),
            ('sequence', '<=', watermark),
        ], order='sequence', limit=limit + 1)
        scanned = changes[:limit]
        room_cache = {}
        visible = []
        for change in scanned:
            kind = change.kind
            room_id = change.room_id.id
            if kind in ('revoked', 'task_revoked'):
                # A member must receive this minimal erasure hint even though
                # the room ACL now correctly rejects its content.
                visible.append({'seq': change.sequence, 'kind': kind,
                                **({'room_id': room_id} if room_id else {}),
                                **({'task_id': change.task_id.id} if change.task_id else {})})
                continue
            if change.company_id and change.company_id.id not in user.company_ids.ids:
                continue
            if room_id:
                if room_id not in room_cache:
                    self.env['baseer.bchat.room']._lock_for_read(room_id)
                    room_cache[room_id] = self.env['baseer.bchat.membership'].sudo().search([
                        ('room_id', '=', room_id), ('user_id', '=', user.id),
                        ('active', '=', True),
                    ], limit=1)
                member = room_cache[room_id]
                if not member or (change.membership_id and change.membership_id.id != member.id):
                    continue
            elif kind == 'task':
                task = change.task_id
                try:
                    self._task_visible(task)
                except AccessError:
                    continue
            elif kind == 'order':
                if not self.env.registry.models.get('baseer.procurement.request'):
                    continue
                order = self.env['baseer.procurement.request'].sudo().browse(change.order_id).exists()
                if (not order or order.company_id.id not in user.company_ids.ids
                        or order.source_channel != 'bchat'
                        or not user.has_group('baseer_bchat_procurement.group_bchat_procurement_operator')):
                    continue
            hint = {'seq': change.sequence, 'kind': kind}
            for name, value in (('room_id', room_id), ('message_id', change.message_id.id),
                                ('task_id', change.task_id.id), ('order_id', change.order_id)):
                if value:
                    hint[name] = value
            visible.append(hint)
        next_after = scanned[-1].sequence if scanned else after
        return {'api_version': 2, 'changes': visible, 'next_after': next_after,
                'watermark': watermark, 'has_more': len(changes) > limit,
                'reset_required': False}

    @api.model
    def _v2_change_snapshot(self, section, before_id=None, watermark=None):
        """Page all current list entries before replaying changes above watermark.

        Message history remains on-demand. Clients must finish every section's
        pages and then apply changes after the same watermark; a single page is
        not a completed reset.
        """
        user = self._require_user()
        if section not in ('rooms', 'tasks', 'orders'):
            raise ProtocolError('invalid_payload', 'Unknown snapshot section.')
        if before_id is not None and (type(before_id) is not int or before_id <= 0):
            raise ProtocolError('invalid_payload', 'before_id must be positive.')
        if type(watermark) is not int or watermark < 0 or watermark > 2147483647:
            raise ProtocolError('invalid_payload', 'A snapshot watermark is required.')
        cursor = self.env['baseer.bchat.change.cursor'].sudo().search([
            ('user_id', '=', user.id),
        ], limit=1)
        if watermark > (cursor.sequence if cursor else 0):
            raise ProtocolError('snapshot_stale', 'Restart the BChat snapshot.', 409)
        if section == 'tasks':
            page = self._v2_tasks(before_id=before_id)
            return {**page, 'section': section, 'snapshot_watermark': watermark}
        if section == 'rooms':
            domain = [('user_id', '=', user.id), ('active', '=', True),
                      ('company_id', 'in', user.company_ids.ids)]
            if before_id:
                domain.append(('id', '<', before_id))
            found = self.env['baseer.bchat.membership'].sudo().search(
                domain, order='id desc', limit=31)
            for room_id in sorted(set(found.mapped('room_id').ids)):
                self.env['baseer.bchat.room']._lock_for_read(room_id)
            found.invalidate_recordset(['active'])
            rows = found[:30].filtered('active')
            return {'api_version': 2, 'section': section,
                    'snapshot_watermark': watermark,
                    'rooms': self._v2_room_rows(rows),
                    'next_before_id': found[29].id if len(found) > 30 else None}
        if not self.env.registry.models.get('baseer.procurement.request'):
            return {'api_version': 2, 'section': section, 'snapshot_watermark': watermark,
                    'orders': [], 'next_before_id': None}
        if not user.has_group('baseer_bchat_procurement.group_bchat_procurement_operator'):
            return {'api_version': 2, 'section': section, 'snapshot_watermark': watermark,
                    'orders': [], 'next_before_id': None}
        domain = [('source_channel', '=', 'bchat'),
                  ('company_id', 'in', user.company_ids.ids)]
        if before_id:
            domain.append(('id', '<', before_id))
        found = self.env['baseer.procurement.request'].sudo().search(
            domain, order='id desc', limit=31)
        page = found[:30]
        return {'api_version': 2, 'section': section,
                'snapshot_watermark': watermark,
                'orders': [self._order_data(order) for order in page],
                'next_before_id': page[-1].id if len(found) > 30 else None}
