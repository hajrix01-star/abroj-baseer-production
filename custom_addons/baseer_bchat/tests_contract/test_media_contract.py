"""Offline checks for bounded BChat media signatures and decoding."""
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
import zipfile
from uuid import uuid4

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'bchat_media_contract_test_package'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
for name in ('contracts', 'media_contracts'):
    spec = importlib.util.spec_from_file_location('%s.%s' % (PACKAGE, name), ROOT / ('%s.py' % name))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
media = sys.modules['%s.media_contracts' % PACKAGE]


class MediaContractTests(unittest.TestCase):
    @staticmethod
    def _m4a():
        def box(kind, body):
            return (len(body) + 8).to_bytes(4, 'big') + kind + body
        return (box(b'ftyp', b'M4A \x00\x00\x00\x00isom') +
                box(b'mdat', b'\x00\x01\x02') + box(b'moov', b'sounmp4a'))

    @staticmethod
    def _office(required, content_type):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('[Content_Types].xml', content_type)
            archive.writestr(required, '<document/>')
        return output.getvalue()

    @staticmethod
    def _png():
        image = Image.new('RGB', (32, 16), (20, 40, 70))
        output = io.BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()

    def _metadata(self, raw, *, kind='image', mime='image/png', **changed):
        result = {
            'api_version': 2, 'membership_id': 9, 'upload_uuid': str(uuid4()),
            'kind': kind, 'mime': mime, 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'name': 'sample.png',
        }
        result.update(changed)
        return result

    def test_image_signature_size_hash_and_thumbnail(self):
        raw = self._png()
        metadata = media.normalize_metadata(self._metadata(raw))
        thumbnail = media.validate_bytes(metadata, raw)
        self.assertTrue(thumbnail.startswith(b'\xff\xd8\xff'))
        self.assertLessEqual(len(thumbnail), 128 * 1024)
        for changed in ({'mime': 'image/jpeg'}, {'sha256': '0' * 64}, {'size': len(raw) + 1}):
            with self.subTest(changed=changed), self.assertRaises(media.ProtocolError):
                other = media.normalize_metadata(self._metadata(raw, **changed))
                media.validate_bytes(other, raw)

    def test_pdf_is_opaque_and_bad_audio_fails_closed(self):
        raw = b'%PDF-1.7\n1 0 obj <<>> endobj\n%%EOF\n'
        pdf = media.normalize_metadata(self._metadata(raw, kind='file',
                                                        mime='application/pdf', name='receipt.pdf'))
        self.assertIsNone(media.validate_bytes(pdf, raw))
        audio = media.normalize_metadata(self._metadata(raw, kind='audio', mime='audio/mp4', name='voice.m4a'))
        with self.assertRaises(media.ProtocolError):
            media.validate_bytes(audio, raw)
        with self.assertRaises(media.ProtocolError):
            media.validate_bytes(pdf, raw[:-5] + b'abcde')

    def test_m4a_office_and_utf8_text_are_bounded_and_typed(self):
        m4a = self._m4a()
        voice = media.normalize_metadata(self._metadata(m4a, kind='audio', mime='audio/mp4', name='voice.m4a'))
        self.assertIsNone(media.validate_bytes(voice, m4a))
        for mime, name, required, content_type in (
            ('application/vnd.openxmlformats-officedocument.wordprocessingml.document',
             'note.docx', 'word/document.xml',
             'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'),
            ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
             'sheet.xlsx', 'xl/workbook.xml',
             'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'),
        ):
            raw = self._office(required, content_type)
            metadata = media.normalize_metadata(self._metadata(raw, kind='file', mime=mime, name=name))
            self.assertIsNone(media.validate_bytes(metadata, raw))
            with self.assertRaises(media.ProtocolError):
                media.validate_bytes(metadata, raw[:-4] + b'bad!')
        raw = 'مرحبا\nHello'.encode('utf-8')
        plain = media.normalize_metadata(self._metadata(raw, kind='file', mime='text/plain', name='note.txt'))
        self.assertIsNone(media.validate_bytes(plain, raw))
        bad = b'\x00\xff'
        with self.assertRaises(media.ProtocolError):
            media.validate_bytes(media.normalize_metadata(self._metadata(
                bad, kind='file', mime='text/plain', name='bad.txt')), bad)

    def test_rejects_oversize_and_bad_metadata(self):
        raw = self._png()
        for changed in ({'size': 5 * 1024 * 1024 + 1}, {'name': '../evil\n.png'},
                        {'membership_id': True}, {'unknown': 1},
                        {'mime': ['image/png']}, {'mime': {'type': 'image/png'}},
                        {'kind': ['image']}):
            with self.subTest(changed=changed), self.assertRaises(media.ProtocolError):
                media.normalize_metadata(self._metadata(raw, **changed))
        for changed in ({'kind': 'audio', 'mime': 'audio/mp4', 'name': 'voice.pdf'},
                        {'kind': 'file', 'mime': 'text/plain', 'name': 'note.xlsx'},
                        {'kind': 'file', 'mime': 'application/octet-stream'}):
            with self.subTest(changed=changed), self.assertRaises(media.ProtocolError):
                media.normalize_metadata(self._metadata(raw, **changed))


if __name__ == '__main__':
    unittest.main()
