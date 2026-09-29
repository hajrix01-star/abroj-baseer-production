"""Standalone artifact checks: page orientation, fonts, column-aligned values."""
import json
from decimal import Decimal
from pathlib import Path
from openpyxl import load_workbook
from pypdf import PdfReader

root = Path(__file__).parent
checks = []
for suffix in ('ar_gross', 'ar_net', 'en_gross', 'en_net', 'ar_year'):
    prefix = 'cash_monthly_' + suffix
    payload = json.loads((root / (prefix+'.json')).read_text(encoding='utf-8'))
    pdf = PdfReader(root / (prefix+'.pdf'))
    assert all(p.mediabox.width < p.mediabox.height for p in pdf.pages), prefix
    text = '\n'.join(p.extract_text() for p in pdf.pages)
    assert ('169.25%' if suffix.endswith('net') else '158.91%') in text.replace(' ', ''), prefix
    fonts = set()
    embedded = set()
    for page in pdf.pages:
        for ref in page['/Resources'].get('/Font', {}).values():
            font = ref.get_object()
            name = str(font.get('/BaseFont', ''))
            fonts.add(name)
            candidates = [font] + [f.get_object() for f in font.get('/DescendantFonts', [])]
            for item in candidates:
                descriptor = item.get('/FontDescriptor')
                if descriptor and any(k in descriptor.get_object() for k in ('/FontFile', '/FontFile2', '/FontFile3')):
                    embedded.add(name)
    if suffix.startswith('ar'):
        assert any('IBMPlexSansArabic' in name for name in embedded), fonts
        assert any('IBMPlexSansArabic-Bold' in name for name in embedded), fonts
    wb = load_workbook(root / (prefix+'.xlsx'), data_only=True)
    sheet = wb.active
    headers = [col['name'] for col in payload['columns']]
    start = next(i for i in range(1, sheet.max_row+1)
                 if [sheet.cell(i, j+1).value for j in range(len(headers))] == headers) + 1
    for index, row in enumerate(payload['lines']):
        assert sheet.cell(start+index, 1).value == row['name']
        for j, source in enumerate(row['columns'], 2):
            actual = sheet.cell(start+index, j)
            expected = source['value']
            if expected is None:
                assert actual.value is None, (prefix, row['id'], j, actual.value)
            elif isinstance(expected, (int, float)):
                assert Decimal(str(actual.value)) == Decimal(str(expected)), (prefix, row['id'], j)
            else:
                assert actual.value == expected
            if headers[j-1] == headers[-1] and expected is not None:
                assert actual.number_format == '0.00"%"', (prefix, row['id'])
    checks.append(dict(file=prefix, pages=len(pdf.pages), portrait=True, rows=len(payload['lines']),
                       columns=len(headers), exact_excel_cells=True, embedded_fonts=sorted(embedded)))
original = PdfReader(root / 'cash_monthly_original_pnl.pdf')
assert all(page.mediabox.width > page.mediabox.height for page in original.pages)
checks.append(dict(file='cash_monthly_original_pnl', landscape=True, injected_context_ignored=True))
(root / 'cash_monthly_file_checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
print('MONTHLY_FILES_SUCCESS', checks)
