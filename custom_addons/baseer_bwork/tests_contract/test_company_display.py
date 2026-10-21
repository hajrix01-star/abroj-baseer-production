"""Pure label contracts: presentation shortening cannot mutate source strings."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('company_display_contract', Path(__file__).resolve().parents[1] / 'company_display.py')
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)


class CompanyDisplayContract(unittest.TestCase):
    def test_localized_aliases_are_trimmed_bounded_and_control_free(self):
        self.assertEqual(display.short_name(' أرز '), 'أرز')
        self.assertFalse(display.short_name(' '))
        for value in (False, None):
            self.assertFalse(display.short_name(value))
        for value in (True, 1, 'x' * 65, 'a\nb', 'a\u200fb'):
            with self.assertRaises(ValueError):
                display.short_name(value)

    def test_compact_bilingual_fallback_preserves_the_original_name(self):
        legal = 'شركة مطعم أرز لتقديم الوجبات | ARZ'
        self.assertEqual(display.compact_name(legal, 'ar'), 'أرز')
        self.assertEqual(display.compact_name(legal, 'en'), 'ARZ')
        self.assertEqual(legal, 'شركة مطعم أرز لتقديم الوجبات | ARZ')
        self.assertEqual(display.compact_name('Fallback', 'ar', 'المعلم الشامي'), 'المعلم الشامي')
        self.assertEqual(display.compact_name('TEST3 | TEST3', 'en'), 'TEST3')
        self.assertEqual(display.compact_name('Unique Brand Company', 'en'), 'Unique Brand Company')
        self.assertEqual(len(display.compact_name('x' * 100, 'en')), display.FALLBACK_LIMIT)

    def test_real_preferences_producer_sanitizes_wire_not_legal_name(self):
        source = Path(__file__).resolve().parents[1] / 'models/company_display_service.py'
        module = ast.parse(source.read_text(encoding='utf-8'))
        service_class = next(node for node in module.body if isinstance(node, ast.ClassDef))
        producer = next(node for node in service_class.body if isinstance(node, ast.FunctionDef) and node.name == '_bwork_company_preferences')
        producer.decorator_list = []
        namespace = {'wire_name': display.wire_name}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[producer], type_ignores=[])), str(source), 'exec'), namespace)
        class Company:
            id = 1
            name = 'Brand\nBranch\x00\u202e'
            bwork_hidden = True
            def sudo(self):
                return self
        class Companies(list):
            def sorted(self, field):
                return self
        company = Company()
        service = SimpleNamespace(
            _require_user=lambda: SimpleNamespace(company_ids=Companies([company])),
            _bwork_company_label=lambda row, language: display.compact_name(row.name, language))
        result = namespace['_bwork_company_preferences'](service)
        self.assertEqual(result[0]['name'], 'Brand Branch')
        self.assertTrue(result[0]['hidden'])
        self.assertEqual(company.name, 'Brand\nBranch\x00\u202e')
        self.assertEqual(len(display.short_name('😀' * 64)), 64)
        self.assertEqual(len(display.wire_name('😀' * 600)), 512)

    def test_real_create_guard_rejects_context_default_metadata_too(self):
        source = Path(__file__).resolve().parents[1] / 'models/company.py'
        module = ast.parse(source.read_text(encoding='utf-8'))
        company_class = next(node for node in module.body if isinstance(node, ast.ClassDef))
        create = next(node for node in company_class.body if isinstance(node, ast.FunctionDef) and node.name == 'create')
        create.decorator_list = []
        fields = {'bwork_short_name_ar', 'bwork_short_name_en', 'bwork_hidden'}
        class GuardError(Exception):
            pass
        namespace = {'DISPLAY_FIELDS': fields, 'AccessError': GuardError}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[create], type_ignores=[])), str(source), 'exec'), namespace)
        for name in fields:
            actor = SimpleNamespace(env=SimpleNamespace(context={'default_' + name: True}, _=lambda value: value))
            with self.assertRaises(GuardError):
                namespace['create'](actor, [{'name': 'No display defaults on company creation'}])


if __name__ == '__main__':
    unittest.main()
