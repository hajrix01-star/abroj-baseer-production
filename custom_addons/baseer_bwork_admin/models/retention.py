"""Explicit OFF-by-default retention; no source ACL or automatic role grants."""
from datetime import timedelta, timezone as datetime_timezone
import json

from odoo import api, fields, models, Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL
from odoo.tools.constants import GC_UNLINK_LIMIT
from zoneinfo import available_timezones
from psycopg2.errors import UniqueViolation

from odoo.addons.baseer_bchat.models.retention import _RETENTION_TOKEN, _READY_KEY
from odoo.addons.baseer_bchat.contracts import ProtocolError
from .. import retention_contracts as rules

_ADMIN_TOKEN = object()
_MODES = [('attachments', 'Attachments only'), ('messages_and_attachments', 'Messages and attachments')]
_MANUAL_MODES = _MODES + [('expired_uploads', 'Expired unlinked uploads')]
_SCOPES = [('company', 'All company rooms'), ('rooms', 'Selected rooms')]
_TZ = [(tz, tz) for tz in sorted(available_timezones())]


def _guard(model, company):
    company_id = company.id if hasattr(company, 'id') else company
    return model.env['baseer.bchat.service']._retention_guard(company_id)


def _record_guard(model, table):
    # Never read company_id through ORM inside check_access: fetch recursively
    # invokes check_access. Also recheck cached/exported record scope via SQL.
    _guard(model, model.env.company)
    ids = [rid for rid in model.ids if type(rid) is int]
    if ids:
        model.env.cr.execute(SQL('SELECT DISTINCT company_id FROM %s WHERE id=ANY(%s)', SQL.identifier(table), ids))
        for (company_id,) in model.env.cr.fetchall():
            _guard(model, company_id)


def _scoped_domain(model, domain):
    user = _guard(model, model.env.company)
    return [('company_id', 'in', sorted(set(user.company_ids.ids) & set(model.env.companies.ids)))] + list(domain)


