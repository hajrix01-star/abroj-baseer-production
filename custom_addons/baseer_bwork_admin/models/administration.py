"""Metadata-only console. No content ACL grants or linked-file mutation."""
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL
from odoo.tools.constants import GC_UNLINK_LIMIT

from .. import contracts

_LOGGER = logging.getLogger(__name__)
_SOURCES = (
    ('baseer.bchat.room', 'baseer_bchat_room'),
    ('baseer.bchat.membership', 'baseer_bchat_membership'),
    ('baseer.bchat.media', 'baseer_bchat_media'),
    ('baseer.bchat.push.event', 'baseer_bchat_push_event'),
    ('baseer.bchat.mobile.upload.grant', 'baseer_bchat_mobile_upload_grant'),
)
_CRONS = ('cron_expire_staged_media', 'cron_expire_mobile_upload_grants',
          'cron_dispatch_push_events', 'cron_work_task_reminders')


def _selected_companies(commands, current=()):
    """Validate the limited many2many UI command vocabulary before any write."""
    ids = set(current)
    if type(commands) is not list:
        raise ValidationError('invalid_company_scope')
    for command in commands:
        if not isinstance(command, (tuple, list)) or not command:
            raise ValidationError('invalid_company_scope')
        if command[0] == 6 and len(command) == 3:
            try:
                ids = set(contracts.company_ids(command[2]))
            except ValueError as error:
                raise ValidationError(str(error)) from None
        elif command[0] in (3, 4) and len(command) in (2, 3) and type(command[1]) is int and command[1] > 0:
            if command[0] == 4:
                ids.add(command[1])
            else:
                ids.discard(command[1])
        elif command[0] == 5:
            ids.clear()
        else:
            raise ValidationError('invalid_company_scope')
    try:
        return contracts.company_ids(sorted(ids))
    except ValueError as error:
        raise ValidationError(str(error)) from None


