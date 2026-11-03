import importlib.util
import json
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('sync_notes', 'tools/grok_notes_sync/sync_notes.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncTest(unittest.TestCase):
    def test_normalize_color(self):
        for index, key in enumerate(sync.COLOR_KEYS):
            for value in (index, str(index), key):
                with self.subTest(value=value):
                    self.assertEqual(sync.normalize_color(value), key)
        for value in (True, False, -1, 12, '12', '-1', 'RED', '', None, 1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sync.normalize_color(value)

    @patch.dict('os.environ', {'ODOO_API_KEY': 'secret'})
    @patch.object(sync.xmlrpc.client, 'ServerProxy')
    def test_push_normalizes_and_validates_colors(self, server):
        for confirm in (False, True):
            server.reset_mock()
            server.return_value.execute_kw.return_value = []
            with patch('builtins.open', unittest.mock.mock_open(read_data='[{"grok_uid":"x", "color":"7"}]')), patch('sys.stdout'):
                sync.main(['push', '--file', 'pending.json'] + (['--confirm'] if confirm else []))
            if confirm:
                self.assertEqual(server.return_value.execute_kw.call_args.args[5][0][0]['color'], 'darkblue')
            with patch('builtins.open', unittest.mock.mock_open(read_data='[{"grok_uid":"x", "color":true}]')), self.assertRaises(ValueError):
                sync.main(['push', '--file', 'pending.json'] + (['--confirm'] if confirm else []))

    @patch.dict('os.environ', {'ODOO_API_KEY': 'secret'})
    @patch.object(sync.xmlrpc.client, 'ServerProxy')
    def test_pull_includes_color_index(self, server):
        server.return_value.execute_kw.return_value = [{
            'id': 1, 'grok_uid': 'x', 'title': 'X', 'body': '', 'is_list': False,
            'color': 'purple', 'pinned': False, 'res_model': False, 'res_id': 0,
            'res_name': False, 'active': True, 'label_ids': [], 'item_ids': [],
            'write_date': '2025-01-01 00:00:00',
        }]
        with patch('sys.stdout') as stdout:
            sync.main(['pull'])
        line = stdout.write.call_args_list[0].args[0]
        note = json.loads(line[len('const NOTES_ODOO: any = '):-1])[0]
        self.assertEqual((note['color'], note['color_index']), ('purple', 8))

    def test_js_line(self):
        line = sync.build_js_line([{'title': 'ملاحظة'}])
        self.assertEqual(json.loads(line[len('const NOTES_ODOO: any = '):-1]), [{'title': 'ملاحظة'}])

    def test_plan(self):
        existing = [{'grok_uid': 'a', 'write_date': '2025-01-01 00:00:00'}]
        notes = [{'grok_uid': 'new'}, {'grok_uid': 'a'}, {'grok_uid': 'a', 'updated_at': '2025-01-01T03:00:00+03:00'}, {'grok_uid': 'a', 'updated_at': '2025-01-02T00:00:00Z'}]
        self.assertEqual([p['action'] for p in sync.plan_push(notes, existing)], ['would-create', 'would-skip', 'would-skip', 'would-update'])
        with self.assertRaises(ValueError):
            sync.plan_push([{}], [])

    @patch.dict('os.environ', {'ODOO_API_KEY': 'secret'})
    @patch.object(sync.xmlrpc.client, 'ServerProxy')
    @patch('builtins.open', new_callable=unittest.mock.mock_open, read_data='[{"grok_uid":"x"}]')
    def test_dry_run_read_only(self, opened, server):
        server.return_value.execute_kw.return_value = []
        with patch('sys.stdout'):
            sync.main(['push', '--file', 'pending.json'])
        calls = server.return_value.execute_kw.call_args_list
        self.assertEqual([call.args[4] for call in calls], ['search_read'])


if __name__ == '__main__':
    unittest.main()