class RetentionPolicy(models.Model):
    _name = 'baseer.bwork.retention.policy'
    _description = 'BWork server retention policy'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict', index=True)
    scope_mode = fields.Selection(_SCOPES, required=True, default='company')
    room_ids = fields.Many2many('baseer.bchat.room', 'bwork_retention_policy_room_rel', 'policy_id', 'room_id')
    enabled = fields.Boolean(default=False, copy=False)
    mode = fields.Selection(_MODES, required=True, default='attachments')
    retention_days = fields.Integer(default=30, required=True)
    schedule_hour = fields.Selection([('%02d' % i, '%02d' % i) for i in range(24)], default='02', required=True)
    schedule_minute = fields.Selection([('%02d' % i, '%02d' % i) for i in range(60)], default='00', required=True)
    timezone = fields.Selection(_TZ, default='Asia/Riyadh', required=True)
    owner_user_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user, readonly=True, ondelete='restrict')
    revision = fields.Integer(default=1, readonly=True)
    next_run_at = fields.Datetime(readonly=True)
    last_run_at = fields.Datetime(readonly=True)
    last_status = fields.Char(readonly=True)
    last_local_date = fields.Date(readonly=True)
    readiness_status = fields.Selection([('not_ready', 'Not activated'), ('ready', 'Activated')], compute='_compute_readiness')
    ack_clients_updated = fields.Boolean(default=False, copy=False)
    ack_legacy_offline = fields.Boolean(default=False, copy=False)

    _company_unique = models.Constraint('UNIQUE(company_id)', 'One server retention policy per company.')

    @api.depends('company_id')
    def _compute_name(self):
        for row in self:
            _guard(row, row.company_id)
            row.name = self.env._('BWork retention — %s', row.company_id.name)

    def _compute_readiness(self):
        for row in self:
            _guard(row, row.company_id)
            row.readiness_status = 'ready' if self.env['baseer.bchat.service']._retention_ready() else 'not_ready'

    def _validate(self):
        for row in self:
            _guard(row, row.company_id)
            if (type(row.retention_days) is not int or not 1 <= row.retention_days <= 36500
                    or row.scope_mode == 'rooms' and not row.room_ids
                    or any(room.company_id != row.company_id for room in row.room_ids)):
                raise ValidationError('invalid_retention_scope_or_days')
            rules.next_slot(fields.Datetime.now(), row.schedule_hour, row.schedule_minute, row.timezone)

    @api.model_create_multi
    def create(self, values):
        if self.env.su:
            raise AccessError('An individual retention actor is required.')
        clean = []
        allowed = {'company_id', 'scope_mode', 'room_ids', 'enabled', 'mode', 'retention_days',
                   'schedule_hour', 'schedule_minute', 'timezone', 'ack_clients_updated', 'ack_legacy_offline'}
        for vals in values:
            if set(vals) - allowed:
                raise AccessError('Policy state is maintained by the retention service.')
            _guard(self, vals.get('company_id', self.env.company.id))
            candidate = self.new(dict(vals, owner_user_id=self.env.uid))
            candidate._validate()
            clean.append(dict(vals, owner_user_id=self.env.uid, revision=1))
        rows = super().create(clean)
        for row in rows:
            row._service_write({'next_run_at': rules.next_slot(fields.Datetime.now(), row.schedule_hour, row.schedule_minute, row.timezone)}, _ADMIN_TOKEN)
            self.env['baseer.bwork.retention.audit']._append('policy_created', row.company_id.id, policy=row, token=_ADMIN_TOKEN)
        return rows

    def write(self, vals):
        editable = {'scope_mode', 'room_ids', 'enabled', 'mode', 'retention_days', 'schedule_hour',
                    'schedule_minute', 'timezone', 'ack_clients_updated', 'ack_legacy_offline'}
        if set(vals) - editable:
            raise AccessError('Policy identity and execution state are immutable.')
        for row in self:
            _guard(row, row.company_id)
            self.env.cr.execute('SELECT id FROM baseer_bwork_retention_policy WHERE id=%s FOR UPDATE', [row.id])
            row.invalidate_recordset()
            test = self.new({name: row[name] for name in ('company_id', 'scope_mode', 'room_ids', 'enabled', 'mode', 'retention_days', 'schedule_hour', 'schedule_minute', 'timezone')})
            test.update(vals)
            test._validate()
            update = dict(vals, revision=row.revision + 1, owner_user_id=self.env.uid,
                          next_run_at=rules.next_slot(fields.Datetime.now(), test.schedule_hour, test.schedule_minute, test.timezone))
            super(RetentionPolicy, row).write(update)
            self.env['baseer.bwork.retention.audit']._append('policy_changed', row.company_id.id, policy=row, token=_ADMIN_TOKEN)
        return True

    def _service_write(self, vals, token):
        if token is not _ADMIN_TOKEN:
            raise AccessError('Verified retention operation required.')
        return super().write(vals)

    def check_access(self, operation):
        _record_guard(self, 'baseer_bwork_retention_policy')
        return super().check_access(operation)

    def _search(self, domain, *args, **kwargs):
        return super()._search(_scoped_domain(self, domain), *args, **kwargs)

    def unlink(self):
        raise AccessError('Retention policies are disabled, not deleted.')

    def action_disable(self):
        self.write({'enabled': False})
        return True

    def _readiness_actor(self):
        user = self.env['baseer.bchat.service']._require_user()
        if user != self.env.ref('base.user_admin') or not user.has_group('base.group_system'):
            raise AccessError('Only the existing system owner can acknowledge global readiness.')
        for row in self:
            _guard(row, row.company_id)

    def action_confirm_readiness(self):
        self.ensure_one()
        self._readiness_actor()
        if not self.ack_clients_updated or not self.ack_legacy_offline:
            raise ValidationError('Acknowledge updated clients and legacy/offline/exported-copy limits.')
        self.env['ir.config_parameter'].sudo().set_param(_READY_KEY, '1')
        self.env['baseer.bwork.retention.audit']._append('readiness_activated', self.company_id.id, policy=self, token=_ADMIN_TOKEN)
        self.invalidate_recordset(['readiness_status'])
        return True

    def action_revoke_readiness(self):
        self.ensure_one()
        self._readiness_actor()
        self.env['ir.config_parameter'].sudo().set_param(_READY_KEY, '0')
        self.env['baseer.bwork.retention.audit']._append('readiness_revoked', self.company_id.id, policy=self, token=_ADMIN_TOKEN)
        self.invalidate_recordset(['readiness_status'])
        return True


class RetentionWizard(models.TransientModel):
    _name = 'baseer.bwork.retention.wizard'
    _description = 'Preview scoped BWork content erasure'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    scope_mode = fields.Selection(_SCOPES, required=True, default='company')
    room_ids = fields.Many2many('baseer.bchat.room', 'bwork_retention_wizard_room_rel', 'wizard_id', 'room_id')
    mode = fields.Selection(_MANUAL_MODES, required=True, default='attachments')
    cutoff_mode = fields.Selection([('before_date', 'Before date'), ('older_than_days', 'Older than days')], default='older_than_days', required=True)
    cutoff_date = fields.Date()
    older_than_days = fields.Integer(default=30)
    timezone = fields.Selection(_TZ, default='Asia/Riyadh', required=True)

    @api.model_create_multi
    def create(self, values):
        for vals in values:
            _guard(self, vals.get('company_id', self.env.company.id))
        return super().create(values)

    def write(self, vals):
        _record_guard(self, 'baseer_bwork_retention_wizard')
        if 'company_id' in vals:
            _guard(self, vals['company_id'])
        return super().write(vals)

    def action_preview(self):
        self.ensure_one()
        _guard(self, self.company_id)
        try:
            cutoff = rules.cutoff(self.cutoff_mode, self.cutoff_date, self.older_than_days,
                                  self.timezone, fields.Datetime.now())
        except ValueError as error:
            raise ValidationError(str(error)) from None
        run = self.env['baseer.bwork.retention.service']._preview(
            self.company_id.id, self.scope_mode, self.room_ids.ids, self.mode, cutoff)
        return run._action()

    def check_access(self, operation):
        if not (self.env.su and operation == 'unlink'):
            _record_guard(self, 'baseer_bwork_retention_wizard')
        return super().check_access(operation)

    def _search(self, domain, *args, **kwargs):
        return super()._search(_scoped_domain(self, domain), *args, **kwargs)

    def _transient_clean_rows_older_than(self, seconds):
        # Same narrow native-vacuum pattern as the existing guarded console.
        cutoff = self.env.cr.now() - timedelta(seconds=max(seconds, 300))
        self.env.cr.execute('SELECT id FROM baseer_bwork_retention_wizard WHERE write_date<%s ORDER BY id LIMIT %s', [cutoff, GC_UNLINK_LIMIT])
        ids = [r[0] for r in self.env.cr.fetchall()]
        self.sudo().browse(ids).unlink()
        return len(ids) == GC_UNLINK_LIMIT


