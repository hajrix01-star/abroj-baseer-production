from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Link legacy promissory notes (res.partner) to standalone contract parties.

    Reuses an existing party with the same name in the company (any type,
    subcontractor first), otherwise creates a subcontractor party. Notes may be
    issued/paid (locked), so the column is set directly; partner_id is kept.
    """
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    Party = env['abroj.contracting.party']
    order = {'subcontractor': 0, 'supplier': 1, 'client': 2}
    cache = {}
    for note in env['abroj.promissory.note'].search([('partner_id', '!=', False), ('party_id', '=', False)]):
        partner, company = note.partner_id, note.company_id or env.company
        key = (partner.id, company.id)
        if key not in cache:
            name = (partner.name or '').strip() or ('#%s' % partner.id)
            found = Party.search([('name', '=', name), ('company_id', '=', company.id)]).sorted(lambda p: order.get(p.party_type, 9))
            cache[key] = found[:1] or Party.create({'name': name, 'party_type': 'subcontractor', 'company_id': company.id,
                                                    'phone': partner.phone or False, 'vat': partner.vat or False})
        cr.execute('UPDATE abroj_promissory_note SET party_id = %s WHERE id = %s', [cache[key].id, note.id])
    env.invalidate_all()
