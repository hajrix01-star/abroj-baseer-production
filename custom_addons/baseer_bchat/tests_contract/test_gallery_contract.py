"""Actual pure gallery codecs/byte-bound formatter; no ORM claim."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
import re
import xml.etree.ElementTree as ET


class MultiDict(dict):
    """Only the query protocol consumed by production; no third-party install."""
    def __init__(self, pairs=(), **values):
        self.pairs = list(pairs) + list(values.items())
        super().__init__(self.pairs)

    def getlist(self, key):
        return [value for name, value in self.pairs if name == key]

ADDON = Path(__file__).resolve().parents[1]
PACKAGE = '_bwork_gallery_contract'
package = ModuleType(PACKAGE)
package.__path__ = [str(ADDON)]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(PACKAGE + '.gallery_contracts', ADDON / 'gallery_contracts.py')
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)


class GalleryContractTests(unittest.TestCase):
    def test_owl_assets_translations_and_exact_isolated_test_count(self):
        admin = ADDON.parent / 'baseer_bwork_admin'
        manifest = ast.literal_eval((admin / '__manifest__.py').read_text(encoding='utf-8'))
        self.assertEqual(manifest['depends'], ['baseer_bchat'])
        self.assertEqual(len(manifest['assets']['web.assets_backend']), 4)
        labels = set()
        root = ET.parse(admin / 'static/src/media_gallery.xml')
        isolated = {element.attrib.get('dir') for element in root.iter('bdi')}
        self.assertEqual(isolated, {'auto', 'ltr'})
        # Odoo's LibSass evaluates CSS min() early and rejects rem/% mixing.
        scss = (admin / 'static/src/media_gallery.scss').read_text(encoding='utf-8')
        self.assertNotIn('min(100%', scss)
        self.assertIn('flex-wrap: wrap', scss)
        for element in root.iter():
            for text in (element.text, element.tail, element.attrib.get('aria-label'), element.attrib.get('alt')):
                if text and re.search(r'[A-Za-z]', text):
                    labels.add(text.strip())
        labels |= set(re.findall(r'_t\("([^"]+)"\)', (ADDON / 'static/src/bwork_gallery/media_gallery.js').read_text(encoding='utf-8')))
        for language in ('ar', 'ar_001'):
            catalog = (admin / 'i18n' / (language + '.po')).read_text(encoding='utf-8')
            entries, key = {}, None
            for line in catalog.splitlines():
                if line.startswith('msgid '):
                    key = ast.literal_eval(line[6:])
                elif line.startswith('msgstr ') and key:
                    entries[key] = ast.literal_eval(line[7:])
            self.assertFalse(labels - entries.keys())
            self.assertTrue(all(entries[label] for label in labels))
        native_tests = (ADDON / 'tests/test_gallery.py').read_text(encoding='utf-8')
        for required in ("_get_asset_bundle(", "'web.assets_backend', css=True, js=False", "self.assertFalse(bundle.css_errors", ".o_bwork_media_gallery", "## CSS error message ##", "css_error_message"):
            self.assertIn(required, native_tests)
        methods = [node.name for node in ast.walk(ast.parse(native_tests))
                   if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
        workflow = (ADDON.parent.parent / '.github/workflows/test-bwork-gallery.yml').read_text(encoding='utf-8')
        self.assertEqual(len(methods), 9)
        self.assertIn('-eq 9', workflow)
        self.assertIn('odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd', workflow)

    def test_strict_query_bounds_and_unknown_duplicate_fields(self):
        self.assertEqual(wire.query(MultiDict()), dict(kind='all', order='newest', limit=30, cursor=None))
        self.assertEqual(wire.query(MultiDict(limit='60'))['limit'], 60)
        for args in (MultiDict([('kind', 'image'), ('kind', 'file')]), MultiDict(token='x'),
                     MultiDict(limit='61'), MultiDict(limit='01'), MultiDict(limit='true'),
                     MultiDict(order='random'), MultiDict(kind='video'), MultiDict(cursor='')):
            with self.subTest(args=args), self.assertRaises(wire.ProtocolError):
                wire.query(args)

    def test_cursor_is_canonical_bounded_and_scope_filter_order_bound(self):
        token = wire.cursor_for(8, 9, 'image', 'largest', 23, 2048)
        self.assertLessEqual(len(token), 256)
        self.assertEqual(wire.anchor(token, 8, 9, 'image', 'largest'), (23, 2048))
        for scope in ((7, 9, 'image', 'largest'), (8, 10, 'image', 'largest'),
                      (8, 9, 'file', 'largest'), (8, 9, 'image', 'oldest')):
            with self.assertRaises(wire.ProtocolError):
                wire.anchor(token, *scope)
        for invalid in (True, '', token + '=', 'x' * 257, '{}', 'e30'):
            with self.assertRaises(wire.ProtocolError):
                wire.anchor(invalid, 8, 9, 'image', 'largest')

    def test_byte_bound_cursor_is_last_emitted_not_last_scanned(self):
        items = [{'id': i, 'text': 'ع' * 12000, 'media': {'size': i}} for i in range(1, 15)]
        page = wire.response(8, 1, 9, 'all', 'oldest', items, False)
        self.assertLess(len(page['items']), len(items))
        self.assertGreater(len(page['items']), 0)
        self.assertLessEqual(wire.encoded_size(page), wire.MAX_BYTES)
        last = page['items'][-1]
        self.assertEqual(wire.anchor(page['next_cursor'], 8, 9, 'all', 'oldest'), (last['id'], last['media']['size']))
        self.assertEqual(len(items), 14)

    def test_no_false_empty_end_and_final_page_has_no_cursor(self):
        self.assertIsNone(wire.response(8, 1, 9, 'all', 'newest', [], False)['next_cursor'])
        row = {'id': 1, 'media': {'size': 1}}
        self.assertIsNone(wire.response(8, 1, 9, 'all', 'newest', [row], False)['next_cursor'])
        self.assertIsNotNone(wire.response(8, 1, 9, 'all', 'newest', [row], True)['next_cursor'])
        with self.assertRaises(wire.ProtocolError) as caught:
            wire.response(8, 1, 9, 'all', 'newest', [{**row, 'text': 'x' * wire.MAX_BYTES}], True)
        self.assertEqual(caught.exception.status, 413)

    def test_integer_backend_size_format_english_digits(self):
        for size, expected in ((0, '0 B'), (1023, '1023 B'), (1024, '1.00 KiB'),
                               (1048576, '1.00 MiB'), (1048576 + 524288, '1.50 MiB')):
            self.assertEqual(wire.size_label(size), expected)
        for invalid in (True, -1, 1.5):
            with self.assertRaises(ValueError):
                wire.size_label(invalid)

    def test_service_has_no_write_receipt_history_or_source_acl_shortcut(self):
        source = (ADDON / 'models/gallery_service.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_v2_gallery')
        calls = [n.func.attr for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertIn('_v2_current_member', calls)
        self.assertIn('_v2_history_payload', calls)
        self.assertNotIn('_v2_history', calls)
        self.assertNotIn('_v2_receipt_ack', calls)
        for mutation in ('create', 'write', 'unlink', '_write_verified'):
            self.assertNotIn(mutation, calls)
        for invariant in ('media.message_id = message.id', 'media.state = \'attached\'',
                          'media.company_id = message.company_id', 'member.joined_after_message_id'):
            self.assertIn(invariant, source)


if __name__ == '__main__':
    unittest.main()
