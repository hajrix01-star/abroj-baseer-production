"""Read-only acceptance script for native Odoo shell on the isolated QA clone.

The caller supplies a private QA_INPUT mapping and the independently verified
QA_EXPECTED_SOURCE marker before this file.  Private inputs must never be
committed alongside this script.  Only status and hashes are printed: neither
private references, per-day amounts nor employee data.
"""
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO

from odoo.exceptions import AccessError
from odoo.fields import Domain
from openpyxl import load_workbook


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def money(value):
    require(not isinstance(value, bool), 'invalid monetary input')
    try:
        number = Decimal(str(value))
        require(number.is_finite() and number == number.quantize(Decimal('.01')),
                'invalid monetary precision')
        return number
    except (InvalidOperation, ValueError, TypeError):
        raise AssertionError('invalid monetary input') from None


def halalas(value):
    require(type(value) is int, 'workbook amounts must be integer halalas')
    return Decimal(value) / Decimal(100)


def scoped(model, company_id):
    return env[model].with_user(user).with_context(
        allowed_company_ids=[company_id], lang='en_US', tz='Asia/Riyadh')


def complete_lines(move):
    move.check_access('read')
    lines = move.line_ids
    lines.check_access('read')
    hidden = Domain('id', '=', move.id) & Domain(
        'line_ids', 'any!', Domain('id', 'not in', lines.ids))
    require(not move.env['account.move'].search_count(hidden, limit=1),
            'source move has inaccessible lines')
    lines.account_id.check_access('read')
    lines.tax_tag_ids.check_access('read')
    return lines


def neutralization():
    require(env['ir.config_parameter'].sudo().get_param('database.is_neutralized') == 'true',
            'candidate is not neutralized')
    checks = {
        'ir.cron': [('active', '=', True)],
        'ir.mail_server': [('active', '=', True)],
        'fetchmail.server': [('active', '=', True)],
        'baseer.print.agent': [('active', '=', True)],
        'baseer.bwork.push.device': [('active', '=', True)],
        'baseer.bank.sms.device': [('active', '=', True)],
        'payment.provider': [('state', '!=', 'disabled')],
    }
    for model, domain in checks.items():
        if model in env:
            require(not env[model].sudo().search_count(domain), 'neutralization guard failed')
    if 'pos.config' in env:
        config = env['pos.config'].sudo()
        for field in ('baseer_direct_print_enabled', 'baseer_native_receipt_enabled',
                      'baseer_print_session_close_report'):
            if field in config._fields:
                require(not config.search_count([(field, '=', True)]), 'print guard failed')


def workbook_rows():
    book = load_workbook(BytesIO(QA_WORKBOOK), data_only=True, read_only=True)
    try:
        require(book.sheetnames == ['بيانات'], 'unexpected workbook sheets')
        rows = iter(book.active.values)
        header = next(rows)
        require(header == ('تاريخ اليوم', 'رقم الملخص', 'عدد العملاء', 'إجمالي المبيعات',
                           'النقد في اليد', 'الحالة', 'ملاحظات', 'قناة: البنك', 'قناة: نقد',
                           'قناة: كيتا', 'قناة: هنجر'), 'unexpected workbook columns')
        selection = []
        for day, summary, _, gross, _, status, _, bank, cash, keeta, hunger in rows:
            if isinstance(day, str) and '2026-11-01' <= day <= '2026-11-18':
                require(status == 'نشط', 'workbook contains an inactive source day')
                selection.append({
                    'day': day, 'summary': summary,
                    'gross': int(money(gross) * 100), 'bank': int(money(bank) * 100),
                    'cash': int(money(cash) * 100), 'keeta': int(money(keeta) * 100),
                    'hunger': int(money(hunger) * 100),
                })
        return selection
    finally:
        book.close()


def check_workbook(data):
    rows = data['days']
    workbook = workbook_rows()
    require(sorted(workbook, key=lambda row: row['day']) ==
            sorted(data['workbook'], key=lambda row: row['day']), 'private input differs from source workbook')
    require(len(rows) == len(workbook) == 18, 'wrong number of source days')
    expected_days = {(date(2026, 11, 1) + timedelta(days=offset)).isoformat()
                     for offset in range(18)}
    by_day = {row['day']: row for row in workbook}
    require(len(by_day) == 18 and set(by_day) == expected_days, 'workbook dates mismatch')
    require(len({row['day'] for row in rows}) == 18
            and {row['day'] for row in rows} == expected_days, 'ledger dates mismatch')
    require(len({row['source_key'] for row in rows}) == 18
            and len({row['move_ref'] for row in rows}) == 18, 'duplicate source identities')
    for row in rows:
        book = by_day[row['day']]
        require(row['summary'] == book['summary'], 'summary identity mismatch')
        channels = row['channels']
        require(set(channels) == {'cash', 'bank', 'keeta', 'hungerstation', 'jahez'},
                'unexpected channel set')
        for key, field in (('cash', 'cash'), ('bank', 'bank'), ('keeta', 'keeta'),
                           ('hungerstation', 'hunger')):
            require(money(channels[key]) == halalas(book[field]), 'workbook channel mismatch')
        require(money(row['gross']) == halalas(book['gross']), 'workbook gross mismatch')
        require(sum((money(value) for value in channels.values()), Decimal(0)) == money(row['gross']),
                'channel gross mismatch')
        require(money(row['net']) + money(row['vat']) == money(row['gross']),
                'ledger net and VAT mismatch')


