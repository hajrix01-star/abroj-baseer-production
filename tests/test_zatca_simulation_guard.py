"""Exercise the actual request guard without loading Odoo or making HTTP calls."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class SimulationRequestGuard(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'ops/qa/zatca-simulation-onboard.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'qa_simulation_onboard')
        functions = [n for n in helper.body if isinstance(n, ast.FunctionDef) and n.name in ('check', 'guarded_request')]
        self.base = 'https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation/'
        self.active = {'failed': False, 'requests': [], 'bodies': set()}
        self.delegate = Mock()
        namespace = {'hashlib': hashlib, 'json': json, 'active': self.active,
                     'base': self.base, 'sequence': ['compliance'] + ['compliance/invoices'] * 6 + ['production/csids'],
                     'original_request': self.delegate}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
        self.request = namespace['guarded_request']
        self.session = SimpleNamespace(get_adapter=lambda url: SimpleNamespace(max_retries=SimpleNamespace(total=0)))

    def assert_followup_blocked(self):
        with self.assertRaises(RuntimeError):
            self.request(self.session, 'POST', self.base + 'compliance/invoices', data='different-body')
        self.assertEqual(self.delegate.call_count, 1)
        self.assertEqual(len(self.active['requests']), 1)

    def test_http_400_latches_failure_before_any_later_request(self):
        response = SimpleNamespace(status_code=400, url=self.base + 'compliance')
        self.delegate.return_value = response
        self.assertIs(self.request(self.session, 'POST', response.url, data='first-body'), response)
        self.assertTrue(self.active['failed'])
        self.assertEqual(self.active['requests'][0]['status'], 400)
        self.assertFalse(self.delegate.call_args.kwargs['allow_redirects'])
        self.assert_followup_blocked()

    def test_transport_exception_keeps_failure_latched(self):
        self.delegate.side_effect = TimeoutError('controlled test failure')
        with self.assertRaises(TimeoutError):
            self.request(self.session, 'POST', self.base + 'compliance', data='first-body')
        self.assertTrue(self.active['failed'])
        self.assertEqual(self.active['requests'][0]['code'], 'transport_error')
        self.assertIsNone(self.active['requests'][0]['status'])
        self.assert_followup_blocked()

    def test_production_url_is_rejected_before_delegation(self):
        with self.assertRaises(RuntimeError):
            self.request(self.session, 'POST', 'https://gw-fatoora.zatca.gov.sa/e-invoicing/core/compliance', data='first-body')
        self.delegate.assert_not_called()
        self.assertEqual(self.active['requests'], [])


if __name__ == '__main__':
    unittest.main()
