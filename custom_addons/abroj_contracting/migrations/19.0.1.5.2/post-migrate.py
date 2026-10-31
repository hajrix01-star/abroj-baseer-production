from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Copy legacy contact parties into standalone contract parties.

    Only name/phone/VAT are copied; the new party keeps no link to res.partner.
    Legacy partner_id values stay untouched so accounting history is unchanged.
    """
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    Party = env['abroj.contracting.party']
    cache = {}

    def party_for(partner, party_type, company):
        key = (partner.id, party_type, company.id)
        if key not in cache:
            name = (partner.name or '').strip() or ('#%s' % partner.id)
            party = Party.search([('name', '=', name), ('party_type', '=', party_type), ('company_id', '=', company.id)], limit=1)
            cache[key] = party or Party.create({'name': name, 'party_type': party_type, 'company_id': company.id,
                                                'phone': partner.phone or False, 'vat': partner.vat or False})
        return cache[key]

    for project in env['project.project'].search([('partner_id', '!=', False), ('abroj_client_party_id', '=', False), ('company_id', '!=', False)]):
        project.abroj_client_party_id = party_for(project.partner_id, 'client', project.company_id)
    for sub in env['abroj.contracting.subcontractor'].search([('partner_id', '!=', False), ('party_id', '=', False)]):
        cr.execute('UPDATE abroj_contracting_subcontractor SET party_id = %s WHERE id = %s', [party_for(sub.partner_id, 'subcontractor', sub.company_id).id, sub.id])
    # Vouchers may be frozen (issued); set the column directly to avoid document locks.
    for v in env['abroj.contracting.voucher'].search([('partner_id', '!=', False), ('party_id', '=', False)]):
        if v.subcontractor_id:
            cr.execute('SELECT party_id FROM abroj_contracting_subcontractor WHERE id = %s', [v.subcontractor_id.id])
            party_id = cr.fetchone()[0]
        elif v.kind == 'receipt' and v.project_id.partner_id == v.partner_id and v.project_id.abroj_client_party_id:
            party_id = v.project_id.abroj_client_party_id.id
        else:
            party_id = party_for(v.partner_id, 'client' if v.kind == 'receipt' else 'subcontractor', v.company_id).id
        cr.execute('UPDATE abroj_contracting_voucher SET party_id = %s WHERE id = %s', [party_id, v.id])
    env.invalidate_all()
