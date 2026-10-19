"""Execute production read/controller bodies with bounded repository-only seams.

This is not an Odoo ORM, ACL, HTTP session or database runtime certificate.
The real Odoo TransactionCase/HttpCase remain in tests/ for the isolated runner.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProtocolError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def positive_id(value, label):
    if type(value) is not int or not 0 < value <= 2147483647:
        raise ProtocolError('invalid_payload', label)
    return value


def production_method(path, class_name, method_name, namespace):
    """Compile the actual function AST, not a second implementation of its body."""
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
    method.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(ROOT / path), 'exec'), namespace)
    return namespace[method_name]


class Records(list):
    def __getitem__(self, key):
        value = super().__getitem__(key)
        return Records(value) if isinstance(key, slice) else value

    def filtered(self, predicate):
        return Records(row for row in self if predicate(row))

    def with_company(self, company):
        if any(row.company_id.id != company.id for row in self):
            raise AssertionError('Serialization used another company context')
        return self


class Service:
    def __init__(self, allowed=(1, 2), receiver=True, rows=None):
        self.allowed, self.receiver, self.events = list(allowed), receiver, []
        self.rows = rows or Records(SimpleNamespace(id=number, company_id=SimpleNamespace(id=1 + number % 3),
            source_channel='bchat', state='sent') for number in range(1, 96))
        self.env = SimpleNamespace(lang='ar_001', user=SimpleNamespace(tz='UTC'))

    def _require_order_receiver(self):
        self.events.append('receiver')
        if not self.receiver:
            raise PermissionError('order_receive is required')

    def _order_read_scopes(self):
        self.events.append('companies')
        return dict.fromkeys(self.allowed)

    def _receipt_scope(self, key):
        self.events.append(('scope', key))
        if key not in self.allowed:
            raise PermissionError('foreign company')
        def summary(row):
            if row.company_id.id != key:
                raise AssertionError('Wrong serializer company')
            return {'id': row.id, 'company_id': key, 'label': 'ر' * 2}
        return SimpleNamespace(env=SimpleNamespace(company=SimpleNamespace(id=key)), _receipt_summary=summary)

    def with_context(self, context):
        self.events.append(('context', context))
        return SimpleNamespace(env={'baseer.procurement.request': self})

    def sudo(self):
        self.events.append('sudo')
        return self

    def search(self, domain, order, limit):
        self.events.append(('search', domain, order, limit))
        def matches(row):
            for name, operator, value in domain:
                actual = row.company_id.id if name == 'company_id' else getattr(row, name)
                if not ({'in': lambda: actual in value, '=': lambda: actual == value, '<': lambda: actual < value}[operator]()):
                    return False
            return True
        return Records(sorted((row for row in self.rows if matches(row)), key=lambda row: row.id, reverse=True)[:limit])


SERVICE_GLOBALS = {'json': json, 'positive_id': positive_id, 'ProtocolError': ProtocolError,
                   'RECEIPT_PAGE_SIZE': 30, 'MAX_RESPONSE_BYTES': 65536}
Service.read = production_method('models/receipt_service.py', 'BChatReceiptService', '_v2_receipts_all', SERVICE_GLOBALS)


class GlobalReceiptContract(unittest.TestCase):
    def test_authorization_precedes_one_bounded_global_query_and_cursor(self):
        service = Service()
        first = service.read()
        self.assertEqual(len(first['orders']), 30)
        self.assertEqual(first['next_before_id'], first['orders'][-1]['id'])
        self.assertEqual({row['company_id'] for row in first['orders']}, {1, 2})
        self.assertEqual(service.events[0], 'receiver')
        sudo = service.events.index('sudo')
        self.assertLess(service.events.index(('scope', 1)), sudo)
        self.assertLess(service.events.index(('scope', 2)), sudo)
        searches = [event for event in service.events if isinstance(event, tuple) and event[0] == 'search']
        self.assertEqual(len(searches), 1, 'no per-company fan-out')
        self.assertEqual(searches[0][2:], ('id desc', 31))
        second = service.read(first['next_before_id'])
        self.assertTrue(all(row['id'] < first['next_before_id'] for row in second['orders']))
        self.assertFalse({row['id'] for row in first['orders']} & {row['id'] for row in second['orders']})

    def test_company_state_channel_and_authority_remain_explicit(self):
        service = Service()
        service.rows.extend([SimpleNamespace(id=100 + index, company_id=SimpleNamespace(id=1), source_channel=channel, state=state)
                             for index, (channel, state) in enumerate([('odoo', 'sent'), ('bchat', 'purchased'), ('bchat', 'cancel')])])
        page = service.read(company_id=1)
        self.assertEqual({row['company_id'] for row in page['orders']}, {1})
        self.assertTrue(all(row['id'] < 100 for row in page['orders']))
        for denied in [Service(receiver=False), Service(allowed=(1,))]:
            with self.assertRaises(PermissionError):
                denied.read(company_id=2)
            self.assertNotIn('sudo', denied.events)
        with self.assertRaises(ProtocolError):
            service.read(before_id=0)

    def test_response_bytes_are_bounded_in_actual_method(self):
        service = Service()
        original = SERVICE_GLOBALS['MAX_RESPONSE_BYTES']
        try:
            SERVICE_GLOBALS['MAX_RESPONSE_BYTES'] = 10
            with self.assertRaises(ProtocolError) as error:
                service.read()
            self.assertEqual(error.exception.code, 'page_too_large')
        finally:
            SERVICE_GLOBALS['MAX_RESPONSE_BYTES'] = original

    def test_actual_controller_preserves_legacy_and_explicit_all_and_rejects_unknown_scope(self):
        class Api:
            args = {}
            calls = []
            def _args(self, allowed):
                if any(key not in allowed for key in self.args):
                    raise ProtocolError('invalid_payload', 'query')
                return self.args
            def _id(self, value, label):
                return positive_id(int(value), label)
            def _service(self):
                return self
            def _v2_receipts_all(self, before, company_id=None):
                self.calls.append(('all', before, company_id))
                return {'all': True}
            def _v2_receipts(self, company, before):
                self.calls.append(('legacy', company, before))
                return {'legacy': True}
            def _response(self, payload):
                return payload
            def _error(self, error):
                return {'error': error.code}
        namespace = {'BChatOrderApi': Api, 'ProtocolError': ProtocolError,
                     'AccessError': PermissionError, 'ValidationError': ValueError, 'UserError': RuntimeError}
        controller = production_method('controllers/receipts.py', 'BChatReceiptApi', 'receipts', namespace)
        for args, expected in [({'scope': 'all'}, ('all', None, None)),
                               ({'scope': 'all', 'company_id': '2', 'before_id': '80'}, ('all', 80, 2)),
                               ({'company_id': '1'}, ('legacy', 1, None))]:
            Api.args = args
            controller(None)
            self.assertEqual(Api.calls[-1], expected)
        before = len(Api.calls)
        for args in [{}, {'before_id': '80'}, {'scope': 'mine'}, {'scope': 'all', 'company_id': '0'}, {'scope': 'all', 'unknown': '1'}]:
            Api.args = args
            self.assertEqual(controller(None), {'error': 'invalid_payload'})
        self.assertEqual(len(Api.calls), before)


if __name__ == '__main__':
    unittest.main()
