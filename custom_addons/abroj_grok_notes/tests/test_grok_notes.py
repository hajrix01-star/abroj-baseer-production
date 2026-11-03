from datetime import datetime, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, new_test_user


class TestGrokNotes(TransactionCase):
    def test_notes_links_and_items(self):
        note = self.env['grok.note'].create({'title': 'Checklist', 'is_list': True, 'item_ids': [(0, 0, {'name': 'Later', 'sequence': 20}), (0, 0, {'name': 'First', 'sequence': 1, 'done': True})]})
        items = note.item_ids.sorted(lambda item: (item.sequence, item.id))
        self.assertEqual(items.mapped('name'), ['First', 'Later'])
        self.assertTrue(items[0].done)
        partner = self.env['res.partner'].create({'name': 'Partner'})
        project = self.env['project.project'].create({'name': 'Project'})
        for record in (partner, project):
            note.link_to(record)
            self.assertEqual(note.res_name, record.display_name)
            self.assertEqual(record.grok_note_count, 1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            note.link_to(self.env.user)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            note.write({'res_model': 'res.users'})

    def test_rules(self):
        a = new_test_user(self.env, login='grok_a', groups='base.group_user,abroj_grok_notes.group_grok_user')
        b = new_test_user(self.env, login='grok_b', groups='base.group_user,abroj_grok_notes.group_grok_user')
        manager = new_test_user(self.env, login='grok_manager', groups='base.group_user,abroj_grok_notes.group_grok_manager')
        notes = self.env['grok.note'].create([{'title': 'A', 'user_id': a.id}, {'title': 'B', 'user_id': b.id}])
        self.assertEqual(self.env['grok.note'].with_user(a).search([('id', 'in', notes.ids)]), notes[0].with_user(a))
        self.assertEqual(set(self.env['grok.note'].with_user(manager).search([('id', 'in', notes.ids)]).ids), set(notes.ids))

    def test_upsert(self):
        model = self.env['grok.note']
        payload = {'grok_uid': 'sync-test', 'title': 'Original', 'items': [{'name': 'Old'}]}
        self.assertEqual(model.grok_upsert([payload])[0]['action'], 'created')
        self.assertEqual(model.grok_upsert([payload])[0]['action'], 'skipped')
        note = model.search([('grok_uid', '=', 'sync-test')])
        self.assertEqual(len(note), 1)
        older = (datetime.utcnow() - timedelta(days=1)).isoformat()
        newer = (datetime.utcnow() + timedelta(days=1)).isoformat()
        update = dict(payload, title='Changed', items=[{'name': 'New', 'done': True}])
        self.assertEqual(model.grok_upsert([dict(update, updated_at=older)])[0]['action'], 'skipped')
        self.assertEqual(note.title, 'Original')
        self.assertEqual(model.grok_upsert([dict(update, updated_at=newer)])[0]['action'], 'updated')
        self.assertEqual(note.item_ids.mapped('name'), ['New'])
        self.assertTrue(note.item_ids.done)
