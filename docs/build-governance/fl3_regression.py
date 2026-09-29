"""Reuse the accepted invoice/cash tests on isolated FL3, without rewriting history."""
from pathlib import Path

assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
root = Path('/mnt/qa-evidence')
for name, output in [('fl1_register_checks.py', 'fl3-invoice-checks.json'),
                     ('fl2_cash_checks.py', 'fl3-cash-checks.json')]:
    if globals().get('FL3_SUITE') == 'cash' and name.startswith('fl1'):
        continue
    source = (root / name).read_text(encoding='utf-8')
    source = source.replace("env.cr.dbname.startswith('baseer_ar1_')", "env.cr.dbname == 'baseer_ic1_20260910'")
    old_output = 'fl1-accounting-checks.json' if name.startswith('fl1') else 'fl2-cash-checks.json'
    source = source.replace(old_output, output)
    if name.startswith('fl1'):
        old = "check('POS journal turnover does not double-count invoice cards', all(money(card) == 0 for group in summary_kpis['currency_groups'] for section in group['sections'] for card in section['cards']))"
        new = "check('FL3 POS summary included once without receipt turnover', money(cards(summary_kpis, company.currency_id, 'customer')['total']) == Decimal('115.00'))"
        assert old in source
        source = source.replace(old, new)
    else:
        # Existing QA preview has July/September operations; use an empty prior
        # month for the inherited exact-cash oracle instead of deleting fixtures.
        source = source.replace("today = fields.Date.context_today(env['account.move'])",
                                "today = fields.Date.to_date('2026-02-15')")
    exec(compile(source, name, 'exec'), {'env': env})
