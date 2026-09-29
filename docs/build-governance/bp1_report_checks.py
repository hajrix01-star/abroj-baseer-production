"""BP1 sequential native PDF renders from existing QA documents, no financial writes."""
import hashlib
import io
import json
import time
from pathlib import Path
from PyPDF2 import PdfReader

assert env.cr.dbname == 'baseer_reports_qa_20260907'
output = Path('/tmp/baseer-bp1-pdfs')
output.mkdir(exist_ok=True)
result = {'status': 'FAIL', 'scope': 'Existing QA native reports; four sequential renders, not a load test', 'files': []}


def stamp():
    value = {}
    for table in ('account_move', 'account_move_line', 'hr_payslip', 'hr_payslip_line', 'res_partner'):
        env.cr.execute("SELECT count(*),md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM " + table + ' t')
        value[table] = env.cr.fetchone()
    return value


try:
    before = stamp()
    cases = [
        ('invoice-ar.pdf', 'account.report_invoice', 'account.move', [130], 'ar_001'),
        ('invoice-en.pdf', 'account.report_invoice', 'account.move', [130], 'en_US'),
        ('payslip-ar.pdf', 'om_hr_payroll.action_report_payslip', 'hr.payslip', [84], 'ar_001'),
        ('invoices-multipage.pdf', 'account.report_invoice', 'account.move', [130, 138, 146], 'en_US'),
    ]
    for filename, report_ref, model, ids, lang in cases:
        docs = env[model].browse(ids).exists()
        assert len(docs) == len(ids)
        company_ids = sorted(docs.company_id.ids)
        assert set(company_ids).issubset({6, 7, 8, 10})
        local = env(context=dict(env.context, allowed_company_ids=company_ids, lang=lang))
        # Native invoice wrapper takes language from partner.lang. Cache only;
        # never write/flush a partner change to the database.
        partners = local[model].browse(ids).partner_id if model == 'account.move' else local['res.partner']
        prior = [(partner, partner.lang) for partner in partners]
        for partner, old_lang in prior:
            local.cache.set(partner, partner._fields['lang'], lang)
        try:
            started = time.monotonic()
            content, kind = local['ir.actions.report']._render_qweb_pdf(report_ref, res_ids=ids)
            elapsed = round(time.monotonic() - started, 3)
        finally:
            for partner, old_lang in prior:
                local.cache.set(partner, partner._fields['lang'], old_lang)
        assert kind == 'pdf' and content.startswith(b'%PDF-')
        pdf = PdfReader(io.BytesIO(content))
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
        assert len(pdf.pages) >= (3 if len(ids) == 3 else 1)
        assert len(text.strip()) > 50
        (output / filename).write_bytes(content)
        result['files'].append({'file': filename, 'report': report_ref, 'document_ids': ids,
                               'company_ids': company_ids, 'language': lang, 'bytes': len(content),
                               'pages': len(pdf.pages), 'text_characters': len(text),
                               'arabic_characters': sum('\u0600' <= char <= '\u06ff' for char in text),
                               'seconds': elapsed, 'sha256': hashlib.sha256(content).hexdigest(),
                               'pdf_signature': True})
    result['unchanged_before_rollback'] = before == stamp()
    assert result['unchanged_before_rollback']
    result['status'] = 'PASS'
except Exception as error:
    result['error'] = type(error).__name__ + ': ' + str(error)
    raise
finally:
    env.cr.rollback()
    result['rollback'] = True
    if 'before' in locals():
        result['existing_rows_preserved'] = before == stamp()
    if result.get('existing_rows_preserved') is False:
        result['status'] = 'FAIL'
    env.cr.rollback()
    result['private_evidence_directory'] = '.local-backups/browser-print-20260909/pdf-evidence'
    Path('/mnt/qa-evidence/bp1-report-checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('BP1_REPORT=' + json.dumps(result), flush=True)
