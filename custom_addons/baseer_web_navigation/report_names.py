"""Presentation-only names shared by operational reports; no ORM mutation."""
import re

_ARABIC = re.compile(r'[\u0620-\u064a\u066e-\u06d3\u06fa-\u06fc]')
_LATIN = re.compile(r'[A-Za-z]')


def report_name(name, lang=None, hierarchy=False):
    if not isinstance(name, str) or not name:
        return name
    if hierarchy and ' / ' in name:
        return ' / '.join(report_name(part, lang) for part in name.split(' / '))
    parts = [part.strip() for part in name.split('|')]
    if len(parts) != 2 or not all(parts):
        return name
    arabic = [part for part in parts if _ARABIC.search(part)]
    english = [part for part in parts if _LATIN.search(part) and not _ARABIC.search(part)]
    if len(arabic) != 1 or len(english) != 1:
        return name
    return arabic[0] if (lang or '').lower().startswith('ar') else english[0]
