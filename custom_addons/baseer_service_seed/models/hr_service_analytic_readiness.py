"""A company-scoped, non-ledger readiness check for employee services."""
from odoo import _, fields, models
from odoo.exceptions import AccessError

from .catalog import SERVICES


HR_SERVICE_TYPES = [(key, english) for key, english, _arabic, _purpose in SERVICES[:15]]


class HrServiceAnalyticReadiness(models.TransientModel):
    _name = 'baseer.hr.service.analytic.readiness'
    _description = 'Employee Service Analytic Readiness'

    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='cascade')
    state = fields.Selection([('ready', 'Ready'), ('blocked', 'Blocked')], readonly=True)
    summary = fields.Text(readonly=True)
    line_ids = fields.One2many('baseer.hr.service.analytic.readiness.line', 'readiness_id', readonly=True)

    def _require_manager(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only Accounting Managers can review employee-service analytic readiness.'))

    @classmethod
    def _baseer_open_for_company(cls, company):
        company._baseer_require_hr_service_analytic_manager()
        wizard = company.env[cls._name].create({'company_id': company.id})
        wizard.action_refresh()
        return {
            'type': 'ir.actions.act_window', 'name': _('Employee Service Readiness'),
            'res_model': cls._name, 'res_id': wizard.id, 'view_mode': 'form',
            'target': 'new',
        }

    def action_refresh(self):
        self._require_manager()
        for wizard in self:
            statuses = wizard.company_id._baseer_hr_service_analytic_status()
            wizard.line_ids.unlink()
            wizard.line_ids = [(0, 0, {
                'service_type': line['service_type'],
                'product_id': line.get('product') and line['product'].id,
                'analytic_account_id': line.get('leaf') and line['leaf'].id,
                'state': line['state'], 'message': line['message'],
            }) for line in statuses]
            blocked = [line for line in statuses if line['state'] == 'blocked']
            missing = [line for line in statuses if line['state'] == 'missing']
            wizard.write({
                'state': 'blocked' if blocked else 'ready' if not missing else 'blocked',
                'summary': (_('Ready: all 15 employee services have a 100%% expected allocation.')
                            if not blocked and not missing else
                            _('Blocked: resolve the marked rows before adding missing setup.')),
            })
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def action_add_missing(self):
        self._require_manager()
        for wizard in self:
            wizard.company_id._baseer_prepare_hr_service_analytics()
        return self.action_refresh()


class HrServiceAnalyticReadinessLine(models.TransientModel):
    _name = 'baseer.hr.service.analytic.readiness.line'
    _description = 'Employee Service Analytic Readiness Line'
    _order = 'service_type, id'

    readiness_id = fields.Many2one('baseer.hr.service.analytic.readiness', required=True, ondelete='cascade')
    service_type = fields.Selection(HR_SERVICE_TYPES, readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    analytic_account_id = fields.Many2one('account.analytic.account', readonly=True)
    state = fields.Selection([('ready', 'Ready'), ('missing', 'Missing'), ('blocked', 'Blocked')], readonly=True)
    message = fields.Char(readonly=True)