class BWorkAdminService(models.AbstractModel):
    _name = 'baseer.bwork.admin.service'
    _description = 'BWork bounded administrative metadata'

    def _guard(self, company_ids, configuration=False):
        # Reuses the UID2 + manager group + effective permission guard, which
        # also rejects superuser mode, inactive and non-internal callers.
        user = self.env['baseer.bchat.service']._require_room_manager()
        if configuration and not user.has_group('base.group_system'):
            raise AccessError(self.env._('System administration is required.'))
        try:
            ids = contracts.company_ids(company_ids)
        except ValueError as error:
            raise ValidationError(str(error)) from None
        if not set(ids) <= set(user.company_ids.ids) & set(self.env.companies.ids):
            raise AccessError(self.env._('Select only currently authorized companies.'))
        return ids

    def _preflight(self, ids):
        remaining = contracts.MAX_SOURCE_ROWS
        for model, table in _SOURCES:
            self.env[model].flush_model()
            self.env.cr.execute(SQL(
                'SELECT count(*) FROM (SELECT id FROM %s WHERE company_id = ANY(%s) LIMIT %s) bounded',
                SQL.identifier(table), ids, remaining + 1))
            remaining -= self.env.cr.fetchone()[0]
            if remaining < 0:
                return False
        self.env['ir.attachment'].flush_model(['file_size'])
        self.env.cr.execute('''
            SELECT count(*) FROM (
                SELECT DISTINCT company_id, attachment_id FROM (
                    SELECT company_id, attachment_id FROM baseer_bchat_media
                    WHERE company_id = ANY(%s) AND state IN ('staged', 'attached')
                    UNION ALL
                    SELECT company_id, thumbnail_attachment_id FROM baseer_bchat_media
                    WHERE company_id = ANY(%s) AND state IN ('staged', 'attached')
                ) refs WHERE attachment_id IS NOT NULL LIMIT %s
            ) bounded
        ''', [ids, ids, remaining + 1])
        return self.env.cr.fetchone()[0] <= remaining

    @api.model
    def snapshot(self, company_ids):
        ids = self._guard(company_ids)
        result = {'version': 1, 'status': 'complete', 'complete': True,
                  'company_ids': ids, 'source_limit': contracts.MAX_SOURCE_ROWS,
                  'companies': [], 'totals': None,
                  'storage_basis': 'logical_distinct_attachments_per_company',
                  'linked_retention': 'preserve_all', 'provider_readiness': 'unverified'}
        if not self._preflight(ids):
            result.update(status='limit_exceeded', complete=False)
            return result
        self.env.cr.execute('''SELECT count(*) FROM (
            SELECT m.id FROM baseer_bchat_media m
            LEFT JOIN ir_attachment a ON a.id = m.attachment_id
            LEFT JOIN ir_attachment t ON t.id = m.thumbnail_attachment_id
            WHERE m.company_id = ANY(%s) AND m.state IN ('staged', 'attached')
              AND (a.id IS NULL OR (m.thumbnail_attachment_id IS NOT NULL AND t.id IS NULL))
        ) broken''', [ids])
        missing = self.env.cr.fetchone()[0]
        result['integrity'] = {'missing_attachment_rows': missing}
        if missing:
            result.update(status='integrity_error', complete=False)
            return result
        rows = {cid: {'company_id': cid, 'rooms': 0, 'memberships': 0,
                      'active_memberships': 0, 'logical_bytes': 0,
                      'original_bytes': 0, 'thumbnail_bytes': 0,
                      'media': {}, 'push': {}, 'push_errors': {}, 'upload_grants': {}}
                for cid in ids}
        for table, column, target in (
                ('baseer_bchat_media', 'state', 'media'),
                ('baseer_bchat_push_event', 'state', 'push'),
                ('baseer_bchat_mobile_upload_grant', 'state', 'upload_grants')):
            self.env.cr.execute(SQL(
                'SELECT company_id, %s, count(*) FROM %s WHERE company_id = ANY(%s) GROUP BY company_id, %s',
                SQL.identifier(column), SQL.identifier(table), ids, SQL.identifier(column)))
            for cid, state, count in self.env.cr.fetchall():
                rows[cid][target][state] = count
        self.env.cr.execute('SELECT company_id, count(*) FROM baseer_bchat_room WHERE company_id = ANY(%s) GROUP BY company_id', [ids])
        for cid, count in self.env.cr.fetchall():
            rows[cid]['rooms'] = count
        self.env.cr.execute('''SELECT company_id, count(*), count(*) FILTER (WHERE active)
            FROM baseer_bchat_membership WHERE company_id = ANY(%s) GROUP BY company_id''', [ids])
        for cid, count, active in self.env.cr.fetchall():
            rows[cid].update(memberships=count, active_memberships=active)
        self.env.cr.execute('''
            SELECT refs.company_id, COALESCE(sum(a.file_size), 0) FROM (
                SELECT company_id, attachment_id FROM baseer_bchat_media
                WHERE company_id = ANY(%s) AND state IN ('staged', 'attached') AND attachment_id IS NOT NULL
                UNION
                SELECT company_id, thumbnail_attachment_id FROM baseer_bchat_media
                WHERE company_id = ANY(%s) AND state IN ('staged', 'attached') AND thumbnail_attachment_id IS NOT NULL
            ) refs JOIN ir_attachment a ON a.id = refs.attachment_id GROUP BY refs.company_id
        ''', [ids, ids])
        for cid, size in self.env.cr.fetchall():
            rows[cid]['logical_bytes'] = int(size)
        for column, key in (('attachment_id', 'original_bytes'), ('thumbnail_attachment_id', 'thumbnail_bytes')):
            self.env.cr.execute(SQL('''SELECT refs.company_id, COALESCE(sum(a.file_size), 0)
                FROM (SELECT DISTINCT company_id, %s AS attachment_id FROM baseer_bchat_media
                      WHERE company_id = ANY(%s) AND state IN ('staged', 'attached')) refs
                JOIN ir_attachment a ON a.id = refs.attachment_id GROUP BY refs.company_id''',
                SQL.identifier(column), ids))
            for cid, size in self.env.cr.fetchall():
                rows[cid][key] = int(size)
        # Only server-owned error codes leave the database; arbitrary historical
        # strings must never turn into an administrative content/secret channel.
        self.env.cr.execute('''SELECT company_id,
            CASE WHEN last_error = ANY(%s) THEN last_error ELSE 'other' END,
            count(*) FROM baseer_bchat_push_event
            WHERE company_id = ANY(%s) AND last_error IS NOT NULL
            GROUP BY company_id, 2''', [list(contracts.PUSH_ERRORS), ids])
        for cid, code, count in self.env.cr.fetchall():
            rows[cid]['push_errors'][code] = count
        settings = self.env['baseer.bwork.admin.policy'].search([('company_id', 'in', ids)])
        warnings = {item.company_id.id: item.warning_mib for item in settings}
        for cid, row in rows.items():
            row['logical_mib'] = contracts.mib(row['logical_bytes'])
            row['original_mib'] = contracts.mib(row['original_bytes'])
            row['thumbnail_mib'] = contracts.mib(row['thumbnail_bytes'])
            row['warning_mib'] = warnings.get(cid, 0)
            row['warning_status'] = contracts.warning_status(row['logical_bytes'], row['warning_mib'])
        result['companies'] = list(rows.values())
        result['totals'] = {key: sum(row[key] for row in rows.values()) for key in (
            'rooms', 'memberships', 'active_memberships', 'logical_bytes')}
        result['totals']['logical_mib'] = contracts.mib(result['totals']['logical_bytes'])
        result['crons'] = []
        for name in _CRONS:
            cron = self.env.ref('baseer_bchat.' + name, raise_if_not_found=False)
            # Fixed metadata fields, fixed XMLIDs, never cron code or arguments.
            if cron:
                cron = cron.sudo()
                result['crons'].append({'code': name, 'present': True, 'active': bool(cron.active),
                                        'nextcall': fields.Datetime.to_string(cron.nextcall) or None})
            else:
                result['crons'].append({'code': name, 'present': False, 'active': False, 'nextcall': None})
        return contracts.bounded_response(result)

    @api.model
    def rooms(self, company_ids, offset=0, limit=contracts.DEFAULT_PAGE):
        ids = self._guard(company_ids)
        try:
            offset, limit = contracts.pagination(offset, limit)
        except ValueError as error:
            raise ValidationError(str(error)) from None
        records = self.env['baseer.bchat.room'].with_context(allowed_company_ids=ids).search(
            [('company_id', 'in', ids)], offset=offset, limit=limit + 1, order='id desc')
        return contracts.bounded_response({'items': records[:limit].read(['name', 'company_id', 'is_group']),
                                            'has_more': len(records) > limit, 'offset': offset, 'limit': limit})

    @api.model
    def members(self, company_ids, offset=0, limit=contracts.DEFAULT_PAGE):
        ids = self._guard(company_ids)
        try:
            offset, limit = contracts.pagination(offset, limit)
        except ValueError as error:
            raise ValidationError(str(error)) from None
        records = self.env['baseer.bchat.membership'].with_context(allowed_company_ids=ids, active_test=False).search(
            [('company_id', 'in', ids)], offset=offset, limit=limit + 1, order='id desc')
        return contracts.bounded_response({'items': records[:limit].read(['room_id', 'company_id', 'user_id', 'active', 'left_at']),
                                            'has_more': len(records) > limit, 'offset': offset, 'limit': limit})


