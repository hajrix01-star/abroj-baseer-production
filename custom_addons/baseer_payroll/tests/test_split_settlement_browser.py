import json

from odoo.tests.common import HttpCase, tagged

from .test_split_settlement import SplitSettlementFixture


class SplitSettlementBrowserJourney(SplitSettlementFixture):
    def _check_split(self, lang, width, label):
        self.env['res.lang']._activate_lang(lang)
        admin = self.env.ref('base.user_admin')
        admin.write({'lang': lang, 'password': admin.login})
        run = self._run()
        action = self.env.ref('baseer_payroll.action_baseer_payroll_runs')
        fixture = json.dumps({
            'primary': self.primary.name,
            'secondary': self.secondary.name,
            'label': label,
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
            const dialog = () => [...document.querySelectorAll('.o_dialog:not(.o_inactive_modal)')]
                .find(el => el.querySelector('button[name="action_confirm"]'));
            const widget = name => dialog()?.querySelector('.o_field_widget[name="' + name + '"]');
            const input = name => widget(name)?.querySelector('input');
            const chooseJournal = async (name, journal) => {
                const field = await waitFor(() => input(name), name + ' input');
                let item;
                if (field.readOnly) {
                    // Odoo opens a full-screen record picker on small screens.
                    field.click();
                    item = await waitFor(() => [...document.querySelectorAll(
                        '.o_dialog:not(.o_inactive_modal) .o_select_create_dialog_content ' +
                        ':is(.o_data_row, .o_kanban_record)'
                    )].find(el => visible(el) && el.textContent.includes(journal)), journal + ' mobile record');
                } else {
                    field.focus();
                    field.value = journal;
                    field.dispatchEvent(new Event('input', { bubbles: true }));
                    item = await waitFor(() => [...widget(name).querySelectorAll('[role="option"]')]
                        .find(el => visible(el) && el.textContent.trim() === journal), journal + ' option');
                }
                item.click();
                await waitFor(() => input(name)?.value === journal, journal + ' selection');
            };
            const withinViewport = (element, description) => {
                const rect = element.getBoundingClientRect();
                if (rect.left < -1 || rect.right > innerWidth + 1) {
                    throw new Error(description + ' extends outside the viewport');
                }
            };
            const shownAmount = (name, digit) => {
                const value = widget(name)?.textContent.trim() || '';
                return new RegExp('(?:^|\\D)' + digit + '[,.\\s\\u066c]?000(?:\\D|$)').test(value);
            };
            if (innerWidth !== fixture.width) {
                throw new Error('Unexpected viewport width: ' + innerWidth);
            }
            document.querySelector('button[name="action_pay"]').click();
            const wizard = await waitFor(dialog, 'settlement wizard');
            if (getComputedStyle(wizard).direction !== fixture.direction) {
                throw new Error('Unexpected direction: ' + getComputedStyle(wizard).direction);
            }
            if (visible(input('second_amount'))) {
                throw new Error('Secondary amount must be hidden until a second account is selected');
            }
            await chooseJournal('journal_id', fixture.primary);
            await chooseJournal('second_journal_id', fixture.secondary);
            await waitFor(() => shownAmount('amount_total', '3'), 'payment total of 3000');
            const second = await waitFor(() => visible(input('second_amount')) && input('second_amount'),
                'single second amount input');
            const fieldLabel = [...wizard.querySelectorAll('label')].find(el => el.htmlFor === second.id);
            if (!fieldLabel || fieldLabel.textContent.trim() !== fixture.label) {
                throw new Error('Unexpected second amount label: ' + fieldLabel?.textContent);
            }
            if (wizard.querySelectorAll('.o_field_widget[name="second_amount"]').length !== 1) {
                throw new Error('The secondary amount must appear once for the entire run');
            }
            second.focus();
            second.value = '1000';
            second.dispatchEvent(new Event('input', { bubbles: true }));
            second.dispatchEvent(new Event('change', { bubbles: true }));
            second.blur();
            await waitFor(() => shownAmount('amount_primary', '2'), 'calculated first amount of 2000');
            if (!shownAmount('amount_total', '3')) {
                throw new Error('Dividing the payment changed the original total');
            }
            const rowView = await waitFor(() => wizard.querySelector(
                fixture.width === 375 ? '.o_kanban_record' : '.o_list_renderer .o_data_row'
            ), 'employee rows');
            const confirm = wizard.querySelector('button[name="action_confirm"]');
            for (const control of [input('journal_id'), input('second_journal_id'), second,
                widget('amount_primary'), widget('amount_total'), rowView, confirm]) {
                withinViewport(control, 'Payroll payment control');
            }
            await waitFor(() => visible(confirm) && !confirm.disabled, 'enabled confirmation');
            confirm.click();
            await waitFor(() => !dialog() && !visible(document.querySelector('button[name="action_pay"]')),
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
        self.assertEqual(len(payments), 2)
        self.assertEqual(
            {payment.journal_id.id: payment.amount for payment in payments},
            {self.primary.id: 2000, self.secondary.id: 1000},
        )


@tagged('post_install', '-at_install')
class PayrollSplitSettlementDesktop(SplitSettlementBrowserJourney, HttpCase):
    browser_size = '1440x900'

    def test_split_payroll_en(self):
        self._check_split('en_US', 1440, 'Amount from second account')


@tagged('post_install', '-at_install')
class PayrollSplitSettlementMobile(SplitSettlementBrowserJourney, HttpCase):
    browser_size = '375x812'
    touch_enabled = True

    def test_split_payroll_ar(self):
        self._check_split('ar_001', 375, 'المبلغ من الحساب الثاني')
