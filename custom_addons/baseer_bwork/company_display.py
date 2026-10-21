"""Presentation-only company labels; never rewrite an Odoo legal name."""
import re
import unicodedata

SHORT_NAME_LIMIT = 64
FALLBACK_LIMIT = 48


def wire_name(value):
    """Safe canonical display copy; the stored legal name is never modified."""
    value = ' '.join((value or '').split())
    return ''.join(char for char in value if not unicodedata.category(char).startswith('C')).strip()[:512]


def short_name(value):
    if value is False or value is None:
        return False
    if not isinstance(value, str):
        raise ValueError('invalid_company_short_name')
    value = value.strip()
    if len(value) > SHORT_NAME_LIMIT or any(
            unicodedata.category(char).startswith('C') for char in value):
        raise ValueError('invalid_company_short_name')
    return value or False


def compact_name(name, language, localized=None):
    """Prefer explicit language fields/pipe sides; strip only known wrappers."""
    value = (localized or '').strip()
    if not value:
        parts = [part.strip() for part in (name or '').split('|') if part.strip()]
        has_arabic = lambda text: bool(re.search(r'[\u0600-\u06ff]', text))
        preferred = [part for part in parts if has_arabic(part) == (language == 'ar')]
        value = (preferred or parts or [''])[0]
    value = wire_name(value)
    if language == 'ar':
        value = re.sub(r'^(?:(?:شركة|مؤسسة|مطعم|مطاعم)\s+)+', '', value)
        value = re.sub(r'\s+(?:لتقديم الوجبات|التجارية|للمقاولات)$', '', value).strip()
    return value if len(value) <= FALLBACK_LIMIT else value[:FALLBACK_LIMIT - 1].rstrip() + '…'
