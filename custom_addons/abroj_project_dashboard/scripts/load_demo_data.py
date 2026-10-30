"""Run through odoo shell with an isolated demo database only."""
from datetime import timedelta
from odoo import Command, fields

for code in ('en_US', 'ar_001'):
    env['res.lang']._activate_and_install_lang(code)

company = env.ref('base.main_company')
admin = env.ref('base.user_admin')
admin.write({'company_id': company.id, 'company_ids': [Command.link(company.id)], 'group_ids': [Command.link(env.ref('analytic.group_analytic_accounting').id)]})
env = env(user=admin, context=dict(env.context, allowed_company_ids=[company.id]))
for login, group in [('owner', 'project.group_project_manager'), ('engineer', 'project.group_project_user')]:
    user = env['res.users'].search([('login', '=', login)], limit=1)
    values = {'name': login.title(), 'login': login, 'password': login, 'company_id': company.id, 'company_ids': [Command.set([company.id])], 'group_ids': [Command.set([env.ref('base.group_user').id, env.ref(group).id])]}
    if user:
        user.write(values)
    else:
        env['res.users'].create(values)
today = fields.Date.today()
client = env['res.partner'].search([('name', '=', 'عميل أبرج التجريبي')], limit=1) or env['res.partner'].create({'name': 'عميل أبرج التجريبي'})
contractor = env['res.partner'].search([('name', '=', 'مقاول أبرج التجريبي')], limit=1) or env['res.partner'].create({'name': 'مقاول أبرج التجريبي'})
plan = env['account.analytic.plan'].search([], limit=1) or env['account.analytic.plan'].create({'name': 'مشاريع أبرج'})
for index, (name, kind, status) in enumerate([
    ('فيلا أم فالح', 'residential', 'at_risk'), ('مجمع تجاري', 'commercial', 'on_track'),
    ('ترميم مبنى', 'renovation', 'off_track'),
]):
    if env['project.project'].search_count([('name', '=', name), ('company_id', '=', company.id)]):
        continue
    account = env['account.analytic.account'].create({'name': name, 'plan_id': plan.id, 'company_id': company.id})
    project = env['project.project'].create({'name': name, 'company_id': company.id, 'account_id': account.id, 'partner_id': client.id, 'user_id': admin.id, 'abroj_type': kind, 'abroj_budget': 1900000, 'abroj_contract_value': 2400000, 'contracting_goal_ar': 'تنفيذ أعمال المشروع', 'contract_payment_schedule_ar': 'دفعات حسب تقدم الأعمال', 'abroj_use_manual_progress': True, 'abroj_manual_progress': [68, 40, 30, 20, 100, 60][index], 'date_start': today - timedelta(days=180), 'date': today + timedelta(days=100 if index != 2 else -20), 'last_update_status': status})
    if 'abroj.contracting.voucher' in env:
        subcontract = env['abroj.contracting.subcontractor'].create({'project_id': project.id, 'partner_id': contractor.id, 'agreed_amount': 450000, 'scope': 'أعمال الهيكل'})
        for kind, amount, partner in [('receipt', 900000, client), ('payment', 400000, contractor)]:
            voucher = env['abroj.contracting.voucher'].create({'project_id': project.id, 'partner_id': partner.id, 'kind': kind, 'amount': amount, 'subcontractor_id': subcontract.id if kind == 'payment' else False})
            voucher.action_issue()
    env['abroj.promissory.note'].create({'project_id': project.id, 'partner_id': contractor.id, 'amount': 25000, 'due_date': today + timedelta(days=90), 'place': 'الرياض'})
    env['abroj.contracting.project.note'].create({'project_id': project.id, 'body': 'متابعة أعمال المشروع'})
    env['ir.attachment'].create({'name': 'ملاحظات.txt', 'raw': 'ملف تجريبي'.encode(), 'res_model': 'project.project', 'res_id': project.id})
    env['project.task'].create({'name': ['إزالة مخلفات', 'صب خرسانة', 'أعمال التشطيب'][index], 'project_id': project.id, 'x_abroj_date_start': today - timedelta(days=1), 'x_abroj_duration_days': 3, 'user_ids': [Command.set([admin.id])]})
    for n, phase in enumerate(['تنظيف 3 أيام', 'حفر', 'قواعد', 'هيكل خرساني', 'مباني', 'كهرباء وسباكة', 'تشطيبات']):
        env['project.task'].create({'name': phase, 'project_id': project.id, 'x_abroj_date_start': today + timedelta(days=-180+n*30), 'x_abroj_duration_days': 3, 'state': '1_done' if n < 2 else '01_in_progress'})
    for n, category in enumerate(['الحفر والأساسات', 'الخرسانة والهيكل', 'الكهرباء', 'السباكة', 'المقاولون من الباطن', 'التشطيبات']):
        line = env['abroj.project.budget.line'].create({'project_id': project.id, 'name': category, 'budget': 300000})
        env['account.analytic.line'].create({'name': category, 'account_id': account.id, 'amount': -[320000, 540000, 95000, 165000, 210000, 35000][n], 'date': today, 'company_id': company.id, 'abroj_budget_line_id': line.id})
env['project.project'].ensure_abroj_closed_stage()
closed_demo = env['project.project'].search([('name', '=', 'ترميم مبنى'), ('company_id', '=', company.id)], limit=1)
if closed_demo and not closed_demo.abroj_closed_date:
    closed_demo.abroj_set_closed(True, 'بيانات تجريبية')
env.cr.commit()
