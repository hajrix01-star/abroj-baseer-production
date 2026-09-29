"""WhatsApp composition only: no browser navigation, recipient, or send action."""
import json
from datetime import date
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError

checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def rejected(name, callback):
    try:
        with env.cr.savepoint():
            callback()
    except (AccessError, UserError, ValidationError):
        checks.append(name)
    else:
        raise AssertionError(name)


class RollbackFixtures(Exception):
    pass


try:
    with env.cr.savepoint():
        qa = env(context=dict(env.context, allowed_company_ids=[6], lang='en_US'))
        Entry, Summary = qa['baseer.pos.day.entry'], qa['baseer.pos.summary']
        config = Summary._default_config()
        method = config.payment_method_ids.filtered(lambda row: row.journal_id.type == 'cash')[:1]
        assert method

        def entry(day, second=230):
            return Entry.create({'business_date': date(2026, 5, day), 'day_schedule': 'split',
                                 'first_customers': 10, 'second_customers': 20,
                                 'first_notes': 'Breakfast & coffee + 50% / صباح', 'second_notes': 'Evening report',
                                 'first_allocation_ids': [Command.create({'slot': 'first', 'payment_method_id': method.id, 'amount': 115})],
                                 'second_allocation_ids': [Command.create({'slot': 'second', 'payment_method_id': method.id, 'amount': second})]})

        def counts():
            return (Summary.search_count([]), qa['pos.order'].search_count([('company_id', '=', 6)]), qa['account.move'].search_count([('company_id', '=', 6)]))

        def decode(action):
            url = urlsplit(action['url'])
            params = parse_qs(url.query)
            check('WhatsApp action opens native Web compose in a new tab', action['type'] == 'ir.actions.act_url' and action['target'] == 'new' and url.scheme == 'https' and url.netloc == 'web.whatsapp.com' and url.path == '/send')
            check('Compose contains only message text with no recipient or automatic-send flag', set(params) == {'text'})
            return params['text'][0]

        main = entry(20)
        rejected('Unapproved entry cannot share a daily report', lambda: main.action_share_whatsapp())
        before = counts()
        invalid = entry(21, second=0)
        rejected('Invalid second card produces no share URL', lambda: invalid.action_save_and_share())
        check('Invalid shared save creates no source or financial documents', counts() == before and invalid.state == 'draft' and not invalid.saved_summary_ids)

        late = entry(22)
        calls = []
        native = type(Summary).action_approve

        def fail_second(row):
            calls.append(row.id)
            if len(calls) == 2:
                raise UserError('Injected second approval failure before sharing')
            return native(row)

        with patch.object(type(Summary), 'action_approve', fail_second):
            rejected('Late shared-save failure returns no message action', lambda: late.action_save_and_share())
        check('Late shared-save failure rolls back native first approval and both new summaries', len(calls) == 2 and counts() == before and late.state == 'draft' and not late.saved_summary_ids)

        text = decode(main.action_save_and_share())
        check('Save and share approves both original shifts', main.state == 'approved' and len(main.saved_summary_ids) == 2 and set(main.saved_summary_ids.mapped('state')) == {'approved'})
        check('English message contains company date and shift headings', qa.company.name in text and '2026-05-20' in text and '*Morning*' in text and '*Evening*' in text)
        check('Per-shift customers and daily customer total remain distinct', all(value in text for value in ('Customers: 10', 'Customers: 20', 'Customers: 30')))
        check('English message includes daily gross average and tax', '345.00' in text and '11.50' in text and '45.00' in text and 'Daily total' in text)
        check('Collections group payment methods once at the daily level', text.count(method.display_name + ':') == 3 and 'Daily collections' in text and '345.00' in text.split('Daily collections', 1)[1])
        check('Message URL encoding preserves Arabic and reserved note characters', 'Breakfast & coffee + 50% / صباح' in text)
        after = counts()
        ids = set(main.saved_summary_ids.ids)
        again = decode(main.action_save_and_share())
        check('Repeated Save and WhatsApp does not duplicate accounting or summaries', counts() == after and set(main.saved_summary_ids.ids) == ids and again == text)
        arabic = decode(main.with_context(lang='ar_001').action_share_whatsapp())
        check('Arabic message carries translated customer labels', all(value in arabic for value in ('عدد العملاء: 10', 'عدد العملاء: 20', 'عدد العملاء: 30')))
        check('Arabic message preserves daily values and note text', all(value in arabic for value in ('345.00', '11.50', '45.00', 'صباح')))
        check('Sharing an approved entry makes no financial change', counts() == after)
        reopened = Entry._from_summaries(main.saved_summary_ids)
        reopened_text = decode(reopened.action_share_whatsapp())
        check('Reopened approved day shares the original source values', reopened_text == text and counts() == after)
        result = {'passed': len(checks), 'checks': checks, 'fixtures': 'rolled back', 'external_send': False, 'recipient': None}
        raise RollbackFixtures()
except RollbackFixtures:
    pass

print('POS_S3_WHATSAPP_RESULT=' + json.dumps(result, ensure_ascii=False))
