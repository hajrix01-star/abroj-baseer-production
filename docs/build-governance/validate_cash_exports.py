import json
from pathlib import Path
from pypdf import PdfReader
from openpyxl import load_workbook

root = Path(__file__).parent
checks = []
for lang in ['ar_001', 'en_US']:
    for mode in ['gross', 'net']:
        stem = f'cash_categories_{lang}_{mode}'
        payload = json.loads((root / (stem + '.json')).read_text(encoding='utf-8'))
        pdf = PdfReader(root / (stem + '.pdf'))
        fonts = []
        for page in pdf.pages:
            for font in page['/Resources'].get('/Font', {}).values():
                value = font.get_object()
                name = str(value.get('/BaseFont', ''))
                font_body = value.get('/DescendantFonts', [value])[0].get_object()
                descriptor = font_body.get('/FontDescriptor')
                embedded = bool(descriptor and any(k in descriptor.get_object() for k in ['/FontFile','/FontFile2','/FontFile3']))
                fonts.append({'name': name, 'embedded': embedded})
        if lang == 'ar_001':
            assert any('IBMPlexSansArabic' in f['name'] and f['embedded'] for f in fonts)
            assert any('IBMPlexSansArabic-Bold' in f['name'] and f['embedded'] for f in fonts)
        workbook = load_workbook(root / (stem + '.xlsx'), data_only=True)
        rows = list(workbook.active.values)
        for line in payload['lines']:
            if not line['id'].startswith('baseer-total-'):
                continue
            matches = [row for row in rows if line['name'] in row]
            assert matches, (stem, 'missing row', line['name'])
            expected = line['columns'][0]['value']
            assert any(expected in row for row in matches), (stem, line['name'], expected, matches)
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
        for amount in ['460.00' if mode == 'gross' else '400.00', '729.00', '271.00']:
            assert amount in text, (stem, 'missing PDF amount', amount)
        checks.append({'file': stem, 'pages': len(pdf.pages), 'fonts': fonts, 'xlsx_totals_match': True, 'pdf_amounts_present': True})
(root / 'cash_categories_file_checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
print('CASH_FILES_VALIDATED', len(checks))
