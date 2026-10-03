"""Preserve the unchanged service-seed onboarding extension on drifted installs.

Only this module's identical stored view is retained during the upgrade. The
legacy parent in company_setup is neither repaired nor reloaded here.
"""

from lxml import etree

from odoo import api, SUPERUSER_ID
from odoo.tools import file_open


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    obsolete = {'setup_tobacco_fee', 'tobacco_fee_state', 'tobacco_fee_message'}
    unsupported = obsolete - env['baseer.company.onboarding']._fields.keys()
    if not unsupported:
        return
    cr.execute("""
        SELECT md.id, md.noupdate, v.arch_db, parent.arch_db
          FROM ir_model_data md
          JOIN ir_ui_view v ON md.model = 'ir.ui.view' AND md.res_id = v.id
          JOIN ir_ui_view parent ON v.inherit_id = parent.id
          JOIN ir_model_data pd ON pd.model = 'ir.ui.view' AND pd.res_id = parent.id
         WHERE md.module = 'baseer_service_seed'
           AND md.name = 'view_baseer_company_onboarding_employee_services'
           AND v.model = 'baseer.company.onboarding'
           AND pd.module = 'baseer_company_setup'
           AND pd.name = 'view_baseer_company_onboarding_form'
           AND parent.model = 'baseer.company.onboarding'
           AND parent.inherit_id IS NULL
         FOR UPDATE OF md
    """)
    row = cr.fetchone()
    if not row:
        return
    xmlid_id, noupdate, arches, parent_arches = row
    if not any(node.get('name') in unsupported
               for arch in parent_arches.values()
               for node in etree.fromstring(arch.encode()).iter('field')):
        return
    # This release changes no onboarding XML. Fail if retaining the view would
    # skip a source change or discard an existing customization.
    parser = etree.XMLParser(remove_blank_text=True)
    with file_open('baseer_service_seed/views/company_onboarding_views.xml') as source:
        root = etree.parse(source, parser)
    expected = root.xpath("//record[@id='view_baseer_company_onboarding_employee_services']/field[@name='arch']")[0][0]
    current = etree.fromstring(arches['en_US'].encode(), parser)
    if etree.tostring(current, method='c14n') != etree.tostring(expected, method='c14n'):
        raise RuntimeError('Cannot retain a changed service-seed onboarding view during this narrow upgrade.')
    cr.execute('CREATE TEMP TABLE baseer_service_seed_retained_view (xmlid_id integer PRIMARY KEY, noupdate boolean NOT NULL) ON COMMIT DROP')
    cr.execute('INSERT INTO baseer_service_seed_retained_view VALUES (%s, %s)', [xmlid_id, noupdate])
    cr.execute('UPDATE ir_model_data SET noupdate = TRUE WHERE id = %s', [xmlid_id])
    env['ir.model.data'].browse(xmlid_id).invalidate_recordset(['noupdate'])
