"""Root-category grouping must preserve the native POS report's grain and money."""

from uuid import uuid4

from lxml import etree

from odoo import Command
from odoo.addons.point_of_sale.report.pos_order_report import ReportPosOrder
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPosRootCategory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env['report.pos.order']
        categories = cls.env['pos.category']
        cls.food = categories.create({'name': 'Root grouping FOOD'})
        cls.drink = categories.create({'name': 'Root grouping DRINK'})
        cls.child = categories.create({'name': 'Meals', 'parent_id': cls.food.id})
        cls.deep = categories.create({'name': 'Lunch', 'parent_id': cls.child.id})
        config = cls.env['pos.config'].create({
            'name': 'Root category report fixture', 'company_id': cls.env.company.id,
        })
        cls.session = cls.env['pos.session'].create({'config_id': config.id})
        cls.products = cls.env['product.product']
        cls.orders = cls.env['pos.order']

    def _order(self, categories, quantity=1, company=None, session=None, price=100):
        company = company if company is not None else self.env.company
        session = session if session is not None else self.session
        product = self.env['product.product'].create({
            'name': 'Root category fixture ' + str(uuid4()),
            'type': 'service', 'available_in_pos': True,
            'list_price': price, 'taxes_id': [Command.clear()],
            'pos_categ_ids': [Command.set(categories.ids)],
        })
        order = self.env['pos.order'].with_company(company).with_context(
            allowed_company_ids=company.ids,
        ).create({
            'session_id': session.id, 'company_id': company.id,
            'state': 'done', 'source': 'pos', 'is_refund': quantity < 0,
            'amount_total': price * quantity, 'amount_tax': 0,
            'amount_paid': price * quantity, 'amount_return': 0,
            'lines': [Command.create({
                'product_id': product.id, 'uuid': str(uuid4()),
                'qty': quantity, 'price_unit': price,
                'price_subtotal': price * quantity,
                'price_subtotal_incl': price * quantity,
                'tax_ids': [Command.clear()],
                'full_product_name': product.display_name,
            })],
        })
        self.products |= product
        self.orders |= order
        self.env.flush_all()
        return product

    def _assert_native_parity(self):
        # Calling the native class directly avoids dispatching the extension's
        # _select/_from into the baseline, which would make parity circular.
        fragments = []
        for name in ('_select', '_from'):
            native = getattr(ReportPosOrder, name, None)
            if native:
                fragments.append(native(self.report))
        self.env.cr.execute(
            'SELECT * FROM (' + ' '.join(fragments) + ') native '
            'WHERE product_id = ANY(%s) ORDER BY id', [self.products.ids],
        )
        baseline = self.env.cr.dictfetchall()
        self.assertTrue(baseline, 'Native report must contain the fixture')
        columns = list(baseline[0])
        self.assertTrue(all(name.replace('_', '').isalnum() for name in columns))
        self.env.cr.execute(
            'SELECT ' + ', '.join('"' + name + '"' for name in columns)
            + ' FROM report_pos_order WHERE product_id = ANY(%s) ORDER BY id',
            [self.products.ids],
        )
        extended = self.env.cr.dictfetchall()
        # Exact equality includes IDs, cardinality and every native numerical
        # column, not merely a hand-picked total that can hide duplicated rows.
        self.assertEqual(extended, baseline)
        return self.report.search([('product_id', 'in', self.products.ids)])

    def test_root_child_deep_and_uncategorized_preserve_native_rows(self):
        expected = {}
        for categories, root in (
            (self.food, self.food), (self.child, self.food),
            (self.deep, self.food), (self.drink, self.drink),
            (self.env['pos.category'], self.env['pos.category']),
        ):
            expected[self._order(categories).id] = root.id or False
        rows = self._assert_native_parity()
        for row in rows:
            self.assertEqual(row.baseer_root_pos_categ_id.id or False,
                             expected[row.product_id.id])

    def test_multicategory_keeps_native_category_choice_and_refund_sign(self):
        self._order(self.deep | self.drink)
        refund_product = self._order(self.child, quantity=-1)
        rows = self._assert_native_parity()
        for row in rows:
            category = row.pos_categ_id
            while category.parent_id:
                category = category.parent_id
            self.assertEqual(row.baseer_root_pos_categ_id, category)
        refund = rows.filtered(lambda row: row.product_id == refund_product)
        self.assertTrue(refund)
        self.assertLess(sum(refund.mapped('price_total')), 0)

    def test_grouping_retains_company_rule_for_non_superuser(self):
        self._order(self.deep)
        foreign = self.env['res.company'].create({
            'name': 'Root category foreign company',
            'currency_id': self.env.company.currency_id.id,
        })
        # A new company has no chart fixtures. Native POS config requires a
        # bank journal even though this test does not post accounting moves.
        self.env['account.journal'].with_company(foreign).with_context(
            allowed_company_ids=foreign.ids,
        ).create({
            'name': 'Foreign category bank', 'code': 'RCFB',
            'type': 'bank', 'company_id': foreign.id,
        })
        foreign_config = self.env['pos.config'].with_company(foreign).with_context(
            allowed_company_ids=foreign.ids,
        ).create({'name': 'Foreign category fixture', 'company_id': foreign.id})
        foreign_session = self.env['pos.session'].with_company(foreign).with_context(
            allowed_company_ids=foreign.ids,
        ).create({'config_id': foreign_config.id})
        foreign_product = self._order(
            self.deep, company=foreign, session=foreign_session, price=777,
        )
        user = self.env['res.users'].create({
            'name': 'Root category POS report user',
            'login': 'root-category-' + str(uuid4()),
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        scoped = self.report.with_user(user).with_context(
            allowed_company_ids=self.env.company.ids,
        )
        rows = scoped.search([('product_id', 'in', self.products.ids)])
        self.assertTrue(rows)
        self.assertEqual(rows.mapped('company_id'), self.env.company)
        self.assertNotIn(foreign_product, rows.mapped('product_id'))
        # No company domain is supplied: existing native record rules must
        # exclude a real foreign sale, not merely a nonexistent fixture.
        self.assertFalse(scoped.search([('product_id', '=', foreign_product.id)]))
        grouped = scoped.read_group(
            [('product_id', 'in', self.products.ids)],
            ['price_total:sum'], ['baseer_root_pos_categ_id'],
        )
        self.assertEqual(sum(item['price_total'] for item in grouped),
                         sum(rows.mapped('price_total')))
        with self.assertRaises(AccessError):
            scoped.with_company(foreign).search([
                ('product_id', '=', foreign_product.id),
            ])

    def test_native_search_view_exposes_root_group_without_removing_leaf(self):
        view = self.report.get_view(view_type='search')
        arch = etree.fromstring(view['arch'].encode())
        contexts = [node.get('context', '') for node in arch.xpath('//filter')]
        self.assertTrue(any('baseer_root_pos_categ_id' in value for value in contexts))
        self.assertTrue(any("'pos_categ_id'" in value or '"pos_categ_id"' in value
                            for value in contexts))