def check_shami(data):
    check_workbook(data)
    company_id = data['company_id']
    require(company_id == 2, 'wrong Shami company')
    Move = scoped('account.move', company_id)
    seen = set()
    labels = {'cash': 'cash', 'bank': 'bank', 'keeta': 'keeta',
              'hungerstation': 'hunger', 'jahez': 'jahez'}
    for row in data['days']:
        source_ids = re.findall(r'(?<!\S)src:([A-Za-z0-9_-]+)(?=\s|$)', row['move_ref'])
        require(row['summary'] in row['move_ref'] and source_ids == [row['source_key']],
                'invalid source identity')
        # Census the entire requested accounting-date scope independently of
        # the expected full reference: a copied source or daily-summary key on
        # another day is not allowed to hide behind the exact-ref lookup.
        scope = [('company_id', '=', company_id), ('state', '=', 'posted'),
                 ('date', '>=', '2026-11-01'), ('date', '<=', '2026-11-18')]
        source_candidates = Move.search(scope + [('ref', 'ilike', 'src:' + row['source_key'])])
        source_candidates.check_access('read')
        source_matches = source_candidates.filtered(lambda candidate:
            row['source_key'] in re.findall(
                r'(?<!\S)src:([A-Za-z0-9_-]+)(?=\s|$)', candidate.ref or ''))
        summary_candidates = Move.search(scope + [('ref', 'ilike', row['summary'])])
        summary_candidates.check_access('read')
        summary_pattern = r'(?<![A-Za-z0-9_-])' + re.escape(row['summary']) + r'(?![A-Za-z0-9_-])'
        summary_matches = summary_candidates.filtered(lambda candidate:
            bool(re.search(summary_pattern, candidate.ref or '')))
        moves = Move.search([('company_id', '=', company_id), ('state', '=', 'posted'),
                             ('ref', '=', row['move_ref']), ('date', '=', row['day'])], limit=2)
        require(len(moves) == 1 and moves.id not in seen, 'source move not unique')
        move = moves
        require(source_matches == move and summary_matches == move,
                'source or summary identity repeated within date scope')
        seen.add(move.id)
        require(move.move_type == 'entry' and move.currency_id == move.company_id.currency_id,
                'source move type or currency mismatch')
        lines = complete_lines(move)
        amounts = {key: Decimal(0) for key in labels}
        net = vat = Decimal(0)
        for line in lines:
            balance = money(line.balance)
            require(line.company_id.id == company_id
                    and line.currency_id == move.company_id.currency_id, 'source line scope mismatch')
            if line.account_id.account_type in ('income', 'income_other'):
                net -= balance
            elif balance < 0 and line.account_id.internal_group == 'liability' and line.tax_tag_ids:
                vat -= balance
            elif balance:
                matches = [key for key, label in labels.items()
                           if line.name == f'Noorix sales {label} {row["day"]}']
                require(len(matches) == 1 and balance > 0
                        and line.account_id.internal_group == 'asset', 'unclassified funding line')
                amounts[matches[0]] += balance
        require(net == money(row['net']) and vat == money(row['vat']), 'posted net or VAT mismatch')
        require(amounts == {key: money(value) for key, value in row['channels'].items()},
                'posted channel mismatch')
        require(net + vat == sum(amounts.values(), Decimal(0)) == money(row['gross']),
                'posted move does not reconcile')
    require(len(seen) == 18, 'wrong source coverage')
    return {'days': 18, 'channels_per_day': 5, 'matched_moves': len(seen)}


def displayed_money(value):
    return money(str(value).replace(',', ''))


