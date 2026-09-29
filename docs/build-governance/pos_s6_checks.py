"""Native checkbox/onchange mapping and unchanged original summary save semantics."""
import json
from datetime import date

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
        Entry = qa['baseer.pos.day.entry']
        config = qa['baseer.pos.summary']._default_config()
        methods = config.payment_method_ids[:2]
        assert len(methods) == 2

        def blank(schedule='split', **extras):
            vals = {'company_id': 6, 'config_id': config.id, 'day_schedule': schedule,
                    'first_allocation_ids': [Command.create({'slot': 'first', 'payment_method_id': method.id, 'amount': 0}) for method in methods],
                    'second_allocation_ids': [Command.create({'slot': 'second', 'payment_method_id': method.id, 'amount': 0}) for method in methods]}
            vals.update(extras)
            record = Entry.new(vals)
            record._compute_shift_picks()
            return record

        def click(record, flag, value):
            record[flag] = value
            return record._onchange_shift_picks()

        def card(record, slot):
            return {'amounts': {line.payment_method_id.id: line.amount for line in record[slot + '_allocation_ids']},
                    'customers': record[slot + '_customers'], 'notes': record[slot + '_notes'], 'zero': record[slot + '_zero_sales']}

        def persist(record, day):
            vals = {'business_date': date(2026, 3, day), 'company_id': 6, 'config_id': config.id, 'day_schedule': record.day_schedule,
                    'pick_morning': record.pick_morning, 'pick_evening': record.pick_evening, 'pick_all': record.pick_all}
            for slot in ('first', 'second'):
                for suffix in ('customers', 'notes', 'zero_sales'):
                    vals[slot + '_' + suffix] = record[slot + '_' + suffix]
                vals[slot + '_allocation_ids'] = [Command.create({'slot': slot, 'payment_method_id': line.payment_method_id.id, 'amount': line.amount}) for line in record[slot + '_allocation_ids']]
            return Entry.create(vals)

        defaults = blank()
        check('Default split selects Morning and Evening only', defaults.pick_morning and defaults.pick_evening and not defaults.pick_all)
        transitions = [('split', 'pick_morning', False, 'evening'), ('split', 'pick_evening', False, 'morning'),
                       ('morning', 'pick_evening', True, 'split'), ('evening', 'pick_morning', True, 'split'),
                       ('morning', 'pick_all', True, 'all'), ('evening', 'pick_all', True, 'all'),
                       ('split', 'pick_all', True, 'all'), ('all', 'pick_morning', True, 'morning'),
                       ('all', 'pick_evening', True, 'evening'), ('all', 'pick_all', False, 'all'),
                       ('morning', 'pick_morning', False, 'morning'), ('evening', 'pick_evening', False, 'evening')]
        for old, flag, value, expected in transitions:
            record = blank(old)
            warning = click(record, flag, value)
            check('Empty transition %s %s=%s maps to %s' % (old, flag, value, expected), record.day_schedule == expected and not warning)
            check('Selection projection remains canonical for %s %s' % (old, flag), (record.pick_morning, record.pick_evening, record.pick_all) == (expected in ('morning', 'split'), expected in ('evening', 'split'), expected == 'all'))

        populated = blank(first_customers=10, second_customers=20, first_notes='Morning note', second_notes='Evening note')
        populated.first_allocation_ids[0].amount = 115
        populated.second_allocation_ids[0].amount = 230
        original_first, original_second = card(populated, 'first'), card(populated, 'second')
        line_slots = [(line.id, line.slot) for line in populated.first_allocation_ids | populated.second_allocation_ids]
        click(populated, 'pick_morning', False)
        check('Evening-only moves the complete Evening card into the first slot', populated.day_schedule == 'evening' and card(populated, 'first') == original_second and card(populated, 'second') == original_first)
        click(populated, 'pick_morning', True)
        check('Returning to both shifts restores complete Morning and Evening data', populated.day_schedule == 'split' and card(populated, 'first') == original_first and card(populated, 'second') == original_second)
        check('Transitions never mutate the line slot or identity', line_slots == [(line.id, line.slot) for line in populated.first_allocation_ids | populated.second_allocation_ids])
        click(populated, 'pick_evening', False)
        check('Morning-only keeps the hidden Evening data intact', populated.day_schedule == 'morning' and card(populated, 'first') == original_first and card(populated, 'second') == original_second)
        click(populated, 'pick_evening', True)
        check('Reselecting Evening restores its previous values', populated.day_schedule == 'split' and card(populated, 'second') == original_second)
        warning = click(populated, 'pick_all', True)
        check('Full day refuses populated shifts without relabelling their sales', warning and populated.day_schedule == 'split' and card(populated, 'first') == original_first and card(populated, 'second') == original_second)

        for name, values in [('customers', {'first_customers': 1}), ('notes', {'second_notes': 'Keep this note'}), ('zero declaration', {'first_zero_sales': True})]:
            record = blank(**values)
            check('Full-day transition rejects existing %s' % name, click(record, 'pick_all', True) and record.day_schedule == 'split')
        full = blank('all', first_notes='Existing full day')
        check('Leaving Full day refuses existing data', click(full, 'pick_evening', True) and full.day_schedule == 'all' and full.first_notes == 'Existing full day')
        asymmetric = blank(second_allocation_ids=[Command.create({'slot': 'second', 'payment_method_id': methods[0].id, 'amount': 230})])
        before_asym = (card(asymmetric, 'first'), card(asymmetric, 'second'))
        check('Asymmetric method sets reject unsafe swaps', click(asymmetric, 'pick_morning', False) and asymmetric.day_schedule == 'split' and (card(asymmetric, 'first'), card(asymmetric, 'second')) == before_asym)
        zero = blank(first_zero_sales=True, first_notes='Zero morning', second_customers=20)
        zero.second_allocation_ids[0].amount = 230
        click(zero, 'pick_morning', False)
        check('No-sales declaration stays with its original shift during swaps', zero.day_schedule == 'evening' and not zero.first_zero_sales and zero.second_zero_sales and zero.second_notes == 'Zero morning' and zero.first_customers == 20)

        immutable = blank(state='approved')
        click(immutable, 'pick_all', True)
        check('Saved readonly selection ignores checkbox mutations', immutable.day_schedule == 'split' and immutable.pick_morning and immutable.pick_evening and not immutable.pick_all)
        normalized = Entry._normalize({'day_schedule': 'morning', 'pick_morning': False, 'pick_evening': True, 'pick_all': 'forged'})
        check('RPC aliases cannot override canonical schedule or add stored fields', normalized == {'day_schedule': 'morning'})
        alias_only = Entry.create({'pick_all': True})
        check('Forged checkbox-only create keeps the canonical default', alias_only.day_schedule == 'split' and not alias_only.pick_all)
        check('Shift checkbox fields are nonstored projections', all(not Entry._fields[name].store for name in ('pick_morning', 'pick_evening', 'pick_all')))

        rpc_values = {'company_id': 6, 'config_id': config.id, 'state': 'draft', 'day_schedule': 'split',
                      'pick_morning': False, 'pick_evening': True, 'pick_all': False, 'first_customers': 10, 'second_customers': 20,
                      'first_notes': 'Morning RPC', 'second_notes': 'Evening RPC', 'first_zero_sales': False, 'second_zero_sales': False}
        for slot, amount in [('first', 115), ('second', 230)]:
            rpc_values[slot + '_allocation_ids'] = [Command.create({'slot': slot, 'payment_method_id': method.id, 'amount': amount if index == 0 else 0}) for index, method in enumerate(methods)]
        spec = {name: {} for name in rpc_values}
        for slot in ('first', 'second'):
            spec[slot + '_allocation_ids'] = {'fields': {'slot': {}, 'payment_method_id': {'fields': {'display_name': {}}}, 'amount': {}}}
        rpc = Entry.onchange(rpc_values, ['pick_morning'], spec)
        check('Native onchange RPC preserves the clicked Evening-only selection', rpc['value'].get('day_schedule') == 'evening')
        check('Native onchange RPC returns swapped customers and notes', rpc['value'].get('first_customers') == 20 and rpc['value'].get('second_customers') == 10 and rpc['value'].get('first_notes') == 'Evening RPC' and rpc['value'].get('second_notes') == 'Morning RPC')
        rpc_amounts = {slot: sum(command[2].get('amount', 0) for command in rpc['value'].get(slot + '_allocation_ids', []) if len(command) > 2 and isinstance(command[2], dict)) for slot in ('first', 'second')}
        check('Native onchange RPC serializes Evening and Morning amounts into the correct cards', rpc_amounts == {'first': 230, 'second': 115})

        # Native RPC/savepoint helpers may clear caches of unrelated virtual
        # records. Build a fresh form buffer for each persisted-save scenario.
        save_form = blank(first_customers=10, second_customers=20, first_notes='Morning save', second_notes='Evening save')
        save_form.first_allocation_ids[0].amount = 115
        save_form.second_allocation_ids[0].amount = 230
        click(save_form, 'pick_morning', False)
        evening = persist(save_form, 20)
        evening.action_save_and_approve()
        check('Saving Evening selection posts only the original Evening amount and customers', len(evening.saved_summary_ids) == 1 and evening.saved_summary_ids.period_scope == 'evening' and evening.saved_summary_ids.amount_gross == 230 and evening.saved_summary_ids.customer_count == 20)
        rejected('Saved entry checkbox aliases cannot bypass immutability', lambda: evening.write({'pick_all': True}))
        both_form = blank(first_customers=10, second_customers=20)
        both_form.first_allocation_ids[0].amount = 115
        both_form.second_allocation_ids[0].amount = 230
        click(both_form, 'pick_morning', False)
        click(both_form, 'pick_morning', True)
        both = persist(both_form, 21)
        both.action_save_and_approve()
        check('Saving both selections preserves separate original shifts', {row.period_scope: (row.amount_gross, row.customer_count) for row in both.saved_summary_ids} == {'morning': (115, 10), 'evening': (230, 20)})
        daily = qa['baseer.pos.daily.report']._aggregate_days(qa.company, date(2026, 3, 21), date(2026, 3, 21))
        check('Selected two shifts still contribute one daily average denominator', daily['totals']['operating_days'] == 1 and daily['totals']['average_daily_sales'] == 345 and daily['totals']['average_daily_customers'] == 30)
        result = {'passed': len(checks), 'checks': checks, 'fixtures': 'rolled back'}
        raise RollbackFixtures()
except RollbackFixtures:
    pass

print('POS_S6_RESULT=' + json.dumps(result, ensure_ascii=False))
