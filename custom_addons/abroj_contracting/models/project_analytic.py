from odoo import api, fields, models
from odoo.exceptions import UserError


class ProjectAnalyticAuto(models.Model):
    _inherit = 'project.project'

    @api.model
    def _abroj_project_analytic_plan(self):
        """Resolve the existing 'Project' analytic plan; never create one."""
        Plan = self.env['account.analytic.plan'].sudo()
        plan = Plan.browse()
        try:
            plan, _others = Plan._get_all_plans()
        except UserError:
            plan = Plan.browse()
        if not plan or not plan.exists():
            plan = Plan.search([('parent_id', '=', False), ('name', 'ilike', 'Project')], limit=1) \
                or Plan.search([('parent_id', '=', False)], order='id', limit=1)
        return plan

    def _abroj_ensure_analytic_account(self, keep_project_company=False):
        """Create and link an analytic account for projects lacking one.

        keep_project_company: link via SQL so a project without company is not
        recomputed to the account's company (used by the backfill migration).
        """
        plan = self._abroj_project_analytic_plan()
        if not plan:
            return
        Account = self.env['account.analytic.account'].sudo()
        for project in self.filtered(lambda p: not p.account_id and not p.is_template):
            company = project.company_id or self.env.company
            account = Account.create({
                'name': project.name,
                'company_id': company.id,
                'partner_id': project.partner_id.id or False,
                'plan_id': plan.id,
            })
            self._abroj_sync_analytic_name(project, account)
            if keep_project_company and not project.company_id:
                self.env.cr.execute(
                    'UPDATE project_project SET account_id = %s WHERE id = %s',
                    (account.id, project.id))
                project.invalidate_recordset(['account_id'])
            else:
                project.sudo().account_id = account

    def _abroj_sync_analytic_name(self, project, account):
        """Copy the project name verbatim (all translations) to the account."""
        project.flush_recordset(['name'])
        account.flush_recordset(['name'])
        cr = self.env.cr
        cr.execute("SELECT pg_typeof(name)::text FROM account_analytic_account WHERE id=%s", (account.id,))
        if cr.fetchone()[0] == 'jsonb':
            cr.execute("""UPDATE account_analytic_account a
                          SET name = CASE WHEN jsonb_typeof(p.name) = 'object' THEN p.name
                                          ELSE a.name END
                          FROM project_project p WHERE p.id=%s AND a.id=%s""", (project.id, account.id))
        account.invalidate_recordset(['name'])

    @api.model_create_multi
    def create(self, vals_list):
        projects = super().create(vals_list)
        projects._abroj_ensure_analytic_account()
        return projects


class AccountMoveProjectAnalytic(models.Model):
    _inherit = 'account.move'

    abroj_project_id = fields.Many2one('project.project', string='مشروع أبروج', index=True, copy=False,
                                       help='المشروع المرتبط؛ يُنسخ حسابه التحليلي إلى بنود الفاتورة.')

    def _abroj_apply_project_analytic(self, include_posted=False):
        """Put the project's analytic account on invoice lines lacking analytics."""
        for move in self.filtered('abroj_project_id'):
            if move.state != 'draft' and not include_posted:
                continue
            account = move.abroj_project_id.account_id
            if not account:
                continue
            lines = move.line_ids.filtered(
                lambda l: l.display_type == 'product' and not l.analytic_distribution)
            if lines:
                lines.with_context(check_move_validity=False).sudo().write(
                    {'analytic_distribution': {str(account.id): 100}})

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._abroj_apply_project_analytic()
        return moves

    def write(self, vals):
        res = super().write(vals)
        if 'abroj_project_id' in vals or 'invoice_line_ids' in vals or 'line_ids' in vals:
            self._abroj_apply_project_analytic()
        return res


class AccountMoveLineProjectAnalytic(models.Model):
    _inherit = 'account.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.move_id.filtered(lambda m: m.abroj_project_id and m.state == 'draft')._abroj_apply_project_analytic()
        return lines
