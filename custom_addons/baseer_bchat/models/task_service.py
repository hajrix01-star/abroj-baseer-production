"""Session-bound service for BChat-owned tasks, never project.task or Discuss."""
import json
import unicodedata

from psycopg2.errors import UniqueViolation

from odoo import api, fields, models
from odoo.exceptions import AccessError

from .. import task_contracts
from ..contracts import ProtocolError, positive_id
from .task import _TASK_SERVICE_TOKEN


class BChatTaskService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _task_publish_change(self, task, former_assignee_id=None):
        if task.room_id:
            members = self.env['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', task.room_id.id), ('active', '=', True),
            ], limit=2049)
            if len(members) > 2048:
                raise ProtocolError('too_many_members', 'This room exceeds its supported member limit.', 409)
            self._change_publish(members.mapped('user_id').ids, 'task',
                room_id=task.room_id.id, task_id=task.id,
                company_id=task.company_id.id,
                memberships={row.user_id.id: row.id for row in members})
        else:
            recipients = {task.creator_id.id, task.assignee_id.id}
            self._change_publish(recipients, 'task', task_id=task.id,
                                 company_id=task.company_id.id)
            if former_assignee_id and former_assignee_id not in recipients:
                self._change_publish([former_assignee_id], 'task_revoked',
                                     task_id=task.id, company_id=task.company_id.id)

    @api.model
    def _task_company(self, company_id):
        user = self._require_user()
        company_id = positive_id(company_id, 'company_id')
        if company_id not in user.company_ids.ids:
            raise AccessError(self.env._('This BChat company is unavailable.'))
        return self.with_context({
            'allowed_company_ids': [company_id],
            'lang': self.env.lang, 'tz': user.tz or 'UTC',
        })

    @api.model
    def _task_label(self, value):
        cleaned = ''.join(char for char in (value or '')
                          if not unicodedata.category(char).startswith('C')).strip()
        return cleaned[:120].encode('utf-8')[:256].decode('utf-8', 'ignore') or 'User'

    @api.model
    def _task_member(self, room_id, user_id):
        return self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room_id), ('user_id', '=', user_id), ('active', '=', True),
        ], limit=1)

    @api.model
    def _task_eligible(self, company_id, user_id, room_id=None):
        user_id = positive_id(user_id, 'assignee_id')
        user = self.env['res.users'].sudo().browse(user_id)
        if (not user.exists() or not user.active or not user._is_internal()
                or company_id not in user.company_ids.ids
                or (room_id and not self._task_member(room_id, user_id))):
            raise AccessError(self.env._('The selected BChat assignee is unavailable.'))
        return user

    @api.model
    def _task_can_act(self, company_id, user_id, room_id):
        user = self.env['res.users'].sudo().browse(user_id)
        return bool(user.exists() and user.active and user._is_internal()
                    and company_id in user.company_ids.ids
                    and (not room_id or self._task_member(room_id, user_id)))

    @api.model
    def _task_room(self, room_id, company_id):
        room = self._v2_lock_room(room_id)
        if room.company_id.id != company_id:
            raise AccessError(self.env._('This BChat room is unavailable.'))
        self._v2_current_member(room)
        return room

    @api.model
    def _task_visible(self, task):
        user = self._require_user()
        if not task.exists() or task.company_id.id not in user.company_ids.ids:
            raise AccessError(self.env._('This BChat task is unavailable.'))
        if task.room_id:
            self._task_room(task.room_id.id, task.company_id.id)
        elif user.id not in (task.creator_id.id, task.assignee_id.id):
            raise AccessError(self.env._('This BChat task is unavailable.'))
        return task

    @api.model
    def _task_stamp(self, value):
        return value.strftime('%Y-%m-%dT%H:%M:%SZ') if value else None

    @api.model
    def _task_data(self, task):
        return {
            'id': task.id, 'company_id': task.company_id.id,
            'room_id': task.room_id.id or None,
            'title': task.title, 'description': task.description or '',
            'due_at': self._task_stamp(task.due_at), 'state': task.state,
            'creator_id': task.creator_id.id,
            'creator_name': self._task_label(task.creator_id.name),
            'assignee_id': task.assignee_id.id,
            'assignee_name': self._task_label(task.assignee_id.name),
            'created_at': self._task_stamp(task.create_date),
            'updated_at': self._task_stamp(task.write_date),
            'revision': task.revision,
            'last_actor_id': task.last_actor_id.id or None,
            'last_changed_at': self._task_stamp(task.last_changed_at),
        }

    @api.model
    def _v2_task_options(self, company_id=None, room_id=None):
        user = self._require_bchat_permission('task_view')
        companies = user.company_ids
        if len(companies) > 20:
            raise ProtocolError('too_many_companies', 'Company selection needs pagination.', 409)
        response = {'api_version': 2, 'companies': [
            {'id': company.id, 'name': self._task_label(company.name)} for company in companies
        ], 'assignees': []}
        if company_id is None:
            if room_id is not None:
                raise ProtocolError('invalid_payload', 'room_id requires company_id.')
            return response
        scoped = self._task_company(company_id)
        if room_id is not None:
            room = scoped._task_room(positive_id(room_id, 'room_id'), company_id)
            members = scoped.env['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', room.id), ('active', '=', True),
            ], order='id', limit=101)
            if len(members) > 100:
                raise ProtocolError('too_many_assignees', 'Assignee selection needs pagination.', 409)
            candidates = members.mapped('user_id')
        else:
            candidates = scoped.env['res.users'].sudo().search([
                ('active', '=', True), ('share', '=', False),
                ('company_ids', 'in', [company_id]),
            ], order='id', limit=101)
            if len(candidates) > 100:
                raise ProtocolError('too_many_assignees', 'Assignee selection needs pagination.', 409)
        response['assignees'] = [
            {'id': candidate.id, 'name': scoped._task_label(candidate.name)}
            for candidate in candidates
            if scoped._task_can_act(company_id, candidate.id, room_id)
        ]
        return response

    @api.model
    def _v2_tasks(self, before_id=None, room_id=None, state=None):
        user = self._require_bchat_permission('task_view')
        if before_id is not None:
            before_id = positive_id(before_id, 'before_id')
        if room_id is not None:
            room_id = positive_id(room_id, 'room_id')
        if state is not None and state not in ('new', 'in_progress', 'done', 'cancelled'):
            raise ProtocolError('invalid_payload', 'Unknown task state.')
        if len(user.company_ids) > 20:
            raise ProtocolError('too_many_companies', 'Task listing needs company selection.', 409)
        members = self.env['baseer.bchat.membership'].sudo().search([
            ('user_id', '=', user.id), ('active', '=', True),
            ('company_id', 'in', user.company_ids.ids),
        ], limit=101)
        if len(members) > 100:
            raise ProtocolError('too_many_rooms', 'Task listing needs room pagination.', 409)
        room_ids = sorted(set(members.mapped('room_id').ids))
        if room_id is not None:
            if room_id not in room_ids:
                raise AccessError(self.env._('This BChat room is unavailable.'))
            room_ids = [room_id]
        for current in room_ids:
            self._v2_lock_room(current)
        # Re-read after room locks; revoke/join mutates the room row and causes
        # a full-request 40001 retry if this snapshot became stale.
        current_rooms = self.env['baseer.bchat.membership'].sudo().search([
            ('user_id', '=', user.id), ('active', '=', True), ('room_id', 'in', room_ids),
        ]).mapped('room_id').ids
        if room_id is not None and room_id not in current_rooms:
            raise AccessError(self.env._('This BChat room is unavailable.'))
        domain = [('company_id', 'in', user.company_ids.ids)]
        if room_id is not None:
            domain.append(('room_id', '=', room_id))
        else:
            domain += ['|', ('room_id', 'in', current_rooms), '&', ('room_id', '=', False),
                       '|', ('creator_id', '=', user.id), ('assignee_id', '=', user.id)]
        if state is not None:
            domain.append(('state', '=', state))
        if before_id is not None:
            domain.append(('id', '<', before_id))
        tasks = self.env['baseer.bchat.task'].sudo()
        found = tasks.search(domain, order='id desc', limit=31)
        if found:
            # A standalone task may be reassigned while this list is being
            # assembled. Lock only the bounded page, in ascending ID order,
            # so a concurrent transition cannot expose an obsolete assignee.
            # Under Odoo's repeatable-read isolation, an intervening update
            # raises 40001 and the whole HTTP request is retried.
            candidate_ids = sorted(found.ids)
            self.env.cr.execute('''
                SELECT id FROM baseer_bchat_task WHERE id = ANY(%s)
                ORDER BY id FOR SHARE
            ''', [candidate_ids])
            locked_ids = {row[0] for row in self.env.cr.fetchall()}
            found.invalidate_recordset()
            found = tasks.search(domain, order='id desc', limit=31)
            if not set(found.ids).issubset(locked_ids):
                raise AccessError(self.env._('This BChat task list changed. Refresh and try again.'))
        page = list(found[:30])
        more = len(found) > 30
        while page:
            payload = {'api_version': 2, 'tasks': [self._task_data(task) for task in page],
                       'next_before_id': page[-1].id if more else None}
            if len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) <= 131072:
                return payload
            page.pop()
            more = True
        return {'api_version': 2, 'tasks': [], 'next_before_id': None}

    @api.model
    def _v2_task_detail(self, task_id):
        self._require_bchat_permission('task_view')
        task_id = positive_id(task_id, 'task_id')
        task = self.env['baseer.bchat.task'].sudo().browse(task_id)
        self._task_visible(task)
        return {'api_version': 2, 'task': self._task_data(task)}

    @api.model
    def _v2_task_create(self, payload):
        self._require_bchat_permission('task_manage')
        normalized = task_contracts.normalize_create(payload)
        scoped = self._task_company(normalized['company_id'])
        user = scoped._require_user()
        with scoped.env.cr.savepoint():
            room_id = normalized['room_id']
            if room_id:
                scoped._task_room(room_id, normalized['company_id'])
            digest = task_contracts.digest('create', 0, normalized)
            tasks = scoped.env['baseer.bchat.task'].sudo()
            existing = tasks.search([('creator_id', '=', user.id),
                                     ('client_uuid', '=', normalized['client_uuid'])], limit=1)
            if existing:
                return scoped._task_create_replay(existing, digest)
            scoped._task_eligible(normalized['company_id'], normalized['assignee_id'], room_id)
            vals = {
                'company_id': normalized['company_id'], 'room_id': room_id,
                'creator_id': user.id, 'assignee_id': normalized['assignee_id'],
                'title': normalized['title'], 'description': normalized['description'],
                'due_at': normalized['due_at'], 'state': 'new', 'revision': 1,
                'client_uuid': normalized['client_uuid'], 'payload_digest': digest,
                'last_actor_id': user.id, 'last_changed_at': fields.Datetime.now(),
            }
            try:
                with scoped.env.cr.savepoint():
                    task = tasks._create_verified(vals, _TASK_SERVICE_TOKEN)
            except UniqueViolation as error:
                if error.diag.constraint_name != 'baseer_bchat_task_creator_uuid_unique':
                    raise
                return scoped._task_fresh_create_replay(normalized, digest)
            scoped._task_publish_change(task)
            return {'api_version': 2, 'client_uuid': task.client_uuid,
                    'task': scoped._task_data(task), 'replayed': False}

    @api.model
    def _task_create_replay(self, task, digest):
        if task.payload_digest != digest:
            raise ProtocolError('idempotency_conflict', 'The UUID belongs to another task.', 409)
        self._task_visible(task)
        return {'api_version': 2, 'client_uuid': task.client_uuid,
                'task': self._task_data(task), 'replayed': True}

    @api.model
    def _task_fresh_create_replay(self, normalized, digest):
        with self.env.registry.cursor() as fresh_cr:
            fresh = api.Environment(fresh_cr, self.env.uid, {
                'allowed_company_ids': [normalized['company_id']],
            })
            service = fresh['baseer.bchat.service']
            service._require_bchat_permission('task_manage')
            service._task_company(normalized['company_id'])
            existing = fresh['baseer.bchat.task'].sudo().search([
                ('creator_id', '=', fresh.uid), ('client_uuid', '=', normalized['client_uuid']),
            ], limit=1)
            if not existing:
                raise ProtocolError('idempotency_conflict', 'The UUID belongs to another task.', 409)
            return service._task_create_replay(existing, digest)

    @api.model
    def _v2_task_transition(self, task_id, payload):
        self._require_bchat_permission('task_manage')
        task_id = positive_id(task_id, 'task_id')
        normalized = task_contracts.normalize_transition(payload)
        user = self._require_user()
        with self.env.cr.savepoint():
            task = self.env['baseer.bchat.task'].sudo().browse(task_id)
            self._task_visible(task)  # Locks linked room before the task row.
            self.env.cr.execute('SELECT id FROM baseer_bchat_task WHERE id = %s FOR UPDATE', [task_id])
            if not self.env.cr.fetchone():
                raise AccessError(self.env._('This BChat task is unavailable.'))
            task.invalidate_recordset()
            self._task_visible(task)
            digest = task_contracts.digest('transition', task_id, normalized)
            event = self.env['baseer.bchat.task.event'].sudo().search([
                ('actor_id', '=', user.id), ('client_uuid', '=', normalized['client_uuid']),
            ], limit=1)
            if event:
                if event.task_id.id != task_id or event.payload_digest != digest:
                    raise ProtocolError('idempotency_conflict', 'The UUID belongs to another operation.', 409)
                return {'api_version': 2, 'task': self._task_data(task),
                        'replayed': True, 'operation_revision': event.result_revision}
            if task.revision != normalized['expected_revision']:
                raise ProtocolError('revision_conflict', 'The task changed. Refresh before continuing.', 409)
            action = normalized['action']
            if task.state in ('done', 'cancelled'):
                raise ProtocolError('state_conflict', 'This task is final.', 409)
            room_id = task.room_id.id or None
            former_assignee_id = task.assignee_id.id
            values = {'revision': task.revision + 1, 'last_actor_id': user.id,
                      'last_changed_at': fields.Datetime.now()}
            if action in ('start', 'done'):
                if task.assignee_id.id != user.id:
                    raise AccessError(self.env._('Only the current assignee may progress this task.'))
                if action == 'start' and task.state == 'new':
                    values.update(state='in_progress', started_at=fields.Datetime.now())
                elif action == 'done' and task.state == 'in_progress':
                    values.update(state='done', done_at=fields.Datetime.now())
                else:
                    raise ProtocolError('state_conflict', 'The task transition is not available.', 409)
            elif action == 'cancel':
                if task.creator_id.id != user.id:
                    raise AccessError(self.env._('Only the task creator may cancel it.'))
                values.update(state='cancelled', cancelled_at=fields.Datetime.now())
            elif action in ('reassign', 'rescue'):
                if action == 'reassign':
                    if task.creator_id.id != user.id:
                        raise AccessError(self.env._('Only the task creator may reassign it.'))
                elif (not room_id or (
                    self._task_can_act(task.company_id.id, task.assignee_id.id, room_id)
                    and self._task_can_act(task.company_id.id, task.creator_id.id, room_id)
                )):
                    raise AccessError(self.env._('Room task rescue is not available.'))
                assignee = self._task_eligible(task.company_id.id, normalized['assignee_id'], room_id)
                if assignee.id == task.assignee_id.id:
                    raise ProtocolError('state_conflict', 'Choose a different assignee.', 409)
                values.update(assignee_id=assignee.id, state='new', started_at=False)
            task._write_verified(values, _TASK_SERVICE_TOKEN)
            event_vals = {
                'task_id': task.id, 'company_id': task.company_id.id,
                'actor_id': user.id, 'client_uuid': normalized['client_uuid'],
                'payload_digest': digest, 'action': action,
                'result_revision': values['revision'], 'reason': normalized['reason'] or False,
            }
            try:
                with self.env.cr.savepoint():
                    self.env['baseer.bchat.task.event'].sudo()._create_verified(
                        event_vals, _TASK_SERVICE_TOKEN)
            except UniqueViolation as error:
                if error.diag.constraint_name != 'baseer_bchat_task_event_actor_uuid_unique':
                    raise
                raise ProtocolError('idempotency_conflict', 'The UUID belongs to another operation.', 409) from None
            self._task_publish_change(task, former_assignee_id)
            return {'api_version': 2, 'task': self._task_data(task),
                    'replayed': False, 'operation_revision': values['revision']}
