"""Keep the stored onboarding parent compatible during a procurement upgrade.

Some deployments retained tobacco setup controls from a newer onboarding
view after returning to company_setup source without those fields. Reloading
the whole dependency also upgrades its dependants. Remove only unsupported
controls from this one parent instead; preserve every other node/translation.
"""

import logging

from lxml import etree
from psycopg2.extras import Json

from odoo import api, SUPERUSER_ID


_logger = logging.getLogger(__name__)
_LEGACY_FIELDS = {'setup_tobacco_fee', 'tobacco_fee_state', 'tobacco_fee_message'}


def migrate(cr, version):
    # Odoo 19 incrementally sets up dependency models before pre migrations.
    env = api.Environment(cr, SUPERUSER_ID, {})
    unsupported = _LEGACY_FIELDS - env['baseer.company.onboarding']._fields.keys()
    if not unsupported:
        return
    env['ir.ui.view'].flush_model(['arch_db'])
    cr.execute("""
        SELECT v.id, v.arch_db
          FROM ir_ui_view v
          JOIN ir_model_data d ON d.model = 'ir.ui.view' AND d.res_id = v.id
         WHERE d.module = 'baseer_company_setup'
           AND d.name = 'view_baseer_company_onboarding_form'
           AND v.model = 'baseer.company.onboarding'
           AND v.inherit_id IS NULL
         FOR UPDATE OF v
    """)
    row = cr.fetchone()
    if not row or not row[1]:
        return
    view_id, translations = row
    changed = False
    for language, arch in translations.items():
        root = etree.fromstring(arch.encode('utf-8'))
        nodes = [node for node in root.iter()
                 if (node.tag == 'field' and node.get('name') in unsupported)
                 or (node.tag == 'label' and node.get('for') in unsupported)]
        if nodes:
            for node in nodes:
                node.getparent().remove(node)
            translations[language] = etree.tostring(root, encoding='unicode')
            changed = True
    if changed:
        cr.execute('UPDATE ir_ui_view SET arch_db = %s WHERE id = %s',
                   [Json(translations), view_id])
        env['ir.ui.view'].browse(view_id).invalidate_recordset(['arch_db'])
        _logger.info('Removed unsupported legacy setup controls from onboarding view %s', view_id)
