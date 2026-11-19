"""Exclude fiscal allowance rows from merchandise counters only."""
from odoo import api, models


class PrintJob(models.Model):
    _inherit = 'baseer.print.job'

    @api.model
    def _session_close_payload(self, session, printer=None, as_of=None):
        payload = super()._session_close_payload(session, printer=printer, as_of=as_of)
        self.env.cr.execute('''
            SELECT COALESCE(SUM(GREATEST(line.qty, 0)), 0), COUNT(DISTINCT line.product_id)
              FROM pos_order_line line
              JOIN pos_order orders ON orders.id = line.order_id
              JOIN product_product product ON product.id = line.product_id
              JOIN product_template template ON template.id = product.product_tmpl_id
             WHERE orders.session_id = %s AND orders.company_id = %s AND orders.config_id = %s
               AND orders.state NOT IN ('draft', 'cancel')
               AND NOT COALESCE(line.baseer_global_discount_line, FALSE)
               AND NOT (COALESCE(orders.baseer_global_discount_locked, FALSE) AND template.type = 'combo')
        ''', [session.id, session.company_id.id, session.config_id.id])
        units, products = self.env.cr.fetchone()
        payload['summary']['units_sold'] = self._format_session_amount(units, session.currency_id)
        payload['summary']['products_sold'] = int(products or 0)
        return payload