class RetentionRun(models.Model):
    _name = 'baseer.bwork.retention.run'
    _description = 'Immutable BWork retention preview and run'
    _order = 'id desc'

    name = fields.Char(compute='_compute_display')
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    policy_id = fields.Many2one('baseer.bwork.retention.policy', readonly=True, ondelete='restrict')
    scope_mode = fields.Selection(_SCOPES, required=True, readonly=True)
    room_ids = fields.Many2many('baseer.bchat.room', 'bwork_retention_run_room_rel', 'run_id', 'room_id', readonly=True)
    mode = fields.Selection(_MANUAL_MODES, required=True, readonly=True)
    scheduled_local_date = fields.Date(readonly=True)
    cutoff_utc = fields.Datetime(required=True, readonly=True)
    as_of = fields.Datetime(required=True, readonly=True)
    expires_at = fields.Datetime(required=True, readonly=True)
    creator_user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    config_revision = fields.Integer(readonly=True)
    permission_revision = fields.Integer(readonly=True)
    state = fields.Selection([(v, v.title()) for v in ('preview', 'queued', 'running', 'done', 'partial', 'cancelled', 'expired', 'failed')], default='preview', required=True, readonly=True, index=True)
    confirmation_checked = fields.Boolean(default=False, copy=False)
    eligible_total = fields.Integer(readonly=True)
    remaining_eligible = fields.Integer(readonly=True)
    batch_limited = fields.Boolean(readonly=True)
    candidate_messages = fields.Integer(readonly=True)
    candidate_media = fields.Integer(readonly=True)
    candidate_bytes = fields.Char(readonly=True, default='0')
    protected_count = fields.Integer(readonly=True)
    integrity_count = fields.Integer(readonly=True)
    processed = fields.Integer(readonly=True)
    removed = fields.Integer(readonly=True)
    skipped = fields.Integer(readonly=True)
    failed = fields.Integer(readonly=True)
    last_error_code = fields.Char(readonly=True)
    item_ids = fields.One2many('baseer.bwork.retention.item', 'run_id', readonly=True)
    audit_ids = fields.One2many('baseer.bwork.retention.audit', 'run_id', readonly=True)
    candidate_messages_display = fields.Char(compute='_compute_display')
    candidate_media_display = fields.Char(compute='_compute_display')
    candidate_bytes_display = fields.Char(compute='_compute_display')
    protected_display = fields.Char(compute='_compute_display')
    progress_display = fields.Char(compute='_compute_display')

    def init(self):
        self.env.cr.execute("CREATE UNIQUE INDEX IF NOT EXISTS bwork_retention_one_active_company ON baseer_bwork_retention_run(company_id) WHERE state IN ('queued','running')")
        self.env.cr.execute('CREATE UNIQUE INDEX IF NOT EXISTS bwork_retention_one_policy_day ON baseer_bwork_retention_run(policy_id,scheduled_local_date) WHERE policy_id IS NOT NULL AND scheduled_local_date IS NOT NULL')

    @api.depends('candidate_messages', 'candidate_media', 'candidate_bytes', 'protected_count', 'processed', 'removed', 'skipped', 'failed')
    def _compute_display(self):
        for row in self:
            _guard(row, row.company_id)
            row.name = self.env._('BWork retention preview')
            row.candidate_messages_display = str(row.candidate_messages)
            row.candidate_media_display = str(row.candidate_media)
            row.candidate_bytes_display = rules.size_label(int(row.candidate_bytes or '0'))
            row.protected_display = str(row.protected_count)
            row.progress_display = self.env._('Processed %s; removed %s; skipped %s; failed %s',
                str(row.processed), str(row.removed), str(row.skipped), str(row.failed))

    @api.model_create_multi
    def create(self, vals):
        raise AccessError('Use the retention preview action.')

    def _create_verified(self, vals, token):
        if token is not _ADMIN_TOKEN:
            raise AccessError('Verified retention operation required.')
        clean_context = {key: value for key, value in self.env.context.items() if not key.startswith('default_')}
        vals = dict(vals, state='preview', confirmation_checked=False,
                    processed=0, removed=0, skipped=0, failed=0)
        return super(RetentionRun, self.with_context(clean_context)).create(vals)

    def _service_write(self, vals, token):
        if token is not _ADMIN_TOKEN:
            raise AccessError('Verified retention operation required.')
        return super().write(vals)

    def write(self, vals):
        if set(vals) != {'confirmation_checked'} or type(vals['confirmation_checked']) is not bool:
            raise AccessError('Retention previews and results are immutable.')
        for row in self:
            row._assert_actor()
            if row.state != 'preview':
                raise AccessError('Only a current preview may be acknowledged.')
        return super().write(vals)

    def check_access(self, operation):
        _record_guard(self, 'baseer_bwork_retention_run')
        return super().check_access(operation)

    def _search(self, domain, *args, **kwargs):
        return super()._search(_scoped_domain(self, domain), *args, **kwargs)

    def unlink(self):
        raise AccessError('Retention evidence cannot be deleted.')

    def _assert_actor(self):
        self.ensure_one()
        user = _guard(self, self.company_id)
        if self.creator_user_id != user:
            raise AccessError('Only the original retention actor may confirm this preview.')
        if user._bchat_effective_permissions()['revision'] != self.permission_revision:
            raise ValidationError('retention_permission_changed')
        if self.policy_id and (self.policy_id.revision != self.config_revision or self.policy_id.owner_user_id != user):
            raise ValidationError('retention_policy_changed')
        if any(room.company_id != self.company_id for room in self.room_ids):
            raise ValidationError('retention_scope_changed')
        return user

    def _action(self):
        return dict(type='ir.actions.act_window', res_model=self._name, res_id=self.id, view_mode='form', target='current')

    def action_confirm(self):
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM baseer_bwork_retention_run WHERE id=%s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        self._assert_actor()
        if not self.env['baseer.bchat.service']._retention_ready(lock=True):
            raise ValidationError(self.env._('Server retention is not activated. Update clients and acknowledge readiness first.'))
        if self.state in ('queued', 'running', 'done', 'partial'):
            return self._action()
        if self.state != 'preview' or self.expires_at <= fields.Datetime.now() or not self.confirmation_checked:
            raise ValidationError('retention_preview_expired_or_unconfirmed')
        try:
            with self.env.cr.savepoint():
                self._service_write({'state': 'queued'}, _ADMIN_TOKEN)
        except UniqueViolation as error:
            if error.diag.constraint_name != 'bwork_retention_one_active_company':
                raise
            raise ValidationError(self.env._('Another deletion run is already active for this company.')) from None
        self.env['baseer.bwork.retention.audit']._append('confirmed', self.company_id.id, run=self, token=_ADMIN_TOKEN)
        return self._action()

    def action_cancel(self):
        for row in self:
            self.env.cr.execute('SELECT id FROM baseer_bwork_retention_run WHERE id=%s FOR UPDATE', [row.id])
            row.invalidate_recordset()
            row._assert_actor()
            if row.state in ('preview', 'queued', 'running'):
                row._service_write({'state': 'cancelled'}, _ADMIN_TOKEN)
                self.env['baseer.bwork.retention.audit']._append('cancelled', row.company_id.id, run=row, token=_ADMIN_TOKEN)
        return True

    def action_refresh(self):
        self.ensure_one()
        _guard(self, self.company_id)
        return self._action()


