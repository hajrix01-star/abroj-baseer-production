import importlib.util
import json
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('sync_notes', 'tools/grok_notes_sync/sync_notes.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncTest(unittest.TestCase):
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
