"""Prepare BP1 translations and isolated QA overlay (no business data)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
addon = ROOT / 'custom_addons/baseer_browser_print'
terms = {
    'Print report': 'طباعة التقرير', 'Print': 'طباعة', 'Download PDF': 'تحميل PDF',
    'Close': 'إغلاق', 'PDF preview': 'معاينة PDF',
    'Alternative preview': 'معاينة بديلة',
    "If the print window does not open, use the PDF viewer's print button or download the PDF.": 'إذا لم تفتح نافذة الطباعة، استخدم زر الطباعة داخل عارض PDF أو حمّل الملف.',
    'The PDF could not be prepared. Check your connection and access, then try again.': 'تعذر تجهيز PDF. تحقق من الاتصال وصلاحية الوصول، ثم أعد المحاولة.',
    'The server did not return a valid PDF report.': 'لم يُرجع الخادم تقرير PDF صالحًا.',
    'Preparing the report took too long. Try a smaller selection.': 'استغرق تجهيز التقرير وقتًا طويلًا. جرّب تحديد عدد أقل من السجلات.',
}
lines = ['msgid ""', 'msgstr ""', '"Project-Id-Version: Odoo 19.0\\n"',
         '"Language: ar_001\\n"', '"Content-Type: text/plain; charset=UTF-8\\n"', '']
for source, translated in terms.items():
    owner = 'report_transport.js' if source.startswith(('The ', 'Preparing ')) else 'print_dialog.js'
    lines += ['#. module: baseer_browser_print', '#. odoo-javascript',
              '#: code:addons/baseer_browser_print/static/src/' + owner + ':0',
              'msgid ' + json.dumps(source), 'msgstr ' + json.dumps(translated, ensure_ascii=False), '']
(addon / 'i18n').mkdir(exist_ok=True)
(addon / 'i18n/ar.po').write_text('\n'.join(lines), encoding='utf8')

back = ROOT / '.local-backups/browser-print-20260909'
back.mkdir(exist_ok=True)
existing = (ROOT / '.local-backups/sales-dashboard-application-share-20260909/compose.qa.yaml').read_text(encoding='utf8')
# Preserve QA's accepted mounts and dashboard demo data; add only the new addon.
existing = existing.replace('    command:', '      - ./custom_addons/baseer_browser_print:/mnt/sales-dashboard-addons/baseer_browser_print:ro\n    command:')
(back / 'compose.qa.yaml').write_text(existing, encoding='utf8')
print('BP1 translations and QA overlay ready')
