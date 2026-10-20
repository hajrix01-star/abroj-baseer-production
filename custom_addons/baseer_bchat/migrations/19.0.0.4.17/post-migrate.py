"""Replace only the obsolete shipped root-menu translation, not custom names.

Normal Odoo translation import preserves existing translated values on upgrade.
Changing the English XML label therefore left ar_001='BChat' in installed QA.
This is bounded module-owned UI metadata, not a permissions/data migration.
"""


def migrate(cr, version):
    cr.execute('''
        UPDATE ir_ui_menu menu
        SET name = (
            SELECT jsonb_object_agg(locale,
                CASE WHEN label = 'BChat' THEN
                    CASE WHEN locale = 'ar' OR left(locale, 3) = 'ar_'
                         THEN 'بيورك' ELSE 'BWork' END
                ELSE label END)
            FROM jsonb_each_text(menu.name) AS translations(locale, label)
        )
        WHERE menu.id = (
            SELECT res_id FROM ir_model_data
            WHERE module = 'baseer_bchat' AND name = 'menu_bchat_root'
              AND model = 'ir.ui.menu'
        )
        AND EXISTS (
            SELECT 1 FROM jsonb_each_text(menu.name) AS translations(locale, label)
            WHERE label = 'BChat'
        )
    ''')
