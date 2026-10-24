"""Bounded presentation contract; no financial calculations or authorization here."""

from math import ceil
from odoo import _
from odoo.exceptions import ValidationError

PAGE_SIZE = 50
MAX_ROWS = 5000


def exact_selector(selector, keys):
    if type(selector) is not dict or set(selector) != set(keys):
        raise ValidationError(_('Select a valid report detail.'))


def positive_id(value):
    if type(value) is not int or value <= 0:
        raise ValidationError(_('Select a valid source.'))
    return value


def drill_result(title, value, basis, columns, rows, page=1):
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise ValidationError(_('The complete detail is too large. Select a shorter period.'))
    total = len(rows)
    if type(page) is not int or not 1 <= page <= max(1, ceil(total / PAGE_SIZE)):
        raise ValidationError(_('Select a valid detail page.'))
    if any(type(text) is not str for text in (title, value, basis)):
        raise ValidationError(_('The report detail is unavailable.'))
    if not columns or len(columns) > 12 or len({column['key'] for column in columns}) != len(columns):
        raise ValidationError(_('The report detail is unavailable.'))
    keys = {column['key'] for column in columns}
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('key'), (str, int)) or
                row['key'] in seen or type(row.get('cells')) is not dict or
                set(row['cells']) - keys or any(type(cell) is not str for cell in row['cells'].values()) or
                any(type(row[key]) is not dict for key in ('source', 'drill') if key in row)):
            raise ValidationError(_('The report detail is unavailable.'))
        seen.add(row['key'])
    return {'title': title, 'value': value, 'basis': basis, 'columns': columns,
            'rows': rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE],
            'page': page, 'page_size': PAGE_SIZE, 'total_count': total}
