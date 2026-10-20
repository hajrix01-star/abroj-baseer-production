"""Bounded, Odoo-independent validation for BWork staged media."""
import hashlib
import io
import re
import unicodedata
import warnings
import zipfile

from PIL import Image, UnidentifiedImageError

from .contracts import ProtocolError, canonical_uuid, positive_id


IMAGE_LIMIT = 5 * 1024 * 1024
PDF_LIMIT = 10 * 1024 * 1024
FILE_LIMIT = 10 * 1024 * 1024
AUDIO_LIMIT = 10 * 1024 * 1024
MAX_UPLOAD_LIMIT = max(IMAGE_LIMIT, PDF_LIMIT, FILE_LIMIT, AUDIO_LIMIT)
MAX_PIXELS = 20_000_000
MIME_FORMAT = {
    'image/jpeg': 'JPEG',
    'image/png': 'PNG',
    'image/webp': 'WEBP',
}
OFFICE_FORMATS = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': (
        '.docx', 'word/document.xml',
        b'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': (
        '.xlsx', 'xl/workbook.xml',
        b'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'),
}
FILE_MIMES = {'application/pdf', 'text/plain', *OFFICE_FORMATS}


def size_limit(kind, mime):
    if kind == 'image' and mime in MIME_FORMAT:
        return IMAGE_LIMIT
    if kind == 'audio' and mime == 'audio/mp4':
        return AUDIO_LIMIT
    if kind == 'file' and mime in FILE_MIMES:
        return PDF_LIMIT if mime == 'application/pdf' else FILE_LIMIT
    raise ProtocolError('unsupported_media', 'The media type is not supported.', 415)


def normalize_metadata(payload):
    fields = {'api_version', 'membership_id', 'upload_uuid', 'kind', 'mime',
              'size', 'sha256', 'name'}
    if type(payload) is not dict or set(payload) != fields:
        raise ProtocolError('invalid_payload', 'Upload metadata fields are invalid.')
    if type(payload['api_version']) is not int or payload['api_version'] != 2:
        raise ProtocolError('unsupported_version', 'Only API version 2 is supported.')
    kind, mime = payload['kind'], payload['mime']
    if type(kind) is not str or type(mime) is not str:
        raise ProtocolError('invalid_payload', 'The media type is invalid.')
    limit = size_limit(kind, mime)
    size = payload['size']
    if type(size) is not int or size < 1 or size > limit:
        raise ProtocolError('payload_too_large', 'The file size is outside its limit.', 413)
    sha = payload['sha256']
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise ProtocolError('invalid_payload', 'A SHA-256 digest is required.')
    name = payload['name']
    if not isinstance(name, str):
        raise ProtocolError('invalid_payload', 'A filename is required.')
    name = name.replace('\\', '/').rsplit('/', 1)[-1].strip()
    try:
        name_size = len(name.encode('utf-8'))
    except UnicodeEncodeError:
        raise ProtocolError('invalid_payload', 'The filename is invalid.') from None
    if (not name or name_size > 160
            or any(unicodedata.category(char).startswith('C') for char in name)):
        raise ProtocolError('invalid_payload', 'The filename is invalid.')
    suffix = ('.m4a' if kind == 'audio' else
              '.txt' if mime == 'text/plain' else
              OFFICE_FORMATS[mime][0] if mime in OFFICE_FORMATS else None)
    if suffix and not name.lower().endswith(suffix):
        raise ProtocolError('unsupported_media', 'The filename does not match its media type.', 415)
    return {
        'membership_id': positive_id(payload['membership_id'], 'membership_id'),
        'upload_uuid': canonical_uuid(payload['upload_uuid']),
        'kind': kind, 'mime': mime, 'size': size, 'sha256': sha, 'name': name,
    }


