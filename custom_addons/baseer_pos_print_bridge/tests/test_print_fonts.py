import os
import re
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models import print_fonts


@tagged('post_install', '-at_install')
class TestBundledKitchenFonts(TransactionCase):
    def test_pinned_static_faces_have_approved_weights_and_license(self):
        directory = print_fonts.font_directory()
        print_fonts._verify_assets(str(directory))
        for style, expected in [('Medium', 500), ('SemiBold', 600), ('Bold', 700)]:
            raw = (directory / ('NotoSansArabic-%s.ttf' % style)).read_bytes()
            count = struct.unpack_from('>H', raw, 4)[0]
            tables = {raw[12 + i * 16:16 + i * 16]:
                      struct.unpack_from('>II', raw, 20 + i * 16) for i in range(count)}
            self.assertNotIn(b'fvar', tables)
            self.assertEqual(struct.unpack_from('>H', raw, tables[b'OS/2'][0] + 4)[0], expected)
        self.assertIn('SIL OPEN FONT LICENSE', (directory / 'OFL.txt').read_text())

    def test_environment_is_child_only_and_temporary_config_survives_until_exit(self):
        with patch.dict(os.environ, {'FONTCONFIG_FILE': '/existing-parent-config'}):
            parent = dict(os.environ)
            with print_fonts.kitchen_font_environment() as environment:
                config = Path(environment['FONTCONFIG_FILE'])
                self.assertTrue(config.is_file())
                root = ET.parse(config).getroot()
                self.assertEqual(root.find('dir').text, str(print_fonts.font_directory()))
                self.assertEqual(root.find("match[@target='pattern']/test").get('qual'), 'first')
                self.assertEqual(os.environ['FONTCONFIG_FILE'], '/existing-parent-config')
                self.assertEqual({k: v for k, v in environment.items() if k != 'FONTCONFIG_FILE'},
                                 {k: v for k, v in parent.items() if k != 'FONTCONFIG_FILE'})
            self.assertFalse(config.exists())
            self.assertEqual(dict(os.environ), parent)

    def test_config_is_cleaned_on_renderer_exception(self):
        with self.assertRaisesRegex(RuntimeError, 'renderer failure'):
            with print_fonts.kitchen_font_environment() as environment:
                config = Path(environment['FONTCONFIG_FILE'])
                raise RuntimeError('renderer failure')
        self.assertFalse(config.exists())

    def test_missing_or_corrupt_asset_fails_without_silent_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.object(print_fonts, 'font_directory', return_value=directory):
                with self.assertRaises(ValidationError):
                    with print_fonts.kitchen_font_environment():
                        self.fail('Missing font must not reach rendering')
            for name in print_fonts.FONT_HASHES:
                (directory / name).write_bytes((print_fonts.font_directory() / name).read_bytes())
            (directory / 'NotoSansArabic-SemiBold.ttf').write_bytes(b'not a font')
            with self.assertRaises(ValidationError):
                print_fonts._verify_assets(str(directory))

    @skipUnless(shutil.which('fc-match'), 'fontconfig executable unavailable')
    def test_exact_bundled_faces_win_over_duplicate_family_and_old_primary_is_preserved(self):
        with print_fonts.kitchen_font_environment() as environment, tempfile.TemporaryDirectory() as duplicate:
            for name in print_fonts.FONT_HASHES:
                if name.endswith('.ttf'):
                    shutil.copyfile(print_fonts.font_directory() / name, Path(duplicate) / name)
            config = Path(environment['FONTCONFIG_FILE'])
            tree = ET.parse(config)
            extra = ET.Element('dir')
            extra.text = duplicate
            tree.getroot().insert(0, extra)
            tree.write(config, encoding='utf-8', xml_declaration=True)
            for style, weight in [('Medium', 100), ('SemiBold', 180), ('Bold', 200)]:
                actual = subprocess.check_output(
                    ['fc-match', 'Noto Sans Arabic:weight=%s' % weight, '-f', '%{file}'],
                    env=environment, text=True, timeout=10)
                self.assertEqual(actual, str(print_fonts.font_directory() / ('NotoSansArabic-%s.ttf' % style)))
            old_pattern = ['fc-match', 'DejaVu Sans,Noto Sans Arabic', '-f', '%{file}']
            self.assertEqual(subprocess.check_output(old_pattern, env=environment, timeout=10),
                             subprocess.check_output(old_pattern, timeout=10))

    @skipUnless(shutil.which('wkhtmltopdf'), 'Qt PDF renderer unavailable')
    def test_actual_qt_renderer_embeds_all_three_approved_faces(self):
        html = '<html><meta charset="utf-8"><body style="font-family:Noto Sans Arabic">'
        for weight in (500, 600, 700):
            html += '<div style="font-weight:%s;font-size:28px">اختبار الطباعة QA 0123456789</div>' % weight
        html += '</body></html>'
        with print_fonts.kitchen_font_environment() as environment, tempfile.TemporaryFile() as output:
            subprocess.run(['wkhtmltopdf', '--disable-local-file-access', '--disable-javascript',
                            '--quiet', '-', '-'], input=html.encode(), stdout=output,
                           stderr=subprocess.DEVNULL, env=environment, timeout=20, check=True)
            output.seek(0)
            pdf = output.read(4 * 1024 * 1024)
        names = {name.split(b'+')[-1] for name in re.findall(rb'/FontName\s*/([^\s/<>\[\]()]+)', pdf)}
        self.assertEqual(names, {b'NotoSansArabic-Medium', b'NotoSansArabic-SemiBold', b'NotoSansArabic-Bold'})
