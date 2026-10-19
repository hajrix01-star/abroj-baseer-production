"""Execute the actual pure formatter methods without claiming an Odoo ORM run.

Run directly with Python's unittest when Odoo/PostgreSQL are unavailable.
Transaction/ACL coverage lives in test_orders.py and requires an isolated Odoo DB.
"""
import ast
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import SimpleNamespace
import unicodedata
import unittest


MODULE = Path(__file__).resolve().parents[1]


class BodyError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def source_functions(path, class_name, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    container = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    functions = [node for node in container.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for function in functions:
        function.decorator_list = []
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)


class Lines(list):
    def sorted(self, field):
        return Lines(sorted(self, key=lambda row: getattr(row, field)))


class WorkflowFormatterCase(unittest.TestCase):
    def setUp(self):
        self.namespace = {
            'Decimal': Decimal, 'ROUND_HALF_UP': ROUND_HALF_UP, 'unicodedata': unicodedata,
            'ProtocolError': BodyError, 'MAX_ROOM_MESSAGE_BYTES': 16384,
        }
        procurement = MODULE.parent / 'baseer_procurement_requests' / 'models' / 'procurement.py'
        tree = ast.parse(procurement.read_text(encoding='utf-8'))
        decimal_total = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_decimal_total')
        self.namespace['MONEY_QUANTUM'] = Decimal('0.01')
        exec(compile(ast.Module(body=[decimal_total], type_ignores=[]), str(procurement), 'exec'), self.namespace)
        source_functions(MODULE / 'models' / 'service.py', 'BChatProcurementService',
                         {'_label', '_money', '_order_room_text'}, self.namespace)
        source_functions(MODULE / 'models' / 'receipt_service.py', 'BChatReceiptService',
                         {'_receipt_result_text'}, self.namespace)
        self.service = SimpleNamespace(_label=self.namespace['_label'], _money=self.namespace['_money'])

    def order(self, count=2):
        lines = Lines()
        for number in range(1, count + 1):
            option = SimpleNamespace(product_id=SimpleNamespace(name='Material %03d' % number),
                                     name='Box', uom_id=SimpleNamespace(name='Unit', display_name='Unit'),
                                     last_price=9999)
            lines.append(SimpleNamespace(id=number, option_id=option, requested_qty=2,
                                         requested_price=1.25, actual_qty=1, actual_price=1.50))
        return SimpleNamespace(name='PR100', company_id=SimpleNamespace(name='Only this company'),
                               currency_id=SimpleNamespace(symbol='SAR', name='SAR'),
                               representative_partner_id=SimpleNamespace(display_name='Buyer'),
                               _purchase_route_label=lambda: 'Representative', line_ids=lines,
                               requested_total=Decimal('2.50') * count,
                               actual_total=Decimal('1.50') * count)

    def test_order_blocks_use_persisted_requested_prices_and_server_total(self):
        body = self.namespace['_order_room_text'](self.service, self.order())
        for expected in ('PR100', 'Only this company', 'Buyer', '1. Material 001', '2. Material 002',
                         'الكمية: 2.00 Unit', 'سعر الوحدة: 1.25 SAR', 'مجموع الصنف: 2.50 SAR', 'الإجمالي: 5.00 SAR'):
            self.assertIn(expected, body)
        self.assertNotIn('9999', body)
        self.assertNotIn('|', body)

    def test_receipt_blocks_distinguish_requested_actual_and_zero_lines(self):
        order = self.order()
        order.line_ids[1].actual_qty = 0
        order.line_ids[1].actual_price = 0
        order.actual_total = Decimal('1.50')
        body = self.namespace['_receipt_result_text'](self.service, order)
        for expected in ('2. Material 002', 'الكمية المطلوبة: 2.00 Unit', 'الكمية الفعلية: 0.00 Unit',
                         'فرق الكمية: -2.00 Unit', 'سعر الوحدة المطلوب: 1.25 SAR',
                         'سعر الوحدة الفعلي: 1.50 SAR', 'الإجمالي الفعلي: 1.50 SAR', 'فرق الإجمالي: -3.50 SAR'):
            self.assertIn(expected, body)
        self.assertNotIn('9999', body)

    def test_complete_100_lines_are_never_silently_truncated_or_split(self):
        order = self.order(100)
        for formatter in ('_order_room_text', '_receipt_result_text'):
            with self.subTest(formatter=formatter):
                self.namespace['MAX_ROOM_MESSAGE_BYTES'] = 1048576
                complete = self.namespace[formatter](self.service, order)
                self.assertIn('1. Material 001', complete)
                self.assertIn('100. Material 100', complete)
                self.namespace['MAX_ROOM_MESSAGE_BYTES'] = 16384
                if len(complete.encode('utf-8')) <= 16384:
                    self.assertEqual(self.namespace[formatter](self.service, order), complete)
                else:
                    with self.assertRaises(BodyError) as overflow:
                        self.namespace[formatter](self.service, order)
                    self.assertEqual((overflow.exception.code, overflow.exception.status), ('room_message_too_long', 413))
                for line in order.line_ids:
                    line.option_id.product_id.name = 'صنف طويل للاختبار ' * 10
                with self.assertRaises(BodyError) as overflow:
                    self.namespace[formatter](self.service, order)
                self.assertEqual((overflow.exception.code, overflow.exception.status), ('room_message_too_long', 413))
                # Each formatter receives the same original short-name fixture.
                order = self.order(100)

    def test_body_exact_utf8_limit_is_accepted_then_rejected_at_one_byte_less(self):
        for formatter in ('_order_room_text', '_receipt_result_text'):
            with self.subTest(formatter=formatter):
                self.namespace['MAX_ROOM_MESSAGE_BYTES'] = 1048576
                body = self.namespace[formatter](self.service, self.order())
                exact = len(body.encode('utf-8'))
                self.namespace['MAX_ROOM_MESSAGE_BYTES'] = exact
                self.assertEqual(self.namespace[formatter](self.service, self.order()), body)
                self.namespace['MAX_ROOM_MESSAGE_BYTES'] = exact - 1
                with self.assertRaises(BodyError):
                    self.namespace[formatter](self.service, self.order())


if __name__ == '__main__':
    unittest.main()