def validate_bytes(metadata, raw):
    if not isinstance(raw, bytes) or len(raw) != metadata['size']:
        raise ProtocolError('invalid_payload', 'The file size changed during upload.')
    if hashlib.sha256(raw).hexdigest() != metadata['sha256']:
        raise ProtocolError('invalid_payload', 'The file digest does not match.')
    if metadata['kind'] == 'audio':
        _validate_m4a(raw)
        return None
    if metadata['mime'] in OFFICE_FORMATS:
        _validate_office(raw, metadata['mime'])
        return None
    if metadata['mime'] == 'text/plain':
        try:
            decoded = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ProtocolError('unsupported_media', 'Text must be UTF-8.', 415) from None
        if any(ord(char) < 32 and char not in '\r\n\t' for char in decoded):
            raise ProtocolError('unsupported_media', 'The file is not plain text.', 415)
        return None
    if metadata['kind'] == 'file':
        if not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-1024:]:
            raise ProtocolError('unsupported_media', 'The file is not a PDF.', 415)
        return None
    mime = metadata['mime']
    if ((mime == 'image/jpeg' and not raw.startswith(b'\xff\xd8\xff'))
            or (mime == 'image/png' and not raw.startswith(b'\x89PNG\r\n\x1a\n'))
            or (mime == 'image/webp' and not (raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'))):
        raise ProtocolError('unsupported_media', 'The image signature is invalid.', 415)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if (image.format != MIME_FORMAT[mime] or image.width > 6000 or image.height > 6000
                        or image.width * image.height > MAX_PIXELS):
                    raise ProtocolError('unsupported_media', 'The image dimensions are invalid.', 415)
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                image.thumbnail((256, 256))
                thumbnail = image.convert('RGB')
                for quality in (80, 65, 50, 35):
                    output = io.BytesIO()
                    thumbnail.save(output, format='JPEG', quality=quality, optimize=True)
                    if output.tell() <= 128 * 1024:
                        return output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombWarning,
            Image.DecompressionBombError):
        pass
    raise ProtocolError('unsupported_media', 'The image cannot be decoded safely.', 415)


def _validate_m4a(raw):
    """Accept the bounded AAC/MPEG-4 output made by Android MediaRecorder."""
    offset, moov, mdat = 0, None, False
    for count in range(128):
        if offset == len(raw):
            break
        if len(raw) - offset < 8:
            break
        box_size = int.from_bytes(raw[offset:offset + 4], 'big')
        box_type = raw[offset + 4:offset + 8]
        header = 8
        if box_size == 1 and len(raw) - offset >= 16:
            box_size = int.from_bytes(raw[offset + 8:offset + 16], 'big')
            header = 16
        elif box_size == 0:
            box_size = len(raw) - offset
        if box_size < header or box_size > len(raw) - offset:
            break
        body = raw[offset + header:offset + box_size]
        if offset == 0 and (box_type != b'ftyp' or len(body) < 8 or
                            not any(brand in body for brand in (b'M4A ', b'isom', b'mp42'))):
            break
        if box_type == b'moov':
            moov = body
        if box_type == b'mdat' and body:
            mdat = True
        offset += box_size
    if (offset != len(raw) or not moov or not mdat or
            b'soun' not in moov or b'mp4a' not in moov or b'vide' in moov):
        raise ProtocolError('unsupported_media', 'The recording is not supported M4A audio.', 415)


def _validate_office(raw, mime):
    _, required, content_type = OFFICE_FORMATS[mime]
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if not 1 <= len(entries) <= 2000:
                raise ValueError('entry count')
            names = {entry.filename for entry in entries}
            if (len(names) != len(entries) or '[Content_Types].xml' not in names
                    or required not in names or any(
                        entry.file_size > 10 * 1024 * 1024 or
                        entry.flag_bits & 1 or entry.compress_type not in (0, 8) or
                        entry.filename.startswith('/') or '..' in entry.filename.split('/') or
                        entry.filename.lower().endswith('vbaproject.bin')
                        for entry in entries)
                    or sum(entry.file_size for entry in entries) > 100 * 1024 * 1024):
                raise ValueError('unsafe OOXML')
            types = archive.read('[Content_Types].xml')
            if len(types) > 2 * 1024 * 1024 or content_type not in types:
                raise ValueError('wrong OOXML class')
            if len(archive.read(required)) > 10 * 1024 * 1024:
                raise ValueError('large document body')
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, EOFError):
        raise ProtocolError('unsupported_media', 'The Office file is invalid.', 415) from None