class BWorkAdminPolicy(models.Model):
    _name = 'baseer.bwork.admin.policy'
    _description = 'BWork storage warning policy'
    _rec_name = 'company_id'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, ondelete='restrict', index=True)
    warning_mib = fields.Integer(string='Warning threshold (MiB)', required=True, default=0,
                                 help='0 disables the warning. This never limits uploads or deletes files.')
    _company_unique = models.Constraint('UNIQUE(company_id)', 'One BWork warning policy per company.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if set(vals) - {'company_id', 'warning_mib'}:
                raise ValidationError(self.env._('Unsupported policy fields.'))
            self.env['baseer.bwork.admin.service']._guard([vals.get('company_id')], configuration=True)
            try:
                contracts.warning(vals.get('warning_mib', 0))
            except ValueError as error:
                raise ValidationError(str(error)) from None
        result = super().create(vals_list)
        _LOGGER.info('BWork warning policy created by uid=%s companies=%s', self.env.uid, result.mapped('company_id').ids)
        return result

    def write(self, vals):
        if set(vals) != {'warning_mib'}:
            raise ValidationError(self.env._('Only the warning threshold can be changed.'))
        self.env['baseer.bwork.admin.service']._guard(self.mapped('company_id').ids, configuration=True)
        try:
            contracts.warning(vals['warning_mib'])
        except ValueError as error:
            raise ValidationError(str(error)) from None
        result = super().write(vals)
        _LOGGER.info('BWork warning policy updated by uid=%s companies=%s', self.env.uid, self.mapped('company_id').ids)
        return result

    def read(self, fields=None, load='_classic_read'):
        self.env['baseer.bwork.admin.service']._guard(self.mapped('company_id').ids or [self.env.company.id])
        return super().read(fields=fields, load=load)

    def _search(self, domain, *args, **kwargs):
        self.env['baseer.bchat.service']._require_room_manager()
        # Always intersect caller filters with the current authorized scope.
        domain = list(domain) + [('company_id', 'in', self.env.companies.ids)]
        return super()._search(domain, *args, **kwargs)

    def check_access(self, operation):
        self.env['baseer.bchat.service']._require_room_manager()
        ids = [rid for rid in self.ids if type(rid) is int]
        if ids:
            self.env.cr.execute('SELECT company_id FROM baseer_bwork_admin_policy WHERE id = ANY(%s)', [ids])
            for (company_id,) in self.env.cr.fetchall():
                self.env['baseer.bwork.admin.service']._guard([company_id])
        return super().check_access(operation)

    def export_data(self, fields_to_export):
        # Read through the guarded native path first, even for an id-only
        # export. This also primes the company field for Odoo's sudo predicate
        # evaluation of its normal company record rule (without a sudo read).
        self.read(['company_id'])
        return super().export_data(fields_to_export)

    def unlink(self):
        raise AccessError(self.env._('BWork warning policies cannot be deleted.'))


class BWorkAdminConsole(models.TransientModel):
    _name = 'baseer.bwork.admin.console'
    _description = 'BWork administration'

    company_ids = fields.Many2many('res.company', 'bwork_admin_console_company_rel', 'console_id', 'company_id',
                                  required=True, default=lambda self: self.env.company)
    status = fields.Char(compute='_compute_snapshot')
    rooms_count = fields.Char(string='Rooms', compute='_compute_snapshot')
    members_count = fields.Char(string='Active memberships', compute='_compute_snapshot')
    logical_storage = fields.Char(string='Logical size (MiB)', compute='_compute_snapshot')
    storage_details = fields.Text(string='Storage details', compute='_compute_snapshot')
    operations = fields.Text(compute='_compute_snapshot')

    def _transient_clean_rows_older_than(self, seconds):
        # Odoo19's inherited vacuum uses sudo().search() before unlink. Never
        # authorize sudo searches/reads merely for housekeeping: select only
        # this derived UI table's expired IDs with the same native clock,
        # minimum age and batch bound, then use its normal unlink lifecycle.
        # This cannot touch policy, room, message, attachment or media tables.
        cutoff = self.env.cr.now() - timedelta(seconds=max(seconds, 300))
        self.env.cr.execute('''SELECT id FROM baseer_bwork_admin_console
            WHERE write_date < %s ORDER BY id LIMIT %s''', [cutoff, GC_UNLINK_LIMIT])
        ids = [row[0] for row in self.env.cr.fetchall()]
        self.sudo().browse(ids).unlink()
        return len(ids) == GC_UNLINK_LIMIT

    @api.depends('company_ids')
    def _compute_snapshot(self):
        service = self.env['baseer.bwork.admin.service']
        for record in self:
            data = service.snapshot(record.company_ids.ids)
            totals = data['totals']
            record.status = self.env._('Complete') if data['complete'] else (
                self.env._('Attachment metadata incomplete — totals unavailable') if data['status'] == 'integrity_error'
                else self.env._('Limit exceeded — narrow the company scope'))
            record.rooms_count = str(totals['rooms']) if totals else '—'
            record.members_count = str(totals['active_memberships']) if totals else '—'
            record.logical_storage = totals['logical_mib'] if totals else '—'
            lines = []
            for company in record.company_ids:
                row = next((item for item in data['companies'] if item['company_id'] == company.id), None)
                if row:
                    state = {'disabled': self.env._('Warning disabled'), 'below': self.env._('Below warning threshold'),
                             'reached': self.env._('Warning threshold reached')}[row['warning_status']]
                    lines.append('%s: %s MiB / %s MiB — %s' % (company.name, row['logical_mib'], row['warning_mib'], state))
                    lines.append('%s: %s MiB; %s: %s MiB' % (self.env._('Originals'), row['original_mib'],
                                                                          self.env._('Thumbnails'), row['thumbnail_mib']))
            record.storage_details = '\n'.join(lines)
            # Code/status counters are server derived. No previews, tokens,
            # arbitrary exception strings, or invented successful delivery.
            lines = [self.env._('Provider readiness: unverified')]
            labels = {
                'media': self.env._('Media'), 'push': self.env._('Push queue'),
                'push_errors': self.env._('Sanitized errors'), 'upload_grants': self.env._('Upload capabilities'),
                'staged': self.env._('Staged'), 'attached': self.env._('Attached'),
                'cancelled': self.env._('Cancelled'), 'expired': self.env._('Expired'),
                'pending': self.env._('Pending'), 'retry': self.env._('Retry'),
                'configuration': self.env._('Configuration'), 'sent': self.env._('Sent to provider'),
                'discarded': self.env._('Discarded'), 'failed': self.env._('Failed'),
                'issued': self.env._('Issued'), 'uploading': self.env._('Uploading'),
                'resolved': self.env._('Resolved'), 'denied': self.env._('Denied'),
                'transport': self.env._('Transport'), 'unregistered': self.env._('Unregistered'),
                'access_revoked': self.env._('Access revoked'), 'other': self.env._('Other'),
            }
            for row in data['companies']:
                company = record.company_ids.filtered(lambda item: item.id == row['company_id'])
                lines.append(company.name)
                for kind in ('media', 'push', 'push_errors', 'upload_grants'):
                    counts = ', '.join('%s: %s' % (labels.get(key, self.env._('Other')), value)
                                       for key, value in sorted(row[kind].items()))
                    lines.append('%s — %s' % (labels[kind], counts or '0'))
            cron_labels = {
                'cron_expire_staged_media': self.env._('Staged media cleanup'),
                'cron_expire_mobile_upload_grants': self.env._('Upload capability cleanup'),
                'cron_dispatch_push_events': self.env._('Push dispatch'),
                'cron_work_task_reminders': self.env._('Task reminders'),
            }
            for cron in data.get('crons', []):
                state = self.env._('Missing') if not cron['present'] else (
                    self.env._('Enabled') if cron['active'] else self.env._('Disabled'))
                lines.append('%s — %s — %s: %s' % (cron_labels[cron['code']], state,
                    self.env._('Next scheduled run (UTC)'), cron['nextcall'] or '—'))
            record.operations = '\n'.join(lines)

    @api.model_create_multi
    def create(self, vals_list):
        self.env['baseer.bchat.service']._require_room_manager()
        if any(set(vals) - {'company_ids'} for vals in vals_list):
            raise ValidationError(self.env._('Unsupported console fields.'))
        for vals in vals_list:
            ids = _selected_companies(vals['company_ids']) if 'company_ids' in vals else [self.env.company.id]
            self.env['baseer.bwork.admin.service']._guard(ids)
        return super().create(vals_list)

    def write(self, vals):
        self.env['baseer.bchat.service']._require_room_manager()
        if set(vals) - {'company_ids'}:
            raise ValidationError(self.env._('Unsupported console fields.'))
        for record in self:
            ids = _selected_companies(vals['company_ids'], record.company_ids.ids) if 'company_ids' in vals else record.company_ids.ids
            self.env['baseer.bwork.admin.service']._guard(ids)
        return super().write(vals)

    def _search(self, domain, *args, **kwargs):
        self.env['baseer.bchat.service']._require_room_manager()
        allowed = sorted(set(self.env.companies.ids) & set(self.env.user.company_ids.ids))
        return super()._search(list(domain) + [
            ('company_ids', '!=', False),
            ('company_ids', 'not any', [('id', 'not in', allowed)])], *args, **kwargs)

    def check_access(self, operation):
        # Odoo may vacuum its own transient UI rows in superuser mode. This
        # exception permits no read/content/configuration operation.
        if not (operation == 'unlink' and self.env.su):
            self.env['baseer.bchat.service']._require_room_manager()
            ids = [rid for rid in self.ids if type(rid) is int]
            if ids:
                # Do not read company_ids through ORM here: fetch itself calls
                # check_access. Fixed relation metadata avoids recursion and
                # validates even an already cached transient/export operation.
                self.env.cr.execute('''SELECT console_id, array_agg(company_id)
                    FROM bwork_admin_console_company_rel WHERE console_id = ANY(%s) GROUP BY console_id''', [ids])
                for _rid, company_ids in self.env.cr.fetchall():
                    self.env['baseer.bwork.admin.service']._guard(company_ids)
        return super().check_access(operation)

    def export_data(self, fields_to_export):
        self.check_access('read')
        return super().export_data(fields_to_export)

    def read(self, fields=None, load='_classic_read'):
        self.env['baseer.bchat.service']._require_room_manager()
        for record in self:
            self.env['baseer.bwork.admin.service']._guard(record.company_ids.ids)
        return super().read(fields=fields, load=load)

    def action_refresh(self):
        self.ensure_one()
        self.env['baseer.bwork.admin.service']._guard(self.company_ids.ids)
        self.invalidate_recordset()
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def _metadata_action(self, model, view):
        self.ensure_one()
        ids = self.env['baseer.bwork.admin.service']._guard(self.company_ids.ids)
        return {'type': 'ir.actions.act_window', 'name': self.env._('BWork metadata'),
                'res_model': model, 'view_mode': 'list,form',
                'views': [(self.env.ref('baseer_bwork_admin.' + view).id, 'list'),
                          (self.env.ref('baseer_bwork_admin.' + view.replace('_list', '_form')).id, 'form')],
                'domain': [('company_id', 'in', ids)], 'limit': contracts.DEFAULT_PAGE,
                'context': {'allowed_company_ids': ids, 'active_test': False,
                            'create': False, 'edit': False, 'delete': False}}

    def action_rooms(self):
        return self._metadata_action('baseer.bchat.room', 'room_list')

    def action_members(self):
        return self._metadata_action('baseer.bchat.membership', 'member_list')

    def action_settings(self):
        self.ensure_one()
        ids = self.env['baseer.bwork.admin.service']._guard(self.company_ids.ids, configuration=True)
        return {'type': 'ir.actions.act_window', 'name': self.env._('BWork warning settings'),
                'res_model': 'baseer.bwork.admin.policy', 'view_mode': 'list,form',
                'domain': [('company_id', 'in', ids)], 'limit': contracts.DEFAULT_PAGE,
                'context': {'allowed_company_ids': ids, 'default_company_id': ids[0]}}
