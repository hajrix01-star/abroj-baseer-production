"""BWork-owned tasks; only the private session service may mutate them."""
from odoo import api, fields, models
from odoo.exceptions import AccessError


_TASK_SERVICE_TOKEN = object()


class BWorkTask(models.Model):
    _name = 'baseer.bwork.task'
    _description = 'BWork private task'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    room_id = fields.Many2one('baseer.bwork.room', readonly=True, ondelete='restrict', index=True)
    creator_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict', index=True)
    assignee_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict', index=True)
    title = fields.Char(required=True, readonly=True, size=160)
    description = fields.Text(readonly=True)
    due_at = fields.Datetime(readonly=True)
    state = fields.Selection([
        ('new', 'New'), ('in_progress', 'In progress'),
        ('done', 'Done'), ('cancelled', 'Cancelled'),
    ], required=True, readonly=True, default='new', index=True)
    revision = fields.Integer(required=True, readonly=True, default=1)
    client_uuid = fields.Char(required=True, readonly=True, size=36)
    payload_digest = fields.Char(required=True, readonly=True, size=64)
    started_at = fields.Datetime(readonly=True)
    done_at = fields.Datetime(readonly=True)
    cancelled_at = fields.Datetime(readonly=True)
    last_actor_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    last_changed_at = fields.Datetime(readonly=True)
    last_note = fields.Char(readonly=True, size=512)
    origin_api = fields.Selection([
        ('tasks_v2', 'Legacy tasks v2'), ('work_tasks_v1', 'Work tasks v1'),
    ], required=True, readonly=True, default='tasks_v2')
    completion_note = fields.Char(readonly=True, size=512)
    done_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    reminder_at = fields.Datetime(readonly=True)
    reminder_emitted_at = fields.Datetime(readonly=True)

    _creator_uuid_unique = models.Constraint(
        'UNIQUE(creator_id, client_uuid)', 'A BWork task UUID identifies one creation.',
    )
    _revision_positive = models.Constraint('CHECK(revision > 0)', 'A task revision must be positive.')
    _digest_format = models.Constraint(
        "CHECK(payload_digest ~ '^[0-9a-f]{64}$')", 'A SHA-256 digest is required.',
    )

    def init(self):
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bwork_task_company_state_id_idx
            ON baseer_bwork_task (company_id, state, id DESC)
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bwork_task_room_id_idx
            ON baseer_bwork_task (room_id, id DESC)
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bwork_task_room_state_idx
            ON baseer_bwork_task (room_id, state)
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bwork_task_assignee_state_id_idx
            ON baseer_bwork_task (assignee_id, state, id DESC)
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bwork_task_creator_state_id_idx
            ON baseer_bwork_task (creator_id, state, id DESC)
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bwork_task_pending_reminder_idx
            ON baseer_bwork_task (reminder_at, id)
            WHERE reminder_emitted_at IS NULL AND reminder_at IS NOT NULL
              AND state IN ('new', 'in_progress')
        ''')

    @api.model
    def _cron_work_task_reminders(self):
        return self.env['baseer.bwork.service']._work_task_schedule_reminders()

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BWork task creation is unavailable.'))

    @api.model
    def _create_verified(self, vals, token):
        if token is not _TASK_SERVICE_TOKEN:
            raise AccessError(self.env._('A verified BWork task operation is required.'))
        return super(BWorkTask, self.sudo()).create(vals)

    def write(self, vals):
        raise AccessError(self.env._('Direct BWork task updates are unavailable.'))

    def _write_verified(self, vals, token):
        if token is not _TASK_SERVICE_TOKEN:
            raise AccessError(self.env._('A verified BWork task operation is required.'))
        return super(BWorkTask, self.sudo()).write(vals)

    def unlink(self):
        raise AccessError(self.env._('BWork tasks cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('BWork tasks cannot be copied.'))


class BWorkTaskEvent(models.Model):
    _name = 'baseer.bwork.task.event'
    _description = 'BWork task operation audit and idempotency receipt'
    _order = 'id desc'
    _check_company_auto = True

    task_id = fields.Many2one('baseer.bwork.task', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    actor_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict', index=True)
    client_uuid = fields.Char(required=True, readonly=True, size=36)
    payload_digest = fields.Char(required=True, readonly=True, size=64)
    action = fields.Selection([
        ('start', 'Start'), ('done', 'Done'), ('cancel', 'Cancel'),
        ('reassign', 'Reassign'), ('rescue', 'Rescue'),
    ], required=True, readonly=True)
    result_revision = fields.Integer(required=True, readonly=True)
    reason = fields.Char(readonly=True, size=512)

    _actor_uuid_unique = models.Constraint(
        'UNIQUE(actor_id, client_uuid)', 'A BWork task operation UUID identifies one mutation.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BWork task audit creation is unavailable.'))

    @api.model
    def _create_verified(self, vals, token):
        if token is not _TASK_SERVICE_TOKEN:
            raise AccessError(self.env._('A verified BWork task operation is required.'))
        return super(BWorkTaskEvent, self.sudo()).create(vals)

    def write(self, vals):
        raise AccessError(self.env._('BWork task audit is immutable.'))

    def unlink(self):
        raise AccessError(self.env._('BWork task audit cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('BWork task audit cannot be copied.'))
