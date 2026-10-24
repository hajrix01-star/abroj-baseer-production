"""Small adapter helpers: type existing source values, never calculate balances."""

from decimal import Decimal
import re

from odoo import _, fields
from odoo.exceptions import AccessError, ValidationError

from .report_document import MAX_CELLS, MAX_ROWS, validate_document


_MONEY = re.compile(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\Z', re.ASCII)


def source_money(value):
    """Lossless normalization of an authoritative decimal or formatted string."""
    if value is None:
        return None
    if isinstance(value, Decimal) and value.is_finite():
        return value
    if type(value) is str and len(value) <= 80 and _MONEY.fullmatch(value):
        return Decimal(value.replace(',', ''))
    raise ValidationError(_('An amount cannot be exported safely.'))


def require_active_filters(env, filters, allowed):
    """Outer transport scope; provider must still validate its own source filters."""
    if type(filters) is not dict or set(filters) - (set(allowed) | {'company_id'}):
        raise ValidationError(_('Select valid report filters.'))
    if type(filters.get('company_id')) is not int or filters['company_id'] != env.company.id:
        raise AccessError(_('Export the report for the active company only.'))
    env.company.check_access('read')


def export_document(env, title, columns, rows, metadata=None, notes=None):
    """Common envelope only; values and ordering stay with each report provider."""
    company = env.company
    arabic = (env.context.get('lang') or env.user.lang or '').startswith('ar')
    if len(rows) > MAX_ROWS or len(rows) * len(columns) > MAX_CELLS:
        raise ValidationError(
            'التقرير الكامل أكبر من حد التصدير. اختر فترة أقصر أو قلّل فترات المقارنة.'
            if arabic else
            'The complete report exceeds the export limit. Select a shorter period or fewer comparison periods.')
    document = {
        'title': title, 'company': company.name, 'currency': company.currency_id.name,
        'lang': 'ar' if arabic else 'en', 'decimals': company.currency_id.decimal_places,
        'columns': columns, 'rows': rows, 'notes': list(notes or []),
        'metadata': list(metadata or []) + [
            ('وقت التصدير UTC' if arabic else 'Exported UTC', fields.Datetime.to_string(fields.Datetime.now()))],
    }
    try:
        return validate_document(document)
    except ValueError as error:
        raise ValidationError(_('The full report cannot be exported safely. Select a shorter period or check its numeric precision.')) from error