def verify_public_report_and_xlsx(report, company, move, account_id):
    """Check the public report projection and the real XLSX export engine.

    One accounting day and the move's journal define the scope. Other moves in
    that scope are included, so the public channel total is independently
    reconciled to the exact scoped ledger, not equated to one chosen move.
    """
    filters = {'company_id': company.id, 'date_from': str(move.date),
               'date_to': str(move.date), 'journal_ids': [move.journal_id.id]}
    public = report.get_report(filters)
    require(public['company']['id'] == company.id
            and public['period']['date_from'] == str(move.date)
            and public['period']['date_to'] == str(move.date), 'ARZ report scope mismatch')
    account = None
    page = 1
    while True:
        detail = report.get_accounts(filters, 'income', page=page)
        for item in detail['accounts']:
            if item['id'] == account_id:
                require(account is None, 'duplicate report account')
                account = item
        if page * detail['page_size'] >= detail['total_count']:
            break
        require(bool(detail['accounts']), 'incomplete report account page')
        page += 1
    require(account is not None, 'ARZ report account unavailable')
    _company, _start, _end, _journals, domain = report._filters(filters)
    domain &= Domain('account_id', '=', account_id)
    lines = report.env['account.move.line'].search(domain)
    report._verify_links(lines)
    ledger_net = sum((-money(line.balance) for line in lines), Decimal(0))
    require(displayed_money(account['amounts']['current']['amount']) == ledger_net,
            'ARZ public account amount mismatch')
    channels = report._revenue_channels(company, domain).get(account_id, {})
    actual = {key: money(value[1]) for key, value in channels.items()}
    public_channels = {item['key']: displayed_money(item['amounts']['current']['amount'])
                       for item in account['channels']}
    require(actual == public_channels and sum(actual.values(), Decimal(0)) == ledger_net,
            'ARZ public channel amount mismatch')

    export = scoped('baseer.report.export', company.id)
    document = export._document('profit_loss', filters)
    summary = [row for row in document['rows'] if row.get('indent', 0) == 0]
    require(len(summary) == len(public['rows']), 'ARZ export summary count mismatch')
    for rendered, source in zip(summary, public['rows']):
        require(money(rendered['cells']['current']) ==
                displayed_money(source['amounts']['current']['amount']), 'ARZ export summary mismatch')
    target_label = f"{account['code']} {account['name']}".strip()
    positions = [index for index, row in enumerate(document['rows'])
                 if row.get('indent', 0) == 1 and row['cells']['label'] == target_label]
    require(len(positions) == 1, 'ARZ export account identity mismatch')
    target = positions[0]
    require(money(document['rows'][target]['cells']['current']) == ledger_net,
            'ARZ export account amount mismatch')
    children = []
    for row in document['rows'][target + 1:]:
        if row.get('indent', 0) != 2:
            break
        children.append((row['cells']['label'], money(row['cells']['current'])))
    expected_children = [(item['name'], displayed_money(item['amounts']['current']['amount']))
                         for item in account['channels']]
    require(children == expected_children, 'ARZ export channels mismatch')

    payload, mime, name = export._export('profit_loss', filters, 'xlsx')
    require(mime == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            and name.endswith('.xlsx') and payload.startswith(b'PK'), 'ARZ XLSX export failed')
    sheet = load_workbook(BytesIO(payload), read_only=False, data_only=False).active
    require(bool(sheet.freeze_panes), 'ARZ XLSX header missing')
    first_row = int(re.search(r'\d+', str(sheet.freeze_panes)).group(0))
    require(len(document['columns']) == 2, 'ARZ XLSX column scope mismatch')
    for index, row in enumerate(document['rows'], first_row):
        label, value = sheet.cell(index, 1), sheet.cell(index, 2)
        require(label.value == row['cells']['label'] and value.data_type == 'n'
                and money(value.value) == money(row['cells']['current']), 'ARZ XLSX row mismatch')
    return True


def check_arz(data, public=True):
    company_id = data['company_id']
    require(company_id == 1 and len(data['cases']) >= 2, 'insufficient ARZ cases')
    require(sum(case.get('role') == 'rounding_november' for case in data['cases']) <= 1,
            'duplicate ARZ November rounding case')
    Move = scoped('account.move', company_id)
    report = scoped('baseer.profit.loss.report', company_id)
    report._check_accounting_access()
    company = scoped('res.company', company_id).browse(company_id).exists()
    require(bool(company), 'ARZ company missing')
    seen, october = set(), 0
    for case in data['cases']:
        moves = Move.search([('company_id', '=', company_id), ('state', '=', 'posted'),
                             ('name', '=', case['move_name'])], limit=2)
        require(len(moves) == 1 and moves.id not in seen, 'ARZ move not unique')
        move = moves
        seen.add(move.id)
        if move.date.year == 2026 and move.date.month == 10:
            october += 1
        if case.get('role') == 'rounding_november':
            require(move.date.year == 2026 and move.date.month == 11,
                    'ARZ rounding case outside November')
        account_id = case['account_id']
        require(type(account_id) is int and account_id > 0, 'invalid ARZ account')
        lines = complete_lines(move).filtered(lambda line: line.account_id.id == account_id)
        require(bool(lines), 'ARZ income account missing')
        net = sum((-money(line.balance) for line in lines), Decimal(0))
        require(net == money(case['expected_net']), 'ARZ posted amount mismatch')
        domain = (Domain('company_id', '=', company_id) & Domain('parent_state', '=', 'posted')
                  & Domain('move_id', '=', move.id) & Domain('account_id', '=', account_id))
        provenance = []
        allocation = report._revenue_channels(company, domain, provenance=provenance)
        require(set(allocation) == {account_id}, 'ARZ allocation account mismatch')
        actual = {key: money(value[1]) for key, value in allocation[account_id].items()}
        expected = {key: money(value) for key, value in case['channels'].items()}
        require(actual == expected and 'unallocated' not in actual,
                'ARZ channel allocation mismatch')
        require(sum(actual.values(), Decimal(0)) == net, 'ARZ allocation does not reconcile')
        require(len(provenance) == len(actual)
                and all(item['move_id'] == move.id and item['account_id'] == account_id
                        and item['channel_key'] in actual and money(item['value']) == actual[item['channel_key']]
                        for item in provenance), 'ARZ provenance mismatch')
        if public:
            verify_public_report_and_xlsx(report, company, move, account_id)
    require(october >= 2, 'insufficient October ARZ cases')
    return {'matched_moves': len(seen), 'october_moves': october,
            'november_rounding': ('PASS' if any(
                case.get('role') == 'rounding_november' for case in data['cases']) else 'NO_FIXTURE')}