class RetentionItem(models.Model):
    _name = 'baseer.bwork.retention.item'
    _description = 'Frozen BWork retention candidate'
    _order = 'id'

    run_id = fields.Many2one('baseer.bwork.retention.run', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='run_id.company_id', store=True, index=True)
    message_id = fields.Many2one('baseer.bchat.message', readonly=True, ondelete='restrict', index=True)
    media_id = fields.Many2one('baseer.bchat.media', readonly=True, ondelete='restrict', index=True)
    fingerprint = fields.Char(required=True, readonly=True)
    logical_bytes = fields.Char(readonly=True, default='0')
    outcome = fields.Selection([(v, v.title()) for v in ('pending', 'removed', 'skipped', 'failed')], default='pending', required=True, readonly=True, index=True)
    code = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals):
        raise AccessError('Retention manifest is service-owned.')

    def _create_verified(self, vals, token):
        if token is not _ADMIN_TOKEN:
            raise AccessError('Verified retention operation required.')
        ids = []
        for row in vals:
            run = self.env['baseer.bwork.retention.run'].browse(row['run_id'])
            _guard(self, run.company_id)
            self.env.cr.execute('''INSERT INTO baseer_bwork_retention_item
                (run_id,company_id,message_id,media_id,fingerprint,logical_bytes,outcome,create_uid,write_uid,create_date,write_date)
                VALUES (%s,%s,%s,%s,%s,%s,'pending',%s,%s,NOW(),NOW()) RETURNING id''',
                [run.id, run.company_id.id, row.get('message_id') or None, row.get('media_id') or None,
                 row['fingerprint'], str(row['logical_bytes']), self.env.uid, self.env.uid])
            ids.append(self.env.cr.fetchone()[0])
        return self.browse(ids)

    def _service_write(self, vals, token):
        if token is not _ADMIN_TOKEN:
            raise AccessError('Verified retention operation required.')
        if set(vals) != {'outcome', 'code'} or vals['outcome'] not in ('removed', 'skipped', 'failed'):
            raise AccessError('Invalid retention item transition.')
        _record_guard(self, 'baseer_bwork_retention_item')
        self.env.cr.execute('UPDATE baseer_bwork_retention_item SET outcome=%s,code=%s WHERE id=ANY(%s)', [vals['outcome'], vals['code'], self.ids])
        self.invalidate_recordset(['outcome', 'code'])
        return True

    def write(self, vals):
        raise AccessError('Retention manifest is immutable.')

    def unlink(self):
        raise AccessError('Retention manifest cannot be deleted.')

    def check_access(self, operation):
        _record_guard(self, 'baseer_bwork_retention_item')
        return super().check_access(operation)

    def _search(self, domain, *args, **kwargs):
        return super()._search(_scoped_domain(self, domain), *args, **kwargs)


