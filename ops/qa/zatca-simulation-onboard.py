"""Execute once through native QA Odoo shell; OTP mapping is injected via stdin."""
import hashlib
import json
import re

import requests


def qa_simulation_onboard(env, otps):
    def check(condition):
        if not condition:
            raise RuntimeError('QA Simulation guard failed')

    targets = {18: 2, 28: 3, 414: 56}
    english = {2: 'Al Moallem Al Shami', 3: 'Doha Consumer'}
    base = 'https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation/'
    sequence = ['compliance'] + ['compliance/invoices'] * 6 + ['production/csids']
    result = {'ok': False, 'journals': [], 'code': 'preflight_failed'}
    original_request, active = requests.Session.request, None
    identities, temporary, documents = [], set(), None

    def identity(record):
        fields = {'name', 'baseer_name_ar', 'baseer_name_en', 'vat', 'company_registry',
                  'street', 'street2', 'city', 'zip', 'state_id', 'country_id'}
        fields.update(k for k in record._fields if k.startswith('l10n_sa_') and any(
            word in k for word in ('building', 'plot', 'identification', 'subdivision', 'crn')))
        return {k: record[k].id if record._fields[k].type == 'many2one' else record[k]
                for k in fields if k in record._fields}

    def unchanged():
        check(all(identity(record) == values for record, values in identities))
        check((env['account.move'].sudo().search_count([]),
               env['account.edi.document'].sudo().search_count([])) == documents)

    def guarded_request(session, method, url, **kwargs):
        check(active is not None and not active['failed'] and method.upper() == 'POST')
        index = len(active['requests'])
        check(index < 8 and url == base + sequence[index])
        check(session.get_adapter(url).max_retries.total == 0)
        body = kwargs.get('data')
        body = json.dumps(body, sort_keys=True).encode() if isinstance(body, dict) else body
        body = body.encode() if isinstance(body, str) else body
        check(isinstance(body, bytes))
        fingerprint = hashlib.sha256(body).digest()
        check(fingerprint not in active['bodies'])
        active['bodies'].add(fingerprint)
        entry = {'count': index + 1, 'status': None, 'code': 'transport_error'}
        active['requests'].append(entry)
        kwargs['allow_redirects'] = False
        active['failed'] = True
        response = original_request(session, method, url, **kwargs)
        entry.update(status=response.status_code, code='HTTP_' + str(response.status_code))
        check(response.url == url)
        if 200 <= response.status_code < 300:
            active['failed'] = False
        return response

    try:
        check(env.cr.dbname == 'baseer_qa_20261023')
        check(env['ir.config_parameter'].sudo().get_param('database.is_neutralized', '').lower() == 'true')
        check(isinstance(otps, dict) and set(otps) == {'18', '28', '414'})
        check(all(isinstance(v, str) and re.fullmatch(r'[0-9]{6}', v) for v in otps.values()))
        modules = env['ir.module.module'].sudo()
        check(modules.search_count([('name', 'in', ['account_edi', 'base_vat', 'certificate', 'l10n_sa_edi']),
                                    ('state', '=', 'installed')]) == 4)
        check(modules.search_count([('name', '=', 'l10n_sa_edi_pos'), ('state', '=', 'uninstalled')]) == 1)
        check(not env['ir.cron'].sudo().search_count([('active', '=', True)]))
        check(not env['account.edi.document'].sudo().search_count([('state', 'in', ['to_send', 'to_cancel'])]))
        journals = env['account.journal'].sudo().with_context(active_test=False).search([])
        check(set(journals.filtered(lambda j: j.edi_format_ids).ids) == set(targets))
        for journal_id, company_id in targets.items():
            journal = journals.browse(journal_id).exists()
            check(len(journal) == 1 and journal.company_id.id == company_id)
            check(journal.edi_format_ids.mapped('code') == ['sa_zatca'])
            check(journal.company_id.l10n_sa_api_mode == 'preprod')
            check(not journal.l10n_sa_compliance_csid_json and not journal.l10n_sa_production_csid_json)
            company = journal.company_id
            if company_id in english:
                check(company.baseer_name_en == english[company_id])
            for record in (company, company.partner_id, company.partner_id.commercial_partner_id):
                if company_id in english:
                    temporary.add((record._name, record.id))
                if not any(r._name == record._name and r.id == record.id for r, values in identities):
                    identities.append((record, identity(record)))
        documents = (env['account.move'].sudo().search_count([]), env['account.edi.document'].sudo().search_count([]))
        requests.Session.request = guarded_request
        for journal_id, company_id in targets.items():
            journal = journals.browse(journal_id).with_company(env['res.company'].browse(company_id))
            item = {'journal_id': journal_id, 'company_id': company_id, 'ok': False, 'requests': [], 'code': 'failed'}
            result['journals'].append(item)
            active = {'requests': item['requests'], 'bodies': set(), 'failed': False}
            try:
                if company_id in english:
                    journal.company_id.write({'baseer_name_ar': False, 'baseer_name_en': english[company_id]})
                journal._l10n_sa_api_onboard_journal(otps[str(journal_id)])
                check(len(item['requests']) == 8 and all(200 <= r['status'] < 300 for r in item['requests']))
                check(journal._l10n_sa_ready_to_submit_einvoices() and journal.l10n_sa_compliance_checks_passed)
                check(journal.l10n_sa_compliance_csid_certificate_id and journal.l10n_sa_production_csid_certificate_id
                      and journal.l10n_sa_chain_sequence_id and journal.company_id.l10n_sa_private_key_id)
                item.update(ok=True, code='onboarded')
            except Exception as error:
                item['code'] = type(error).__name__
            finally:
                try:
                    for record, values in identities:
                        if (record._name, record.id) not in temporary:
                            continue
                        names = {k: values[k] for k in ('name', 'baseer_name_ar', 'baseer_name_en') if k in values}
                        if any(record[k] != value for k, value in names.items()):
                            record.write(names)
                    unchanged()
                    env.cr.commit()
                except Exception:
                    env.cr.rollback()
                    item.update(ok=False, code='identity_restore_rolled_back')
                    unchanged()
                active = None
            if not item['ok']:
                break
        unchanged()
        result['ok'] = len(result['journals']) == 3 and all(j['ok'] for j in result['journals'])
        result['code'] = 'completed' if result['ok'] else 'stopped'
    except Exception as error:
        result.update(ok=False, code=type(error).__name__)
    finally:
        requests.Session.request = original_request
        if isinstance(otps, dict):
            otps.clear()
    return result


qa_phase2_result = qa_simulation_onboard(env, qa_phase2_otps)
print(json.dumps(qa_phase2_result, sort_keys=True))
if not qa_phase2_result['ok']:
    raise SystemExit(1)
