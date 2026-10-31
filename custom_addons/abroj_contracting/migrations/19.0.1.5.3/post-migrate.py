from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Copy legacy cost suppliers (res.partner) into supplier contract parties.

    Only name/phone/VAT are copied; partner_id stays untouched as hidden history.
    Confirmed costs are frozen, so the column is set directly.
    """
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    Party = env['abroj.contracting.party']
    cache = {}
    for cost in env['abroj.contracting.cost'].search([('partner_id', '!=', False), ('party_id', '=', False)]):
        partner, company = cost.partner_id, cost.company_id
        key = (partner.id, company.id)
        if key not in cache:
            name = (partner.name or '').strip() or ('#%s' % partner.id)
            cache[key] = Party.search([('name', '=', name), ('party_type', '=', 'supplier'), ('company_id', '=', company.id)], limit=1) \
                or Party.create({'name': name, 'party_type': 'supplier', 'company_id': company.id,
                                 'phone': partner.phone or False, 'vat': partner.vat or False})
        cr.execute('UPDATE abroj_contracting_cost SET party_id = %s WHERE id = %s', [cache[key].id, cost.id])
    env.invalidate_all()