class RetentionAudit(models.Model):
    _name = 'baseer.bwork.retention.audit'
    _description = 'Append-only BWork retention audit'
    _order = 'id desc'

    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    policy_id = fields.Many2one('baseer.bwork.retention.policy', readonly=True, ondelete='restrict')
    run_id = fields.Many2one('baseer.bwork.retention.run', readonly=True, ondelete='restrict')
    action = fields.Char(required=True, readonly=True)
    actor_user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    at = fields.Datetime(required=True, readonly=True)
    count = fields.Integer(readonly=True)
    bytes = fields.Char(readonly=True, default='0')
    code = fields.Char(readonly=True)

    def _append(self, action, company_id, *, run=None, policy=None, count=0, size=0, code=None, token=None):
        if token is not _ADMIN_TOKEN:
            raise AccessError('Verified retention audit required.')
        _guard(self, company_id)
        self.env.cr.execute('''INSERT INTO baseer_bwork_retention_audit
            (company_id,run_id,policy_id,action,actor_user_id,at,count,bytes,code,create_uid,write_uid,create_date,write_date)
            VALUES (%s,%s,%s,%s,%s,NOW(),%s,%s,%s,%s,%s,NOW(),NOW()) RETURNING id''',
            [company_id, run.id if run else None, policy.id if policy else None, action,
             self.env.uid, count, str(size), code, self.env.uid, self.env.uid])
        return self.browse(self.env.cr.fetchone()[0])

    @api.model_create_multi
    def create(self, vals):
        raise AccessError('Retention audit is service-owned.')

    def write(self, vals):
        raise AccessError('Retention audit is append-only.')

    def unlink(self):
        raise AccessError('Retention audit cannot be deleted.')

    def check_access(self, operation):
        _record_guard(self, 'baseer_bwork_retention_audit')
        return super().check_access(operation)

    def _search(self, domain, *args, **kwargs):
        return super()._search(_scoped_domain(self, domain), *args, **kwargs)


