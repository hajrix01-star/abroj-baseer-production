import json

from odoo.tests.common import HttpCase, tagged

from .test_split_settlement import SplitSettlementFixture


class SplitSettlementBrowserJourney(SplitSettlementFixture):
    def _check_split(self, lang, width, add_label):
        self.env['res.lang']._activate_lang(lang)
        admin = self.env.ref('base.user_admin')
        admin.write({'lang': lang, 'password': admin.login})
        run = self._run()
        action = self.env.ref('baseer_payroll.action_baseer_payroll_runs')
        fixture = json.dumps({
            'primary': self.primary.name,
            'secondary': self.secondary.name,
            'third': self.third.name,
            'sameTreasury': self.same_treasury.name,
            'addLabel': add_label,
            'lang': lang,
            'direction': 'rtl' if lang == 'ar_001' else 'ltr',
            'width': width,
        })
        script = r"""
        (async () => {
            const fixture = __FIXTURE__;
            const visible = element => element && element.getClientRects().length;
            const waitFor = async (predicate, description) => {
                const deadline = performance.now() + 15000;
                while (performance.now() < deadline) {
                    const result = predicate();
                    if (result) {
                        return result;
                    }
                    await new Promise(resolve => setTimeout(resolve, 50));
                }
                throw new Error('Payroll payment timeout: ' + description);
            };
            const dialogs = () => [...document.querySelectorAll('.o_dialog:not(.o_inactive_modal)')];
            const payrollDialog = () => dialogs().find(el => el.querySelector('button[name="action_confirm"]'));
            const widget = (scope, name) => scope?.querySelector('.o_field_widget[name="' + name + '"]');
            const input = (scope, name) => widget(scope, name)?.querySelector('input');
            const chooseJournal = async (scope, journal, unavailable = []) => {
                const field = await waitFor(() => input(scope, 'journal_id'), 'journal input');
                let choices;
                if (field.readOnly) {
                    // Odoo opens a full-screen record picker on small screens.
                    field.click();
                    choices = () => [...document.querySelectorAll(
                        '.o_dialog:not(.o_inactive_modal) .o_select_create_dialog_content ' +
                        ':is(.o_data_row, .o_kanban_record)'
                    )].filter(visible);
                } else {
                    field.focus();
                    field.value = unavailable.length ? 'Split test' : journal;
                    field.dispatchEvent(new Event('input', { bubbles: true }));
                    choices = () => [...widget(scope, 'journal_id').querySelectorAll('[role="option"]')]
                        .filter(visible);
                }
                const item = await waitFor(() => choices().find(el => el.textContent.includes(journal) &&
                    !el.textContent.includes(fixture.sameTreasury)),
                    journal + ' available choice');
                for (const excluded of unavailable) {
                    if (choices().some(el => el.textContent.includes(excluded))) {
                        throw new Error('Previously used treasury remains selectable: ' + excluded);
                    }
                }
                item.click();
                await waitFor(() => input(scope, 'journal_id')?.value === journal, journal + ' selection');
            };
            const withinViewport = (element, description) => {
                const rect = element.getBoundingClientRect();
                if (rect.left < -1 || rect.right > innerWidth + 1) {
                    throw new Error(description + ' extends outside the viewport');
                }
            };
            const shownAmount = (scope, name, digit) => {
                const value = widget(scope, name)?.textContent.trim() || '';
                return new RegExp('(?:^|\\D)' + digit + '[,.\\s\\u066c]?000(?:\\D|$)').test(value);
            };
            if (innerWidth !== fixture.width) {
                throw new Error('Unexpected viewport width: ' + innerWidth);
            }
            document.querySelector('button[name="action_pay"]').click();
            const wizard = await waitFor(payrollDialog, 'settlement wizard');
            if (getComputedStyle(wizard).direction !== fixture.direction) {
                throw new Error('Unexpected direction: ' + getComputedStyle(wizard).direction);
            }
            const funding = () => widget(wizard, 'funding_line_ids');
            const addControl = () => [...(funding()?.querySelectorAll('button, a, .o-kanban-button-new') || [])]
                .find(el => visible(el) && el.textContent.trim() === fixture.addLabel);
            const enterFunding = async (journal, amount, excluded) => {
                const add = await waitFor(addControl, 'Add payment method control');
                withinViewport(add, 'Add payment method control');
                add.click();
                const editor = await waitFor(() => dialogs().find(el => el !== wizard && input(el, 'amount')),
                    'additional payment editor');
                await chooseJournal(editor, journal, excluded);
                await waitFor(() => input(editor, 'payment_method_line_id')?.value,
                    'default outbound payment method');
                const editorAmount = input(editor, 'amount');
                for (const control of [input(editor, 'journal_id'), input(editor, 'payment_method_line_id'), editorAmount]) {
                    withinViewport(control, 'Additional payment control');
                }
                editorAmount.focus();
                editorAmount.value = amount;
                editorAmount.dispatchEvent(new Event('input', { bubbles: true }));
                editorAmount.dispatchEvent(new Event('change', { bubbles: true }));
                editorAmount.blur();
                editor.querySelector('button.o_form_button_save').click();
                await waitFor(() => !editor.isConnected && funding().textContent.includes(journal),
                    journal + ' saved in payment sources');
            };
            await chooseJournal(wizard, fixture.primary);
            await waitFor(() => input(wizard, 'payment_method_line_id')?.value,
                'primary outbound payment method');
            await waitFor(() => shownAmount(wizard, 'amount_total', '3'), 'payment total of 3000');
            await enterFunding(fixture.secondary, '800', [fixture.primary, fixture.sameTreasury]);
            await enterFunding(fixture.third, '200', [fixture.primary, fixture.sameTreasury, fixture.secondary]);
            await waitFor(() => shownAmount(wizard, 'amount_primary', '2'), 'calculated first amount of 2000');
            if (!shownAmount(wizard, 'amount_total', '3')) {
                throw new Error('Dividing the payment changed the original total');
            }
            const rowView = await waitFor(() => widget(wizard, 'line_ids')?.querySelector(
                fixture.width === 375 ? '.o_kanban_record' : '.o_list_renderer .o_data_row'
            ), 'employee rows');
            const confirm = wizard.querySelector('button[name="action_confirm"]');
            for (const control of [input(wizard, 'journal_id'), funding(),
                widget(wizard, 'amount_primary'), widget(wizard, 'amount_total'), rowView, confirm]) {
                withinViewport(control, 'Payroll payment control');
            }
            await waitFor(() => visible(confirm) && !confirm.disabled, 'enabled confirmation');
            confirm.click();
            await waitFor(() => !payrollDialog() && !visible(document.querySelector('button[name="action_pay"]')),
                'return to the fully paid run');
            console.log('PAYROLL_SPLIT_UI_PASS ' + fixture.lang + ' ' + innerWidth);
            console.log('test successful');
        })().catch(error => { console.error(error); throw error; });
        """.replace('__FIXTURE__', fixture)
        self.browser_js(
            f'/odoo/action-{action.id}/{run.id}',
            script,
            ready='!!document.querySelector(\'button[name="action_pay"]\')',
            login=admin.login,
            timeout=100,
        )
        run.invalidate_recordset()
        self.assertEqual(run.baseer_payment_state, 'paid')
        self.assertEqual(run.baseer_residual, 0)
        payments = run.slip_ids._baseer_payments()
        self.assertEqual(len(payments), 3)
        self.assertEqual(
            {payment.journal_id.id: payment.amount for payment in payments},
            {self.primary.id: 2000, self.secondary.id: 800, self.third.id: 200},
        )


@tagged('post_install', '-at_install')
class PayrollSplitSettlementDesktop(SplitSettlementBrowserJourney, HttpCase):
    browser_size = '1440x900'

    def test_split_payroll_en(self):
        self._check_split('en_US', 1440, 'Add payment method')


@tagged('post_install', '-at_install')
class PayrollSplitSettlementMobile(SplitSettlementBrowserJourney, HttpCase):
    browser_size = '375x812'
    touch_enabled = True

    def test_split_payroll_ar(self):
        self._check_split('ar_001', 375, 'إضافة طريقة دفع')
