"""Locale-independent month labels for dashboard-generated text."""

# Full names suit titles and pickers; use short names for dense tables, charts and year tiles.
MONTHS_FULL = ('January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December')
MONTHS_SHORT = tuple(name[:3] for name in MONTHS_FULL)


def month_label(value, short=False, year=False):
    if isinstance(value, str):
        y, m = map(int, value.split('-')[:2])
    else:
        y, m = value.year, value.month
    if not 1 <= m <= 12:
        raise ValueError('Invalid month')
    label = (MONTHS_SHORT if short else MONTHS_FULL)[m - 1]
    return '%s %s' % (label, y) if year else label


# Existing user and noupdate event text can contain Arabic month names. Keep
# this input vocabulary here so output always uses the same English helper.
_ARABIC_MONTHS = (
    ('يناير', 'كانون الثاني'), ('فبراير', 'شباط'), ('مارس', 'آذار'),
    ('أبريل', 'إبريل', 'نيسان'), ('مايو', 'أيار'), ('يونيو', 'حزيران'),
    ('يوليو', 'تموز'), ('أغسطس', 'آب'), ('سبتمبر', 'أيلول'),
    ('أكتوبر', 'تشرين الأول'), ('نوفمبر', 'تشرين الثاني'), ('ديسمبر', 'كانون الأول'),
)


def english_months(text):
    import re
    if not text:
        return text
    for index, names in enumerate(_ARABIC_MONTHS, 1):
        for name in names:
            text = re.sub(r'(?<![\w])' + re.escape(name) + r'(?![\w])',
                          month_label('2000-%02d' % index), text)
    return text