class RetentionService(models.AbstractModel):
    _name = 'baseer.bwork.retention.service'
    _description = 'Bounded BWork retention operations'

    @api.model
    def overview(self, company_ids):
        from ..contracts import company_ids as normalize_ids
        ids = normalize_ids(company_ids)
        for cid in ids:
            _guard(self, cid)
        empty = dict(status='limit_exceeded', total_bytes=None, total_display='—',
                     by_room_display='', by_kind_display='')
        # All logical byte sources share ONE 100k budget. No physical-disk claim.
        self.env.cr.execute('''SELECT count(*) FROM (
            SELECT id FROM baseer_bchat_media WHERE company_id=ANY(%s)
            UNION ALL SELECT DISTINCT attachment_id FROM (
                SELECT attachment_id FROM baseer_bchat_media WHERE company_id=ANY(%s) AND retention_state='active'
                UNION ALL SELECT thumbnail_attachment_id FROM baseer_bchat_media WHERE company_id=ANY(%s) AND retention_state='active'
            ) files WHERE attachment_id IS NOT NULL LIMIT 100001) bounded''', [ids, ids, ids])
        if self.env.cr.fetchone()[0] > rules.MAX_SOURCE_ROWS:
            return empty
        self.env.cr.execute('''SELECT media.id,media.company_id,media.room_id,media.kind,attachment.id,attachment.file_size,
                attachment.res_model,attachment.res_id,attachment.company_id
            FROM baseer_bchat_media media
            CROSS JOIN LATERAL (VALUES (media.attachment_id),(media.thumbnail_attachment_id)) file(id)
            LEFT JOIN ir_attachment attachment ON attachment.id=file.id
            WHERE media.company_id=ANY(%s) AND media.retention_state='active'
                AND media.state IN ('staged','attached') AND file.id IS NOT NULL''', [ids])
        by_room, by_kind, seen = {}, {}, set()
        for mid, cid, room_id, kind, aid, size, model, source_id, company_id in self.env.cr.fetchall():
            if (not aid or type(size) is not int or size < 0 or cid != company_id or cid not in ids
                    or model != 'baseer.bchat.media' or source_id != mid or kind not in ('image', 'file', 'audio')):
                return dict(empty, status='integrity_error')
            if aid in seen:
                continue
            seen.add(aid)
            by_room[room_id] = by_room.get(room_id, 0) + size
            by_kind[kind] = by_kind.get(kind, 0) + size
        if len(by_room) > 100:
            return empty
        rooms = self.env['baseer.bchat.room'].sudo().browse(sorted(by_room))
        room_names = {r.id: r.name for r in rooms}
        return dict(status='available', total_bytes=str(sum(by_room.values())),
            total_display=rules.size_label(sum(by_room.values())),
            by_room_display='\n'.join('%s: %s' % (room_names[rid], rules.size_label(size)) for rid, size in sorted(by_room.items())),
            by_kind_display='\n'.join('%s: %s' % (self.env._({'image': 'Images', 'audio': 'Audio', 'file': 'Files'}[kind]), rules.size_label(size)) for kind, size in sorted(by_kind.items())))

    def _rooms(self, company_id, scope_mode, room_ids):
        _guard(self, company_id)
        if scope_mode not in ('company', 'rooms') or (scope_mode == 'rooms' and not room_ids):
            raise ValidationError('invalid_retention_scope')
        domain = [('company_id', '=', company_id)]
        if scope_mode == 'rooms':
            if type(room_ids) is not list or len(room_ids) != len(set(room_ids)) or any(type(i) is not int or i <= 0 for i in room_ids):
                raise ValidationError('invalid_retention_rooms')
            domain.append(('id', 'in', room_ids))
        # Explicit metadata authority, not source-content read ACL.
        rows = self.env['baseer.bchat.room'].sudo().search(domain, order='id', limit=101)
        if len(rows) > 100 or scope_mode == 'rooms' and set(rows.ids) != set(room_ids):
            raise ValidationError('retention_room_scope_exceeded_or_changed')
        return rows

    def _preview(self, company_id, scope_mode, room_ids, mode, cutoff, policy=None):
        user = _guard(self, company_id)
        if mode not in dict(_MANUAL_MODES) or not cutoff or cutoff > fields.Datetime.now() or policy and mode == 'expired_uploads':
            raise ValidationError('invalid_retention_mode_or_cutoff')
        rooms = self._rooms(company_id, scope_mode, room_ids)
        # Conservative aggregate budget includes all materialized source rows,
        # not only eligible/approved records. Never a partial headline.
        self.env.cr.execute('''SELECT count(*) FROM (
            SELECT id FROM baseer_bchat_message WHERE company_id=%s AND room_id=ANY(%s)
            UNION ALL SELECT id FROM baseer_bchat_media WHERE company_id=%s AND room_id=ANY(%s)
            UNION ALL SELECT file.id FROM baseer_bchat_media media
              CROSS JOIN LATERAL (VALUES(media.attachment_id),(media.thumbnail_attachment_id)) file(id)
              WHERE media.company_id=%s AND media.room_id=ANY(%s) AND file.id IS NOT NULL
            UNION ALL SELECT event.id FROM baseer_bchat_push_event event
              JOIN baseer_bchat_message m ON m.id=event.message_id WHERE m.company_id=%s AND m.room_id=ANY(%s)
            LIMIT 100001) bounded''', [company_id, rooms.ids] * 4)
        if self.env.cr.fetchone()[0] > rules.MAX_SOURCE_ROWS:
            raise ValidationError('limit_exceeded')
        if mode == 'expired_uploads':
            cutoff = min(cutoff, fields.Datetime.now() - timedelta(hours=24))
        messages = self.env['baseer.bchat.message'].sudo().search([
            ('company_id', '=', company_id), ('room_id', 'in', rooms.ids),
            ('create_date', '<', cutoff), ('retention_state', '=', 'active'),
        ], order='create_date,id', limit=rules.MAX_SOURCE_ROWS + 1) if mode != 'expired_uploads' else self.env['baseer.bchat.media'].sudo().search([
            ('company_id', '=', company_id), ('room_id', 'in', rooms.ids),
            ('state', '=', 'staged'), ('message_id', '=', False), ('create_date', '<', cutoff),
        ], order='create_date,id', limit=rules.MAX_SOURCE_ROWS + 1)
        if len(messages) > rules.MAX_SOURCE_ROWS:
            raise ValidationError('limit_exceeded')
        source = self.env['baseer.bchat.service']
        candidates, eligible, protected, integrity = [], 0, 0, 0
        for message in messages:
            if mode == 'attachments' and (not message.media_id or message.media_id.retention_state != 'active'):
                continue
            staged = mode == 'expired_uploads'
            reason, attachments, size = (source._retention_inspect_staged(message, _RETENTION_TOKEN)
                                         if staged else source._retention_inspect(message, _RETENTION_TOKEN))
            if reason == 'eligible':
                eligible += 1
                if len(candidates) < rules.MAX_VICTIMS:
                    candidates.append(dict(message_id=False if staged else message.id,
                        media_id=message.id if staged else message.media_id.id,
                        fingerprint=(source._retention_staged_fingerprint(message, _RETENTION_TOKEN)
                                     if staged else source._retention_fingerprint(message, _RETENTION_TOKEN)), logical_bytes=size))
            elif reason == 'integrity_error':
                integrity += 1
            else:
                protected += 1
        now = fields.Datetime.now()
        run = self.env['baseer.bwork.retention.run']._create_verified(dict(company_id=company_id,
            policy_id=policy.id if policy else False, scope_mode=scope_mode,
            room_ids=[Command.set(rooms.ids)], mode=mode, cutoff_utc=cutoff, as_of=now,
            expires_at=now + timedelta(seconds=rules.PREVIEW_SECONDS), creator_user_id=user.id,
            config_revision=policy.revision if policy else 0,
            permission_revision=user._bchat_effective_permissions()['revision'], eligible_total=eligible,
            remaining_eligible=max(0, eligible - len(candidates)), batch_limited=eligible > len(candidates),
            candidate_messages=sum(bool(i['message_id']) for i in candidates), candidate_media=sum(bool(i['media_id']) for i in candidates),
            candidate_bytes=sum(i['logical_bytes'] for i in candidates), protected_count=protected,
            integrity_count=integrity), _ADMIN_TOKEN)
        if candidates:
            self.env['baseer.bwork.retention.item']._create_verified([dict(row, run_id=run.id) for row in candidates], _ADMIN_TOKEN)
        self.env['baseer.bwork.retention.audit']._append('preview', company_id, run=run,
            count=len(candidates), size=run.candidate_bytes, token=_ADMIN_TOKEN)
        return run

    def _execute_batch(self, run):
        self.env.cr.execute('SELECT id FROM baseer_bwork_retention_run WHERE id=%s FOR UPDATE', [run.id])
        run.invalidate_recordset()
        run._assert_actor()
        source = self.env['baseer.bchat.service']
        # Existing upload writers use room -> user. Keep that lock order while
        # linearizing role/policy revocation against this bounded atomic batch.
        for room in run.room_ids.sudo().sorted('id'):
            self.env['baseer.bchat.room']._lock_for_mutation(room.id)
        self.env.cr.execute('SELECT id FROM res_users WHERE id=%s FOR SHARE', [self.env.uid])
        self.env.user.invalidate_recordset()
        if run.policy_id:
            self.env.cr.execute('SELECT id FROM baseer_bwork_retention_policy WHERE id=%s FOR SHARE', [run.policy_id.id])
            run.policy_id.invalidate_recordset()
        run._assert_actor()
        if not source._retention_ready(lock=True):
            raise ValidationError('retention_not_ready')
        if run.policy_id and not run.policy_id.enabled:
            raise ValidationError('retention_policy_disabled')
        if run.state not in ('queued', 'running'):
            return False
        items = self.env['baseer.bwork.retention.item'].search([('run_id', '=', run.id), ('outcome', '=', 'pending')], order='id', limit=rules.BATCH_SIZE)
        changed = self.env['baseer.bchat.room'].sudo()
        removed = skipped = failed = size = 0
        for item in items:
            # Latch, authority, policy and scope are checked for EVERY victim.
            run._assert_actor()
            if not source._retention_ready():
                raise ValidationError('retention_not_ready')
            with self.env.cr.savepoint():
                staged = run.mode == 'expired_uploads'
                outcome, reclaimed = (source._retention_expire_staged(item.media_id.sudo(), item.fingerprint, _RETENTION_TOKEN)
                    if staged else source._retention_scrub(item.message_id.sudo(), run.mode, item.fingerprint, _RETENTION_TOKEN))
                if outcome == 'removed':
                    if not staged:
                        changed |= item.message_id.sudo().room_id
                    removed += 1
                    size += reclaimed
                    item._service_write({'outcome': 'removed', 'code': 'content_removed'}, _ADMIN_TOKEN)
                else:
                    skipped += 1
                    item._service_write({'outcome': 'skipped', 'code': outcome}, _ADMIN_TOKEN)
        if changed:
            source._retention_publish_rooms(changed, _RETENTION_TOKEN)
        remaining = self.env['baseer.bwork.retention.item'].search_count([('run_id', '=', run.id), ('outcome', '=', 'pending')])
        state = 'running' if remaining else ('partial' if run.skipped + skipped + run.failed + failed else 'done')
        run._service_write(dict(state=state, processed=run.processed + len(items),
            removed=run.removed + removed, skipped=run.skipped + skipped, failed=run.failed + failed), _ADMIN_TOKEN)
        self.env['baseer.bwork.retention.audit']._append('batch', run.company_id.id, run=run,
            count=removed, size=size, code=state, token=_ADMIN_TOKEN)
        return bool(remaining)

    @api.model
    def _cron_tick(self):
        # Cron has no source authority. Reconstitute each approving actor in
        # a one-company, non-sudo environment before any operation.
        if not self.env.su:
            raise AccessError('Private cron entry required.')
        if not self.env['baseer.bchat.service']._retention_ready():
            return
        # No catch-up burst: only today's local slot is eligible, once per
        # policy/local date. One active job per company is enforced by SQL.
        now = fields.Datetime.now()
        self.env.cr.execute('''SELECT id,owner_user_id,company_id FROM baseer_bwork_retention_policy
            WHERE enabled AND next_run_at<=%s ORDER BY next_run_at,id LIMIT %s FOR UPDATE SKIP LOCKED''', [now, rules.MAX_POLICIES])
        due = self.env.cr.fetchall()
        for policy_id, actor_id, company_id in due:
            service = self.with_user(actor_id).with_context({'allowed_company_ids': [company_id]})
            try:
                with self.env.cr.savepoint():
                    policy = service.env['baseer.bwork.retention.policy'].browse(policy_id)
                    _guard(service, company_id)
                    day = now.replace(tzinfo=datetime_timezone.utc).astimezone(rules.zone(policy.timezone)).date()
                    self.env.cr.execute("SELECT 1 FROM baseer_bwork_retention_run WHERE company_id=%s AND state IN ('queued','running') LIMIT 1", [company_id])
                    if self.env.cr.fetchone():
                        continue
                    today_slot = rules.local_slot(day, policy.schedule_hour, policy.schedule_minute, policy.timezone)
                    if policy.last_local_date != day and today_slot <= now:
                        cutoff = rules.cutoff('older_than_days', None, policy.retention_days, policy.timezone, now)
                        run = service._preview(company_id, policy.scope_mode, policy.room_ids.ids, policy.mode, cutoff, policy=policy)
                        if not service.env['baseer.bchat.service']._retention_ready(lock=True):
                            raise ValidationError('retention_not_ready')
                        run._service_write({'state': 'queued', 'scheduled_local_date': day}, _ADMIN_TOKEN)
                        service.env['baseer.bwork.retention.audit']._append('scheduled', company_id, run=run, policy=policy, token=_ADMIN_TOKEN)
                        policy._service_write({'last_local_date': day, 'last_run_at': now, 'last_status': 'queued'}, _ADMIN_TOKEN)
                    policy._service_write({'next_run_at': rules.next_slot(now, policy.schedule_hour, policy.schedule_minute, policy.timezone)}, _ADMIN_TOKEN)
            except (AccessError, ValidationError, ProtocolError, ValueError):
                # Disable stale authority/configuration rather than inventing a
                # sudo actor or retrying destructive work under another user.
                self.env.cr.execute("UPDATE baseer_bwork_retention_policy SET enabled=FALSE,last_status='authority_or_configuration_changed' WHERE id=%s", [policy_id])
        self.env.cr.execute("SELECT id,creator_user_id,company_id FROM baseer_bwork_retention_run WHERE state IN ('queued','running') ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED", [rules.MAX_POLICIES])
        for run_id, actor_id, company_id in self.env.cr.fetchall():
            service = self.with_user(actor_id).with_context({'allowed_company_ids': [company_id]})
            try:
                with self.env.cr.savepoint():
                    service._execute_batch(service.env['baseer.bwork.retention.run'].browse(run_id))
            except (AccessError, ValidationError, ProtocolError):
                # A revoked actor cannot append through the public guard. This
                # fixed, private cron transition writes ONLY derived job/audit
                # metadata; it never restores that actor's source authority.
                self.env.cr.execute('''WITH cancelled AS (
                    UPDATE baseer_bwork_retention_run SET state='cancelled',
                        last_error_code='authority_or_readiness_changed'
                    WHERE id=%s AND state IN ('queued','running') RETURNING id,company_id
                ) INSERT INTO baseer_bwork_retention_audit
                    (company_id,run_id,action,actor_user_id,at,count,bytes,code,create_uid,write_uid,create_date,write_date)
                    SELECT company_id,id,'cancelled',%s,NOW(),0,'0','authority_or_readiness_changed',%s,%s,NOW(),NOW()
                    FROM cancelled''', [run_id, self.env.uid, self.env.uid, self.env.uid])


class BChatRetentionAdministration(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    def _retention_admin_available(self):
        return True

    def _retention_audit_preserve(self, message, preserved):
        self.env['baseer.bwork.retention.audit']._append('preserved' if preserved else 'unpreserved',
            message.company_id.id, code='explicit_server_hold', token=_ADMIN_TOKEN)
