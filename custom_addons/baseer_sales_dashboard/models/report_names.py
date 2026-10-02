"""Presentation-only labels; never rename source records or grouping keys."""
import re

_ARABIC = re.compile(r'[\u0620-\u064a\u066e-\u06d3\u06fa-\u06fc]')
_LATIN = re.compile(r'[A-Za-z]')


def report_name(name, lang=None):
    """Select an explicit Arabic | English pair, preserving ambiguous labels."""
    if not name or '|' not in name:
        return name
    parts = [part.strip() for part in name.split('|')]
    if len(parts) != 2 or not all(parts):
        return name
    arabic = [part for part in parts if _ARABIC.search(part)]
    english = [part for part in parts if _LATIN.search(part) and not _ARABIC.search(part)]
    if len(arabic) != 1 or len(english) != 1:
        return name
    return arabic[0] if (lang or '').lower().startswith('ar') else english[0]
