"""Release-local OFL fonts for the kitchen renderer; no system installation."""
import hashlib
import os
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from odoo import _
from odoo.exceptions import ValidationError


FONT_FAMILY = 'Noto Sans Arabic'
PRIVATE_FAMILY = 'Baseer Bundled Noto Sans Arabic'
FONT_HASHES = {
    'NotoSansArabic-Medium.ttf': '60b7f433bd5f3e0b317eb3715d9f4ef74980132afbcc7fb2aee959c94c8af787',
    'NotoSansArabic-SemiBold.ttf': '784bfd6b3f573eab6bc621fd0e3897a6216eb8a3ea6521b77c2218e5aadf0231',
    'NotoSansArabic-Bold.ttf': 'fad3cb45bef32b97cfa5c132576fe3426ab349bd9fb6f64a6879eaafd9070428',
    'OFL.txt': '07fc70bfeb985cc1a87a8587d0a0c80bab11c86c9dc3fd95b6f0cb332f983e96',
}


def font_directory():
    return Path(__file__).resolve().parents[1] / 'static' / 'src' / 'fonts' / 'noto_arabic'


@lru_cache(maxsize=8)
def _verify_assets(directory):
    # Deployment paths are immutable and workers restart when a release changes.
    for name, expected in FONT_HASHES.items():
        asset = Path(directory) / name
        try:
            if asset.is_symlink() or not 0 < asset.stat().st_size <= 512 * 1024:
                raise ValueError('Invalid font asset')
            if hashlib.sha256(asset.read_bytes()).hexdigest() != expected:
                raise ValueError('Invalid font asset checksum')
        except (OSError, ValueError) as error:
            raise ValidationError(_('The bundled kitchen font is missing or invalid.')) from error


@contextmanager
def kitchen_font_environment():
    directory = str(font_directory())
    _verify_assets(directory)
    root = ET.Element('fontconfig')
    # Keep the installed system fonts and existing writable user cache behavior.
    ET.SubElement(root, 'include').text = '/etc/fonts/fonts.conf'
    ET.SubElement(root, 'dir').text = directory
    # Give only the pinned release faces an extra family name. Do not modify TTFs.
    scan = ET.SubElement(root, 'match', target='scan')
    test = ET.SubElement(scan, 'test', name='file', compare='contains')
    ET.SubElement(test, 'string').text = directory + os.sep
    edit = ET.SubElement(scan, 'edit', name='family', mode='prepend', binding='strong')
    ET.SubElement(edit, 'string').text = PRIVATE_FAMILY
    # A DejaVu-first historical snapshot must retain its original first choice.
    pattern = ET.SubElement(root, 'match', target='pattern')
    test = ET.SubElement(pattern, 'test', name='family', qual='first')
    ET.SubElement(test, 'string').text = FONT_FAMILY
    edit = ET.SubElement(pattern, 'edit', name='family', mode='prepend', binding='strong')
    ET.SubElement(edit, 'string').text = PRIVATE_FAMILY
    with tempfile.TemporaryDirectory(prefix='baseer-kitchen-font-') as temporary:
        config = Path(temporary) / 'fonts.conf'
        ET.ElementTree(root).write(config, encoding='utf-8', xml_declaration=True)
        environment = os.environ.copy()
        environment['FONTCONFIG_FILE'] = str(config)
        yield environment
