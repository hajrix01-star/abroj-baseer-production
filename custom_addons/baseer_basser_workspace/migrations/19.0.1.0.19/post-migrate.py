from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'lang': 'en_US'})
    item = env.ref('baseer_basser_workspace.workspace_item_cashier_procurement_requests', raise_if_not_found=False)
    if item and item.description == 'Review requests and record the received purchase.':
        item.write({'description': 'Review and resend previous requests.'})
        arabic = item.with_context(lang='ar_001')
        if arabic.description == 'مراجعة الطلبات وتسجيل استلام المشتريات.':
            arabic.write({'description': 'مراجعة الطلبات السابقة وإعادة إرسالها.'})
