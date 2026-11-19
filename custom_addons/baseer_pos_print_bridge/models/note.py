import json
from collections.abc import Mapping


def plain_note(value):
    """Render Odoo structured notes as text while preserving legacy strings."""
    if isinstance(value, str):
        original = value
        value = value.strip()
        if not value:
            return ''
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return original if value.startswith(('[', '{')) else value
        if not isinstance(parsed, list) and not (isinstance(parsed, dict) and 'text' in parsed):
            return original
        value = parsed
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ''
    texts = []
    for entry in value:
        if isinstance(entry, Mapping):
            text = entry.get('text')
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return '، '.join(texts)


def normalize_detail_notes(details):
    """Copy details, normalizing note fields that are present."""
    result = dict(details)
    for key in ('note', 'customer_note'):
        if key in result:
            result[key] = plain_note(result[key])
    return result