env.cr.rollback()
env.cr.execute('SET TRANSACTION READ ONLY')
try:
    require(env.cr.dbname == 'baseer_qa_20261121b', 'wrong acceptance database')
    env.cr.execute('SHOW transaction_read_only')
    require(env.cr.fetchone()[0] == 'on', 'transaction is not read-only')
    require(isinstance(QA_INPUT, dict), 'private acceptance input missing')
    require(isinstance(QA_EXPECTED_SOURCE, str)
            and bool(re.fullmatch(r'[0-9a-f]{40}', QA_EXPECTED_SOURCE)),
            'verified source marker missing')
    require(QA_INPUT['source_sha'] == QA_EXPECTED_SOURCE, 'candidate source marker mismatch')
    require(bool(re.fullmatch(r'[a-fA-F0-9]{64}', QA_INPUT['prepared_sha256'])), 'invalid prepare receipt hash')
    user = env['res.users'].browse(2).exists()
    require(bool(user) and user.active and {1, 2}.issubset(set(user.company_ids.ids)),
            'owner or company access missing')
    module = env['ir.module.module'].sudo().search([('name', '=', 'baseer_profit_loss_report')], limit=2)
    require(len(module) == 1 and module.state == 'installed'
            and module.installed_version == '19.0.1.1.4', 'report module version mismatch')
    neutralization()
    shami = check_shami(QA_INPUT['shami'])
    arz = check_arz(QA_INPUT['arz'])
    require(shami == check_shami(QA_INPUT['shami']) and arz == check_arz(QA_INPUT['arz'], public=False),
            'repeated input changed read results')
    accountants = env['res.users'].sudo().search([
        ('active', '=', True), ('share', '=', False), ('id', 'not in', [1, 2]),
    ], limit=50)
    guard = 'NO_FIXTURE'
    guard_scope = 'none'
    for accountant in accountants:
        if accountant.with_user(accountant).has_group('base.group_system'):
            continue
        memberships = set(accountant.company_ids.ids)
        allowed = min(memberships - {2}, default=None)
        if allowed is None:
            continue
        candidate = env['baseer.profit.loss.report'].with_user(accountant).with_context(
            allowed_company_ids=[allowed])
        try:
            candidate._check_accounting_access()
        except AccessError:
            continue
        accepted = candidate.get_context(company_id=allowed)
        require(accepted['default_company_id'] == allowed
                and {company['id'] for company in accepted['companies']} == {allowed},
                'active company input did not limit the report')
        try:
            candidate.get_context(company_id=2)
        except AccessError:
            guard = 'PASS'
            guard_scope = 'assigned_membership' if 2 not in memberships else 'active_company'
            if guard_scope == 'assigned_membership':
                break
        else:
            raise AssertionError('out-of-scope company was accepted')
    print('QA_REFRESH_ODOO=' + json.dumps({
        'source_sha': QA_INPUT['source_sha'], 'prepared_sha256': QA_INPUT['prepared_sha256'],
        'database': env.cr.dbname, 'module_version': module.installed_version,
        'arz': 'PASS', 'shami': 'PASS', 'public_report': 'PASS', 'xlsx': 'PASS',
        'numeric_verification': {'arz': arz, 'shami': shami},
        'repeat': 'PASS', 'company_guard': guard, 'company_guard_scope': guard_scope, 'read_only': True,
    }, sort_keys=True))
finally:
    env.cr.rollback()
