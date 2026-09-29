assert env.cr.dbname == 'baseer_ic1_20260910'
from odoo.tools.translate import trans_export
with open('/mnt/qa-evidence/ic1.pot', 'wb') as stream:
    trans_export(None, ['baseer_financial_correction'], stream, 'po', env)
env.cr.rollback()
print('Translation template exported')
