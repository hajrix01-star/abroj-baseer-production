"""Real reminder race proof, only after ORM tests exit in disposable bwork_tasks_ci.

Never import from tests/__init__.py. Fresh Odoo shell avoids the TransactionCase
outer transaction holding the default digest row while a seed user subscribes.
No production cron/model is mocked; only the exactly marked fixture is removed.
"""
import logging
import unittest
from datetime import timedelta
from uuid import uuid4

from odoo import SUPERUSER_ID, Command, api, fields, sql_db
from odoo.addons.baseer_bchat.models.task import _TASK_SERVICE_TOKEN


_logger = logging.getLogger(__name__)


def _bounded(cursor):
    cursor.execute("SET LOCAL lock_timeout = '2s'")
    cursor.execute("SET LOCAL statement_timeout = '15s'")


def run(env):
    if env.cr.dbname != 'bwork_tasks_ci':
        raise RuntimeError('Refusing committed reminder probe outside disposable bwork_tasks_ci')
    check = unittest.TestCase()
    db = sql_db.db_connect(env.cr.dbname)
    marker = 'bwork-reminder-lock-' + uuid4().hex
    task_id = user_id = partner_id = None
    committed = False
    try:
        _logger.info('BWork reminder concurrency: seed')
        with db.cursor() as seed_cr:
            _bounded(seed_cr)
            seed = api.Environment(seed_cr, SUPERUSER_ID, {})
            company = seed.ref('base.main_company')
            user = seed['res.users'].with_context(no_reset_password=True).create({
                'name': marker, 'login': marker, 'company_id': company.id,
                'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set([seed.ref('base.group_user').id])],
                'bchat_task_view': True, 'bchat_task_manage': True,
            })
            user_id, partner_id = user.id, user.partner_id.id
            task = seed['baseer.bchat.task']._create_verified({
                'company_id': company.id, 'creator_id': user.id, 'assignee_id': user.id,
                'title': marker, 'client_uuid': str(uuid4()), 'payload_digest': 'a' * 64,
                'state': 'new', 'revision': 1, 'origin_api': 'work_tasks_v1',
                'reminder_at': fields.Datetime.now() - timedelta(minutes=1),
            }, _TASK_SERVICE_TOKEN)
            task_id = task.id
            seed_cr.commit()
            committed = True
        with db.cursor() as locker:
            _bounded(locker)
            locker.execute('SELECT id FROM baseer_bchat_task WHERE id=%s FOR UPDATE', [task_id])
            check.assertEqual(locker.fetchone(), (task_id,))
            with db.cursor() as worker_cr:
                _bounded(worker_cr)
                worker = api.Environment(worker_cr, SUPERUSER_ID, {})
                check.assertEqual(worker['baseer.bchat.task']._cron_work_task_reminders(), 0)
                worker_cr.execute('SELECT reminder_emitted_at FROM baseer_bchat_task WHERE id=%s', [task_id])
                check.assertIsNone(worker_cr.fetchone()[0])
                worker_cr.execute('SELECT COUNT(*) FROM baseer_bchat_change WHERE task_id=%s', [task_id])
                check.assertEqual(worker_cr.fetchone()[0], 0)
                _logger.info('BWork reminder concurrency: locked task skipped without hint/marker')
            locker.rollback()
        with db.cursor() as worker_cr:
            _bounded(worker_cr)
            worker = api.Environment(worker_cr, SUPERUSER_ID, {})
            check.assertEqual(worker['baseer.bchat.task']._cron_work_task_reminders(), 1)
            check.assertEqual(worker['baseer.bchat.task']._cron_work_task_reminders(), 0)
            worker_cr.execute('SELECT reminder_emitted_at FROM baseer_bchat_task WHERE id=%s', [task_id])
            check.assertIsNotNone(worker_cr.fetchone()[0])
            worker_cr.execute('SELECT COUNT(*) FROM baseer_bchat_change WHERE task_id=%s', [task_id])
            check.assertEqual(worker_cr.fetchone()[0], 1)
            worker_cr.commit()
            _logger.info('BWork reminder concurrency: one emission/hint/marker, no second emission')
    finally:
        if committed and task_id and user_id:
            with db.cursor() as cleanup_cr:
                _bounded(cleanup_cr)
                cleanup = api.Environment(cleanup_cr, SUPERUSER_ID, {})
                cleanup_cr.execute('SELECT title,creator_id FROM baseer_bchat_task WHERE id=%s', [task_id])
                check.assertEqual(cleanup_cr.fetchone(), (marker, user_id))
                check.assertEqual(cleanup['res.users'].browse(user_id).login, marker)
                cleanup_cr.execute('DELETE FROM baseer_bchat_change WHERE task_id=%s', [task_id])
                cleanup_cr.execute('DELETE FROM baseer_bchat_change_cursor WHERE user_id=%s', [user_id])
                cleanup_cr.execute('DELETE FROM baseer_bchat_task WHERE id=%s AND creator_id=%s AND title=%s',
                                   [task_id, user_id, marker])
                check.assertEqual(cleanup_cr.rowcount, 1)
                cleanup['res.users'].browse(user_id).unlink()
                cleanup['res.partner'].browse(partner_id).unlink()
                cleanup_cr.commit()
                _logger.info('BWork reminder concurrency: exact fixture cleaned')
    print('BWORK_TASK_REMINDER_CONCURRENCY=PASS')
