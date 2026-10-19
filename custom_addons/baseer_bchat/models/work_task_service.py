"""Modern, bounded work tasks over the private legacy task store."""
from psycopg2.errors import UniqueViolation

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import SQL

from .. import work_task_contracts as wire
from ..contracts import ProtocolError, positive_id
from .task import _TASK_SERVICE_TOKEN
from .push import _PUSH_TOKEN


class BChatWorkTaskService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _work_task_envelope(self, **values):
        return dict(api_version=2, work_tasks_version=1,
                    server_now=self._task_stamp(fields.Datetime.now()), **values)

    @api.model
    def _work_task_label(self, value):
        # Names are presentation labels, not canonical task text. Reserve
        # space for worst-case JSON escaping of full valid description/notes
        # so even a maximal task remains within its 12 KiB row contract.
        return self._task_label(value)[:96].encode('utf-8')[:192].decode('utf-8', 'ignore')

    @api.model
    def _work_task_scope(self, company_id=None, manage=False):
        user = self._require_bchat_permission('task_manage' if manage else 'task_view')
        companies = sorted(user.company_ids.ids)
        if len(companies) > 1000:
            raise ProtocolError('bounded_capacity', 'Company scope exceeds 1000 companies.', 409)
        if company_id is not None:
            company_id = positive_id(company_id, 'company_id')
            if company_id not in companies:
                raise AccessError(self.env._('This work-task company is unavailable.'))
            companies = [company_id]
        return user, companies

    @api.model
    def _work_task_can_execute(self, company_id, user_id, room_id=None):
        if not self._task_can_act(company_id, user_id, room_id):
            return False
        rights = self.env['res.users'].sudo().browse(user_id)._bchat_effective_permissions()
        return bool(rights.get('task_view') and rights.get('task_manage'))

    @api.model
    def _work_task_eligible(self, company_id, user_id, room_id=None):
        candidate = self._task_eligible(company_id, user_id, room_id)
        if not self._work_task_can_execute(company_id, candidate.id, room_id):
            raise AccessError(self.env._('The assignee must be allowed to view and execute tasks.'))
        return candidate

    @api.model
    def _work_task_actions(self, task):
        user = self._require_user()
        if task.state not in ('new', 'in_progress'):
            return []
        if not user._bchat_effective_permissions().get('task_manage'):
            return []
        actions = []
        if user.id == task.assignee_id.id and self._work_task_can_execute(
                task.company_id.id, user.id, task.room_id.id or None):
            if task.state == 'new':
                actions.append('start')
            actions.append('done')
        if user.id == task.creator_id.id:
            actions += ['cancel', 'reassign']
        return actions

    @api.model
    def _work_task_data(self, task, now=None):
        now = now or fields.Datetime.now()
        data = self._task_data(task)
        data.update(
            creator_name=self._work_task_label(task.creator_id.name),
            assignee_name=self._work_task_label(task.assignee_id.name),
            company_name=self._work_task_label(task.company_id.name),
            started_at=self._task_stamp(task.started_at), done_at=self._task_stamp(task.done_at),
            cancelled_at=self._task_stamp(task.cancelled_at),
            completion_note=task.completion_note or '', done_by_id=task.done_by_id.id or None,
            done_by_name=self._work_task_label(task.done_by_id.name) if task.done_by_id else '',
            reminder_at=self._task_stamp(task.reminder_at),
            reminder_emitted_at=self._task_stamp(task.reminder_emitted_at),
            reminder_due=bool(task.state in ('new', 'in_progress') and task.reminder_at
                              and task.reminder_at <= now),
            origin_api=task.origin_api or 'tasks_v2', allowed_actions=self._work_task_actions(task))
        return wire.bounded(data, wire.TASK_BYTES)

    @api.model
    def _work_task_options(self):
        user, company_ids = self._work_task_scope()
        permissions = user._bchat_effective_permissions()
        companies = self.env['res.company'].sudo().browse(company_ids)
        return wire.bounded(self._work_task_envelope(
            companies=[{'id': company.id, 'name': self._task_label(company.name)} for company in companies],
            default_company_id=company_ids[0] if len(company_ids) == 1 else None,
            can_view=permissions['task_view'], can_manage=permissions['task_manage'],
            capabilities={'direct_done': True, 'reminders': True}), wire.OPTIONS_BYTES)

    @api.model
    def _work_task_assignees(self, company_id, q='', after_id=None):
        self._work_task_scope(company_id, manage=True)
        company_id = positive_id(company_id, 'company_id')
        q = wire.legacy._text(q, 'q', 256)
        if after_id is not None:
            after_id = positive_id(after_id, 'after_id')
        # share is Odoo's stored internal-user/group boundary. Effective task
        # switches are intersected *before* pagination, not filtered from a
        # bounded page after fetching otherwise ineligible employees.
        domain = [('active', '=', True), ('share', '=', False),
                  ('company_ids', 'in', [company_id]), ('bchat_task_view', '=', True),
                  ('bchat_task_manage', '=', True)]
        if after_id is not None:
            domain.append(('id', '>', after_id))
        if q:
            domain.append(('name', 'ilike', q))
        candidates = self.env['res.users'].sudo().search(domain, order='id', limit=51)
        page = candidates[:50]
        for candidate in page:
            self._work_task_eligible(company_id, candidate.id)
        return wire.bounded(dict(api_version=2, work_tasks_version=1, company_id=company_id,
            assignees=[{'id': row.id, 'name': self._task_label(row.name)} for row in page],
            next_after_id=page[-1].id if len(candidates) > 50 else None), wire.ASSIGNEES_BYTES)

    @api.model
    def _work_tasks(self, view='mine', state='open', company_id=None, before_id=None):
        user, companies = self._work_task_scope(company_id)
        if view not in ('mine', 'created') or state not in ('open', 'done', 'cancelled'):
            raise ProtocolError('invalid_payload', 'Unknown task list perspective or state.')
        if before_id is not None:
            before_id = positive_id(before_id, 'before_id')
        states = ['new', 'in_progress'] if state == 'open' else [state]
        perspective = 'assignee_id' if view == 'mine' else 'creator_id'
        self.env['baseer.bchat.task'].flush_model([
            'company_id', 'state', 'assignee_id', 'creator_id', 'room_id'])
        self.env['baseer.bchat.membership'].flush_model(['room_id', 'user_id', 'company_id', 'active'])
        # One bounded global page. The only formatted SQL fragment is this
        # closed server-owned column choice; every client value is a parameter.
        self.env.cr.execute(f'''
            SELECT task.id FROM baseer_bchat_task AS task
            WHERE task.company_id = ANY(%s) AND task.state = ANY(%s)
              AND task.{perspective} = %s AND (%s IS NULL OR task.id < %s)
              AND (task.room_id IS NULL OR EXISTS (
                  SELECT 1 FROM baseer_bchat_membership AS member
                  WHERE member.room_id = task.room_id AND member.user_id = %s
                    AND member.company_id = task.company_id AND member.active))
            ORDER BY task.id DESC LIMIT 31
        ''',
            [companies, states, user.id, before_id, before_id, user.id])
        ids = [row[0] for row in self.env.cr.fetchall()]
        tasks = self.env['baseer.bchat.task'].sudo().browse(ids).exists()
        # Follow the existing room-before-task lock order. Membership changes
        # or reassignment race a whole-request serialization retry, not stale
        # private data. No full history or per-company query is performed.
        for room_id in sorted(set(tasks.mapped('room_id').ids)):
            self._v2_lock_room(room_id)
        if ids:
            self.env.cr.execute('''SELECT id FROM baseer_bchat_task WHERE id = ANY(%s)
                                   ORDER BY id FOR SHARE''', [sorted(ids)])
            self.env.cr.fetchall()
            tasks.invalidate_recordset()
        for task in tasks:
            self._task_visible(task)
            if getattr(task, perspective).id != user.id:
                raise AccessError(self.env._('This task list changed. Refresh and try again.'))
        now = fields.Datetime.now()
        rows = [self._work_task_data(task, now) for task in tasks[:30]]
        return wire.page(self._work_task_envelope(view=view, company_id=company_id), rows, len(ids) > 30)

    @api.model
    def _work_task_locked(self, task_id, company_id, *, update=False):
        self._work_task_scope(company_id)
        task_id = positive_id(task_id, 'task_id')
        task = self.env['baseer.bchat.task'].sudo().browse(task_id).exists()
        self._task_visible(task)
        if task.company_id.id != company_id:
            raise AccessError(self.env._('This work-task company is unavailable.'))
        self.env.cr.execute('SELECT id FROM baseer_bchat_task WHERE id = %s FOR ' +
                            ('UPDATE' if update else 'SHARE'), [task_id])
        if not self.env.cr.fetchone():
            raise AccessError(self.env._('This work task is unavailable.'))
        task.invalidate_recordset()
        return self._task_visible(task)

    @api.model
    def _work_task_detail(self, task_id, company_id):
        task = self._work_task_locked(task_id, company_id)
        return wire.bounded(self._work_task_envelope(task=self._work_task_data(task)), wire.LIST_BYTES)

    @api.model
    def _work_task_receipt(self, task, client_uuid, replayed, operation_revision):
        return wire.bounded(self._work_task_envelope(task=self._work_task_data(task),
            client_uuid=client_uuid, replayed=replayed, operation_revision=operation_revision), wire.LIST_BYTES)

    @api.model
    def _work_task_create_replay(self, task, normalized, digest):
        task = self._work_task_locked(task.id, normalized['company_id'])
        if task.payload_digest != digest:
            raise ProtocolError('idempotency_conflict', 'The UUID belongs to another task.', 409)
        return self._work_task_receipt(task, normalized['client_uuid'], True, 1)

    @api.model
    def _work_task_fresh_create_replay(self, normalized, digest):
        with self.env.registry.cursor() as fresh_cr:
            fresh = api.Environment(fresh_cr, self.env.uid, {
                'allowed_company_ids': [normalized['company_id']],
            })
            service = fresh['baseer.bchat.service']
            service._work_task_scope(normalized['company_id'], manage=True)
            task = fresh['baseer.bchat.task'].sudo().search([
                ('creator_id', '=', fresh.uid), ('client_uuid', '=', normalized['client_uuid'])], limit=1)
            if not task:
                raise ProtocolError('idempotency_conflict', 'The UUID belongs to another task.', 409)
            return service._work_task_create_replay(task, normalized, digest)

    @api.model
    def _work_task_create(self, payload):
        normalized = wire.normalize_create(payload)
        user, _companies = self._work_task_scope(normalized['company_id'], manage=True)
        digest = wire.digest('create', 0, normalized)
        tasks = self.env['baseer.bchat.task'].sudo()
        with self.env.cr.savepoint():
            existing = tasks.search([('creator_id', '=', user.id),
                                     ('client_uuid', '=', normalized['client_uuid'])], limit=1)
            if existing:
                return self._work_task_create_replay(existing, normalized, digest)
            self._work_task_eligible(normalized['company_id'], normalized['assignee_id'])
            values = {key: value for key, value in normalized.items() if key != 'client_uuid'}
            values.update(creator_id=user.id, state='new', revision=1,
                          origin_api='work_tasks_v1', client_uuid=normalized['client_uuid'],
                          payload_digest=digest, last_actor_id=user.id,
                          last_changed_at=fields.Datetime.now())
            try:
                with self.env.cr.savepoint():
                    task = tasks._create_verified(values, _TASK_SERVICE_TOKEN)
            except UniqueViolation as error:
                if error.diag.constraint_name != 'baseer_bchat_task_creator_uuid_unique':
                    raise
                return self._work_task_fresh_create_replay(normalized, digest)
            self._task_publish_change(task, notification_action='created', actor_id=user.id)
            return self._work_task_receipt(task, normalized['client_uuid'], False, 1)

    @api.model
    def _work_task_transition(self, task_id, payload):
        normalized = wire.normalize_transition(payload)
        user, _companies = self._work_task_scope(normalized['company_id'], manage=True)
        with self.env.cr.savepoint():
            task = self._work_task_locked(task_id, normalized['company_id'], update=True)
            digest = wire.digest('transition', task.id, normalized)
            events = self.env['baseer.bchat.task.event'].sudo()
            event = events.search([('actor_id', '=', user.id),
                                   ('client_uuid', '=', normalized['client_uuid'])], limit=1)
            # Reauthenticate and validate current visibility, then settle a
            # matching receipt BEFORE terminal-state/revision checks.
            if event:
                if event.task_id.id != task.id or event.payload_digest != digest:
                    raise ProtocolError('idempotency_conflict', 'The UUID belongs to another operation.', 409)
                return self._work_task_receipt(task, normalized['client_uuid'], True, event.result_revision)
            if task.revision != normalized['expected_revision']:
                raise ProtocolError('revision_conflict', 'The task changed. Refresh before continuing.', 409)
            action = normalized['action']
            if action not in self._work_task_actions(task):
                raise AccessError(self.env._('This task action is unavailable to the current user.'))
            now = fields.Datetime.now()
            values = {'revision': task.revision + 1, 'last_actor_id': user.id, 'last_changed_at': now}
            if normalized['reason']:
                values['last_note'] = normalized['reason']
            former_assignee_id = task.assignee_id.id
            if action in ('start', 'done'):
                self._work_task_eligible(task.company_id.id, user.id, task.room_id.id or None)
                if action == 'start':
                    values.update(state='in_progress', started_at=now)
                else:
                    values.update(state='done', done_at=now, done_by_id=user.id,
                                  completion_note=normalized['reason'] or False)
            elif action == 'cancel':
                values.update(state='cancelled', cancelled_at=now)
            elif action == 'reassign':
                assignee = self._work_task_eligible(task.company_id.id, normalized['assignee_id'],
                                                    task.room_id.id or None)
                if assignee.id == task.assignee_id.id:
                    raise ProtocolError('state_conflict', 'Choose a different assignee.', 409)
                values.update(assignee_id=assignee.id, state='new', started_at=False)
            task._write_verified(values, _TASK_SERVICE_TOKEN)
            try:
                with self.env.cr.savepoint():
                    events._create_verified({
                        'task_id': task.id, 'company_id': task.company_id.id, 'actor_id': user.id,
                        'client_uuid': normalized['client_uuid'], 'payload_digest': digest,
                        'action': action, 'result_revision': values['revision'],
                        'reason': normalized['reason'] or False}, _TASK_SERVICE_TOKEN)
            except UniqueViolation as error:
                if error.diag.constraint_name != 'baseer_bchat_task_event_actor_uuid_unique':
                    raise
                raise ProtocolError('idempotency_conflict', 'The UUID belongs to another operation.', 409) from None
            self._task_publish_change(task, former_assignee_id, notification_action=action, actor_id=user.id)
            return self._work_task_receipt(task, normalized['client_uuid'], False, values['revision'])

    @api.model
    def _work_task_reminder_candidates(self, now):
        # Intersect eligibility before LIMIT as well as after locking. Fifty
        # revoked old reminders must not starve later eligible reminders.
        relation = self.env['res.users']._fields['company_ids']
        query = SQL('''
            SELECT task.id FROM baseer_bchat_task AS task
            JOIN res_users AS assignee ON assignee.id = task.assignee_id
            WHERE task.reminder_at <= %s AND task.reminder_emitted_at IS NULL
              AND task.state IN ('new', 'in_progress')
              AND assignee.active AND NOT assignee.share
              AND assignee.bchat_task_view AND assignee.bchat_task_manage
              AND EXISTS (SELECT 1 FROM %s AS scope
                          WHERE scope.%s = task.assignee_id
                            AND scope.%s = task.company_id)
              AND (task.room_id IS NULL OR EXISTS (
                  SELECT 1 FROM baseer_bchat_membership AS member
                  WHERE member.room_id = task.room_id AND member.active
                    AND member.company_id = task.company_id
                    AND member.user_id = task.assignee_id))
            ORDER BY task.reminder_at, task.id LIMIT 50
        ''', now, SQL.identifier(relation.relation), SQL.identifier(relation.column1),
            SQL.identifier(relation.column2))
        self.env['baseer.bchat.task'].flush_model([
            'reminder_at', 'reminder_emitted_at', 'state', 'assignee_id', 'company_id', 'room_id'])
        self.env['res.users'].flush_model([
            'active', 'share', 'bchat_task_view', 'bchat_task_manage', 'company_ids'])
        self.env['baseer.bchat.membership'].flush_model(['room_id', 'active', 'company_id', 'user_id'])
        self.env.cr.execute(query)
        return self.env['baseer.bchat.task'].sudo().browse([row[0] for row in self.env.cr.fetchall()])

    @api.model
    def _work_task_schedule_reminders(self):
        """Atomic queue marker; not a delivery receipt or an FCM enablement."""
        now = fields.Datetime.now()
        candidates = self._work_task_reminder_candidates(now)
        emitted = 0
        for task in candidates:
            with self.env.cr.savepoint():
                # Same source lock ordering as transition/revoke. Skip a busy
                # task so one in-flight mutation does not stall the batch.
                if task.room_id:
                    self.env['baseer.bchat.room']._lock_for_read(task.room_id.id)
                self.env.cr.execute('''SELECT id FROM baseer_bchat_task
                                       WHERE id = %s FOR UPDATE SKIP LOCKED''', [task.id])
                if not self.env.cr.fetchone():
                    continue
                task.invalidate_recordset()
                if (task.state not in ('new', 'in_progress') or task.reminder_emitted_at
                        or not task.reminder_at or task.reminder_at > now
                        or not self._work_task_can_execute(task.company_id.id, task.assignee_id.id,
                                                          task.room_id.id or None)):
                    continue
                recipient = task.assignee_id.id
                memberships = {}
                if task.room_id:
                    memberships[recipient] = self._task_member(task.room_id.id, recipient).id
                self._change_publish([recipient], 'task', task_id=task.id,
                    company_id=task.company_id.id, room_id=task.room_id.id or None,
                    memberships=memberships)
                devices = self.env['baseer.bchat.push.device'].sudo().search([
                    ('user_id', '=', recipient), ('active', '=', True)], limit=5)
                queued = self.env['baseer.bchat.push.event']._queue_verified([{
                    'recipient_id': recipient, 'device_id': device.id, 'task_id': task.id,
                    'company_id': task.company_id.id, 'event_kind': 'reminder',
                    'task_revision': task.revision, 'state': 'pending', 'next_attempt_at': now,
                } for device in devices], _PUSH_TOKEN)
                task._write_verified({'reminder_emitted_at': now}, _TASK_SERVICE_TOKEN)
                if queued:
                    queued._schedule_fast_dispatch(queued.ids)
                emitted += 1
        return emitted
