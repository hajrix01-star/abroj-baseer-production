from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'abroj_contracting')
class AbrojCompanyForceCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.company'].create({'name': 'Restaurant Test Co'})
        cls.abroj = cls.env['res.company'].create({'name': 'Abroj Test Co'})
        cls.env['ir.config_parameter'].sudo().set_param('abroj_project_dashboard.company_id', str(cls.abroj.id))
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Admin restaurant default', 'login': 'abroj-company-force-test',
            'company_id': cls.restaurant.id, 'company_ids': [Command.set([cls.restaurant.id, cls.abroj.id])],
            'group_ids': [Command.set([cls.env.ref('base.group_system').id, cls.env.ref('project.group_project_manager').id])],
        })

    def env_rest(self):
        return self.env(user=self.user, context=dict(allowed_company_ids=[self.restaurant.id, self.abroj.id]))

    def test_resolver_uses_parameter(self):
        self.assertEqual(self.env['res.company']._abroj_company(), self.abroj)

    def test_project_forced_to_abroj(self):
        env = self.env_rest()
        self.assertEqual(env.company, self.restaurant)
        project = env['project.project'].create({'name': 'P', 'company_id': self.restaurant.id})
        self.assertEqual(project.company_id, self.abroj)
        self.assertEqual(project.account_id.company_id, self.abroj)

    def test_party_forced_to_abroj(self):
        env = self.env_rest()
        party = env['abroj.contracting.party'].create({'name': 'Client X', 'party_type': 'client'})
        self.assertEqual(party.company_id, self.abroj)
        party2 = env['abroj.contracting.party'].create({'name': 'Client Y', 'party_type': 'client', 'company_id': self.restaurant.id})
        self.assertEqual(party2.company_id, self.abroj)
        pid, _name = env['abroj.contracting.party'].name_create('Client Z')
        self.assertEqual(env['abroj.contracting.party'].browse(pid).company_id, self.abroj)

    def test_documents_follow_abroj(self):
        env = self.env_rest()
        project = env['project.project'].create({'name': 'P2'})
        partner = env['res.partner'].create({'name': 'Sub'})
        sub = env['abroj.contracting.subcontractor'].create({'project_id': project.id, 'partner_id': partner.id, 'agreed_amount': 10})
        voucher = env['abroj.contracting.voucher'].create({'project_id': project.id, 'partner_id': partner.id, 'subcontractor_id': sub.id, 'amount': 5})
        self.assertEqual(sub.company_id, self.abroj)
        self.assertEqual(voucher.company_id, self.abroj)
