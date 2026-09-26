from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBaseerPosProductSubstitution(TransactionCase):
    def _protected_order(self, *, enabled=False):
        config = self.env['pos.config'].create({
            'name': 'PPS controlled register',
            'company_id': self.env.company.id,
            'baseer_substitution_enabled': enabled,
        })
        config.open_ui()
        # A freshly opened POS test session can still be in opening control.
        # The protected-substitution workflow is intentionally available only
        # after the cashier has opened the register.
        config.current_session_id.write({'state': 'opened'})
        replacement = self.env['product.template'].create({
            'name': 'PPS replacement', 'available_in_pos': True, 'list_price': 10,
        }).product_variant_id
        source = self.env['product.template'].create({
            'name': 'PPS protected source', 'available_in_pos': True, 'list_price': 10,
            'baseer_substitution_product_ids': [Command.set(replacement.ids)],
            'baseer_substitution_enabled': True,
        }).product_variant_id
        order = self.env['pos.order'].create({
            'company_id': self.env.company.id,
            'session_id': config.current_session_id.id,
            'amount_tax': 0, 'amount_total': 10, 'amount_paid': 0, 'amount_return': 0,
            'lines': [Command.create({
                'product_id': source.id, 'uuid': str(uuid4()), 'qty': 1,
                'price_unit': 10, 'price_subtotal': 10, 'price_subtotal_incl': 10,
                'full_product_name': source.display_name,
            })],
        })
        order.write({'state': 'draft'})
        return config, order, replacement

    def test_pos_configuration_defaults_to_disabled(self):
        config = self.env['pos.config'].create({
            'name': 'PPS disabled register',
            'company_id': self.env.company.id,
        })
        self.assertFalse(config.baseer_substitution_enabled)

    def test_pos_configuration_loader_keeps_native_pos_fields(self):
        """The POS config loader must retain Odoo's bootstrap fields.

        Never narrow that list merely to add our feature flag: doing so strips
        currency/pricelist fields and prevents the whole POS client from booting.
        """
        config = self.env['pos.config'].create({
            'name': 'PPS loader compatibility register',
            'company_id': self.env.company.id,
        })
        [payload] = config._load_pos_data_read(config, config)
        self.assertIn('currency_id', payload)
        self.assertIn('use_pricelist', payload)
        self.assertIn('baseer_substitution_enabled', payload)
        self.assertIn('baseer_substitution_policies', payload)
        self.assertIn('baseer_substitution_locked_lines', payload)
        config_fields = config._load_pos_data_fields(config)
        if config_fields:  # [] is Odoo's all-fields contract, not an empty payload.
            self.assertIn('currency_id', config_fields)
            self.assertIn('use_pricelist', config_fields)
            self.assertIn('baseer_direct_print_enabled', config_fields)
            self.assertIn('baseer_substitution_enabled', config_fields)
        self.assertEqual(len(config_fields), len(set(config_fields)))

    def test_protected_product_policy_is_present_in_the_pos_payload(self):
        """A cashier must receive the stored protection policy after a cache reload."""
        config, _order, replacement = self._protected_order(enabled=True)
        source = self.env['product.template'].create({
            'name': 'PPS loaded protected source', 'available_in_pos': True,
            'baseer_substitution_product_ids': [Command.set(replacement.ids)],
            'baseer_substitution_enabled': True,
        }).product_variant_id
        [payload] = source._load_pos_data_read(source, config)
        self.assertTrue(payload['baseer_substitution_enabled'])
        self.assertEqual(payload['baseer_substitution_product_ids_json'], replacement.ids)

        template_fields = source.product_tmpl_id._load_pos_data_fields(config)
        if template_fields:
            self.assertIn('baseer_substitution_enabled', template_fields)
            self.assertIn('baseer_substitution_product_ids_json', template_fields)

        [config_payload] = config._load_pos_data_read(config, config)
        self.assertIn(
            {'source_product_id': source.id, 'replacement_product_ids': replacement.ids},
            config_payload['baseer_substitution_policies'],
        )

    def test_substitution_requires_the_register_toggle(self):
        config = self.env['pos.config'].create({
            'name': 'PPS enabled register',
            'company_id': self.env.company.id,
        })
        self.assertFalse(config.baseer_substitution_enabled)
        config.write({'baseer_substitution_enabled': True})
        self.assertTrue(config.baseer_substitution_enabled)

    def test_server_rejects_protected_substitution_when_register_is_disabled(self):
        _config, order, replacement = self._protected_order(enabled=False)
        action = self.env['baseer.pos.substitution']._normalize_action({
            'action_uuid': str(uuid4()),
            'source_line_uuid': order.lines.uuid,
            'replacements': [{'product_id': replacement.id, 'quantity': 1, 'line_uuid': str(uuid4())}],
        })
        with self.assertRaises(AccessError):
            self.env['pos.order']._baseer_substitution_validate_before_sync(order, action)

    def test_server_accepts_protected_substitution_when_register_is_enabled(self):
        _config, order, replacement = self._protected_order(enabled=True)
        action = self.env['baseer.pos.substitution']._normalize_action({
            'action_uuid': str(uuid4()),
            'source_line_uuid': order.lines.uuid,
            'replacements': [{'product_id': replacement.id, 'quantity': 1, 'line_uuid': str(uuid4())}],
        })
        source, snapshot = self.env['pos.order']._baseer_substitution_validate_before_sync(order, action)
        self.assertEqual(source, order.lines)
        self.assertEqual(snapshot['product_id'], order.lines.product_id.id)

    def test_full_substitution_replaces_lines_and_creates_an_audit_event(self):
        """A taxed protected item can become two taxed lines, silently and atomically."""
        config, order, _replacement = self._protected_order(enabled=True)
        source = order.lines
        first = self.env['product.template'].create({
            'name': 'PPS 35 replacement', 'available_in_pos': True, 'list_price': 35,
        }).product_variant_id
        second = self.env['product.template'].create({
            'name': 'PPS 20 replacement', 'available_in_pos': True, 'list_price': 20,
        }).product_variant_id
        source.product_id.product_tmpl_id.write({
            'list_price': 55,
            'baseer_substitution_product_ids': [Command.set((first | second).ids)],
        })
        source.write({
            'price_unit': 55,
            'price_subtotal': 55,
            # The default sale tax on the test company is 15%, exactly as the
            # two replacement product prices are evaluated by the server.
            'price_subtotal_incl': 63.25,
        })
        first_uuid = str(uuid4())
        second_uuid = str(uuid4())
        action_uuid = str(uuid4())
        action = {
            'action_uuid': action_uuid,
            'source_line_uuid': source.uuid,
            'replacements': [
                {'product_id': first.id, 'quantity': 1, 'line_uuid': first_uuid},
                {'product_id': second.id, 'quantity': 1, 'line_uuid': second_uuid},
            ],
        }
        updated_order = {
            'uuid': order.uuid,
            'session_id': config.current_session_id.id,
            'state': 'draft',
            'amount_tax': 0,
            'amount_total': 63.25,
            'amount_paid': 0,
            'amount_return': 0,
            'lines': [
                Command.unlink(source.id),
                Command.create({
                    'product_id': first.id, 'uuid': first_uuid, 'qty': 1,
                    'price_unit': 35, 'price_subtotal': 35, 'price_subtotal_incl': 35,
                    'full_product_name': first.display_name,
                }),
                Command.create({
                    'product_id': second.id, 'uuid': second_uuid, 'qty': 1,
                    'price_unit': 20, 'price_subtotal': 20, 'price_subtotal_incl': 20,
                    'full_product_name': second.display_name,
                }),
            ],
            'baseer_substitution_action': action,
        }
        result = order.baseer_apply_protected_action('edit', action, order._baseer_revision())
        self.assertTrue(result['accepted'])
        order.invalidate_recordset()
        self.assertEqual(set(order.lines.product_id.ids), {first.id, second.id})
        event = self.env['baseer.pos.substitution'].search([
            ('order_id', '=', order.id), ('action_uuid', '=', action_uuid),
        ])
        self.assertEqual(len(event), 1)
        self.assertEqual(event.source_gross, 63.25)
        self.assertEqual(event.replacement_gross, 63.25)
        self.assertFalse(self.env['baseer.print.job'].search([
            ('source_order_id', '=', order.id),
        ]))
        self.assertTrue(all(not line.product_id.baseer_substitution_enabled for line in order.lines))
        [config_payload] = config._load_pos_data_read(config, config)
        self.assertEqual(
            {entry['line_uuid']: entry['minimum_quantity']
             for entry in config_payload['baseer_substitution_locked_lines']},
            {first_uuid: 1, second_uuid: 1},
        )
        locked = self.env['pos.order']._baseer_substitution_locked_snapshots(order)
        self.assertEqual(set(locked), {first_uuid, second_uuid})
        self.assertEqual(locked[first_uuid]['discount'], 0)
        self.env['pos.order']._baseer_assert_substitution_lines_unchanged(locked, order)

        # The ordinary POS sync/RPC path cannot remove the accepted UUID,
        # even if it bypasses the cashier's line-action dialog.
        with self.assertRaises(AccessError):
            with self.env.cr.savepoint():
                self.env['pos.order']._process_order({
                    'uuid': order.uuid,
                    'session_id': config.current_session_id.id,
                    'state': 'draft',
                    'amount_tax': 0,
                    'amount_total': 63.25,
                    'amount_paid': 0,
                    'amount_return': 0,
                    'lines': [Command.unlink(order.lines.filtered(lambda line: line.uuid == first_uuid).id)],
                }, order)
        self.assertEqual(set(order.lines.mapped('uuid')), {first_uuid, second_uuid})

        # The order's regular UI/RPC delete path must not erase an approved
        # replacement line; the attempted mutation rolls back atomically.
        with self.assertRaises(AccessError):
            with self.env.cr.savepoint():
                order.lines.filtered(lambda line: line.uuid == first_uuid).unlink()
        self.assertIn(first_uuid, order.lines.mapped('uuid'))

        # Nor may the cashier lower the replacement quantity or alter its price.
        first_line = order.lines.filtered(lambda line: line.uuid == first_uuid)
        with self.assertRaises(AccessError):
            with self.env.cr.savepoint():
                first_line.write({'qty': 0.5})
        self.assertEqual(first_line.qty, 1)
        with self.assertRaises(AccessError):
            with self.env.cr.savepoint():
                first_line.write({'price_unit': first_line.price_unit + 1})
        self.assertEqual(first_line.price_unit, 35)

        # Even if an allowed alternative is independently configured as a
        # source product, the exact line created by this substitution cannot
        # enter a recursive replacement chain.
        recursive_source = self.env['product.template'].create({
            'name': 'PPS recursive source', 'available_in_pos': True, 'list_price': 5,
        }).product_variant_id
        first_line.product_id.product_tmpl_id.write({
            'baseer_substitution_product_ids': [Command.set(recursive_source.ids)],
            'baseer_substitution_enabled': True,
        })
        recursive_action = {
            'action_uuid': str(uuid4()),
            'source_line_uuid': first_uuid,
            'replacements': [{
                'product_id': recursive_source.id, 'quantity': 1, 'line_uuid': str(uuid4()),
            }],
        }
        with self.assertRaises(AccessError):
            order.baseer_apply_protected_action('edit', recursive_action, order._baseer_revision())
        self.assertEqual(set(order.lines.mapped('uuid')), {first_uuid, second_uuid})

    def test_locked_substitution_line_rejects_price_discount_and_tax_changes(self):
        # Existing replacement locks survive disabling protection for new sources.
        _config, order, replacement = self._protected_order(enabled=False)
        line = order.lines
        line.write({'product_id': replacement.id, 'full_product_name': replacement.display_name})
        snapshot = {
            'line_uuid': line.uuid,
            'product_id': replacement.id,
            'quantity': 1,
            'unit_price': 10,
            'discount': 0,
            'tax_ids': [],
        }
        event = self.env['baseer.pos.substitution'].with_context(baseer_substitution_internal=True).sudo().create({
            'company_id': order.company_id.id,
            'order_id': order.id,
            'pos_config_id': order.config_id.id,
            'session_id': order.session_id.id,
            'cashier_id': self.env.user.id,
            'action_uuid': str(uuid4()),
            'event_at': fields.Datetime.now(),
            'order_reference': order.name,
            'source_product_id': line.product_id.id,
            'source_line_uuid': str(uuid4()),
            'source_quantity': 1,
            'source_gross': 10,
            'replacement_gross': 10,
            'currency_id': order.currency_id.id,
            'replacement_product_ids': [Command.set(replacement.ids)],
            'source_snapshot': {'line_uuid': str(uuid4())},
            'replacement_snapshot': [snapshot],
        })
        self.assertTrue(event)
        line.write({'qty': 2})
        self.assertEqual(line.qty, 2)
        line.write({'qty': 1})
        self.assertEqual(line.qty, 1)
        for values in ({'discount': 1}, {'price_unit': 11}):
            with self.assertRaises(AccessError):
                with self.env.cr.savepoint():
                    line.write(values)
        tax = self.env['account.tax'].create({
            'name': 'PPS changed tax', 'amount': 5, 'type_tax_use': 'sale',
            'company_id': order.company_id.id,
        })
        with self.assertRaises(AccessError):
            with self.env.cr.savepoint():
                line.write({'tax_ids': [Command.set(tax.ids)]})
        self.assertEqual(line.discount, 0)
        self.assertEqual(line.price_unit, 10)
        self.assertFalse(line.tax_ids)

        # Cancelling the whole order remains separate and valid, but it cannot
        # be used as a way to erase the substituted line or its audit trail.
        order.write({'state': 'cancel'})
        with self.assertRaises(AccessError):
            with self.env.cr.savepoint():
                line.unlink()
        with self.assertRaises(AccessError):
            with self.env.cr.savepoint():
                order.unlink()
        self.assertTrue(line.exists())

    def test_action_contract_rejects_browser_amounts_and_invalid_quantities(self):
        Event = self.env['baseer.pos.substitution']
        with self.assertRaises(ValidationError):
            Event._normalize_action({
                'action_uuid': str(uuid4()),
                'source_line_uuid': 'source',
                'replacements': [{'product_id': 1, 'quantity': float('nan'), 'line_uuid': 'replacement'}],
            })
        action = Event._normalize_action({
            'action_uuid': str(uuid4()),
            'source_line_uuid': 'source',
            'replacements': [{'product_id': 1, 'quantity': 1, 'line_uuid': 'replacement'}],
            'gross': 0.01,
            'tax_ids': [1],
        })
        self.assertEqual(set(action), {'action_uuid', 'source_line_uuid', 'reason_note', 'replacements'})

    def test_source_configuration_requires_allowed_pos_product(self):
        source = self.env['product.template'].create({
            'name': 'PPS protected source', 'available_in_pos': True,
        })
        with self.assertRaises(ValidationError):
            source.write({'baseer_substitution_enabled': True})
        replacement = self.env['product.template'].create({
            'name': 'PPS allowed replacement', 'available_in_pos': True,
        }).product_variant_id
        source.write({
            'baseer_substitution_product_ids': [(6, 0, replacement.ids)],
            'baseer_substitution_enabled': True,
        })
        self.assertTrue(source.baseer_substitution_enabled)

    def test_audit_model_rejects_direct_create_and_mutation(self):
        with self.assertRaises(AccessError):
            self.env['baseer.pos.substitution'].create({})

    def test_protected_item_cancellation_requires_reason_and_creates_immutable_event(self):
        config, order, _replacement = self._protected_order(enabled=True)
        source = order.lines
        Event = self.env['baseer.pos.protected_item_cancellation']
        action = {
            'action_uuid': str(uuid4()), 'source_line_uuid': source.uuid,
            'reason_code': 'wrong_order', 'reason_note': '',
        }
        result = order.baseer_apply_protected_action('cancel', action, order._baseer_revision())
        self.assertTrue(result['accepted'])
        self.assertEqual(order.state, 'cancel')
        event = Event.search([('order_id', '=', order.id), ('action_uuid', '=', action['action_uuid'])])
        self.assertEqual(len(event), 1)
        self.assertEqual(event.reason_code, 'wrong_order')
        self.assertFalse(order.lines)
        with self.assertRaises(AccessError):
            event.write({'reason_note': 'changed'})
        with self.assertRaises(AccessError):
            Event.create({})

    def test_protected_item_cancellation_rejects_missing_reason(self):
        _config, _order, _replacement = self._protected_order(enabled=True)
        with self.assertRaises(ValidationError):
            self.env['baseer.pos.protected_item_cancellation']._normalize_action({
                'action_uuid': str(uuid4()), 'source_line_uuid': str(uuid4()),
                'reason_code': '', 'reason_note': '',
            })

    def _atomic_edit_fixture(self):
        config, order, replacement = self._protected_order(enabled=True)
        replacement.product_tmpl_id.write({'taxes_id': [Command.clear()]})
        action = {
            'action_uuid': str(uuid4()), 'source_line_uuid': order.lines.uuid,
            'replacements': [{'product_id': replacement.id, 'quantity': 1, 'line_uuid': str(uuid4())}],
        }
        return config, order, replacement, action

    def test_atomic_command_returns_native_data_and_authoritative_policy(self):
        _config, order, replacement, action = self._atomic_edit_fixture()
        result = order.baseer_apply_protected_action('edit', action, order._baseer_revision())
        self.assertTrue(result['accepted'])
        self.assertEqual(result['state'], 'draft')
        self.assertEqual(order.amount_total, 10)
        self.assertEqual(order.lines.product_id, replacement)
        self.assertEqual(result['data']['pos.order'][0]['baseer_protected_revision'], result['revision'])
        self.assertEqual(result['data']['pos.order.line'][0]['baseer_substitution_minimum_quantity'], 1)
        self.assertEqual(result['data']['pos.order.line'][0]['baseer_substitution_silent_quantity'], 1)
        self.assertFalse(self.env['baseer.print.job'].search([('source_order_id', '=', order.id)]))
        import json
        baseline = json.loads(order.last_order_preparation_change)
        self.assertNotIn(action['source_line_uuid'], baseline['lines'])
        self.assertEqual(baseline['lines'][order.lines.uuid]['quantity'], 1)

    def test_atomic_command_exact_retry_recovers_after_payment_without_reapplying(self):
        _config, order, _replacement, action = self._atomic_edit_fixture()
        revision = order._baseer_revision()
        first = order.baseer_apply_protected_action('edit', action, revision)
        line_ids = order.lines.ids
        order.write({'state': 'paid'})  # Simulates acknowledged native payment; command must not mutate it.
        retry = order.baseer_apply_protected_action('edit', action, revision)
        self.assertTrue(first['accepted'])
        self.assertTrue(retry['accepted'])
        self.assertEqual(retry['state'], 'paid')
        self.assertEqual(order.lines.ids, line_ids)
        self.assertEqual(self.env['baseer.pos.substitution'].search_count([('order_id', '=', order.id)]), 1)

    def test_atomic_command_rejects_id_reuse_and_stale_revision(self):
        _config, order, _replacement, action = self._atomic_edit_fixture()
        revision = order._baseer_revision()
        with self.assertRaises(ValidationError):
            order.baseer_apply_protected_action('edit', action, 'stale')
        order.baseer_apply_protected_action('edit', action, revision)
        changed = dict(action, reason_note='different payload')
        with self.assertRaises(ValidationError):
            order.baseer_apply_protected_action('edit', changed, revision)
        with self.assertRaises(ValidationError):
            order.baseer_apply_protected_action('cancel', {
                'action_uuid': action['action_uuid'], 'source_line_uuid': action['source_line_uuid'],
                'reason_code': 'wrong_order',
            }, revision)

    def test_atomic_command_ignores_collateral_order_fields_and_preserves_other_lines(self):
        _config, order, _replacement, action = self._atomic_edit_fixture()
        another = order.lines.copy({'uuid': str(uuid4()), 'order_id': order.id})
        action.update(state='paid', amount_total=0, payment_ids=[Command.clear()],
                      lines=[Command.delete(another.id)])
        order.baseer_apply_protected_action('edit', action, order._baseer_revision())
        self.assertTrue(another.exists())
        self.assertEqual(order.state, 'draft')
        self.assertEqual(len(order.lines), 2)
        self.assertFalse(order.payment_ids)

    def test_obsolete_source_cannot_be_restored_by_native_sync_or_direct_create(self):
        config, order, _replacement, action = self._atomic_edit_fixture()
        source_product = order.lines.product_id
        order.baseer_apply_protected_action('edit', action, order._baseer_revision())
        old_line = {
            'order_id': order.id, 'product_id': source_product.id, 'uuid': action['source_line_uuid'],
            'qty': 1, 'price_unit': 10, 'price_subtotal': 10, 'price_subtotal_incl': 10,
        }
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.env['pos.order.line'].create(old_line)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.env['pos.order']._process_order({
                'uuid': order.uuid, 'session_id': config.current_session_id.id, 'state': 'draft',
                'lines': [Command.create(old_line)], 'amount_total': 20,
            }, order)
        self.assertNotIn(action['source_line_uuid'], order.lines.mapped('uuid'))

    def test_legacy_metadata_does_not_short_circuit_native_processing(self):
        config, order, _replacement, action = self._atomic_edit_fixture()
        order.baseer_apply_protected_action('edit', action, order._baseer_revision())
        # Unlike the former early return, native synchronization must apply
        # unrelated legitimate fields even with exact acknowledged metadata.
        self.env['pos.order']._process_order({
            'uuid': order.uuid, 'session_id': config.current_session_id.id, 'state': 'draft',
            'baseer_substitution_action': action, 'general_customer_note': 'after edit saved',
        }, order)
        self.assertEqual(order.general_customer_note, 'after edit saved')

    def test_new_legacy_action_is_rejected_without_mutating_the_order(self):
        config, order, _replacement, action = self._atomic_edit_fixture()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['pos.order']._process_order({
                'uuid': order.uuid, 'session_id': config.current_session_id.id, 'state': 'paid',
                'baseer_substitution_action': action, 'lines': [Command.clear()],
            }, order)
        self.assertEqual(order.state, 'draft')
        self.assertEqual(len(order.lines), 1)

    def test_new_command_rejects_paid_order_and_existing_payment(self):
        _config, order, _replacement, action = self._atomic_edit_fixture()
        order.write({'state': 'paid'})
        with self.assertRaises(AccessError):
            order.baseer_apply_protected_action('edit', action, order._baseer_revision())
        # Never move a paid order back to draft: native Odoo correctly forbids
        # that. Exercise the independent payment-bearing draft case separately.
        config, order, _replacement, action = self._atomic_edit_fixture()
        method = config.payment_method_ids[:1]
        self.assertTrue(method, 'The POS test fixture needs an active payment method.')
        self.env['pos.payment'].create({
            'pos_order_id': order.id, 'payment_method_id': method.id, 'amount': 1,
        })
        with self.assertRaises(AccessError):
            order.baseer_apply_protected_action('edit', action, order._baseer_revision())

    def test_cancellation_retry_keeps_empty_order_cancelled(self):
        _config, order, _replacement = self._protected_order(enabled=True)
        action = {'action_uuid': str(uuid4()), 'source_line_uuid': order.lines.uuid,
                  'reason_code': 'wrong_order', 'reason_note': ''}
        revision = order._baseer_revision()
        result = order.baseer_apply_protected_action('cancel', action, revision)
        retry = order.baseer_apply_protected_action('cancel', action, revision)
        self.assertEqual(result['state'], 'cancel')
        self.assertEqual(retry['state'], 'cancel')
        self.assertFalse(order.lines)
        self.assertEqual(self.env['baseer.pos.protected_item_cancellation'].search_count([('order_id', '=', order.id)]), 1)

    def test_audit_company_rules_are_global_for_both_event_models(self):
        for xmlid in ('rule_baseer_pos_substitution_manager_company',
                      'rule_baseer_pos_protected_cancellation_company'):
            rule = self.env.ref('baseer_pos_product_substitution.' + xmlid)
            self.assertTrue(rule['global'])
            self.assertIn('company_ids', rule.domain_force)

    def test_manager_cannot_read_events_or_retry_command_in_another_active_company(self):
        _config, order, _replacement, action = self._atomic_edit_fixture()
        revision = order._baseer_revision()
        order.baseer_apply_protected_action('edit', action, revision)
        other = self.env['res.company'].create({'name': 'PPS isolation other company'})
        manager = self.env['res.users'].create({
            'name': 'PPS manager', 'login': 'pps.manager.' + str(uuid4()),
            'company_id': other.id, 'company_ids': [Command.set((self.env.company | other).ids)],
            'group_ids': [Command.set([self.env.ref('point_of_sale.group_pos_manager').id])],
        })
        Event = self.env['baseer.pos.substitution'].with_user(manager).with_context(allowed_company_ids=[other.id])
        self.assertEqual(Event.search_count([('order_id', '=', order.id)]), 0)
        with self.assertRaises(AccessError):
            order.with_user(manager).with_context(allowed_company_ids=[other.id]).baseer_apply_protected_action(
                'edit', action, revision)
