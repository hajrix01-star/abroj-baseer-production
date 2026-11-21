"""Rebase dashboard targets with actual posted tax for three complete months."""
import logging
from datetime import date, timedelta

from odoo import SUPERUSER_ID, api, fields
from odoo.addons.baseer_dashboard2.models.tax_math import convert_target

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['ir.config_parameter'].sudo()
    if config.get_param('baseer_dashboard2.target_basis') == 'inclusive':
        return
    today = fields.Date.context_today(env.user)
    end = today.replace(day=1) - timedelta(days=1)
    index = end.year * 12 + end.month - 3
    year, month = divmod(index, 12)
    start = date(year, month + 1, 1)
    companies = env['res.company'].browse([1, 2, 3]).exists().ids
    service = env['baseer.dashboard2.service'].with_context(
        allowed_company_ids=companies, _bd2_request_cache={},
        _bd2_tax_companies=companies, _bd2_tax_window=(start, end))
    for target in env['baseer.dashboard2.target'].sudo().search([]):
        ids = [target.company_id.id] if target.company_id else companies
        if not ids or any(cid not in companies for cid in ids):
            _logger.warning('Target %s unchanged: company outside scope', target.id)
            continue
        parts = [service._accounting_gross([cid], start, end) for cid in ids]
        values = (sum(p['tax']['sales_net_pre_tax'] for p in parts), sum(p['sales_net'] for p in parts),
                  sum(service._accounting([cid], start, end)['categories'].get('food_cost', 0) for cid in ids),
                  sum(p['categories'].get('food_cost', 0) for p in parts),
                  sum(p['categories'].get('salaries', 0) for p in parts),
                  sum(service._accounting([cid], start, end)['net_profit'] for cid in ids),
                  sum(p['net_profit'] for p in parts))
        converted = convert_target(target.key, target.value, *values)
        if converted is None:
            _logger.warning('Target %s (%s) unchanged: missing denominator', target.id, target.key)
            continue
        _logger.info('Target %s (%s): %s -> %s', target.id, target.key, target.value, converted)
        target.value = converted
    config.set_param('baseer_dashboard2.target_basis', 'inclusive')
