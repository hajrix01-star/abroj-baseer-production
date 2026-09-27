from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBankSms(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Message = self.env['baseer.bank.sms.message']
        self.Instrument = self.env['baseer.bank.sms.instrument']
        self.Card = self.env['baseer.bank.sms.instrument.card']
        self.Rule = self.env['baseer.bank.sms.rule']

    def test_ingest_is_idempotent_and_classifies_outgoing_purchase(self):
        instrument = self.Instrument.create({
            'name': 'Test work card', 'sender': 'TestBank', 'token': '4567',
        })
        message = self.Message.ingest(
            source_device_id='device-a', idempotency_key='1001', sender='TestBank',
            body='Purchase of 25.50 SAR using card *4567',
        )
        duplicate = self.Message.ingest(
            source_device_id='device-a', idempotency_key='1001', sender='TestBank',
            body='Purchase of 25.50 SAR using card *4567',
        )
        self.assertEqual(message, duplicate)
        self.assertEqual(message.instrument_id, instrument)
        self.assertEqual(message.direction, 'out')
        self.assertEqual(message.operation_type, 'card_purchase')
        self.assertEqual(self.Message.search_count([('source_device_id', '=', 'device-a'), ('idempotency_key', '=', '1001')]), 1)

    def test_instrument_uses_sender_catalogue_and_reanalysis_stays_nonfinancial(self):
        sender = self.env['baseer.bank.sms.sender'].create({
            'name': 'Test bank', 'sender': 'TestBank',
        })
        message = self.Message.ingest(
            source_device_id='device-catalogue', idempotency_key='before-reference', sender='TestBank',
            body='Purchase of 10.00 SAR using card *4567',
        )
        self.assertFalse(message.instrument_id)
        instrument = self.Instrument.create({
            'name': 'Test card', 'sender_id': sender.id, 'token': '4567',
        })
        self.assertEqual(instrument.sender, 'TestBank')
        self.Message.reanalyse_received_messages([('id', '=', message.id)])
        self.assertEqual(message.instrument_id, instrument)
        self.assertFalse(message.company_id)
        self.assertFalse(message.journal_id)

    def test_masked_account_form_handles_bidi_order_without_financial_routing(self):
        instrument = self.Instrument.create({
            'name': 'Masked account', 'sender': 'TestBank', 'token': '5204',
        })
        self.env['baseer.bank.sms.instrument.alias'].create({
            'instrument_id': instrument.id, 'prefix': '375', 'suffix': '204',
        })
        message = self.Message.ingest(
            source_device_id='device-masked', idempotency_key='masked-1001', sender='TestBank',
            body='تم سحب 20.00 ريال رقم حسابك 204***375',
        )
        self.assertEqual(message.instrument_id, instrument)
        self.assertFalse(message.company_id)
        self.assertFalse(message.journal_id)
        self.assertFalse(message.applied_rule_id)

    def test_ambiguous_masked_account_form_stays_unmatched(self):
        first = self.Instrument.create({
            'name': 'First masked account', 'sender': 'TestBank', 'token': '5204',
        })
        second = self.Instrument.create({
            'name': 'Second masked account', 'sender': 'TestBank', 'token': '1296',
        })
        Alias = self.env['baseer.bank.sms.instrument.alias']
        Alias.create({'instrument_id': first.id, 'prefix': '375', 'suffix': '204'})
        Alias.create({'instrument_id': second.id, 'prefix': '375', 'suffix': '204'})
        message = self.Message.ingest(
            source_device_id='device-masked', idempotency_key='masked-1002', sender='TestBank',
            body='تم سحب 20.00 ريال رقم حسابك 204***375',
        )
        self.assertFalse(message.instrument_id)

    def test_complete_account_is_editable_and_updates_its_matching_form(self):
        instrument = self.Instrument.create({
            'name': 'Configured account', 'sender': 'TestBank', 'token': '5204',
            'account_number': '3750005204',
        })
        self.assertEqual(instrument.account_number, '3750005204')
        self.assertTrue(instrument.account_fingerprint)
        self.assertTrue(instrument.alias_ids)
        instrument.write({'account_number': '37512345204'})
        self.assertEqual(instrument.account_number, '37512345204')
        self.assertEqual(instrument.alias_ids.filtered('generated_from_account').suffix, '204')

    def test_complete_iban_matches_an_internal_masked_slice_without_guessing(self):
        instrument = self.Instrument.create({
            'name': 'Internal masked account', 'sender': 'SNB-AlAhli', 'token': '0409',
            'account_number': 'SA2810000007871436000409',
        })
        message = self.Message.ingest(
            source_device_id='device-internal-mask', idempotency_key='internal-mask-1',
            sender='SNB-AlAhli', body='إيداع في حساب 078*409 مبلغ 207 SAR',
        )
        self.assertEqual(message.instrument_id, instrument)
        self.assertFalse(message.company_id)
        self.assertFalse(message.journal_id)

    def test_outgoing_transfer_uses_the_debited_account_not_the_beneficiary(self):
        source = self.Instrument.create({
            'name': 'Duha operating account', 'sender': 'SNB-AlAhli', 'token': '0409',
            'analysis_company_id': self.env.company.id,
        })
        self.Instrument.create({
            'name': 'Beneficiary account', 'sender': 'SNB-AlAhli', 'token': '9940',
        })
        message = self.Message.ingest(
            source_device_id='device-transfer-source', idempotency_key='transfer-source-1',
            sender='SNB-AlAhli',
            body='حوالة صادرة محلية مبلغ 13595 SAR رسوم 7 SAR من 0409* مستفيد مؤسسة مثال إلى *9940 بنك RIYAD BANK',
        )
        self.assertEqual(message.instrument_id, source)
        self.assertEqual(message.source_token, '0409')
        self.assertEqual(message.analysis_company_id, self.env.company)
        self.assertFalse(message.company_id)
        self.assertFalse(message.journal_id)

    def test_bill_payment_uses_an_explicit_unmasked_source_suffix(self):
        instrument = self.Instrument.create({
            'name': 'Al Rajhi payment source', 'sender': 'AlRajhiBank', 'token': '5204',
        })
        message = self.Message.ingest(
            source_device_id='device-alrajhi-bill', idempotency_key='alrajhi-bill-5204',
            sender='AlRajhiBank',
            body='سداد فاتورة من: 5204 مبلغ: SAR 3961.81 مفوتر: 002 الشركة السعودية للكهرباء',
        )
        self.assertEqual(message.operation_type, 'bill_payment')
        self.assertEqual(message.identifier_token, '5204')
        self.assertEqual(message.source_token, '5204')
        self.assertEqual(message.instrument_id, instrument)

    def test_source_learning_creates_one_reusable_identifier_without_financial_routing(self):
        Target = self.env['baseer.bank.sms.analysis.target']
        Wizard = self.env['baseer.bank.sms.source.learning.wizard']
        target = Target.create({'name': 'Personal review', 'kind': 'personal'})
        first = self.Message.ingest(
            source_device_id='device-source-learning', idempotency_key='source-learning-1',
            sender='TestBank',
            body='Outgoing transfer 100 SAR from 7788* to *1111 beneficiary Example',
        )
        second = self.Message.ingest(
            source_device_id='device-source-learning', idempotency_key='source-learning-2',
            sender='TestBank',
            body='Outgoing transfer 200 SAR from 7788* to *2222 beneficiary Other',
        )
        self.assertEqual(first.source_token, '7788')
        self.assertFalse(first.instrument_id)
        Wizard.create({
            'message_id': first.id, 'analysis_target_id': target.id,
        }).action_create_source_identifier()
        instrument = self.Instrument.search([('sender', '=', 'TestBank'), ('token', '=', '7788')])
        self.assertEqual(len(instrument), 1)
        self.assertEqual(instrument.analysis_target_ids, target)
        self.assertEqual(first.instrument_id, instrument)
        self.assertEqual(first.analysis_target_id, target)
        self.assertEqual(second.instrument_id, instrument)
        self.assertEqual(second.analysis_target_id, target)
        self.assertFalse(first.company_id)
        self.assertFalse(first.journal_id)

    def test_shared_identifier_preserves_history_and_requires_a_choice_for_new_messages(self):
        Target = self.env['baseer.bank.sms.analysis.target']
        Wizard = self.env['baseer.bank.sms.source.learning.wizard']
        first_target = Target.create({'name': 'Osama custody', 'kind': 'custody'})
        second_target = Target.create({'name': 'Personal', 'kind': 'personal'})
        first = self.Message.ingest(
            source_device_id='device-shared-source', idempotency_key='shared-source-1', sender='TestBank',
            body='Outgoing transfer 100 SAR from 6677* to *1111 beneficiary One',
        )
        Wizard.create({
            'message_id': first.id, 'analysis_target_id': first_target.id,
        }).action_create_source_identifier()
        second = self.Message.ingest(
            source_device_id='device-shared-source', idempotency_key='shared-source-2', sender='TestBank',
            body='Outgoing transfer 200 SAR from 6677* to *2222 beneficiary Two',
        )
        Wizard.create({
            'message_id': second.id, 'analysis_target_id': second_target.id,
        }).action_create_source_identifier()
        instrument = self.Instrument.search([('sender', '=', 'TestBank'), ('token', '=', '6677')])
        self.assertEqual(instrument.analysis_target_ids, first_target | second_target)
        self.assertEqual(first.manual_analysis_target_id, first_target)
        self.assertEqual(second.manual_analysis_target_id, second_target)
        third = self.Message.ingest(
            source_device_id='device-shared-source', idempotency_key='shared-source-3', sender='TestBank',
            body='Outgoing transfer 300 SAR from 6677* to *3333 beneficiary Three',
        )
        self.assertEqual(third.instrument_id, instrument)
        self.assertFalse(third.analysis_target_id)
        self.assertFalse(third.company_id)
        self.assertFalse(third.journal_id)

    def test_analysis_company_is_visible_without_financial_routing(self):
        instrument = self.Instrument.create({
            'name': 'Analytical account',
            'sender': 'TestBank',
            'token': '5555',
            'analysis_company_id': self.env.company.id,
        })
        message = self.Message.ingest(
            source_device_id='device-analysis', idempotency_key='analysis-company-only',
            sender='TestBank', body='Purchase of 10 SAR using card *5555',
        )
        self.assertEqual(message.instrument_id, instrument)
        self.assertEqual(message.analysis_company_id, self.env.company)
        self.assertFalse(message.company_id)
        self.assertFalse(message.journal_id)

    def test_linked_card_resolves_to_its_parent_identifier_without_financial_routing(self):
        instrument = self.Instrument.create({
            'name': 'Analytical account', 'sender': 'TestBank', 'token': '1111',
            'analysis_company_id': self.env.company.id,
        })
        card = self.Card.create({
            'name': 'Purchasing card', 'instrument_id': instrument.id, 'token': '2222',
        })
        message = self.Message.ingest(
            source_device_id='device-card', idempotency_key='linked-card-1', sender='TestBank',
            body='Purchase 75.00 SAR using card *2222',
        )
        self.assertEqual(message.instrument_id, instrument)
        self.assertEqual(message.card_id, card)
        self.assertEqual(message.analysis_company_id, self.env.company)
        self.assertFalse(message.company_id)
        self.assertFalse(message.journal_id)
        self.assertFalse(message.applied_rule_id)

    def test_dashboard_groups_evidence_by_identifier_and_currency_without_accounting_writes(self):
        instrument = self.Instrument.create({
            'name': 'Monthly analysis account', 'sender': 'TestBank', 'token': '3333',
            'analysis_company_id': self.env.company.id,
        })
        incoming = self.Message.ingest(
            source_device_id='device-dashboard', idempotency_key='dashboard-in', sender='TestBank',
            body='Incoming transfer 150.00 SAR account *3333',
        )
        outgoing = self.Message.ingest(
            source_device_id='device-dashboard', idempotency_key='dashboard-out', sender='TestBank',
            body='Purchase 40.00 SAR using card *3333',
        )
        dashboard = self.Message.get_analysis_dashboard()
        card = next(item for item in dashboard['identifiers'] if item['id'] == instrument.id)
        metric = next(item for item in card['metrics'] if item['incoming']['currency'] == 'SAR')
        self.assertEqual(metric['incoming']['value'], '150.00')
        self.assertEqual(metric['outgoing']['value'], '40.00')
        self.assertEqual(metric['net']['value'], '110.00')
        self.assertFalse(incoming.company_id)
        self.assertFalse(outgoing.company_id)
        self.assertFalse(incoming.journal_id)
        self.assertFalse(outgoing.journal_id)

    def test_dashboard_reconciles_visible_cards_with_unassigned_and_inactive_identifiers(self):
        sender = 'DashboardReconBank'
        active_instrument = self.Instrument.create({
            'name': 'Visible dashboard account', 'sender': sender, 'token': '3333',
        })
        inactive_instrument = self.Instrument.create({
            'name': 'Archived dashboard account', 'sender': sender, 'token': '4444',
        })
        self.Message.ingest(
            source_device_id='dashboard-reconciliation', idempotency_key='visible', sender=sender,
            body='Incoming transfer 150.00 SAR account *3333',
        )
        self.Message.ingest(
            source_device_id='dashboard-reconciliation', idempotency_key='unassigned', sender=sender,
            body='Incoming transfer 25.00 SAR',
        )
        self.Message.ingest(
            source_device_id='dashboard-reconciliation', idempotency_key='inactive', sender=sender,
            body='Purchase 40.00 SAR using card *4444',
        )
        inactive_instrument.active = False

        dashboard = self.Message.get_analysis_dashboard(sender=sender)

        def sar_metric(metrics):
            return next(metric for metric in metrics if metric['incoming']['currency'] == 'SAR')

        total = sar_metric(dashboard['totals'])
        cards = sar_metric(dashboard['card_totals'])
        unassigned = sar_metric(dashboard['unassigned_totals'])
        hidden = sar_metric(dashboard['hidden_identifier_totals'])
        self.assertEqual((total['incoming']['value'], total['outgoing']['value'], total['message_count']), ('175.00', '40.00', 3))
        self.assertEqual((cards['incoming']['value'], cards['outgoing']['value'], cards['message_count']), ('150.00', '0.00', 1))
        self.assertEqual((unassigned['incoming']['value'], unassigned['outgoing']['value'], unassigned['message_count']), ('25.00', '0.00', 1))
        self.assertEqual((hidden['incoming']['value'], hidden['outgoing']['value'], hidden['message_count']), ('0.00', '40.00', 1))
        self.assertEqual(
            dashboard['message_count'],
            dashboard['linked_message_count'] + dashboard['unassigned_message_count'] + dashboard['hidden_identifier_message_count'],
        )

    def test_otp_is_preserved_for_review_not_discarded(self):
        message = self.Message.ingest(
            source_device_id='device-a', idempotency_key='1002', sender='TestBank',
            body='OTP 123456. Do not share this verification code.',
        )
        self.assertTrue(message.suspected_otp)
        self.assertEqual(message.operation_type, 'otp')
        self.assertEqual(message.state, 'trash')

    def test_real_bank_patterns_keep_financial_and_nonfinancial_messages_separate(self):
        deposit = self.Message.ingest(
            source_device_id='device-a', idempotency_key='deposit-1001', sender='TestBank',
            body='تم ايداع 926.00 ريال لحسابك 204***375 .',
        )
        declined = self.Message.ingest(
            source_device_id='device-a', idempotency_key='declined-1001', sender='TestBank',
            body='Transaction Declined: Insufficient funds. Card: 7463 Amount: USD 2.71',
        )
        purchase = self.Message.ingest(
            source_device_id='device-a', idempotency_key='purchase-1001', sender='TestBank',
            body='PoS Purchase By:0187;mada Amount: SAR 20',
        )
        credit_card_payment = self.Message.ingest(
            source_device_id='device-a', idempotency_key='credit-card-payment-1001', sender='TestBank',
            body='Credit Card:Payment Card:Visa Amount:SR 100 Balance:107.58 SR',
        )
        self.assertEqual((deposit.direction, deposit.operation_type, deposit.amount, deposit.currency_code), ('in', 'deposit', 926, 'SAR'))
        self.assertEqual(deposit.identifier_token, '375')
        self.assertEqual((declined.direction, declined.operation_type, declined.state), ('unknown', 'declined', 'rejected'))
        self.assertEqual((declined.amount, declined.currency_code, declined.identifier_token), (2.71, 'USD', '7463'))
        self.assertEqual((purchase.direction, purchase.operation_type, purchase.amount, purchase.identifier_token), ('out', 'card_purchase', 20, '0187'))
        self.assertEqual((credit_card_payment.direction, credit_card_payment.operation_type, credit_card_payment.state), ('out', 'bill_payment', 'new'))

    def test_real_rajhi_and_ahli_variants_are_classified_from_their_text(self):
        internal = self.Message.ingest(
            source_device_id='device-a', idempotency_key='internal-1001', sender='TestBank',
            body='Credit Transfer Internal Amount:SR 1500 To:1994 From:2029',
        )
        withdrawal = self.Message.ingest(
            source_device_id='device-a', idempotency_key='withdrawal-1001', sender='TestBank',
            body='Withdrawal:ATM By:0187;mada Amount:SR 3800',
        )
        fee = self.Message.ingest(
            source_device_id='device-a', idempotency_key='fee-1001', sender='TestBank',
            body='خصم رسوم نقاط بيع ودفع الكتروني من 0409* ب4.44 SAR',
        )
        notice = self.Message.ingest(
            source_device_id='device-a', idempotency_key='notice-1001', sender='TestBank',
            body='5225 point of your LAK points will expire on 01/10/2026',
        )
        self.assertEqual((internal.operation_type, internal.state), ('internal_transfer_candidate', 'review'))
        self.assertEqual((withdrawal.direction, withdrawal.operation_type, withdrawal.identifier_token), ('out', 'cash_withdrawal', '0187'))
        self.assertEqual((fee.direction, fee.operation_type, fee.identifier_token), ('out', 'card_fee', '0409'))
        self.assertEqual((notice.operation_type, notice.state), ('nonfinancial_notice', 'trash'))

    def test_foreign_currency_is_retained_without_sar_conversion(self):
        message = self.Message.ingest(
            source_device_id='device-a', idempotency_key='1002-kwd', sender='TestBank',
            body='Purchase 0.665 KWD card *4567',
        )
        self.assertEqual(message.currency_code, 'KWD')
        self.assertEqual(message.currency_id.name, 'KWD')
        self.assertEqual(message.amount, 0.665)

    def test_rule_routes_without_creating_accounting_entry(self):
        instrument = self.Instrument.create({
            'name': 'Osama custody card', 'sender': 'TestBank', 'token': '4567',
        })
        self.Rule.create({
            'name': 'TestBank card to current company',
            'sender': 'TestBank', 'instrument_id': instrument.id,
            'direction': 'out', 'company_id': self.env.company.id,
        })
        message = self.Message.ingest(
            source_device_id='device-a', idempotency_key='1003', sender='TestBank',
            body='Purchase 10.00 SAR card *4567',
        )
        self.assertEqual(message.state, 'routed')
        self.assertEqual(message.company_id, self.env.company)

    def test_device_secret_and_payload_ingestion(self):
        self.env['baseer.bank.sms.sender'].create({'name': 'Test bank', 'sender': 'TestBank'})
        device = self.env['baseer.bank.sms.device'].create({
            'name': 'Owner phone', 'device_code': 'owner-phone',
        })
        secret_action = device.action_rotate_secret()
        wizard = self.env['baseer.bank.sms.device.secret.wizard'].with_context(secret_action['context']).create({
            'device_id': device.id, 'secret': secret_action['context']['default_secret'],
        })
        self.assertTrue(device.verify_secret(wizard.secret))
        self.assertIn('TestBank', device.allowed_senders())
        self.assertIn('AlRajhiBank', device.allowed_senders())
        self.assertIn('SNB-AlAhli', device.allowed_senders())
        message = device.ingest_payload({
            'device_code': 'owner-phone', 'idempotency_key': 'unique-key-1004',
            'sender': 'TestBank', 'body': 'Incoming transfer 12.00 SAR *4567',
            'received_at': '2026-09-26 12:00:00',
        })
        self.assertEqual(message.direction, 'in')

    def test_v2_heartbeat_keeps_only_operational_metadata(self):
        device = self.env['baseer.bank.sms.device'].create({
            'name': 'QA test phone', 'device_code': 'qa-health-device',
        })
        status = device.record_heartbeat({
            'device_code': 'qa-health-device',
            'app_version': '2.0.0-qa',
            'protocol_version': '2',
            'monitoring_enabled': True,
            'queued_count': 1400,
            'retry_count': 3,
            'blocked_count': 2,
            'oldest_pending_at': '2026-09-27T08:00:00Z',
            'last_error_code': 'http_429',
        })
        self.assertEqual(status['environment_label'], 'QA')
        self.assertEqual(device.connection_state, 'online')
        self.assertEqual(device.queued_count, 1400)
        self.assertEqual(device.last_error_code, 'http_429')
        self.assertTrue(device.last_heartbeat_at)
        self.assertFalse(device.last_message_ingested_at)

    def test_v2_heartbeat_rejects_unknown_or_sensitive_fields(self):
        device = self.env['baseer.bank.sms.device'].create({
            'name': 'QA test phone', 'device_code': 'qa-health-device-2',
        })
        with self.assertRaisesRegex(ValueError, 'unsupported_field'):
            device.record_heartbeat({
                'device_code': 'qa-health-device-2',
                'queued_count': 0,
                'retry_count': 0,
                'blocked_count': 0,
                'body': 'must never enter health telemetry',
            })
